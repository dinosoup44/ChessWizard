"""Outcome-first X-ray interpretation; no persistence or engine access."""
import chess
from tactical_opportunities import (Attribution, Evaluation, LineRelationship, PayoffTiming,
    PieceReference, PresentationLevel, ProofEvidence, TacticalMotif, TacticalOpportunity,
    TacticalOutcome, TacticalPresentation)
from xray_geometry import PIECE_VALUES


def xray_opportunity(row, choice, line, assessment, attribution):
    resolution, proof, scores = attribution.resolution, assessment.proof, assessment.scores["deep"]
    rear = chess.piece_name(line.rear.piece_type)
    gain = resolution.related_material_cp
    if gain >= PIECE_VALUES[line.rear.piece_type] and not resolution.attacker_exchanged:
        kind = {"queen":"win_queen", "rook":"win_rook"}.get(rear, "win_piece")
        title = f"Win the {rear}"
    elif rear == "rook" and gain == 200:
        kind, title = "win_exchange", "Win the exchange"
    else:
        kind, title = "force_favorable_exchange", "Gain material through an exchange"
    motifs = [TacticalMotif("xray", True, Attribution.SUPPORTED, attribution.rationale)]
    if resolution.resolution == "removed_by_other_piece":
        motifs.append(TacticalMotif("removal_of_defender", False, Attribution.SUPPORTED,
            "Another piece captures the intervening blocker before the slider wins the rear target."))
    if line.front.color != line.attacker.color and PIECE_VALUES[line.front.piece_type] < PIECE_VALUES[line.rear.piece_type]:
        motifs.append(TacticalMotif("pin", False, Attribution.CONTEXT_ONLY,
            "Relative-pin geometry is present, but this proof credits removal of the blocker, not a proven movement constraint."))
    if resolution.attacker_exchanged or (line.front.color == line.attacker.color and resolution.resolution == "captured_by_rear"):
        motifs.append(TacticalMotif("sacrifice", False, Attribution.SUPPORTED,
            "The related gain remains after charging the sacrificed line participant."))
    def ref(p):
        return PieceReference(chess.piece_name(p.piece_type), "white" if p.color else "black", chess.square_name(p.square))
    evidence = ProofEvidence(played_move_uci=row["uci_played"], tactical_move_uci=choice.move_uci,
        line_san=" ".join([choice.move_san, *(step.san for step in proof.steps)]),
        best_defense_uci=proof.steps[0].uci, window_user_moves=proof.window.user_moves,
        scope=f"{proof.window.version}_depth18_each_ply_plus_{proof.window.settlement_plies}_settlement_plies_not_exhaustive",
        score_pov=row["color"], material_before_cp=assessment.initial_cp, material_after_cp=assessment.final_cp,
        material_value_profile="P100_N300_B300_R500_Q900_K0",
        evaluation_before=Evaluation(cp=scores["before"]), evaluation_after_played=Evaluation(cp=scores["played"]),
        evaluation_after_tactic=Evaluation(cp=scores["tactic"]), evaluation_after_settlement=Evaluation(cp=scores["final"]),
        best_defense_checked=True, settled_position_reached=True, relationship_survived=resolution.relationship_survived,
        retained_material_gain_cp=assessment.final_cp-assessment.initial_cp)
    level = PresentationLevel.SECONDARY_MOTIF if kind == "force_favorable_exchange" else PresentationLevel.STRONG_CALLOUT
    return TacticalOpportunity(TacticalOutcome(kind, rear), tuple(motifs),
        PayoffTiming.IMMEDIATE if resolution.payoff_user_move == 1 else PayoffTiming.DELAYED,
        evidence, TacticalPresentation(level, title, attribution.rationale),
        (LineRelationship("xray", ref(line.attacker), ref(line.rear), ref(line.front),
                          tuple(chess.square_name(p.square) for p in (line.attacker,line.front,line.rear)), line.step),),
        {"blocker_resolution":resolution.resolution, "blocker_resolution_ply":resolution.resolution_ply,
         "related_retained_material_cp":gain, "payoff_user_move":resolution.payoff_user_move,
         "attacker_exchanged":resolution.attacker_exchanged,
         "settlement_plies_used":max(0, len(proof.steps)-(2*proof.window.user_moves+1))})
