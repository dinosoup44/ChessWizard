"""Rule outcomes and draw claims, without engine-score interpretation."""
import chess
from .models import TerminalState


def supplied_history_complete(board: chess.Board, explicit: bool | None) -> bool:
    if explicit is not None:
        if type(explicit) is not bool:
            raise ValueError("history_complete must be bool or None")
        return explicit
    return board.root().fen() == chess.STARTING_FEN


def terminal_state(board: chess.Board, *, history_complete: bool | None = None) -> TerminalState:
    """Positive history evidence proves repetition; missing earlier history cannot disprove it.

    Claims are opportunities, not automatic game endings. FEN halfmove counters are trusted.
    This function copies before python-chess's history probes, preserving the caller's board.
    """
    if type(board) is not chess.Board or not board.is_valid():
        raise ValueError("Expected a valid standard/Chess960 board")
    b = board.copy(stack=True)
    complete = supplied_history_complete(b, history_complete)
    count, check = b.legal_moves.count(), b.is_check()
    base = dict(side_to_move=b.turn, in_check=check, legal_move_count=count,
                history_complete=complete, winner=None)
    if not count or b.is_insufficient_material() or b.is_seventyfive_moves():
        state = ("checkmate" if check else "stalemate") if not count else (
            "insufficient_material" if b.is_insufficient_material() else "other_draw")
        reason = None if state == "checkmate" else ("seventyfive_moves" if state == "other_draw" else state)
        base["winner"] = not b.turn if state == "checkmate" else None
        return TerminalState(**base, state=state, is_terminal=True, draw_reason=reason,
            repetition_claimable=None, fifty_move_claimable=False, history_requirements=(),
            determined_from_position_alone=True)
    if b.is_fivefold_repetition():
        return TerminalState(**base, state="other_draw", is_terminal=True, draw_reason="fivefold_repetition",
            repetition_claimable=True, fifty_move_claimable=False,
            history_requirements=("supplied_move_history",), determined_from_position_alone=False)
    repetition = b.can_claim_threefold_repetition()
    fifty = b.can_claim_fifty_moves()
    state = "fifty_move_claimable" if fifty else "repetition_claimable" if repetition else (
        "nonterminal" if complete else "unknown_history_dependent")
    return TerminalState(**base, state=state, is_terminal=False,
        draw_reason="fifty_moves" if fifty else "threefold_repetition" if repetition else None,
        repetition_claimable=repetition if repetition or complete else None, fifty_move_claimable=fifty,
        history_requirements=() if fifty else ("supplied_move_history",) if repetition or complete else
            ("earlier_repetition_history_unavailable",), determined_from_position_alone=fifty)
