"""Bounded phase-aware supervision with cancellation and profile-wide worker leases."""
from __future__ import annotations
import atexit
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import queue
import re
import sys
import threading
import time
import uuid
from plugin_locking import PluginBusyError, file_lease
from plugin_models import PluginLimits
from plugin_process import ManagedProcess
from plugin_protocol import PROTOCOL_VERSION, encode_message
from plugin_repository import checked_path
from plugin_state import decode_json


class PluginWorkerError(RuntimeError):
    """Expose a safe phase/type without retaining arbitrary plugin exception text.

    Args:
        phase: Core-observed execution phase.
        kind: Bounded failure category.
        message: Core-authored explanation without context or plugin output.
    """
    def __init__(self, phase: str, kind: str, message: str) -> None:
        """Store safe diagnostic fields.

        Args:
            phase: Execution phase.
            kind: Failure classification.
            message: Safe core explanation.
        """
        super().__init__(message)
        self.phase, self.kind = phase, kind


class PluginCancelledError(PluginWorkerError):
    """Signal cancelled/stale work, which must never produce a delivered result."""


def host_command() -> list[str]:
    """Locate the frozen or source host without consulting PATH.

    Returns:
        Absolute executable/entry arguments.
    """
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).with_name("ChessWizardPluginHost.exe"))]
    return [sys.executable, "-B", str(Path(__file__).with_name("plugin_host.py"))]


def run_worker(request: dict, limits: PluginLimits, *, cancelled: threading.Event | None = None,
               current: Callable[[], bool] | None = None) -> dict:
    """Execute one versioned JSON exchange under bounded process-tree supervision.

    Args:
        request: Data-only operation and bounded context.
        limits: Operational phase/output limits.
        cancelled: Optional explicit cancellation signal.
        current: Optional state/generation check; false discards work immediately.

    Returns:
        Validated transport response; factual validation remains in core.

    Raises:
        PluginWorkerError: Phase deadline, protocol, output, or process failure.
        PluginCancelledError: Work was disabled, superseded, or cancelled.
    """
    nonce = uuid.uuid4().hex
    request = {**request, "protocol_version": PROTOCOL_VERSION, "nonce": nonce}
    payload = encode_message(request, limits.max_message_bytes)
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    process = ManagedProcess(host_command() + ["worker"], environment, Path(sys.executable).parent)
    messages: queue.Queue[bytes] = queue.Queue(maxsize=8)
    exceeded, input_failed = threading.Event(), threading.Event()
    threads = []

    def read_output() -> None:
        pending, size = bytearray(), 0
        try:
            while chunk := process.stdout.read(4096):
                size += len(chunk)
                if size > limits.max_message_bytes:
                    exceeded.set(); return
                pending.extend(chunk)
                while b"\n" in pending:
                    line, _, rest = pending.partition(b"\n")
                    pending = bytearray(rest)
                    try:
                        messages.put_nowait(bytes(line))
                    except queue.Full:
                        exceeded.set(); return
            if pending:
                exceeded.set()
        except (OSError, ValueError):
            input_failed.set()
        finally:
            process.stdout.close()

    def read_diagnostics() -> None:
        size = 0
        try:
            while chunk := process.stderr.read(4096):
                size += len(chunk)
                if size > limits.max_diagnostic_bytes:
                    exceeded.set(); return
        except (OSError, ValueError):
            input_failed.set()
        finally:
            process.stderr.close()

    def write_input() -> None:
        try:
            view = memoryview(payload)
            while view:
                count = process.stdin.write(view)
                if not count:
                    raise OSError("Worker input closed")
                view = view[count:]
        except (OSError, ValueError):
            input_failed.set()
        finally:
            process.stdin.close()

    for function in (read_output, read_diagnostics, write_input):
        thread = threading.Thread(target=function, daemon=True)
        thread.start(); threads.append(thread)
    phase, result, seen = "discovery", None, []
    budgets = {"discovery": min(limits.timeout_seconds, limits.metadata_timeout_seconds),
               "import": min(limits.timeout_seconds, limits.import_timeout_seconds),
               "invoke": limits.timeout_seconds,
               "shutdown": min(limits.timeout_seconds, limits.shutdown_timeout_seconds)}
    deadline = time.monotonic() + budgets[phase]
    expected = ["import", "invoke", "shutdown"] if request.get("operation") == "analyze" else []
    try:
        while True:
            if cancelled and cancelled.is_set() or current is not None and not current():
                raise PluginCancelledError(phase, "cancelled", "Plugin work cancelled or superseded")
            if exceeded.is_set():
                raise PluginWorkerError(phase, "output_limit", "Plugin worker exceeded output limit")
            try:
                raw = messages.get(timeout=limits.poll_seconds)
            except queue.Empty:
                if process.poll() is not None:
                    process.terminate_tree()
                    if not threads[0].is_alive() and not threads[1].is_alive():
                        break
                if time.monotonic() >= deadline:
                    raise PluginWorkerError(phase, "timeout", "Plugin worker exceeded time limit")
                continue
            if exceeded.is_set():
                raise PluginWorkerError(phase, "output_limit", "Plugin worker exceeded output limit")
            try:
                frame = decode_json(raw)
                if not isinstance(frame, dict) or frame.get("protocol_version") != PROTOCOL_VERSION or frame.get("nonce") != nonce:
                    raise ValueError("Invalid protocol identity")
                if result is not None:
                    raise ValueError("Unexpected trailing worker output")
                kind = frame.get("kind")
                if kind == "phase":
                    next_phase = frame.get("phase")
                    if len(seen) >= len(expected) or next_phase != expected[len(seen)]:
                        raise ValueError("Invalid phase transition")
                    seen.append(next_phase); phase = next_phase
                    deadline = time.monotonic() + budgets[phase]
                elif kind == "error":
                    error_type = frame.get("error_type", "worker_failure")
                    if not isinstance(error_type, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,63}", error_type):
                        error_type = "worker_failure"
                    failure_phase = frame.get("phase", phase)
                    if failure_phase not in ("discovery", *seen):
                        raise ValueError("Invalid error phase")
                    raise PluginWorkerError(failure_phase, error_type, "Plugin worker failed during " + failure_phase)
                elif kind == "result" and seen == expected and isinstance(frame.get("payload"), dict):
                    result = frame["payload"]
                    deadline = time.monotonic() + budgets["shutdown"]
                else:
                    raise ValueError("Unexpected worker frame")
            except (ValueError, TypeError, KeyError) as error:
                raise PluginWorkerError(phase, "protocol_error", "Invalid worker protocol response") from error
        if process.poll() != 0 or result is None or input_failed.is_set():
            raise PluginWorkerError(phase, "abnormal_exit", "Plugin worker exited without a complete response")
        if current is not None and not current():
            raise PluginCancelledError(phase, "stale_result", "Plugin result no longer matches requested state")
        return result
    finally:
        process.close()
        for thread in threads:
            thread.join(timeout=limits.shutdown_timeout_seconds)


