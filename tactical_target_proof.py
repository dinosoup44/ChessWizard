"""Identity tracking and conservative target accounting for bounded proofs."""
from dataclasses import dataclass
import chess


@dataclass(frozen=True)
class TargetSettlement:
    captured_targets: tuple[int, ...]
    target_captures: tuple[dict, ...]
    attributable_cp: int
    own_losses_cp: int
    attacker_lost: bool
    payoff_user_move: int | None
    events: tuple[dict, ...]


def trace_target_settlement(after_tactic, attacker_square, targets, proof, values):
    """Credit only original attacker's target captures in the payoff window.

    Follow moving identities, including castling rooks, and charge every own
    loss through settlement. Unrelated captures never finance attributed gain.
    This is a conservative lower bound, not proof that uncaptured targets cannot
    be won in another line. Captures after the payoff window receive no credit.
    """
    color = not after_tactic.turn
    identities = {piece.square:piece.square for piece in targets}
    attacker = attacker_square
    captures, events = [], []
    gains = losses = 0
    attacker_lost = False
    countercapture_debt = {}
    for ply, step in enumerate(proof.steps,1):
        board = chess.Board(step.before_fen)
        move = chess.Move.from_uci(step.uci)
        victims = [origin for origin,square in identities.items() if square == step.captured_square and square is not None]
        credited = (step.actor==color and move.from_square==attacker and victims
                    and step.in_payoff_window and step.user_move_number<=proof.window.user_moves)
        if step.actor != color and step.captured_piece:
            losses += values[step.captured_piece]
        if step.actor != color:
            debt = countercapture_debt.pop(move.from_square,0)
            if step.captured_piece: debt += values[step.captured_piece]
            if debt: countercapture_debt[move.to_square] = debt
        elif step.captured_piece and step.captured_square in countercapture_debt:
            # Recover only the exchange cost attached to this counter-capturer;
            # unrelated captures cannot subsidize the fork target credit.
            debt = countercapture_debt.pop(step.captured_square)
            if not credited:
                losses -= min(debt,values[step.captured_piece])
        if credited:
            gains += values[step.captured_piece]
            for origin in victims:
                captures.append({"original_square":chess.square_name(origin),"capture_square":chess.square_name(step.captured_square),
                                 "piece":chess.piece_name(step.captured_piece),"move":step.san,
                                 "ply":ply,"user_move":step.user_move_number})
        event = {"ply":ply,"move":step.san,"actor":"white" if step.actor else "black",
                 "capture":chess.piece_name(step.captured_piece) if step.captured_piece else None,
                 "capture_square":chess.square_name(step.captured_square) if step.captured_square is not None else None,
                 "material_cp":step.material_cp,"answers_check":board.is_check(),
                 "gives_check":board.gives_check(move),"target_capture_credited":bool(credited)}
        events.append(event)
        if attacker is not None and step.captured_square==attacker:
            attacker_lost, attacker = True,None
        elif attacker==move.from_square:
            attacker = move.to_square
        for origin,square in list(identities.items()):
            if square is None: continue
            if square==step.captured_square: identities[origin]=None
            elif square==move.from_square: identities[origin]=move.to_square
            elif board.is_castling(move) and board.piece_at(square)==chess.Piece(chess.ROOK,step.actor):
                rank = chess.square_rank(move.from_square)
                kingside = board.is_kingside_castling(move)
                if square==chess.square(7 if kingside else 0,rank):
                    identities[origin]=chess.square(5 if kingside else 3,rank)
    return TargetSettlement(tuple(chess.parse_square(c["original_square"]) for c in captures),tuple(captures),
                            gains-losses,losses,attacker_lost,
                            min((c["user_move"] for c in captures),default=None),tuple(events))
