"""Bounded local diagnostics containing core explanations, never raw game context."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from plugin_models import InstalledPlugin, PluginLimits
from plugin_repository import atomic_bytes, checked_path
from plugin_locking import file_lease
from plugin_state import decode_json


@dataclass(frozen=True, slots=True)
class PluginDiagnostic:
    """Describe a local failure without retaining arbitrary plugin exception text.

    Args:
        plugin_id: Stable ID, or empty for a state-level failure.
        version: Known distribution version.
        artifact_sha256: Exact artifact identity when known.
        phase: Discovery, import, invoke, shutdown, or lifecycle phase.
        error_type: Core-defined failure category.
        timestamp: UTC observation time.
        message: Core-authored explanation, not worker stderr or FEN.
    """
    plugin_id: str
    version: str
    artifact_sha256: str
    phase: str
    error_type: str
    timestamp: str
    message: str


class PluginDiagnostics:
    """Retain a finite deduplicated log without telemetry or private context.

    Args:
        root: Plugin repository root.
        limits: Retention and message bounds.
    """

    def __init__(self, root: Path, limits: PluginLimits) -> None:
        """Select local diagnostics without writing.

        Args:
            root: Contained plugin repository root.
            limits: Typed retention bounds.
        """
        self.root, self.limits = root, limits

    def record(self, receipt: InstalledPlugin | None, phase: str, error_type: str, message: str) -> None:
        """Record a bounded core-authored failure, deduplicating exact repetitions.

        Args:
            receipt: Known provenance, or None for state-level problems.
            phase: Bounded operation phase.
            error_type: Core-selected error category.
            message: Fixed safe explanation; never pass raw exception output.
        """
        try:
            directory = checked_path(self.root, "diagnostics")
            path = checked_path(directory, "events.json")
            with file_lease(checked_path(directory, "events.lock"), self.limits.lock_timeout_seconds):
                rows = []
                if path.exists() and path.stat().st_size <= self.limits.max_diagnostics * (self.limits.max_diagnostic_message + 1024):
                    try:
                        rows = decode_json(path.read_bytes())
                    except ValueError:
                        rows = []
                if not isinstance(rows, list):
                    rows = []
                # Callers supply fixed explanations; these bounds are a second barrier.
                clean = lambda value: re.sub(r"[\x00-\x1f]", " ", value)[:self.limits.max_diagnostic_message]
                row = asdict(PluginDiagnostic(receipt.plugin_id if receipt else "", receipt.version if receipt else "",
                             receipt.artifact_sha256 if receipt else "", clean(phase), clean(error_type),
                             datetime.now(timezone.utc).isoformat(), clean(message)))
                identity = {k: v for k, v in row.items() if k != "timestamp"}
                if any(isinstance(old, dict) and {k: v for k, v in old.items() if k != "timestamp"} == identity for old in rows):
                    return
                rows.append(row)
                atomic_bytes(path, (json.dumps(rows[-self.limits.max_diagnostics:], indent=2, sort_keys=True) + "\n").encode())
        except (OSError, ValueError, RuntimeError):
            # Diagnostics cannot turn a bad plugin or unwritable profile into startup failure.
            return
