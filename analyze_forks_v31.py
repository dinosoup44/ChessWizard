"""Opt-in Fork V3.1 proposals: Normal breadth plus bounded shared escalation."""
from copy import deepcopy
from dataclasses import asdict, replace

from analysis_settings import load_profile
from analysis_backbone import AnalysisBackbone
from analyze_forks_v3 import POLICY, PIECE_VALUES, interpret_proof
from analyze_forks_v3_multiline import analyze_existing_candidate as analyze_breadth, analyze_position as analyze_move
from analyze_forks_v3_multiline import evaluate_fork_move as evaluate_move
from candidate_verification_result import CandidateVerificationResult
from fork_robustness import summarize_continuations
from fork_verification_branches import summarize_branch
from proof_escalation import ApprovedPrefixMove, ProofEscalationRequest
from settlement_extension import SettlementExtensionContext, settlement_extension_eligibility

PROOF_SCOPE = "fork_v31_approved_prefix_deep_pv_endpoint_v1"


def _prefix(context, branch):
    board = context.after.copy(stack=False)
    result = []
    for key in ("opponent_move_uci", "player_move_uci"):
        uci = branch.get(key)
        if not uci:
            break
        approval = context.evidence.approved(board.fen())
        result.append(ApprovedPrefixMove(approval, uci))
        board.push_uci(uci)
    return tuple(result)


def review_counterplay(context, branches, results, escalation):
    """Preserve every approved branch; stronger evidence replaces only its own proof."""
    original = summarize_continuations(branches)
    context.details["normal_robustness"] = asdict(original)
    context.details["normal_branches"] = deepcopy(branches)
    attempts = []
    context.details["escalation_attempts"] = attempts
    if original.classification != "ambiguous" or any(b.get("critical_fallback") for b in branches):
        return
    normal_results = {}
    for index, result in escalation.escalate_selected(_selected_requests(context, branches), PIECE_VALUES):
        branch = branches[index]
        reason = "payoff_disagreement" if branch["proof_state"] == "stable" else "proof_unsettled"
        request = ProofEscalationRequest(context.after.fen(), context.row["color"], reason,
            branch["proof_state"], _prefix(context, branch), root_admitted=True)
        normal_results[index] = (request, result)
        _apply_escalation_result(context, branches, results, escalation, index, result)
    if context.profile.escalation.settlement_extension.enabled:
        _extend_pure_window(context, branches, results, escalation, normal_results)


def _extension_context(context, branches):
    """Translate specialist-owned blockers into the shared eligibility contract."""
    blockers = set()
    attempts = context.details.get("escalation_attempts", [])
    if any(a["status"] == "error" for a in attempts):
        blockers.add("operational_error")
    if any(b["proof_state"] in {"mate", "mate_baseline", "deferred", "terminal", "draw", "terminal_after_reply"} for b in branches):
        blockers.add("terminal_or_deferred_ownership")
    if any(b.get("critical_fallback") or b.get("causality_uncertain") for b in branches):
        blockers.add("explicit_causality_uncertainty")
    if context.details.get("causality_uncertain"):
        blockers.add("explicit_causality_uncertainty")
    if any(b["proof_state"] not in {"stable", "unsettled", "mate", "mate_baseline", "draw"} for b in branches):
        blockers.add("incomplete_evidence")
    if any(a["status"] == "incomplete" for a in attempts):
        blockers.add("incomplete_evidence")
    if any(a["status"] == "budget_exhausted" and branches[a["branch_index"]]["proof_state"] != "stable" for a in attempts):
        blockers.add("budget_denial_primary_blocker")
    if summarize_continuations(branches).reason == "acceptable_continuations_disagree":
        blockers.add("genuine_settled_disagreement")
    return SettlementExtensionContext(context.details.get("root_move_passes_gate") is True,
        tuple(sorted(blockers)), (("analyzer", "missed_fork:3.1"),
        ("profile_currentness", context.profile.currentness_identity)))


def _extend_pure_window(context, branches, results, escalation, normal_results):
    decisions = []
    context.details["settlement_extension_eligibility"] = decisions
    for index, (request, normal) in normal_results.items():
        eligibility = settlement_extension_eligibility(normal.proof,
            _extension_context(context, branches), context.profile.escalation.settlement_extension)
        decisions.append({"branch_index": index, **asdict(eligibility)})
        if not eligibility.eligible:
            continue
        result = escalation.extend_settlement(request, normal, eligibility, PIECE_VALUES)
        _apply_escalation_result(context, branches, results, escalation, index, result,
            stage="selective_settlement_extension")


