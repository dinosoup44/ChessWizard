"""Verify one existing stored fork, never discover moves or access persistence."""
from dataclasses import asdict, dataclass
import json
import chess
from analysis_results import HeavyResult
from analysis_scout import validate_stored_move
from board_analysis import attacked_pieces, attackers, material_balance, capture_square
from engine_cache import score_for_color
from tactical_proof import ProofWindow, validate_evaluation, verify_bounded_line
from tactical_target_proof import trace_target_settlement
from tactical_opportunities import (Evaluation, ProofEvidence, TacticalMotif, TacticalOpportunity,
                                    TacticalOutcome, TacticalPresentation)

ANALYZER_VERSION = "3"
PIECE_VALUES = {chess.PAWN:100,chess.KNIGHT:300,chess.BISHOP:300,chess.ROOK:500,chess.QUEEN:900,chess.KING:0}


@dataclass(frozen=True)
class ForkVerificationPolicy:
    profile: str = "tactic_verify_v1"
    window: ProofWindow = ProofWindow()
    meaningful_gain_cp: int = 150
    acceptable_floor_cp: int = -100
    winning_floor_cp: int = 300
    acceptable_drop_cp: int = 150
    minimum_related_cp: int = 100


POLICY = ForkVerificationPolicy()


def evaluation_acceptance(before, played, tactic, final, policy=POLICY):
    """No move-rank/#1 requirement; retain improvement or sound alternatives."""
    floor = min(tactic,final)
    if floor < policy.acceptable_floor_cp: return None
    if floor-played >= policy.meaningful_gain_cp: return "meaningful_improvement"
    if floor >= policy.winning_floor_cp: return "preserves_winning_position"
    if before-floor <= policy.acceptable_drop_cp: return "preserves_acceptable_position"
    return None


def analyze_existing_candidate(row, analyze_fen, policy=POLICY):
    if not row.get("candidate_id") or row.get("tactic_type")!="missed_fork":
        raise ValueError("Fork V3 requires an existing fork candidate")
    if row.get("candidate_status")!="candidate" or str(row.get("detector_version"))!="2":
        raise ValueError("Only explicitly selected active Fork V2 candidates are eligible")
    validate_stored_move(row)
    board = chess.Board(row["fen_before"])
    move = board.parse_uci(row["solution_move_uci"])
    if board.san(move)!=row["solution_move_san"]: raise ValueError("Stored fork identity conflicts")
    color = board.turn
    after = board.copy(stack=False);after.push(move)
    targets = attacked_pieces(after,move.to_square,target_color=not color,
        piece_types=(chess.KNIGHT,chess.BISHOP,chess.ROOK,chess.QUEEN,chess.KING))
    geometry = [{"piece":chess.piece_name(t.piece_type),"square":chess.square_name(t.square),
                 "defenders":[chess.square_name(s) for s in attackers(after,t.square,not color)]} for t in targets]
    details = {"candidate_id":row["candidate_id"],"analyzer_version":ANALYZER_VERSION,
               "geometric_targets":geometry,"policy":asdict(policy),"realizable_scope":"observed_bounded_best_defense_line_only"}
    def reject(reason, ambiguous=False):
        return HeavyResult("error" if ambiguous else "analyzed_no_hit",details={**details,"reason":reason,
                           "classification":"ambiguous" if ambiguous else "rejected"})
    if len(targets)<2: return reject("stored_move_no_longer_has_fork_geometry")
    cache,evidence = {},[]
    def raw(fen):
        if fen not in cache:
            value = validate_evaluation(analyze_fen(fen,policy.profile));cache[fen]=value
            evidence.append({"cache_id":value.get("cache_id"),"profile":policy.profile})
        return cache[fen]
    def score(fen): return score_for_color(raw(fen),color)
    baseline = {"before":score(row["fen_before"]),"played":score(row["fen_after"]),"tactic":score(after.fen())}
    details["evaluations"] = baseline
    details["evidence"] = evidence
    if any(s["score_type"]!="cp" for s in baseline.values()):
        return reject("mate_evidence_requires_separate_review",True)
    proof = verify_bounded_line(after,color,raw,PIECE_VALUES,policy.window)
    line = " ".join([row["solution_move_san"],*(s.san for s in proof.steps)])
    details.update(proof_state=proof.state,proof_line=line,proof_steps=[asdict(s) for s in proof.steps],final_fen=proof.final_fen)
    if proof.state!="stable": return reject("proof_"+proof.state,True)
    return interpret_proof(row,proof,baseline,score(proof.final_fen)["score_cp"],details,policy)


