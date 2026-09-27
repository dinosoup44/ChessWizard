"""Opt-in Pin V2 read-only verification; no registry, engine lifecycle or persistence."""
from dataclasses import dataclass, replace
from analysis_results import HeavyResult
from tactical_opportunities import TacticalOutcome
import chess
from analysis_backbone import AnalysisBackbone
from analysis_states import EvidenceState
from analyze_pins_v2 import analyze_single_move, ANALYZER_VERSION
from approved_bounded_proof import verify_approved_bounded_line
from candidate_lines import to_data
from candidate_line_proof import IncompleteLineEvidence
from candidate_verification_result import CandidateVerificationResult
from pin_consensus import branch_consensus, motif_consensus
from threshold_review import ThresholdReviewService
from proof_escalation import EscalationBudgetReached
from pin_analysis_settings import PinBackbonePolicy, PinPolicy, pin_profile, pin_evaluation_profiles
from pin_geometry import pinning_moves, PIECE_VALUES
from position_line_replay import RecordedPositionReplay
from proof_escalation import ApprovedPrefixMove, ProofEscalationRequest
from settlement_evidence import settlement_evidence
from tactical_proof import verify_bounded_line


@dataclass(frozen=True)
class PinReplay:
    result: HeavyResult
    provenance: dict
    settlements: tuple


def replay_single_position(row, lookup, *, policy=PinPolicy()):
    """Exact legacy-result equivalence via recorded one-line evidence, with no fallback."""
    backbones = {key: AnalysisBackbone(None, profile) for key, profile in pin_evaluation_profiles().items()}
    evidence = RecordedPositionReplay(lookup, backbones)
    settlements = []
    def prove(after, color, evaluate, values, window):
        proof = verify_bounded_line(after, color, evaluate, values, window)
        settlements.append(settlement_evidence(after.fen(), "white" if color else "black", proof,
            profile_identity="recorded:tactic_verify_v1", evidence_requests=tuple(sorted(
                (fen, source) for (fen, key), source in evidence.sources.items()
                if key == "tactic_verify_v1" and fen in {proof.final_fen, *(s.before_fen for s in proof.steps)}))))
        return proof
    result = analyze_single_move(row, evidence.evaluate, proof_solver=prove, policy=policy)
    provenance = {key: to_data(backbone.provenance("missed_pin", ANALYZER_VERSION,
        interpretation_policy=policy)) for key, backbone in backbones.items()}
    return PinReplay(result, {"source": "recorded_single_pv_not_new_cache", "new_cache_requested":False,
        "profile_templates": provenance, "recorded_requests":tuple(sorted((fen, key, source)
        for (fen, key), source in evidence.sources.items()))}, tuple(settlements))