def _apply_escalation_result(context, branches, results, escalation, index, result, *, stage="verification"):
    branch = branches[index]
    reason = "payoff_disagreement" if branch["proof_state"] == "stable" else "proof_unsettled"
    prefix = _prefix(context, branch)
    context.details["escalation_attempts"].append({"branch_index": index, "trigger": reason, "status": result.status,
        "reason": result.reason, "request_identities": result.request_identities,
        "proof": asdict(result.proof) if result.proof else None,
        "escalation_attempt_state": result.escalation_attempt_state,
        "evidence_state": result.evidence_state, **({"evidence_stage": stage} if stage != "verification" else {})})
    branch["escalation_attempt_state"] = result.escalation_attempt_state
    if result.status == "error":
        raise RuntimeError(result.reason)
    if result.status == "not_needed":
        return
    if result.status != "complete" or result.proof is None:
        # Failed/denied rechecks add an attempt record, never erase retained proof.
        # An actual unfinished replacement remains separate evidence for review.
        if result.proof is not None and branch["proof_state"] != "stable":
            branch.update(proof_state=result.proof.state, final_fen=result.proof.final_fen,
                proof_steps=[asdict(step) for step in result.proof.steps],
                proof_line=" ".join([context.row["solution_move_san"], *(step.san for step in result.proof.steps)]))
        return
    proof = result.proof
    if any(score["score_type"] != "cp" for score in context.baseline.values()):
        branch.update(proof_state="mate_baseline", state="ambiguous", classification="ambiguous")
        return
    raw = proof.final_evidence
    final_cp = raw["score_cp"] * (1 if context.row["color"] == "white" else -1)
    details = {"geometric_targets": context.details["geometric_targets"],
               "realizable_scope": "observed_bounded_best_defense_line_only"}
    policy = replace(POLICY, window=proof.window, profile=escalation.profile.generator.engine.profile_id)
    interpreted = interpret_proof(context.row, proof, context.baseline, final_cp, details, policy,
        objective_acceptance="shared_quality_gate", proof_scope=PROOF_SCOPE)
    if len(prefix) != 2:
        branch.update(proof_state="incomplete_prefix", state="ambiguous", classification="ambiguous")
        return
    reply, response = (next(line for line in entry.approval.lines if line.move_uci == entry.move_uci)
                       for entry in prefix)
    line = " ".join([context.row["solution_move_san"], *(step.san for step in proof.steps)])
    branches[index] = summarize_branch(reply, response, proof, line, interpreted, len(results))
    branches[index]["evidence_stage"] = stage
    branches[index]["escalation_attempt_state"] = result.escalation_attempt_state
    results.append(interpreted)


def _selected_requests(context, branches):
    # Unfinished branches block any consensus, so resolve those before disagreements.
    order = sorted(range(len(branches)), key=lambda index: (branches[index]["proof_state"] == "stable", index))
    for index in order:
        robust = summarize_continuations(branches)
        if robust.classification != "ambiguous":
            break
        branch = branches[index]
        if branch["proof_state"] == "stable" and robust.reason != "acceptable_continuations_disagree":
            continue
        reason = "payoff_disagreement" if branch["proof_state"] == "stable" else "proof_unsettled"
        prefix = _prefix(context, branch)
        request = ProofEscalationRequest(context.after.fen(), context.row["color"], reason,
            branch["proof_state"], prefix, root_admitted=True)
        yield index, request

def analyze_existing_candidate(row, breadth_service, verification_service=None, profile=None):
    """Candidate-only adapter; calculation never persists candidates or coverage."""
    return _analyze(row, breadth_service, verification_service, profile)


def analyze_position(row, move_uci, breadth_service, verification_service=None, profile=None):
    """The same V3.1 proof pipeline for one unpersisted, explicitly selected move."""
    return _analyze(row, breadth_service, verification_service, profile, move_uci)


def evaluate_fork_move(row, move_uci, breadth_service, verification_service=None, profile=None):
    """Use unchanged V3.1 proof for a selected move, including an actual played root."""
    return _analyze(row, breadth_service, verification_service, profile, move_uci,
                    move_evaluator=evaluate_move)


def _analyze(row, breadth_service, verification_service, profile, move_uci=None, *, move_evaluator=None):
    move_evaluator = move_evaluator or analyze_move
    profile = profile or load_profile("normal_escalation")
    backbone = AnalysisBackbone(breadth_service, profile, verification_service=verification_service)
    escalation = backbone.escalation
    def review(context, branches, results):
        review_counterplay(context, branches, results, escalation)
    result = (analyze_breadth(row, breadth_service, profile, review_branches=review, backbone=backbone)
              if move_uci is None else move_evaluator(row, move_uci, breadth_service, profile, review_branches=review, backbone=backbone))
    details = {**result.details, "analyzer_version": "3.1", "escalation": escalation.audit()}
    details.setdefault("normal_robustness", {"classification": details["classification"], "reason": details["reason"]})
    details["backbone_provenance"] = asdict(backbone.provenance("missed_fork", "3.1",
        interpretation_policy={"fork_policy": asdict(POLICY), "proof_scope": PROOF_SCOPE}))
    state = "ambiguous" if details["classification"] == "ambiguous" else result.state
    return CandidateVerificationResult(state, result.candidate, details, result.opportunity)
