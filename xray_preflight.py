"""X-ray policy over existing cache/ownership only; no geometry or score changes."""
from dataclasses import asdict
from typing import Any
import chess
from analysis_preflight import PreflightResult
from analysis_scout import validate_stored_move
from analyze_xrays import ANALYZER_VERSION, POLICY
from engine_cache import score_for_color
from xray_geometry import xray_moves

PREFLIGHT_VERSION = "1"


def preflight_existing_evidence(row, context):
    provenance = {"preflight_version":PREFLIGHT_VERSION, "analyzer_version":context.analyzer_version,
                  "policy":asdict(POLICY), "mate_policy":"xray_material_baseline_mate_deferral",
                  "ownership_policy":"other_canonical_same_move_and_solution_v1",
                  "ownership_requires_transactional_recheck":True, "evidence":[], "alternatives":[]}
    def result(disposition, reason):
        return PreflightResult(disposition, reason, provenance)
    if context.analyzer_version != ANALYZER_VERSION:
        return result("heavy_required", "unsupported_analyzer_version")
    provenance["quick_profile_identity"] = context.positions.identity(POLICY.quick_profile)
    validate_stored_move(row)
    # Checkmate only: played draws/stalemates can still miss a winning tactic.
    if chess.Board(row["fen_after"]).is_checkmate():
        provenance["terminal_fact"] = {"played_uci":row["uci_played"], "fen_after":row["fen_after"], "checkmate":True}
        return result("played_checkmate", "actual_played_move_delivered_checkmate")
    choices = tuple(xray_moves(chess.Board(row["fen_before"]), row["uci_played"]))
    if not choices:
        return result("heavy_required", "no_alternatives_requires_revalidation")
    color = row["color"] == "white"
    def read(fen, role):
        lookup = context.positions.position(fen, POLICY.quick_profile)
        entry = {"role":role, "key":lookup.key, "availability":lookup.reason}
        if lookup.available:
            score = score_for_color(lookup.record, color)
            entry.update(cache_id=lookup.record["cache_id"], score=score)
        else:
            score = None
            provenance["missing_or_incompatible_evidence"] = True
        provenance["evidence"].append(entry)
        return score
    before, played = read(row["fen_before"], "before"), read(row["fen_after"], "played")
    if before is not None and played is not None and any(s["score_type"] == "mate" for s in (before, played)):
        return result("mate_deferred", "current_quick_baseline_requires_material_mate_deferral")
    all_failed, all_owned = True, True
    any_passed = False
    for choice in choices:
        score = read(choice.fen_after, choice.move_uci)
        owner = context.ownership.owner(row["move_id"], context.analysis_type, choice.move_uci)
        cp = all(s is not None and s["score_type"] == "cp" for s in (before, played, score))
        failed = (score["score_cp"]-played["score_cp"] < POLICY.quick_gain_cp or
                  before["score_cp"]-score["score_cp"] > POLICY.quick_drop_cp) if cp else None
        all_failed = all_failed and failed is True
        all_owned = all_owned and owner is not None
        any_passed = any_passed or failed is False
        provenance["alternatives"].append({"move_uci":choice.move_uci, "move_san":choice.move_san,
            "quick_gate":"rejected" if failed is True else "passes" if failed is False else "unresolved",
            "owner":owner})
    if all_failed:
        return result("cached_quick_rejected", "every_geometric_alternative_fails_current_cached_quick_policy")
    if all_owned:
        return result("already_owned", "every_geometric_alternative_has_another_canonical_owner")
    # Do not combine ownership with quick failures to remove a position: the
    # approved predicates each require all alternatives to satisfy that rule.
    return result("heavy_required", "quick_gate_survives" if any_passed else "unresolved_alternatives")


def deferred_contract_identity() -> dict[str, Any]:
    """Expose existing preflight policy for conservative receipt invalidation.

    Returns:
        Existing policy and raw request identities; no thresholds are changed.
    """
    from existing_position_evidence import position_evidence_identity
    return {"preflight_version":PREFLIGHT_VERSION, "specialist_version":ANALYZER_VERSION,
            "policy":asdict(POLICY), "mate_policy":"xray_material_baseline_mate_deferral",
            "ownership_policy":"other_canonical_same_move_and_solution_v1",
            "quick_profile_identity":position_evidence_identity(POLICY.quick_profile)}