def analyze_candidate_position(row, move_uci, line_service, *, profile=None, policy=PinPolicy(), quick_profile=None, backbone_policy=PinBackbonePolicy()):
    """Inspect one explicit move. Never discover extra root candidates or write proposals."""
    profile = profile or pin_profile()
    if profile.proof != policy.proof or profile.escalation.proof != policy.proof:
        raise ValueError("Pin V2 breadth and escalation must preserve the same proof window")
    backbone = AnalysisBackbone(line_service, profile, escalation_solver=verify_approved_bounded_line)
    evaluations = {key: AnalysisBackbone(line_service, value) for key, value in pin_evaluation_profiles(profile, quick_profile).items()}
    boundary = None
    interpretation = {"pin":to_data(policy), "backbone":to_data(backbone_policy)}
    audit = {"move_uci": move_uci, "root_move_passes_gate": None, "branches": []}
    def finish(classification, chosen=None):
        audit["boundary_review"] = boundary.audit() if boundary else {"entered":False}
        audit["backbone_policy"] = to_data(backbone_policy)
        audit.update(classification=classification, escalation=backbone.escalation.audit(),
            backbone_provenance=to_data(backbone.provenance("missed_pin", ANALYZER_VERSION, interpretation_policy=interpretation)),
            evaluation_provenance={k: to_data(v.provenance("missed_pin", ANALYZER_VERSION, interpretation_policy=interpretation))
                                   for k, v in evaluations.items()})
        state = {"verified": "candidate", "verified_payoff_changed": "candidate", "rejected": "analyzed_no_hit",
                 "ambiguous": "ambiguous", "error": "error"}[classification]
        return CandidateVerificationResult(state, chosen.candidate if chosen else None, audit,
                                           chosen.opportunity if chosen else None)
    try:
        choices = [c for c in pinning_moves(chess.Board(row["fen_before"]), row["uci_played"]) if c.move_uci == move_uci]
        if not choices:
            audit["reason"] = "no_new_direct_pin"
            return finish("rejected")
        choice = choices[0]
        audit["pin_relationships"] = [{"pin_type":p.pin_type, "attacker":to_data(p.attacker),
            "pinned":to_data(p.pinned), "rear_target":to_data(p.behind)} for p in choice.pins]
        admission = backbone.admit(row["fen_before"], move_uci)
        if admission.approved.state == "incomplete":
            raise IncompleteLineEvidence("Root admission incomplete")
        decision = admission.decision
        admitted = bool(decision and decision.normal_accepted)
        audit["root_move_passes_gate"] = admitted
        audit["root_gate"] = to_data(admission.approved)
        audit["scale"] = to_data(backbone.weigh(admission.approved))
        if not admitted:
            audit["evidence_state"] = EvidenceState.REJECTED_BY_QUALITY_GATE
            return finish("rejected")
        defense = backbone.request(choice.fen_after)
        if defense.state == "incomplete":
            raise IncompleteLineEvidence("Defense admission incomplete")
        if defense.forced_deterioration or not defense.lines:
            audit["evidence_state"] = EvidenceState.PROOF_DEFERRED
            return finish("ambiguous")
        player = row["color"]
        branches = []
        def evaluate(fen, key):
            return evaluations[key].evidence.raw(fen)
        def interpret(prefix, supplied=None):
            proofs = []
            def prove(after, color, unused, values, window):
                proof = supplied or verify_approved_bounded_line(after, color, prefix,
                    evaluations["tactic_verify_v1"].evidence.best, values, window)
                proofs.append(proof)
                return proof
            result = analyze_single_move(row, evaluate, choices=choices, proof_solver=prove, policy=policy,
                proof_depth=evaluations["tactic_verify_v1"].profile.generator.engine.depth)
            unresolved = any(p.state != "stable" for p in proofs)
            deferred = result.details.get("reason") == "mate_score_deferred" or any(
                r.get("reason") == "mate_alternative_deferred" for r in result.details.get("rejections", []))
            state = "ambiguous" if unresolved or deferred else result.state
            details = dict(result.details)
            if deferred or any(p.state in {"mate", "draw"} for p in proofs):
                details["evidence_state"] = EvidenceState.PROOF_DEFERRED
            elif unresolved:
                details["evidence_state"] = EvidenceState.PROOF_UNSETTLED
            normalized = CandidateVerificationResult(state, result.candidate, details, result.opportunity)
            return normalized, proofs
        for line in defense.lines:
            prefix = (ApprovedPrefixMove(defense, line.move_uci),)
            result, proofs = interpret(prefix)
            branches.append([prefix, result, proofs])
        # A failed comparison can request one stronger evidence set, never a discounted threshold.
        failures = branches[0][1].details.get("rejections", []) if branches else []
        edge = next((r for r in failures if r.get("reason")=="insufficient_deep_gain"
            and r.get("gain_cp") is not None and r.get("drop_from_best_cp",0)<=policy.verify_max_drop_cp
            and backbone_policy.boundary.requires_review(r["gain_cp"],policy.verify_min_gain_cp)),None)
        if edge:
            boundary = ThresholdReviewService(line_service, evaluations["tactic_verify_v1"].profile, backbone_policy.boundary)
            decision = boundary.review_gain(row["fen_before"],row["fen_after"],choice.fen_after,player,
                edge["gain_cp"],policy.verify_min_gain_cp)
            if decision.state=="deferred":
                audit["evidence_state"]=EvidenceState.PROOF_DEFERRED
                return finish("ambiguous")
            evaluations["tactic_verify_v1"] = boundary.backbone
            audit["before_boundary_branches"] = [to_data(b[1]) for b in branches]
            branches = [[prefix, *interpret(prefix)] for prefix, _, _ in branches]
        initial, _ = branch_consensus([b[1] for b in branches], backbone_policy)
        def selections():
            if boundary is not None:
                return  # Confirmation is one bounded stronger pass; never fall back to depth 18.
            for index, (prefix, result, proofs) in enumerate(branches):
                # Stable positional/no-hit consensus does not justify extra searches.
                if proofs and (proofs[-1].state not in {"stable", "mate", "draw"} or
                               (initial == "ambiguous" and proofs[-1].state == "stable")):
                    reason = "payoff_disagreement" if proofs[-1].state == "stable" else "proof_unsettled"
                    yield index, ProofEscalationRequest(choice.fen_after, player, reason, proofs[-1].state, prefix)
        for index, escalated in backbone.escalation.escalate_selected(selections(), PIECE_VALUES):
            prefix, old, proofs = branches[index]
            if escalated.status == "complete":
                result, proofs = interpret(prefix, escalated.proof)
                branches[index] = [prefix, result, proofs]
            elif escalated.status == "error":
                branches[index][1] = CandidateVerificationResult("error", details={**old.details, "escalation_status":escalated.status, "escalation_reason":escalated.reason})
            elif escalated.status != "not_needed":
                branches[index][1] = CandidateVerificationResult("ambiguous", details={**old.details, "escalation_status":escalated.status, "escalation_reason":escalated.reason})
        for prefix, result, proofs in branches:
            audit["branches"].append({"defense_uci": prefix[0].move_uci, "state": result.state,
                "result": to_data(result), "settlements": [to_data(settlement_evidence(choice.fen_after, player, p,
                profile_identity=evaluations["tactic_verify_v1"].profile.currentness_identity,
                evidence_requests=proof_requests(p, prefix, evaluations["tactic_verify_v1"].evidence,
                                                 backbone.escalation.evidence))) for p in proofs]})
        classification, chosen = branch_consensus([b[1] for b in branches], backbone_policy)
        audit.update(motif_consensus([b[1] for b in branches]))
        audit["continuation_count_considered"] = len(branches)
        audit["branches_settled"] = sum(bool(b[2]) and b[2][-1].state == "stable" for b in branches)
        audit["payoff_consensus"] = classification
        audit["robustness"] = pin_robustness(audit["branches"])
        return finish(classification, chosen)
    except (IncompleteLineEvidence, EscalationBudgetReached) as error:
        audit.update(reason=str(error), evidence_state=EvidenceState.INCOMPLETE)
        return finish("ambiguous")
    except Exception as error:
        audit.update(reason=f"{type(error).__name__}: {error}", evidence_state=EvidenceState.EXECUTION_ERROR)
        return finish("error")


