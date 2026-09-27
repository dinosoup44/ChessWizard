"""Controlled negative-only writes. No heavy-analyzer imports or dispatch.

Plans and writes share one path. Dry runs isolate new engine evidence in memory.
Positive scout findings remain pending; they cannot be marked completed here.
"""
from __future__ import annotations
from typing import Any, Callable, Iterable, Mapping, Sequence, TYPE_CHECKING
from sqlite_transaction import SqliteTransaction
if TYPE_CHECKING:
    from analysis_registry import AnalyzerDefinition
    from analysis_results import HeavyResult

from collections import Counter
from contextlib import closing, ExitStack
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import time

import chess.engine

from analysis_scout import (
    SCOUT_PROFILE, SCOUT_ENGINE_OPTIONS, ScoutEvidence, validate_stored_move,
)
from engine_cache import STOCKFISH_PATH, get_cached_position, get_or_analyze


NEGATIVE_STATUSES = {"screened_out", "scouted_out"}
PROTECTED_STATUSES = {"candidate", "rejected", "analyzed_no_hit"}


from analysis_scope import validation_scope_ids


from analysis_engine import LazyScoutEngine, DryRunEvidence

from analysis_safety import coverage_rows, protected_snapshot, integrity_check, create_backup, write_authorizer


from analysis_planner import plan_negatives

def apply_negatives(connection: sqlite3.Connection, plans: Sequence[Mapping[str, Any]],
                    game_ids: Sequence[int], analysis_types: set[str], *,
                    validate_integrity: bool = True) -> Counter:
    """Persist completed negatives without replacing protected heavy evidence.

    Args:
        connection: Repository connection; outer transactions are never committed.
        plans: Completed static/scout rejection payloads.
        game_ids: Authorized real-game scope.
        analysis_types: Authorized tactic types.
        validate_integrity: Run SQLite integrity checks inside this unit.

    Returns:
        Counts of inserted, updated, unchanged and protected rows.

    Raises:
        ValueError: A plan exceeds scope or claims unsupported analysis evidence.
        sqlite3.Error: The nested or standalone transaction failed.
    """
    if not game_ids:
        if plans:
            raise ValueError("Cannot write outside an empty scope")
        return Counter()
    placeholders = ",".join("?" for _ in game_ids)
    counts = Counter()
    connection.set_authorizer(write_authorizer(coverage=True))
    transaction = SqliteTransaction(connection)
    try:
        transaction.begin()
        scope_moves = {r[0] for r in connection.execute(
            f"SELECT m.move_id FROM moves m JOIN games g ON g.game_id=m.game_id "
            f"WHERE m.game_id IN ({placeholders}) AND m.is_user_move=1 AND COALESCE(g.source,'')<>'dev'", game_ids)}
        for plan in plans:
            if plan["move_id"] not in scope_moves or plan["analysis_type"] not in analysis_types:
                raise ValueError("Negative plan falls outside selected scope")
            if plan["coverage_status"] not in NEGATIVE_STATUSES or plan["analyzer_version"] != "0":
                raise ValueError("Only negative coverage without heavy analysis is allowed")
            if plan["coverage_status"] == "screened_out" and (plan["scout_version"] != "0" or plan["scout_config"]):
                raise ValueError("Static coverage cannot claim scout evidence")
            previous = connection.execute(
                "SELECT * FROM analysis_coverage WHERE move_id=? AND analysis_type=?",
                (plan["move_id"], plan["analysis_type"]),
            ).fetchone()
            if previous is not None:
                if previous["coverage_status"] not in NEGATIVE_STATUSES | {"error"} or previous["candidate_id"] is not None:
                    counts["protected"] += 1
                    continue
                # Avoid even a no-op UPSERT: SQLite could advance its sequence.
                if all(previous[field] == plan[field] for field in (
                    "coverage_status", "screener_version", "scout_version", "scout_config", "analyzer_version"
                )):
                    counts["unchanged"] += 1
                    continue
            cursor = connection.execute("""
                INSERT INTO analysis_coverage (
                    move_id,analysis_type,coverage_status,screener_version,
                    scout_version,scout_config,analyzer_version,details_json
                ) SELECT :move_id,:analysis_type,:coverage_status,:screener_version,
                         :scout_version,:scout_config,'0',:details_json
                  WHERE NOT EXISTS (
                    SELECT 1 FROM tactic_candidates WHERE move_id=:move_id AND tactic_type=:analysis_type
                  )
                ON CONFLICT(move_id,analysis_type) DO UPDATE SET
                    coverage_status=excluded.coverage_status,
                    screener_version=excluded.screener_version,
                    scout_version=excluded.scout_version,
                    scout_config=excluded.scout_config,
                    analyzer_version='0', details_json=excluded.details_json,
                    checked_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                WHERE analysis_coverage.coverage_status IN ('screened_out','scouted_out','error')
                  AND analysis_coverage.candidate_id IS NULL
            """, plan)
            if cursor.rowcount:
                counts[plan["coverage_status"]] += 1
                counts["inserted" if previous is None else "updated"] += 1
            else:
                counts["protected"] += 1
        if validate_integrity:
            integrity_check(connection)
        transaction.commit()
    except BaseException:
        transaction.rollback()
        raise
    finally:
        connection.set_authorizer(None)
    return counts


