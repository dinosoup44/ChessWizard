import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from contextlib import ExitStack
from typing import Any
from concurrent.futures import TimeoutError as FutureTimeout
from analysis_control import check_cancelled
import chess.engine
from analysis_scout import SCOUT_PROFILE, SCOUT_ENGINE_OPTIONS, ScoutEvidence
from engine_cache import STOCKFISH_PATH, get_cached_position

"""Position evidence access, independent of analyzer calculation/persistence."""
from engine_cache import get_or_analyze
from analysis_safety import write_authorizer


class PositionAnalysisService:
    def __init__(self, connection, engine, stats):
        self.connection, self.engine, self.stats = connection, engine, stats
        self.evidence = []

    def position(self, fen, profile):
        result = get_or_analyze(self.connection, self.engine, fen, profile)
        self.stats["hits" if result["cache_hit"] else "misses"] += 1
        if result["score_pov"] != "white":
            raise ValueError("Position analysis requires White-POV cache evidence")
        field = "mate" if result["score_type"] == "mate" else "score_cp"
        if result[field] is None:
            raise ValueError("Engine returned no usable score")
        self.evidence.append({"cache_id": result["cache_id"], "profile": profile})
        return result

ENGINE_CANCEL_POLL_SECONDS = 0.05
ENGINE_SHUTDOWN_TIMEOUT_SECONDS = 2.0


class LazyScoutEngine:
    """One engine per worker; cancellation kills only this worker's process.

    Normal requests still call SimpleEngine.analyse with identical arguments.
    Aborted requests never return partial scores/PVs to the evidence services.

    Args:
        stack: Worker-owned resource lifetime.
        project_root: Application directory containing Stockfish.
        cancel: Optional cooperative Stop event.
    """
    def __init__(self, stack: ExitStack, project_root: Path, cancel: threading.Event | None = None) -> None:
        """Initialize a lazy worker engine; no process starts yet.

        Args:
            stack: Context stack that owns the worker lifetime.
            project_root: Application directory containing the configured engine.
            cancel: Optional cooperative Stop event.
        """
        self.stack, self.project_root, self.engine = stack, project_root, None
        self.cancel = cancel
        self.searches = 0
        self.startup_seconds = self.search_seconds = 0.0
        self._finished = threading.Event()
        self._watcher = None
        stack.callback(self.close)

    def _watch_cancel(self) -> None:
        while not self._finished.wait(ENGINE_CANCEL_POLL_SECONDS):
            if self.cancel.is_set():
                if self.engine is not None:
                    self.engine.close()
                    return

    def close(self) -> None:
        """Terminate the owned child and join its cancellation watcher.

        Raises:
            RuntimeError: Process exit could not be confirmed within the grace period.
        """
        self._finished.set()
        if self._watcher is not None:
            self._watcher.join(ENGINE_SHUTDOWN_TIMEOUT_SECONDS)
        if self.engine is not None:
            self.engine.close()
            try:
                self.engine.returncode.result(timeout=ENGINE_SHUTDOWN_TIMEOUT_SECONDS)
            except FutureTimeout as error:
                raise RuntimeError('Stockfish shutdown could not be confirmed; its state will not be reused') from error

    def analyse(self, *args: Any, **kwargs: Any) -> chess.engine.InfoDict | list[chess.engine.InfoDict]:
        """Run an unchanged exact request, discarding its output if Stop arrives.

        Args:
            *args: Positional arguments forwarded to SimpleEngine.analyse.
            **kwargs: Engine budget, options and restrictions forwarded unchanged.

        Returns:
            The completed engine information in python-chess's original shape.

        Raises:
            AnalysisCancelled: Stop interrupted the request.
            chess.engine.EngineError: An uncancelled engine request failed.
            OSError: Stockfish could not be started.
        """
        check_cancelled(self.cancel)
        try:
            if self.engine is None:
                if self.cancel is not None:
                    self._watcher = threading.Thread(target=self._watch_cancel, name='analysis-engine-stop', daemon=True)
                    self._watcher.start()
                started = time.monotonic()
                self.engine = self.stack.enter_context(chess.engine.SimpleEngine.popen_uci(
                    str(self.project_root / STOCKFISH_PATH),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                ))
                self.startup_seconds += time.monotonic() - started
                check_cancelled(self.cancel)
                self.engine.configure(SCOUT_ENGINE_OPTIONS)
            check_cancelled(self.cancel)
            self.searches += 1
            started = time.monotonic()
            try:
                result = self.engine.analyse(*args, **kwargs)
            finally:
                self.search_seconds += time.monotonic() - started
            check_cancelled(self.cancel)
            return result
        except Exception:
            check_cancelled(self.cancel)
            raise


