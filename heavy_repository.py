"""ID-preserving storage for structured specialist results; no engine access."""
from __future__ import annotations
from typing import Any, Callable, Iterable, Mapping, TYPE_CHECKING
from sqlite_transaction import SqliteTransaction
if TYPE_CHECKING:
    from analysis_registry import AnalyzerDefinition
    from analysis_results import HeavyResult

import json
import sqlite3
from tactical_opportunity_repository import prepare_opportunity_payload
from solution_ownership import find_solution_owner


CANDIDATE_FIELDS = (
    "candidate_status", "confidence", "detector_version", "solution_move_uci",
    "solution_move_san", "solution_line", "notes", "metadata_json",
)


def repository_authorizer(action, table, column, database, trigger):
    if action == sqlite3.SQLITE_DELETE:
        return sqlite3.SQLITE_DENY
    if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE}:
        return sqlite3.SQLITE_OK if table in {"analysis_coverage","tactic_candidates","sqlite_sequence"} else sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def save_heavy_result(connection: sqlite3.Connection, definition: AnalyzerDefinition,
                      row: Mapping[str, Any] | sqlite3.Row, result: HeavyResult,
                      allowed_keys: set[tuple[int, str]],
                      decide: Callable[[AnalyzerDefinition, sqlite3.Row | None], str], *,
                      reconcile_stale: bool = False, expected_no_hit_version: str | None = None,
                      preserve_existing: bool = False) -> dict[str, Any]:
    """Persist one validated result atomically, preserving canonical identities.

    Args:
        connection: Repository connection; an enclosing stage retains commit ownership.
        definition: Registered analyzer and current version metadata.
        row: Specific stored move being analyzed.
        result: Structured specialist result.
        allowed_keys: Explicitly authorized move/tactic pairs.
        decide: Existing coverage-currentness rule.
        reconcile_stale: Explicit permission for stale candidate reconciliation.
        expected_no_hit_version: Optional guarded stale-no-hit refresh version.
        preserve_existing: Protect any canonical candidate from product discovery.

    Returns:
        Persistence action, resulting state and candidate ID when present.

    Raises:
        ValueError: Scope, result, version or canonical identity is unsafe.
        sqlite3.Error: The atomic write failed.
    """
    key = (row["move_id"],definition.analysis_type)
    if key not in allowed_keys:
        raise ValueError("Heavy result is outside the authorized pending queue")
    if result.state not in {"candidate","analyzed_no_hit","error"}:
        raise ValueError("Unknown specialist result state")
    if result.opportunity is not None and result.state != "candidate":
        raise ValueError("Only candidate results may persist an opportunity")
    if expected_no_hit_version is not None and reconcile_stale:
        raise ValueError("No-hit refresh and candidate reconciliation are separate operations")
    connection.set_authorizer(repository_authorizer)
    transaction = SqliteTransaction(connection)
    try:
        transaction.begin()
        previous = connection.execute("SELECT * FROM analysis_coverage WHERE move_id=? AND analysis_type=?",key).fetchone()
        if previous is not None and decide(definition,previous) == "current":
            transaction.rollback()
            return {"action":"unchanged", "state":previous["coverage_status"]}
        if previous is not None and previous["coverage_status"] in {"candidate","rejected"} and not reconcile_stale:
            transaction.rollback()
            return {"action":"protected", "state":previous["coverage_status"]}
        canonical = connection.execute(
            "SELECT * FROM tactic_candidates WHERE move_id=? AND tactic_type=? ORDER BY candidate_id",key
        ).fetchall()
        if len(canonical) > 1:
            raise ValueError("Ambiguous canonical candidates; refusing to choose or delete an ID")
        candidate = canonical[0] if canonical else None
        candidate_id = candidate["candidate_id"] if candidate else None
        if candidate is not None and preserve_existing:
            transaction.rollback()
            return {"action":"protected", "state":candidate["candidate_status"], "candidate_id":candidate_id}
        if expected_no_hit_version is not None:
            if (candidate is not None or previous is None or previous["candidate_id"] is not None
                    or previous["coverage_status"] != "analyzed_no_hit"
                    or str(previous["analyzer_version"]) != str(expected_no_hit_version)
                    or decide(definition, previous) != "needs_reanalysis"):
                raise ValueError("Authorized stale no-hit changed or acquired a candidate; refusing refresh")
        state = result.state
        action = "coverage_only"
        result_details = result.details
        # Opt-in opportunity ownership, independent of tactic names. Preserve
        # another canonical owner of the identical tactical move and its history.
        # Existing analyzers retain their previous behavior by default.
        if state == "candidate" and definition.deduplicate_opportunities and candidate is None:
            owner = find_solution_owner(connection, row["move_id"], definition.analysis_type,
                                        result.candidate["solution_move_uci"])
            if owner is not None:
                state = "analyzed_no_hit"
                result_details = {"reason":"existing_opportunity_owned", "owner_candidate_id":owner["candidate_id"],
                                  "owner_analysis_type":owner["tactic_type"], "specialist_evidence":result.details}
        if state == "candidate":
            payload = result.candidate
            if not payload or str(payload["detector_version"]) != definition.analyzer_version:
                raise ValueError("Candidate payload/version mismatch")
            payload = prepare_opportunity_payload(payload, result.opportunity, row, candidate)
            values = tuple(payload.get(field) for field in CANDIDATE_FIELDS)
            if candidate:
                if tuple(candidate[field] for field in CANDIDATE_FIELDS) != values:
                    columns = ",".join(f"{field}=?" for field in CANDIDATE_FIELDS)
                    connection.execute(f"UPDATE tactic_candidates SET {columns} WHERE candidate_id=?",(*values,candidate_id))
                action = "candidate_updated"
            else:
                columns = ",".join(CANDIDATE_FIELDS)
                placeholders = ",".join("?" for _ in CANDIDATE_FIELDS)
                cursor = connection.execute(
                    f"INSERT INTO tactic_candidates(move_id,tactic_type,{columns}) VALUES(?,?,{placeholders})",(*key,*values))
                candidate_id = cursor.lastrowid
                action = "candidate_created"
        elif state == "analyzed_no_hit" and candidate:
            if not reconcile_stale or str(candidate["detector_version"]) == definition.analyzer_version:
                transaction.rollback()
                return {"action":"protected", "state":"candidate", "candidate_id":candidate_id}
            # Explicit stale-version reconciliation retains the solution and
            # history anchor, and records rejection rather than erasing evidence.
            metadata = json.loads(candidate["metadata_json"] or "{}")
            metadata["heavy_reconciliation"] = result.details
            connection.execute(
                "UPDATE tactic_candidates SET candidate_status='rejected',detector_version=?,metadata_json=? WHERE candidate_id=?",
                (definition.analyzer_version,json.dumps(metadata,sort_keys=True),candidate_id))
            state, action = "rejected", "candidate_reconciled"
        details = json.dumps({"stage":"heavy","result":state,**result_details},sort_keys=True)
        if previous is not None and all(previous[field] == value for field,value in (
                ("coverage_status",state),("screener_version",definition.screener_version),
                ("scout_version",definition.scout_version),("scout_config",definition.scout_config()),
                ("analyzer_version",definition.analyzer_version),("candidate_id",candidate_id),("details_json",details))):
            transaction.rollback()
            return {"action":"unchanged", "state":state, "candidate_id":candidate_id}
        connection.execute("""
            INSERT INTO analysis_coverage(move_id,analysis_type,coverage_status,screener_version,
                scout_version,scout_config,analyzer_version,candidate_id,details_json)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(move_id,analysis_type) DO UPDATE SET
                coverage_status=excluded.coverage_status,screener_version=excluded.screener_version,
                scout_version=excluded.scout_version,scout_config=excluded.scout_config,
                analyzer_version=excluded.analyzer_version,candidate_id=excluded.candidate_id,
                details_json=excluded.details_json,checked_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
        """,(*key,state,definition.screener_version,definition.scout_version,
               definition.scout_config(),definition.analyzer_version,candidate_id,details))
        transaction.commit()
        return {"action":action,"state":state,"candidate_id":candidate_id}
    except BaseException:
        transaction.rollback()
        raise
    finally:
        connection.set_authorizer(None)