class WorkerSupervisor:
    """Share profile-wide worker bounds, cancellation, and session failures.

    Args:
        root: Checked plugin storage root.
    """
    def __init__(self, root: Path) -> None:
        """Create in-memory supervision without starting workers.

        Args:
            root: Managed plugin storage root.
        """
        self.root = root
        self._lock = threading.RLock()
        self._active: dict[str, list[threading.Event]] = {}
        self._analyzing: set[threading.Event] = set()
        self._failed: dict[str, PluginWorkerError] = {}
        self.closed = False

    @contextmanager
    def _slot(self, limits: PluginLimits) -> Iterator[None]:
        for index in range(limits.max_workers):
            lease = file_lease(checked_path(self.root, f"leases/slot-{index}.lock"))
            try:
                lease.__enter__()
            except PluginBusyError:
                continue
            try:
                yield
            finally:
                lease.__exit__(None, None, None)
            return
        raise PluginBusyError("Plugin worker limit reached; retry explicitly")

    def call(self, installation_id: str, request: dict, limits: PluginLimits,
             current: Callable[[], bool] | None = None) -> dict:
        """Run one bounded request while making it cancellable by installation ID.

        Args:
            installation_id: Selected receipt or staged identity.
            request: Versioned data-only operation.
            limits: Operational limits.
            current: Optional generation/currentness check.

        Returns:
            Validated transport payload.

        Raises:
            RuntimeError: Worker bound, cancellation, or runtime failure.
        """
        event = threading.Event()
        with self._lock:
            if self.closed:
                raise PluginCancelledError("discovery", "closed", "Plugin supervisor is closed")
            self._active.setdefault(installation_id, []).append(event)
            if request.get("operation") == "analyze":
                self._analyzing.add(event)
        try:
            with self._slot(limits):
                return run_worker(request, limits, cancelled=event, current=current)
        finally:
            with self._lock:
                self._analyzing.discard(event)
                self._active[installation_id].remove(event)
                if not self._active[installation_id]:
                    del self._active[installation_id]

    def cancel(self, installation_id: str) -> None:
        """Signal every active call for one installation.

        Args:
            installation_id: Core installation identity.
        """
        with self._lock:
            for event in self._active.get(installation_id, ()):
                event.set()

    def running(self, installation_id: str) -> bool:
        """Report implementation invocation activity, excluding metadata-only helpers.

        Args:
            installation_id: Selected installation.

        Returns:
            Whether a local implementation invocation is active.
        """
        with self._lock:
            return any(event in self._analyzing for event in self._active.get(installation_id, ()))

    def failure(self, installation_id: str, value: PluginWorkerError | None = None, *, clear: bool = False) -> PluginWorkerError | None:
        """Read or explicitly change the session failure latch.

        Args:
            installation_id: Installation identity.
            value: New failure, when present.
            clear: Explicit owner re-enable clears a prior failure.

        Returns:
            Current session failure, if any.
        """
        with self._lock:
            if clear:
                self._failed.pop(installation_id, None)
            if value is not None:
                self._failed[installation_id] = value
            return self._failed.get(installation_id)

    def close(self, timeout: float = 2.0) -> None:
        """Cancel active workers and wait a bounded shutdown interval.

        Args:
            timeout: Maximum seconds to wait for supervised calls.
        """
        with self._lock:
            self.closed = True
            for events in self._active.values():
                for event in events:
                    event.set()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if not self._active:
                    return
            time.sleep(0.01)


_SUPERVISORS: dict[Path, WorkerSupervisor] = {}
_SUPERVISORS_LOCK = threading.Lock()


def supervisor_for(root: Path) -> WorkerSupervisor:
    """Share supervision across services in the same process/profile.

    Args:
        root: Checked canonical plugin root.

    Returns:
        Existing or new bounded supervisor.
    """
    with _SUPERVISORS_LOCK:
        if root not in _SUPERVISORS or _SUPERVISORS[root].closed:
            _SUPERVISORS[root] = WorkerSupervisor(root)
        return _SUPERVISORS[root]


def _shutdown() -> None:
    for supervisor in tuple(_SUPERVISORS.values()):
        supervisor.close()


atexit.register(_shutdown)
