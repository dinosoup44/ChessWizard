from __future__ import annotations
from collections.abc import Callable, Sequence
from typing import Any, TYPE_CHECKING
import sqlite3
if TYPE_CHECKING:
    from analysis_registry import AnalyzerDefinition
from collections import Counter
import json
import chess.engine
from analysis_scout import validate_stored_move
from analysis_safety import coverage_rows
from analysis_preflight import apply_existing_preflight
PROTECTED_STATUSES = {'candidate', 'rejected', 'analyzed_no_hit'}


def plan_stale_no_hits(connection, definitions, moves, decide, from_version):
    """Explicit heavy-version-only refresh; never screen, scout, or reconcile.

Canonical candidates and candidate-linked coverage always win over eligibility.
Upstream staleness is an error requiring a separate rollout, not implicit work.
"""
    if not from_version or any(d.analyzer_version == str(from_version) for d in definitions):
        raise ValueError("Refresh requires distinct explicit source/target heavy versions")
    existing = coverage_rows(connection)
    candidates = {(r["move_id"],r["tactic_type"]):r["candidate_id"]
                  for r in connection.execute("SELECT candidate_id,move_id,tactic_type FROM tactic_candidates")}
    pending, errors, protected = [], [], set()
    metrics = {d.analysis_type:Counter() for d in definitions}
    for row in moves:
        for definition in definitions:
            key = (row["move_id"], definition.analysis_type)
            counts = metrics[definition.analysis_type]
            counts["total"] += 1
            previous = existing.get(key)
            if key in candidates or previous and (previous["candidate_id"] is not None or previous["coverage_status"] in {"candidate", "rejected"}):
                counts["protected_candidates"] += 1
                if key in candidates:
                    protected.add(candidates[key])
                if previous and previous["candidate_id"] is not None:
                    protected.add(previous["candidate_id"])
                continue
            if previous is None:
                counts["not_selected"] += 1
                continue
            decision = decide(definition, previous)
            if decision == "current":
                counts["current"] += 1
            elif previous["coverage_status"] == "error":
                counts["retryable_errors_not_selected"] += 1
            elif previous["coverage_status"] == "analyzed_no_hit" and str(previous["analyzer_version"]) == str(from_version):
                if decision != "needs_reanalysis":
                    errors.append({"move_id":key[0], "analysis_type":key[1], "message":"Source no-hit requires upstream revalidation; refresh-only rollout refuses it"})
                    counts["errors"] += 1
                    continue
                validate_stored_move(row)
                pending.append({"move_id":key[0], "analysis_type":key[1]})
                counts["pending_stale_no_hits"] += 1
            else:
                counts["not_selected"] += 1
    return {"analyzers":metrics, "errors":errors, "pending_heavy_checks":pending,
            "protected_candidate_ids_in_scope":sorted(protected), "engine_cache":{},
            "refresh_from_version":str(from_version), "static_scout_work":0}

def evidence_summary(row, evidence):
    fields = ("cache_id", "score_type", "score_cp", "mate", "score_pov",
              "best_move_uci", "depth", "nodes", "analysis_profile")
    return {stage: {field: result.get(field) for field in fields}
            for stage, fen in (("before", row["fen_before"]), ("after_played", row["fen_after"]))
            if (result := evidence.positions.get(fen)) is not None}


