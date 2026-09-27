"""Outcome-first Pin V2 result construction; no persistence or engine access."""
import chess
from analysis_settings import VERIFICATION_GENERATOR
from board_analysis import direction
from tactical_opportunities import (
    Attribution, Evaluation, LineRelationship, PayoffTiming, PieceReference,
    PresentationLevel, ProofEvidence, TacticalMotif, TacticalOpportunity,
    TacticalOutcome, TacticalPresentation,
)
from pin_geometry import PIECE_VALUES


def material_outcome(piece, retained_cp, pinner_exchanged=False):
    """Describe retained value, without calling a queen-for-two-pieces a clean win."""
    captured_value = PIECE_VALUES[chess.PIECE_NAMES.index(piece)] if piece else 0
    if pinner_exchanged or (piece != "pawn" and retained_cp < captured_value):
        if piece == "rook" and retained_cp == 200:
            return TacticalOutcome("win_exchange", "rook"), "Win the exchange"
        return TacticalOutcome("force_favorable_exchange", piece), "Force a favorable exchange"
    if piece == "pawn":
        return TacticalOutcome("win_pawn", "pawn"), "Win a pawn" if retained_cp < 200 else "Win pawns"
    if piece == "queen":
        return TacticalOutcome("win_queen", "queen"), "Win the queen"
    return TacticalOutcome("win_piece", piece), f"Win a {piece or 'piece'}"


def pin_opportunity(row, choice, pin, proof, attribution, scores, material_before, material_after, *, tactical, material_context=False, proof_depth=VERIFICATION_GENERATOR.engine.depth):
    related = attribution.related_material_cp
    piece = attribution.captured_piece
    if not tactical and not material_context:
        outcome, title = TacticalOutcome("positional_pressure"), "Pin pressure; no verified pin-driven material win"
    else:
        outcome, title = material_outcome(piece, related, attribution.pinner_exchanged)
    check = attribution.kind == "check_led"
    motif = TacticalMotif(f"{pin.pin_type}_pin", primary=not check,
                         attribution=Attribution.CONTEXT_ONLY if check or not tactical else Attribution.SUPPORTED,
                         rationale=attribution.rationale)
    motifs = [motif]
    if check:
        motifs = [TacticalMotif("check", True, Attribution.SUPPORTED, attribution.rationale),
                  TacticalMotif("double_attack", attribution=Attribution.SUPPORTED,
                                rationale="The tactical move checks the king and attacks the captured piece."), motif]
        title = "Check and " + title.lower()
    if attribution.pinner_exchanged:
        motifs.append(TacticalMotif("sacrifice", attribution=Attribution.SUPPORTED,
                                    rationale="The proof accounts for losing the pinner and the subsequent favorable recapture."))
    if attribution.defender_removed and tactical:
        motifs.append(TacticalMotif("removal_of_defender", attribution=Attribution.SUPPORTED,
                                    rationale="Before the related payoff, the line captures a piece defending the pinned target; its exchange cost is included."))
    payoff = attribution.payoff_move
    timing = PayoffTiming.IMMEDIATE if payoff == 1 else PayoffTiming.DELAYED if payoff else PayoffTiming.POSITIONAL
    if not tactical and not material_context:
        timing = PayoffTiming.POSITIONAL
    line = " ".join([choice.move_san, *(s.san for s in proof.steps)])
    evidence = ProofEvidence(
        played_move_uci=row["uci_played"], tactical_move_uci=choice.move_uci, line_san=line,
        best_defense_uci=proof.steps[0].uci if proof.steps else None,
        window_user_moves=proof.window.user_moves, scope=(f"{proof.window.version}_approved_entry_then_depth{proof_depth}_each_ply_plus_{proof.window.settlement_plies}_settlement_plies_not_exhaustive"
            if proof.window.version == "approved_entry_each_ply_v1" else
            f"{proof.window.version}_depth{proof_depth}_each_ply_plus_{proof.window.settlement_plies}_settlement_plies_not_exhaustive"),
        score_pov=row["color"], material_before_cp=material_before, material_after_cp=material_after,
        material_value_profile="P100_N300_B300_R500_Q900_K0",
        evaluation_before=Evaluation(cp=scores["before"]), evaluation_after_played=Evaluation(cp=scores["played"]),
        evaluation_after_tactic=Evaluation(cp=scores["tactic"]),
        evaluation_after_settlement=Evaluation(cp=scores["final"]) if proof.state == "stable" else None,
        best_defense_checked=bool(proof.steps), settled_position_reached=proof.state == "stable",
        relationship_survived=attribution.relationship_survived,
        retained_material_gain_cp=material_after - material_before)
    def ref(piece):
        return PieceReference(chess.piece_name(piece.piece_type), "white" if piece.color else "black", chess.square_name(piece.square))
    relationship = LineRelationship(f"{pin.pin_type}_pin", ref(pin.attacker), ref(pin.behind), ref(pin.pinned),
                                    ray_direction=direction(pin.attacker.square, pin.behind.square))
    level = PresentationLevel.STRONG_CALLOUT if tactical else PresentationLevel.POSITIONAL_NOTE
    if material_context:
        level = PresentationLevel.SECONDARY_MOTIF
        title = "Rook pressure wins a pawn"
        motifs = [TacticalMotif("rook_pressure", True, Attribution.SUPPORTED,
                               "The rook attacks and captures the pawn in the verified line; the pin's causal role is not established."),
                  TacticalMotif(f"{pin.pin_type}_pin", attribution=Attribution.CONTEXT_ONLY,
                                rationale=attribution.rationale)]
    return TacticalOpportunity(outcome, tuple(motifs), timing, evidence,
        TacticalPresentation(level, title, attribution.rationale), (relationship,),
        {"movement_constraint": attribution.constraint, "related_retained_material_cp": related,
         "payoff_user_move": payoff, "settlement_plies_used": max(0, len(proof.steps) - (2 * proof.window.user_moves + 1))})
