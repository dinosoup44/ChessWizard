"""Small frontend-neutral Admin Console snapshots; no action or persistence semantics."""
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DatabaseStatus:
    path: str
    available: bool
    size_bytes: int | None = None
    schema_version: int | None = None
    user_version: int | None = None
    page_count: int | None = None
    page_size: int | None = None
    journal_mode: str | None = None
    counts: dict[str, int | None] = field(default_factory=dict)
    coverage: tuple[dict, ...] = ()
    candidate_counts: dict[str, int] = field(default_factory=dict)
    stored_versions: tuple[dict, ...] = ()
    occurrence: dict = field(default_factory=dict)
    allocated_bytes: dict[str, int] = field(default_factory=dict)
    cache_payload_bytes: dict[str, int] = field(default_factory=dict)
    quick_check: str = "Not run"
    foreign_key_violations: int | None = None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class EngineStatus:
    path: str
    found: bool
    configured_version: str
    size_bytes: int | None = None
    diagnostic: str = "Not tested"
    reported_name: str | None = None
    error: str = ""


@dataclass(frozen=True)
class AdminSnapshot:
    captured_at: str
    build: dict[str, Any]
    database: DatabaseStatus
    engine: EngineStatus
    capabilities: dict[str, Any]
    profiles: dict[str, Any]
    application: dict[str, Any]