def interpret_proof(row, proof, baseline, final_cp, details, policy=POLICY, *,
                    objective_acceptance=None, proof_scope="fork_v3_depth18_each_ply_bounded_best_line_not_exhaustive"):
    """Interpret an already-computed stable proof; no engine calls or persistence."""
    if proof.state != "stable":
        raise ValueError("Only stable proof can be interpreted as completed evidence")
    details = dict(details)
    details["interpretation_version"] = "fork_v3_target_payoff_v1"
    board = chess.Board(row["fen_before"])
    color = board.turn
    move = board.parse_uci(row["solution_move_uci"])
    after = board.copy(stack=False); after.push(move)
    targets = attacked_pieces(after,move.to_square,target_color=not color,
        piece_types=(chess.KNIGHT,chess.BISHOP,chess.ROOK,chess.QUEEN,chess.KING))
    geometry = details["geometric_targets"]
    line = " ".join([row["solution_move_san"],*(s.san for s in proof.steps)])
    def reject(reason):
        return HeavyResult("analyzed_no_hit",details={**details,"reason":reason,"classification":"rejected"})
    settlement = trace_target_settlement(after,move.to_square,targets,proof,PIECE_VALUES)
    initial = material_balance(board,color,PIECE_VALUES)
    after_material = material_balance(after,color,PIECE_VALUES)
    final = material_balance(chess.Board(proof.final_fen),color,PIECE_VALUES)
    sequence = next((s.material_cp for s in reversed(proof.steps) if s.in_payoff_window),after_material)
    scores = {k:s["score_cp"] for k,s in baseline.items()}
    scores["final"] = final_cp
    details["evaluation_player_cp"] = scores
    actual = [g for t,g in zip(targets,geometry) if t.square in settlement.captured_targets]
    acceptance = objective_acceptance or evaluation_acceptance(**scores,policy=policy)
    captured_square = capture_square(board,move)
    initial_capture = board.piece_at(captured_square) if captured_square is not None else None
    initial_capture_cp = PIECE_VALUES[initial_capture.piece_type] if initial_capture else 0
    retained_sequence = settlement.attributable_cp + initial_capture_cp if actual else 0
    realizable = actual if acceptance and retained_sequence>=policy.minimum_related_cp and final-initial>=policy.minimum_related_cp else []
    details.update(realizable_targets=realizable,captured_geometric_targets=actual,realized_payoff={"net_material_cp":final-initial,
        "material_before_cp":initial,"material_after_fork_cp":after_material,
        "material_after_sequence_cp":sequence,"material_settled_cp":final,
        "fork_attributable_cp":settlement.attributable_cp,"initial_capture_cp":initial_capture_cp,
        "move_sequence_retained_cp":retained_sequence},settlement=asdict(settlement),
        best_response_changed=(line.split()[1:2] != (row.get("solution_line") or "").split()[1:2]),
        geometric_vs_realizable_differ=(len(realizable)!=len(geometry)))
    if acceptance is None: return reject("settled_evaluation_not_acceptable")
    if not actual: return reject("no_target_realized_in_bounded_best_line")
    if retained_sequence < policy.minimum_related_cp or final-initial < policy.minimum_related_cp:
        return reject("target_gain_not_retained_after_counterplay")
    gain = min(retained_sequence,final-initial)
    causal_fork = settlement.attributable_cp >= policy.minimum_related_cp
    piece = max(actual,key=lambda t:PIECE_VALUES[chess.PIECE_NAMES.index(t["piece"])] )["piece"]
    value = PIECE_VALUES[chess.PIECE_NAMES.index(piece)]
    kind = ("win_exchange" if gain==200 and piece=="rook" else
            "win_queen" if piece=="queen" and gain>=value else "win_rook" if piece=="rook" and gain>=value else
            "win_piece" if piece in {"bishop","knight"} and gain>=value else "force_favorable_exchange")
    if not causal_fork and initial_capture and gain>=initial_capture_cp:
        piece = chess.piece_name(initial_capture.piece_type)
        kind = "win_pawn" if piece=="pawn" else "force_favorable_exchange"
    captures = settlement.target_captures
    rationale = "The original fork attacker captures an attacked target under the selected best-defense continuation; retained target value accounts for all own losses through settlement."
    if not causal_fork:
        rationale = "The move's initial capture remains after the target exchange and counterplay; the fork geometry alone does not establish additional net material gain."
    opportunity = TacticalOpportunity(TacticalOutcome(kind,piece),
        (TacticalMotif("fork",causal_fork,"supported" if causal_fork else "context_only",rationale),),
        payoff_timing="immediate" if settlement.payoff_user_move==1 else "delayed",
        proof=ProofEvidence(played_move_uci=row["uci_played"],tactical_move_uci=move.uci(),line_san=line,
            best_defense_uci=proof.steps[0].uci,window_user_moves=policy.window.user_moves,
            scope=proof_scope,score_pov=row["color"],
            material_before_cp=initial,material_after_cp=final,material_value_profile="P100_N300_B300_R500_Q900_K0",
            evaluation_before=Evaluation(cp=scores["before"]),evaluation_after_played=Evaluation(cp=scores["played"]),
            evaluation_after_tactic=Evaluation(cp=scores["tactic"]),evaluation_after_settlement=Evaluation(cp=scores["final"]),
            best_defense_checked=True,settled_position_reached=True,retained_material_gain_cp=final-initial),
        presentation=TacticalPresentation("strong_callout" if causal_fork and gain>=300 else "secondary_motif",explanation=rationale),
        metadata={"geometric_targets":geometry,"realizable_targets":actual,"realized_payoff":details["realized_payoff"],
                  "target_captures":list(captures),"realizable_scope":details["realizable_scope"],"evaluation_acceptance":acceptance})
    old = json.loads(row.get("metadata_json") or "{}")
    previous_piece = old.get("realization",{}).get("won_piece")
    # New discovery has no historical target/defense to compare against.
    changed = (not causal_fork or gain<value or bool(row.get("candidate_id")) and
               (previous_piece!=piece or details["best_response_changed"]))
    details.update(reason="fork_v3_verified",classification="verified_payoff_changed" if changed else "verified",
                   evaluation_acceptance=acceptance)
    metadata = {"fork_v3":{k:v for k,v in details.items() if k not in {"proof_steps","evidence"}},
                "analyzer":"missed_fork","analyzer_version":ANALYZER_VERSION}
    payload = {"candidate_status":"candidate","confidence":row.get("confidence"),"detector_version":3,
               "solution_move_uci":move.uci(),"solution_move_san":row["solution_move_san"],"solution_line":line,
               "notes":rationale,"metadata_json":json.dumps(metadata,sort_keys=True)}
    return HeavyResult("candidate",payload,details,opportunity)
