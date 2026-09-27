"""Read-only line and decision presentation shared by Opening Review frontends."""
import chess
from game_context import ActualMoveRow, actual_move_rows
from opening_exploration import OpeningExplorationState
from opening_intelligence_models import OpeningMoveAssessment
from move_quality import MoveQuality


def actual_opening_rows(moves: tuple[OpeningMoveAssessment, ...]) -> tuple[ActualMoveRow, ...]:
    """Pair opening-region actual moves using the existing game-row convention.

    Args:
        moves: Consecutive actual moves beginning at the game's initial ply.

    Returns:
        Move/White/Black rows with exact actual half-move targets.
    """
    return actual_move_rows(tuple(dict(move_number=m.move_number, color=m.actor_color,
                                      san_played=m.played_san, uci_played=m.played_uci) for m in moves))


def authored_opening_rows(state: OpeningExplorationState) -> tuple[ActualMoveRow, ...]:
    """Pair an authored continuation while retaining its independent line cursor.

    Args:
        state: Frozen authored line and actual decision anchor.

    Returns:
        Move/White/Black rows; targets are line plies, never actual-game plies.
    """
    board = chess.Board(state.decision_fen)
    moves = []
    for move in state.line:
        moves.append(dict(move_number=board.fullmove_number, color='white' if board.turn else 'black',
                          san_played=move.san, uci_played=move.uci))
        board.push_uci(move.uci)
    return actual_move_rows(moves)


def opening_decision_text(move: OpeningMoveAssessment, quality: MoveQuality | None = None) -> str:
    """Keep authored membership separate from compatible actual-move evaluations.

    Args:
        move: Exact actual decision and authored choices.
        quality: Existing move-quality evidence, or None when unavailable.

    Returns:
        Compact decision wording without judging departures as mistakes.
    """
    state = ('In opening' if move.played_move_in_book else
             'You left the opening' if move.deviation_relation == 'user' and move.deviation else
             'Opponent left the opening' if move.deviation_relation == 'opponent' and move.deviation else
             'Outside opening')
    lines = [f'At {move.move_label}', f'Actual move: {move.played_san}', f'Opening status: {state}']
    preferred = move.preferred_move or (move.available_moves[0] if len(move.available_moves) == 1 else None)
    if preferred:lines.append(f'Opening move: {preferred.san}')
    score = quality.played_continuation_eval.pov('white') if quality and quality.played_continuation_eval else None
    evaluation = ('Not analyzed' if score is None else f'{score.score_cp / 100:+.2f} (White)' if score.score_cp is not None
                  else f'M{abs(score.mate_score)} for {score.mate_winner.title()}')
    lines.append('Actual move evaluation: '+evaluation)
    if quality and quality.accuracy is not None:lines.append(f'Accuracy: {quality.accuracy:.1f}')
    if quality and quality.eval_loss_cp is not None:lines.append(f'Eval loss: {quality.eval_loss_cp} cp')
    return '\n'.join(lines)
