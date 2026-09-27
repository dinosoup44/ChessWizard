"""Read-only cache diagnostics for tools and future configuration frontends."""
from collections import Counter
from dataclasses import dataclass
import json
from candidate_line_repository import CandidateLineRepository
from migrate_candidate_line_cache import validate_schema


@dataclass(frozen=True)
class CacheIdentitySummary:
    engine_identity: str
    profile: str | None
    row_count: int
    payload_bytes: int
    oldest_timestamp: str | None
    newest_timestamp: str | None


@dataclass(frozen=True)
class CandidateLineCacheDiagnostics:
    table_exists: bool
    row_count: int
    payload_bytes: int
    database_allocated_bytes: int
    database_free_bytes: int
    identities: tuple[CacheIdentitySummary, ...]
    oldest_timestamp: str | None
    newest_timestamp: str | None
    duplicate_keys: int
    impossible_rows: int
    issues: tuple[tuple[str, int], ...]
    health: str
    validation_scope: str


class CandidateLineDiagnosticsService:
    """Never migrates, searches, updates timestamps, deletes rows or vacuums.

    Basic inspection scans payload envelopes, not every chess PV. Full legal/model
    validation is explicit because it is more expensive. Allocation is for the
    whole SQLite file, not attributed to this cache or equal to payload bytes.
    """
    def __init__(self, connection):
        self.connection = connection

    def inspect(self, *, validate_payloads=False):
        db = self.connection
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        allocated = db.execute("PRAGMA page_count").fetchone()[0] * page_size
        free = db.execute("PRAGMA freelist_count").fetchone()[0] * page_size
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='engine_candidate_line_cache'").fetchone():
            return CandidateLineCacheDiagnostics(False, 0, 0, allocated, free, (), None, None,
                0, 0, (), "not_installed", "no_table")
        issues = Counter()
        try:
            validate_schema(db)
        except ValueError:
            issues["incompatible_schema"] += 1
        duplicates = db.execute("SELECT count(*) FROM (SELECT fen,engine_identity FROM engine_candidate_line_cache GROUP BY fen,engine_identity HAVING count(*)>1)").fetchone()[0]
        if duplicates:
            issues["duplicate_exact_request_keys"] = duplicates
        groups, times, count, payload_bytes, impossible = {}, [], 0, 0, 0
        repository = CandidateLineRepository(db)
        for fen, engine_id, version, payload, created in db.execute(
                "SELECT fen,engine_identity,schema_version,payload_json,created_at FROM engine_candidate_line_cache ORDER BY line_set_id"):
            count += 1
            size = len(payload.encode("utf-8")) if isinstance(payload, str) else len(payload or b"")
            payload_bytes += size
            profile, problems = None, set()
            try:
                data = json.loads(payload)
                if not isinstance(data, dict):
                    raise ValueError("Payload object required")
                profile = data.get("analysis_profile")
                if not isinstance(profile, str) or not profile:
                    profile = None
                    problems.add("missing_profile")
                if version != 1 or data.get("schema_version") != 1:
                    problems.add("unsupported_schema_version")
                if data.get("fen") != fen or data.get("engine_identity") != engine_id:
                    problems.add("envelope_identity_mismatch")
                lines, requested, metadata = data.get("lines"), data.get("requested_line_count"), data.get("generation_metadata")
                if not isinstance(lines, list) or type(requested) is not int or not 1 <= requested <= 256 or not isinstance(metadata, dict):
                    problems.add("invalid_payload_shape")
                else:
                    if metadata.get("complete") is not True:
                        problems.add("persisted_incomplete_evidence")
                    if len(lines) > requested or (not lines and not metadata.get("terminal")):
                        problems.add("impossible_line_count")
                    roots = [line.get("move_uci") for line in lines if isinstance(line, dict)]
                    if len(roots) != len(lines) or None in roots or len(set(roots)) != len(roots):
                        problems.add("invalid_or_duplicate_root_moves")
                if validate_payloads:
                    repository.get(fen, engine_id)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError):
                problems.add("invalid_payload")
            if not fen or not engine_id or not created:
                problems.add("missing_envelope_field")
            if problems:
                impossible += 1
                issues.update(problems)
            key = (engine_id, profile)
            group = groups.setdefault(key, [0, 0, []])
            group[0] += 1; group[1] += size
            if created:
                group[2].append(created); times.append(created)
        identities = tuple(CacheIdentitySummary(engine, profile, values[0], values[1],
            min(values[2], default=None), max(values[2], default=None))
            for (engine, profile), values in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1] or "")))
        return CandidateLineCacheDiagnostics(True, count, payload_bytes, allocated, free, identities,
            min(times, default=None), max(times, default=None), duplicates, impossible,
            tuple(sorted(issues.items())), "issues_found" if issues else "checks_passed",
            "full_legal_payloads" if validate_payloads else "schema_keys_and_payload_envelopes")
