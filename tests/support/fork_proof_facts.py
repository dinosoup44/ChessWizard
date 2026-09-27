"""Read-only explanation of recorded proof states; never changes an analyzer verdict."""
from collections import Counter
import chess

CAUSES=("settlement_window_exhausted","branch_limit_exhausted","request_limit_exhausted","child_depth_limit","engine_depth_insufficient","unresolved_recapture","unresolved_counter_capture","unresolved_forcing_sequence","mate_deferred","continuation_missing","genuine_branch_disagreement","geometry/payoff_causality_uncertain","other")


def recorded_cause(row: dict, details: dict) -> dict:
    """Explain supplied proof-state metadata without changing analyzer truth.

    Args:
        row: Supplied position/move record.
        details: Supplied analyzer details; never regenerated here.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    attempts=details.get("escalation_attempts",[]);reasons={a["reason"] for a in attempts}
    normal=details.get("normal_branches",details.get("branches",[]));states={b["proof_state"] for b in normal+details.get("branches",[])}
    after=chess.Board(row["fen_before"])
    after.push_uci(details["root_admission"]["required_move"])
    played=chess.Board(row["fen_after"])
    flags=[]
    if details["reason"]=="acceptable_continuations_disagree":flags.append("genuine_branch_disagreement")
    if played.is_checkmate() or after.is_checkmate() or any("mate" in state for state in states) or any(a["reason"]=="mate" or (a.get("proof") or {}).get("state")=="mate" for a in attempts):flags.append("mate_deferred")
    if "branch_limit" in reasons:flags.append("branch_limit_exhausted")
    if "verification_request_limit" in reasons:flags.append("request_limit_exhausted")
    if "child_depth_limit" in reasons:flags.append("child_depth_limit")
    if any(a.get("proof") and a["proof"]["state"]=="unsettled" and len(a["proof"]["steps"])==2*a["proof"]["window"]["user_moves"]+1+a["proof"]["window"]["settlement_plies"] for a in attempts):flags.append("settlement_window_exhausted")
    if details["reason"]=="incomplete_continuation_evidence" and not played.is_game_over() and not after.is_game_over():flags.append("continuation_missing")
    if any(b.get("critical_fallback") for b in normal):flags.append("geometry/payoff_causality_uncertain")
    if not flags:flags.append("other")
    relabels=[a["branch_index"] for a in attempts if a["status"]=="budget_exhausted" and a.get("proof") is None and normal[a["branch_index"]]["proof_state"]=="stable"]
    return {"primary":flags[0],"secondary":flags[1:],"stable_evidence_relabel_branches":relabels,
        "played_terminal":str(played.outcome()) if played.is_game_over() else None,"tactical_terminal":str(after.outcome()) if after.is_game_over() else None,
        "bounds_hit":sorted(reasons&{"branch_limit","verification_request_limit","child_depth_limit"}),
        "precedence":"Settled contradiction, then terminal/mate blocker, branch/request/child bound, actual settlement bound, missing evidence, critical fallback. Secondary bounds remain explicit; this is diagnostic precedence, not exclusive causal proof."}


def retained_branch_evidence(details: dict, index: int) -> dict:
    """Keep an existing proof when a denied recheck supplies no replacement.

    Args:
        details: Supplied analyzer details; never regenerated here.
        index: Zero-based branch index.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    branch=details["branches"][index]
    attempt=next((a for a in reversed(details.get("escalation_attempts",[])) if a["branch_index"]==index),None)
    if attempt and attempt.get("proof"):
        proof=attempt["proof"]
        return {"source":"latest_escalation_proof","state":proof["state"],"fen":proof["final_fen"],"steps":proof["steps"],"raw":proof["final_evidence"],"window":proof["window"],"attempt":attempt}
    normal=details.get("normal_branches",details["branches"])[index]
    retained=normal if attempt and attempt["status"]=="budget_exhausted" else branch
    return {"source":"retained_normal_proof" if retained is normal else "recorded_branch","state":retained["proof_state"],"fen":retained.get("final_fen"),"line":retained.get("proof_line"),"window":details["profile"]["proof"],"attempt":attempt}


def common_outcome(details: dict) -> dict:
    """Find conservative shared payoff claims across supplied branches.

    Args:
        details: Supplied analyzer details; never regenerated here.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    branches=details.get("branches",[])
    all_stable=bool(branches) and all(b["proof_state"]=="stable" and not b.get("critical_fallback") for b in branches)
    supported=all_stable and all(b["state"]=="candidate" and b.get("payoff_signature",[None,None])[1]=="supported" and b.get("retained_related_cp",0)>0 for b in branches)
    return {"all_settled":all_stable,"causal_payoff_survives_all":supported,"conservative_common_outcome_supported":supported,
        "target_disagreement":len({tuple(b.get("realizable_target_squares",[])) for b in branches})>1,
        "payoff_amounts":sorted({b.get("retained_related_cp",0) for b in branches}),
        "hit_vs_no_hit_disagreement":len({b["state"]=="candidate" for b in branches})>1,
        "attribution":"primary" if not supported else "supported_primary_with_amount_or_target_variance"}


