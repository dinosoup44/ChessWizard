"""Read-only bounded aggregate queries; never return moves, FENs, cache payloads or IDs."""
from contextlib import closing
from pathlib import Path
import sqlite3
import time
from admin_models import DatabaseStatus

TABLES = ("games", "moves", "tactic_candidates", "tactic_occurrences",
          "tactic_occurrence_evidence", "tactic_occurrence_lines",
          "tactic_occurrence_legacy_candidates", "tactic_occurrence_review_links",
          "training_attempts", "analysis_coverage", "engine_position_cache",
          "engine_candidate_line_cache")
QUERY_BUDGET_SECONDS = 20
INTEGRITY_BUDGET_SECONDS = 60


def database_status(path, *, diagnostics=False) -> DatabaseStatus:
    path = Path(path).absolute()
    values = dict(path=str(path), available=False, counts={name: None for name in TABLES})
    errors = []
    try:
        values["size_bytes"] = path.stat().st_size
        with closing(sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, timeout=2)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            deadline = time.monotonic() + QUERY_BUDGET_SECONDS
            connection.set_progress_handler(lambda: time.monotonic() > deadline, 10000)
            connection.execute("BEGIN")
            schema = {r["name"]:r["tbl_name"] for r in connection.execute(
                "SELECT name,tbl_name FROM sqlite_master WHERE type IN ('table','index')")}
            for name in ("schema_version", "user_version", "page_count", "page_size", "journal_mode"):
                values[name] = connection.execute("PRAGMA "+name).fetchone()[0]
            values["available"] = True
            for name in TABLES:
                if name in schema:
                    values["counts"][name] = connection.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0]

            def optional(label, query, args=()):
                try:
                    return [dict(r) for r in connection.execute(query,args)]
                except sqlite3.Error as error:
                    errors.append(label+": "+str(error))
                    return []

            if "tactic_candidates" in schema:
                values["candidate_counts"] = {r["tactic_type"]:r["count"] for r in optional(
                    "Candidate counts", "SELECT tactic_type,COUNT(*) AS count FROM tactic_candidates GROUP BY tactic_type")}
                values["stored_versions"] = tuple(optional("Stored versions",
                    "SELECT tactic_type,detector_version,COUNT(*) AS count FROM tactic_candidates GROUP BY tactic_type,detector_version"))
            if "analysis_coverage" in schema:
                values["coverage"] = tuple(optional("Coverage",
                    "SELECT analysis_type,coverage_status,analyzer_version,COUNT(*) AS count "
                    "FROM analysis_coverage GROUP BY analysis_type,coverage_status,analyzer_version"))
            occurrence_tables = set(TABLES[3:8])
            present = occurrence_tables.intersection(schema)
            occurrence = dict(schema_state="present" if present == occurrence_tables else "partial" if present else "absent",
                              relation_basis="Current games.user_color; unknown when perspective is unavailable",
                              relations=None, mapped_candidates=None, broken_links=None)
            if {"tactic_occurrence_legacy_candidates","tactic_occurrences","tactic_candidates"} <= schema.keys():
                mapped = optional("Occurrence links",
                    "SELECT COUNT(*) AS mapped FROM tactic_occurrence_legacy_candidates l "
                    "JOIN tactic_candidates c USING(candidate_id) JOIN tactic_occurrences o USING(occurrence_id)")
                if mapped:
                    occurrence["mapped_candidates"] = mapped[0]["mapped"]
                    occurrence["broken_links"] = values["counts"]["tactic_occurrence_legacy_candidates"]-mapped[0]["mapped"]
            if {"tactic_occurrences","games"} <= schema.keys():
                relations = optional("Occurrence relationships", """
                    SELECT CASE
                    WHEN g.user_color IS NULL OR g.user_color NOT IN ('white','black')
                         OR o.occurrence_kind NOT IN ('played','missed') THEN 'unknown'
                    WHEN o.occurrence_kind='played' AND o.actor_color=g.user_color THEN 'played_by_user'
                    WHEN o.occurrence_kind='played' THEN 'played_by_opponent'
                    WHEN o.actor_color=g.user_color THEN 'missed_by_user'
                    ELSE 'missed_by_opponent' END AS relation, COUNT(*) AS count
                    FROM tactic_occurrences o LEFT JOIN games g USING(game_id) GROUP BY relation
                """)
                if relations or values["counts"]["tactic_occurrences"] == 0:
                    occurrence["relations"] = {name:0 for name in (
                        "missed_by_user","played_by_user","played_by_opponent","missed_by_opponent","unknown")}
                    occurrence["relations"].update({r["relation"]:r["count"] for r in relations})
            if "application_metadata" in schema:
                occurrence["bootstrap"] = {r["key"]: r["value"] for r in optional("Bootstrap metadata",
                    "SELECT key,value FROM application_metadata WHERE key IN "
                    "('bootstrap_version','base_schema_sha256','occurrence_storage_version','occurrence_identity_versions')")}
            values["occurrence"] = occurrence
            if diagnostics:
                # A full-file integrity scan on removable storage needs its own budget.
                deadline = time.monotonic() + INTEGRITY_BUDGET_SECONDS
                checks = connection.execute("PRAGMA quick_check").fetchall()
                values["quick_check"] = "ok" if [r[0] for r in checks] == ["ok"] else "failed"
                values["foreign_key_violations"] = sum(1 for _ in connection.execute("PRAGMA foreign_key_check"))
            deadline = time.monotonic() + QUERY_BUDGET_SECONDS
            allocated = {}
            for row in optional("Allocated table footprint (dbstat may be unavailable)",
                                "SELECT name,SUM(pgsize) AS bytes FROM dbstat GROUP BY name"):
                table = schema.get(row["name"])
                if table in TABLES:
                    allocated[table] = allocated.get(table,0) + row["bytes"]
            values["allocated_bytes"] = allocated
            payload_bytes = {}
            # Optional full payload scans must not delay refresh or mask completed health checks.
            for table in (("engine_position_cache", "engine_candidate_line_cache") if diagnostics else ()):
                if table not in schema:
                    continue
                columns = [r["name"] for r in connection.execute('PRAGMA table_info("'+table+'")')
                           if r["type"].upper() in ("TEXT", "BLOB")]
                if columns:
                    terms = ['coalesce(length(CAST("'+name.replace('"','""')+'" AS BLOB)),0)' for name in columns]
                    measured = optional("Cache payload size", 'SELECT coalesce(sum('+"+".join(terms)+'),0) AS bytes FROM "'+table+'"')
                    if measured:
                        payload_bytes[table] = measured[0]["bytes"]
            values["cache_payload_bytes"] = payload_bytes
            connection.rollback()
    except (OSError, sqlite3.Error) as error:
        errors.append(type(error).__name__+": "+str(error))
    return DatabaseStatus(**values, errors=tuple(errors))