def run_negative_scope(connection, definitions, moves, game_ids, database_path, decide, *, apply=False, validation_scope=False):
    started = time.monotonic()
    if validation_scope:
        if sorted(game_ids) != validation_scope_ids(database_path.parent):
            raise ValueError("Selected games differ from the saved 500-game validation scope")
    elif apply and len(game_ids) > 10:
        raise ValueError("Writes beyond 10 games require the exact saved 500-game validation scope")
    connection.execute("PRAGMA foreign_keys=ON")
    original = protected_snapshot(connection)
    original_coverage = coverage_rows(connection)
    original_sequence = [tuple(r) for r in connection.execute("SELECT * FROM sqlite_sequence ORDER BY name")]
    with ExitStack() as stack:
        engine = LazyScoutEngine(stack, database_path.parent)
        scratch = stack.enter_context(closing(sqlite3.connect(":memory:")))
        plans, preview = plan_negatives(connection, definitions, moves, DryRunEvidence(connection,engine,scratch), decide)
        print("Dry-run negative plan:", json.dumps(preview, indent=2), flush=True)
        report = {"mode": "negative_write" if apply else "negative_preview", "preview": preview}
        if preview["errors"]:
            report.update(aborted=True, writes={}, errors=preview["errors"])
        elif apply and not plans:
            # Nothing to persist: do not churn sequences, timestamps, cache, or backups.
            report.update(evaluation=preview,writes={},errors=[],backup=None)
        elif apply:
            # No live database writes, including engine cache, precede this backup.
            report["backup"] = str(create_backup(connection,database_path))
            connection.set_authorizer(write_authorizer())
            try:
                plans, evaluated = plan_negatives(connection, definitions, moves, ScoutEvidence(connection,engine), decide)
            finally:
                connection.set_authorizer(None)
            report["evaluation"] = evaluated
            report["errors"] = evaluated["errors"]
            if evaluated["errors"]:
                report.update(aborted=True,writes={})
            else:
                report["writes"] = dict(apply_negatives(connection,plans,game_ids,{d.analysis_type for d in definitions}))
        else:
            report.update(writes={}, errors=[])
    after = protected_snapshot(connection)
    if original != after:
        raise RuntimeError("Protected data changed; inspect backup before proceeding")
    final_coverage = coverage_rows(connection)
    written_by_tactic = {d.analysis_type: {"screened_out":0,"scouted_out":0} for d in definitions}
    for key, row in final_coverage.items():
        if row != original_coverage.get(key) and row["coverage_status"] in NEGATIVE_STATUSES:
            written_by_tactic[row["analysis_type"]][row["coverage_status"]] += 1
    scope_keys = {(r["move_id"],d.analysis_type) for r in moves for d in definitions}
    if {k:v for k,v in original_coverage.items() if k not in scope_keys} != {k:v for k,v in final_coverage.items() if k not in scope_keys}:
        raise RuntimeError("Coverage outside scope changed")
    protected = {k:v for k,v in original_coverage.items() if v["coverage_status"] in {"candidate","rejected"}}
    if any(final_coverage.get(k) != v for k,v in protected.items()):
        raise RuntimeError("Candidate/rejected coverage changed")
    integrity_check(connection)
    report.update(games=len(game_ids),game_ids=game_ids,moves=len(moves),
                  analysis_types=[d.analysis_type for d in definitions],
                  protected_data_unchanged=True,outside_scope_unchanged=True,
                  candidate_rejected_preserved_global=len(protected),
                  candidate_rejected_preserved_in_scope=sum(k in scope_keys for k in protected),
                  candidate_counts={"before":original["tactic_candidates"]["count"],"after":after["tactic_candidates"]["count"]},
                  training_attempt_counts={"before":original["training_attempts"]["count"],"after":after["training_attempts"]["count"]},
                  coverage_counts={"before":len(original_coverage),"after":len(final_coverage)},
                  written_by_tactic=written_by_tactic,
                  validation_scope=validation_scope,
                  coverage_unchanged=original_coverage==final_coverage,
                  sequences_unchanged=original_sequence==[tuple(r) for r in connection.execute("SELECT * FROM sqlite_sequence ORDER BY name")],
                  elapsed_seconds=round(time.monotonic()-started,2),
                  quick_check="ok",foreign_key_check="ok")
    # The full report retains all selected IDs; avoid flooding terminal output.
    terminal_report = {k:v for k,v in report.items() if k != "game_ids"}
    print("Negative coverage result:",json.dumps(terminal_report,indent=2),flush=True)
    return report