class DryRunPositionAnalysisService(PositionAnalysisService):
    """Heavy evidence for explicitly selected validation cases; live DB read-only.

Reuse the live cache, but send cache misses to a caller-owned temporary SQLite
connection. Scratch IDs are never exposed as durable evidence references.
"""
    def __init__(self, connection, engine, stats, scratch):
        super().__init__(connection, engine, stats)
        self.scratch = scratch
        schema = connection.execute("SELECT sql FROM sqlite_master WHERE name='engine_position_cache' AND type='table'").fetchone()[0]
        scratch.execute(schema)

    def position(self, fen, profile):
        result = get_cached_position(self.connection, fen, profile)
        if result is not None:
            self.stats["live_hits"] += 1
        else:
            result = get_or_analyze(self.scratch, self.engine, fen, profile)
            self.stats["scratch_hits" if result["cache_hit"] else "engine_searches"] += 1
            result = {**result, "cache_id": None}
        self.stats["hits" if result["cache_hit"] else "misses"] += 1
        if result["score_pov"] != "white":
            raise ValueError("Position analysis requires White-POV cache evidence")
        field = "mate" if result["score_type"] == "mate" else "score_cp"
        if result[field] is None:
            raise ValueError("Engine returned no usable score")
        self.evidence.append({"cache_id": result["cache_id"], "profile": profile})
        return result


class DryRunEvidence(ScoutEvidence):
    """Read through live cache; store cache misses only in a temporary DB."""
    def __init__(self, connection, engine, scratch):
        super().__init__(connection, engine)
        self.scratch = scratch
        schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='engine_position_cache' AND type='table'"
        ).fetchone()[0]
        scratch.execute(schema)

    def position(self, fen):
        if fen in self.positions:
            self.stats["memory_hits"] += 1
            return self.positions[fen]
        result = get_cached_position(self.connection, fen, SCOUT_PROFILE)
        if result is None:
            result = get_or_analyze(self.scratch, self.engine, fen, SCOUT_PROFILE)
            # Scratch IDs must not masquerade as persistent evidence references.
            result["cache_id"] = None
            self.stats["engine_searches"] += 1
        else:
            self.stats["database_hits"] += 1
        if result["score_pov"] != "white":
            raise ValueError("Scout requires White-POV evidence")
        self.positions[fen] = result
        return result

    def persist_scout_cache(self):
        """Promote inspected scratch evidence after caller's verified backup.

        Reuse exact cached results without another search. No candidate/coverage
        writes; existing evidence and IDs are preserved. Only positions requested
        by this planner instance are eligible. Read-only previews never call this.
        """
        columns = (
            "fen", "engine_name", "engine_version", "analysis_profile", "analysis_version",
            "limit_type", "limit_value", "side_to_move", "score_type", "score_cp", "mate",
            "best_move_uci", "best_move_san", "principal_variation", "depth", "seldepth",
            "nodes", "time_ms", "score_pov",
        )
        inserted = 0
        self.connection.set_authorizer(write_authorizer())
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            for fen in self.positions:
                if get_cached_position(self.connection, fen, SCOUT_PROFILE) is not None:
                    continue
                cached = get_cached_position(self.scratch, fen, SCOUT_PROFILE)
                if cached is None or cached["score_pov"] != "white":
                    raise ValueError("Missing or invalid scratch scout evidence")
                field = "mate" if cached["score_type"] == "mate" else "score_cp"
                if cached[field] is None:
                    raise ValueError("Scratch scout evidence has no usable score")
                self.connection.execute(
                    f"INSERT INTO engine_position_cache({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                    tuple(cached[column] for column in columns))
                inserted += 1
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        finally:
            self.connection.set_authorizer(None)
        return inserted



