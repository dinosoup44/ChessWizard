"""Nonblocking frontend controller over the approved plugin lifecycle services."""
from collections.abc import Callable
from dataclasses import dataclass
from queue import Empty, Queue
import threading
import uuid
from chesswizard_plugin_api import PositionContext
from plugin_presentation import PluginRow, present_material, present_plugin
from plugin_runtime import PluginCancelledError, PluginWorkerError
from plugin_service import PluginService


@dataclass(frozen=True, slots=True)
class DisplayedPosition:
    """Identify a real frontend position, including navigation away and back.

    Args:
        fen: FEN currently displayed by Game Review, including line playback.
        revision: Frontend revision incremented whenever its displayed position changes.
    """
    fen: str
    revision: int


@dataclass(frozen=True, slots=True)
class _Completion:
    lane: str
    operation: str
    value: object = None
    message: str = ""
    revision: int = 0
    position: DisplayedPosition | None = None


class PluginManagerController:
    """Keep worker results separate from frontend-thread state and stale positions.

    Public methods are called on the frontend thread; background workers only send
    completion records. There is one control lane and one invocation lane, allowing
    disable during a hung invocation without an unbounded work queue.

    Args:
        service_factory: Lazy service constructor called off the frontend thread.
    """
    def __init__(self, service_factory: Callable[[], PluginService]) -> None:
        """Initialize empty presentation without touching plugin storage.

        Args:
            service_factory: Creates the profile service on first explicit refresh.
        """
        self._factory = service_factory
        self._service: PluginService | None = None
        self._service_lock = threading.Lock()
        self._queue: Queue[_Completion] = Queue()
        self._closed = threading.Event()
        self._busy: set[str] = set()
        self._revision = 0
        self._position: DisplayedPosition | None = None
        self._refresh_needed = False
        self.rows: tuple[PluginRow, ...] = ()
        self.message = "Refresh to discover installed plugins."
        self.result = ""
        self.running_id: str | None = None

    @property
    def control_busy(self) -> bool:
        """Report control-lane availability.

        Returns:
            Whether a discovery or intent change is in progress.
        """
        return "control" in self._busy

    @property
    def invocation_busy(self) -> bool:
        """Report invocation-lane activity.

        Returns:
            Whether an explicit factual request is still completing.
        """
        return "invoke" in self._busy

    def _get_service(self) -> PluginService:
        with self._service_lock:
            if self._closed.is_set():
                raise PluginCancelledError("lifecycle", "closed", "Manager closed")
            if self._service is None:
                self._service = self._factory()
            return self._service

    def _snapshot(self) -> tuple[tuple[PluginRow, ...], str]:
        service = self._get_service()
        snapshot = service.scan()
        rows = tuple(present_plugin(view, service.diagnostics.read(view.installed)) for view in snapshot.plugins)
        message = "\n".join(snapshot.diagnostics) or (f"{len(rows)} installed plugin(s)." if rows else "No plugins installed. Install a local wheel using the CLI.")
        return rows, message

    def _submit(self, lane: str, operation: str, work: Callable[[], object],
                position: DisplayedPosition | None = None) -> bool:
        if self._closed.is_set() or lane in self._busy:
            return False
        self._busy.add(lane)
        revision = self._revision

        def worker() -> None:
            value, message = None, ""
            try:
                if not self._closed.is_set():
                    value = work()
            except PluginCancelledError:
                message = "Plugin work cancelled or superseded."
            except PluginWorkerError as error:
                # Do not render exception strings, worker stderr, or supplied context.
                message = "Plugin worker failed during " + (error.phase if error.phase in
                    {"discovery", "import", "invoke", "shutdown"} else "execution") + ". See Details."
            except Exception:
                message = "Plugin operation failed. Refresh and review compatibility, trust, and diagnostics."
            self._queue.put(_Completion(lane, operation, value, message, revision, position))

        threading.Thread(target=worker, name="plugin-manager-" + lane, daemon=True).start()
        return True

    def refresh(self) -> bool:
        """Start one explicit metadata rescan without importing plugin implementation.

        Returns:
            Whether the control lane accepted the request.
        """
        accepted = self._submit("control", "scan", self._snapshot)
        if accepted:
            self.message = "Discovering plugins…"
        return accepted

    def set_enabled(self, row: PluginRow, enabled: bool, *, acknowledged: bool = False) -> bool:
        """Queue an artifact-bound enable or independently cancellable disable.

        Args:
            row: Exact displayed artifact the user selected.
            enabled: Requested intent.
            acknowledged: Explicit acknowledgement of the displayed executable artifact.

        Returns:
            Whether a bounded operation was queued; false if busy or closed.
        """
        def change() -> object:
            self._get_service().set_enabled(row.view.installed.plugin_id, enabled,
                acknowledge_trust=acknowledged, expected_artifact_sha256=row.view.installed.artifact_sha256)
            return self._snapshot()

        if self.control_busy or self._closed.is_set():
            return False
        self._revision += 1
        self.result = ""
        self.message = "Enabling plugin…" if enabled else "Disabling plugin and stopping active work…"
        return self._submit("control", "change", change)

    def observe_position(self, position: DisplayedPosition | None) -> bool:
        """Invalidate stale output as soon as the displayed board changes.

        Args:
            position: Actual board snapshot, or None when no game is displayed.

        Returns:
            Whether the position changed and prior output was cleared.
        """
        if position == self._position:
            return False
        self._position = position
        self._revision += 1
        self.result = ""
        return True

    def run(self, row: PluginRow, position: DisplayedPosition | None) -> bool:
        """Request core-validated facts for the actual current board.

        Args:
            row: Selected ready installation.
            position: Actual displayed position; no synthetic fallback is allowed.

        Returns:
            Whether the explicit factual request was accepted.
        """
        self.observe_position(position)
        if position is None or not row.can_run or self.control_busy or self.invocation_busy:
            return False
        context = PositionContext(uuid.uuid4().hex, position.fen)
        self.result = ""
        self.message = "Running plugin on the current Game Review position…"
        accepted = self._submit("invoke", "analyze",
            lambda: row.values[0] + "\n" + present_material(
                self._get_service().analyze(row.view.installed.plugin_id, context)), position)
        if accepted:
            self.running_id = row.view.installed.installation_id
        return accepted

    def poll(self, position: DisplayedPosition | None) -> bool:
        """Apply queued results on the frontend thread and discard superseded facts.

        Args:
            position: Current frontend snapshot, checked before delivering any result.

        Returns:
            Whether presentation changed. No service or filesystem work runs here.
        """
        changed = self.observe_position(position)
        if self._closed.is_set():
            return changed
        while True:
            try:
                event = self._queue.get_nowait()
            except Empty:
                break
            changed = True
            self._busy.discard(event.lane)
            if event.lane == "invoke":
                self.running_id = None
                self._refresh_needed = True
                if event.revision != self._revision or event.position != position:
                    self.message = "Position or plugin state changed; previous result discarded."
                    continue
                self.result = event.value if isinstance(event.value, str) else ""
                self.message = event.message or "Validated material facts for the current position."
            elif event.value is not None:
                self.rows, summary = event.value
                # Preserve a useful failure/result message across the post-call rescan.
                if self.message == "Discovering plugins…" or event.operation == "change":
                    self.message = summary
            if event.message:
                self.message = event.message
                if event.operation != "scan":
                    self._refresh_needed = True
        if self._refresh_needed and not self.control_busy and not self.invocation_busy:
            self._refresh_needed = False
            self._submit("control", "scan", self._snapshot)
        return changed

    def close(self) -> None:
        """Stop accepting work and asynchronously cancel owned workers without changing intent."""
        if self._closed.is_set():
            return
        self._closed.set()
        self._revision += 1
        self.result = ""

        def shutdown() -> None:
            with self._service_lock:
                if self._service is not None:
                    self._service.close()
        threading.Thread(target=shutdown, name="plugin-manager-close", daemon=True).start()