def pin_robustness(branches):
    """Summarize Pin identities/causality without borrowing Fork target semantics."""
    summaries = [summary for b in branches for summary in (
        *b["result"]["details"].get("rejections", []),
        *([b["result"]["details"]["selected"]] if "selected" in b["result"]["details"] else []))
        if "attribution" in summary]
    material = [s["retained_material_cp"] for s in summaries]
    evaluations = [s["evaluation_player_cp"]["final"] for s in summaries]
    causal = sorted({s["attribution"]["kind"] for s in summaries})
    identities = sorted({(s["pin_type"], s["pinned_square"]) for s in summaries})
    return {"proof_states":[s["state"] for b in branches for s in b["settlements"]],
        "material_gain_range_cp":[min(material), max(material)] if material else None,
        "evaluation_range_cp":[min(evaluations), max(evaluations)] if evaluations else None,
        "causality_observed":causal, "causality_consensus":len(causal)==1 if causal else None,
        "pin_identities":identities,
        "relationship_survival":sorted({s["attribution"]["relationship_survived"] for s in summaries})}


def analyze_existing_candidate(row, line_service, profile=None):
    """Candidate-verification registry contract, anchored to the stored solution move."""
    return analyze_candidate_position(row, row["solution_move_uci"], line_service, profile=profile)


def proof_requests(proof, prefix, *sources):
    """Attach only position requests used by this proof, including its approved entry."""
    positions = {proof.final_fen, *(step.before_fen for step in proof.steps)}
    requests = {entry.approval.source.fen:entry.approval.source.engine_identity for entry in prefix
                if entry.approval.source.fen in positions}
    for source in sources:
        for fen in positions - requests.keys():
            if fen in source.positions:
                requests[fen] = source.positions[fen].source.engine_identity
    return tuple(sorted(requests.items()))
