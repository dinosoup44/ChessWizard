"""Outcome-first Skewer V1 result construction; no engine or persistence."""
import chess
from tactical_opportunities import (
    Attribution, Evaluation, LineRelationship, PayoffTiming, PieceReference,
    PresentationLevel, ProofEvidence, TacticalMotif, TacticalOpportunity,
    TacticalOutcome, TacticalPresentation,
)
from skewer_geometry import PIECE_VALUES


def skewer_opportunity(row, choice, skewer, proof, attribution, scores, initial, final):
    line, resolution = skewer.line, attribution.resolution
    target_type = line.front.piece_type if resolution.front_captured_by_attacker else line.rear.piece_type
    target = chess.piece_name(target_type)
    gain = resolution.related_material_cp
    if resolution.attacker_exchanged or gain < PIECE_VALUES[target_type]:
        kind,title = ("win_exchange","Win the exchange") if target=="rook" and gain==200 else ("force_favorable_exchange","Force a favorable exchange")
    else:
        kind = {"pawn":"win_pawn","rook":"win_rook","queen":"win_queen"}.get(target,"win_piece")
        title = f"Win the {target}"
    motifs = [TacticalMotif("skewer",True,Attribution.SUPPORTED,attribution.rationale)]
    if line.front.piece_type == chess.KING:
        motifs.append(TacticalMotif("check",False,Attribution.SUPPORTED,"The front king must answer the slider's check."))
        title = "Check and " + title.lower()
    if resolution.attacker_exchanged:
        motifs.append(TacticalMotif("sacrifice",False,Attribution.SUPPORTED,"The proof charges the attacker's loss and still retains a favorable line-related material balance."))
    def ref(piece):
        return PieceReference(chess.piece_name(piece.piece_type),"white" if piece.color else "black",chess.square_name(piece.square))
    evidence = ProofEvidence(played_move_uci=row["uci_played"],tactical_move_uci=choice.move_uci,
        line_san=" ".join([choice.move_san,*(s.san for s in proof.steps)]),
        best_defense_uci=proof.steps[0].uci if proof.steps else None,window_user_moves=proof.window.user_moves,
        scope=f"{proof.window.version}_depth18_each_ply_plus_{proof.window.settlement_plies}_settlement_plies_not_exhaustive",
        score_pov=row["color"],material_before_cp=initial,material_after_cp=final,
        material_value_profile="P100_N300_B300_R500_Q900_K0",
        evaluation_before=Evaluation(cp=scores["before"]),evaluation_after_played=Evaluation(cp=scores["played"]),
        evaluation_after_tactic=Evaluation(cp=scores["tactic"]),evaluation_after_settlement=Evaluation(cp=scores["final"]),
        best_defense_checked=True,settled_position_reached=True,relationship_survived=resolution.relationship_survived,
        retained_material_gain_cp=final-initial)
    return TacticalOpportunity(TacticalOutcome(kind,target),tuple(motifs),
        PayoffTiming.IMMEDIATE if resolution.payoff_user_move==1 else PayoffTiming.DELAYED,evidence,
        TacticalPresentation(PresentationLevel.STRONG_CALLOUT,title,attribution.rationale),
        (LineRelationship(f"{skewer.skewer_type}_skewer",ref(line.attacker),ref(line.rear),ref(line.front),
                          relevant_squares=tuple(chess.square_name(p.square) for p in (line.attacker,line.front,line.rear)),ray_direction=line.step),),
        {"front_resolution":resolution.front_resolution,"front_captured_by_attacker":resolution.front_captured_by_attacker,"front_threat_cp":attribution.front_threat_cp,
         "rear_exposed":resolution.rear_exposed,"related_retained_material_cp":gain,
         "payoff_user_move":resolution.payoff_user_move,"attacker_exchanged":resolution.attacker_exchanged,
         "settlement_plies_used":max(0,len(proof.steps)-(2*proof.window.user_moves+1))})