def plan_negatives(connection: sqlite3.Connection, definitions: Sequence[AnalyzerDefinition],
                   moves: Sequence[sqlite3.Row], evidence: Any,
                   decide: Callable[[AnalyzerDefinition, sqlite3.Row | None], str], *,
                   existing: dict | None = None, tactic_keys: set | None = None) -> tuple[list[dict], dict]:
    """Plan scoped filters and heavy obligations, reusing current durable outcomes.

    Args:
        connection: Caller-owned database connection; this planner never writes.
        definitions: Registered tactic specialists and optional completion contracts.
        moves: Exact stored user moves to inspect.
        evidence: Shared scout evidence service.
        decide: Existing stage-aware coverage currentness function.
        existing: Optional scoped coverage snapshot.
        tactic_keys: Optional canonical candidate identity snapshot.

    Returns:
        Negative-write proposals and structured pending/preflight diagnostics.

    Raises:
        sqlite3.Error: Required database state could not be read.
        ValueError: The optional ledger schema is incompatible.
    """
    from analysis_deferred_repository import DeferredCheckRepository
    deferred = DeferredCheckRepository(connection)
    existing = coverage_rows(connection) if existing is None else existing
    if tactic_keys is None:
        tactic_keys = {(r[0], r[1]) for r in connection.execute("SELECT move_id,tactic_type FROM tactic_candidates")}
    plans, errors, pending = [], [], []
    metrics = {definition.analysis_type: Counter() for definition in definitions}
    for row in moves:
        for definition in definitions:
            key = (row["move_id"], definition.analysis_type)
            previous = existing.get(key)
            counts = metrics[definition.analysis_type]
            decision = decide(definition, previous)
            counts["total"] += 1
            # Preserve all heavy results, even stale ones, plus any canonical
            # candidate without matching coverage. No negative may erase them.
            if previous and (previous["coverage_status"] in PROTECTED_STATUSES or previous["candidate_id"] is not None):
                counts["protected"] += 1
                if previous["coverage_status"] in {"candidate", "rejected"}:
                    counts["candidate_rejected_preserved"] += 1
                counts["current" if decision == "current" else "pending_heavy_refresh"] += 1
                continue
            if key in tactic_keys:
                counts["protected_canonical_candidate"] += 1
                continue
            if decision == "current":
                counts["current"] += 1
                continue
            if deferred.is_current(definition, row):
                counts["current"] += 1
                counts["current_deferred"] += 1
                continue
            counts["examined"] += 1
            try:
                validate_stored_move(row)
                static_rejected = decision != "needs_scout" and not definition.screener(row)
                if static_rejected:
                    if not definition.has_safe_screener:
                        raise ValueError("Unsafe static rejection cannot be persisted")
                    status, scout_version, config = "screened_out", "0", ""
                    details = {"stage": "static", "reason": definition.screen_rejection_reason}
                else:
                    config = definition.scout_config()
                    result = definition.scout(row, evidence)
                    counts["scout_calls"] += 1
                    if config != definition.scout_config():
                        raise ValueError("Scout configuration changed during analysis")
                    if result.send_to_heavy:
                        counts["pending_heavy"] += 1
                        pending.append({"move_id":row["move_id"],"analysis_type":definition.analysis_type})
                        continue
                    status, scout_version = "scouted_out", definition.scout_version
                    details = {"stage": "scout", "reason": result.reason,
                               "evidence": evidence_summary(row, evidence),
                               "interpretation": "no_hit_at_configured_scout_budget"}
                details.update(player_color=row["color"], played_move_uci=row["uci_played"], heavy_analysis_performed=False)
                plans.append({"move_id": row["move_id"], "analysis_type": definition.analysis_type,
                              "coverage_status": status, "screener_version": definition.screener_version,
                              "scout_version": scout_version, "scout_config": config,
                              "analyzer_version": "0", "details_json": json.dumps(details, sort_keys=True)})
                counts[status] += 1
            except (ValueError, chess.engine.EngineError, TimeoutError) as exc:
                counts["errors"] += 1
                errors.append({"move_id": row["move_id"], "analysis_type": definition.analysis_type, "message": str(exc), "error_type": type(exc).__name__})
                if isinstance(exc, (chess.engine.EngineError, TimeoutError)):
                    return plans, {"analyzers": metrics, "errors": errors, "engine_cache": dict(evidence.stats), "pending_heavy_checks":pending}
    report = {"analyzers": metrics, "errors": errors, "engine_cache": dict(evidence.stats), "pending_heavy_checks":pending}
    return plans, apply_existing_preflight(connection, definitions, moves, report)


def preview_heavy_refresh(connection, definitions, moves, evidence, decide):
    """Read-only proposal, never a write/dispatch authorization.

Existing orchestration deliberately protects stale heavy rows. Show stale
no-hit work separately for an explicit future refresh rollout, while protecting
every canonical candidate and candidate/rejected coverage row.
"""
    plans, report = plan_negatives(connection, definitions, moves, evidence, decide)
    existing = coverage_rows(connection)
    canonical = {(r[0], r[1]) for r in connection.execute("SELECT move_id,tactic_type FROM tactic_candidates")}
    by_type = {d.analysis_type: d for d in definitions}
    selected = {r["move_id"] for r in moves}
    proposal = list(report["pending_heavy_checks"])
    for definition in definitions:
        counts = report["analyzers"][definition.analysis_type]
        counts["stale_no_hit_version_only"] = 0
        counts["protected_stale_candidates"] = 0
        counts["refresh_requires_upstream_revalidation"] = 0
    for key, row in existing.items():
        definition = by_type.get(key[1])
        if definition is None or key[0] not in selected:
            continue
        counts = report["analyzers"][definition.analysis_type]
        decision = decide(definition, row)
        if decision == "current":
            continue
        if row["coverage_status"] in {"candidate", "rejected"} or row["candidate_id"] is not None or key in canonical:
            counts["protected_stale_candidates"] += 1
        elif row["coverage_status"] == "analyzed_no_hit":
            if decision == "needs_reanalysis":
                counts["stale_no_hit_version_only"] += 1
                proposal.append({"move_id": key[0], "analysis_type": key[1], "reason": "stale_heavy_version_only"})
            else:
                counts["refresh_requires_upstream_revalidation"] += 1
    report["proposed_heavy_checks"] = proposal
    report["proposed_heavy_by_tactic"] = dict(Counter(p["analysis_type"] for p in proposal))
    report["negative_plan_count"] = len(plans)
    report["proposal_only_not_authorized_dispatch"] = True
    return report



