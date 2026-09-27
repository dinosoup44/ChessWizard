"""Material arithmetic with caller-owned valuation policy."""
import chess


def material_balance(board: chess.Board, color: chess.Color, piece_values) -> int | float:
    """Own minus opposing material. Require a value for every present piece type.

    This is accounting, not an evaluation: pins, mobility and exchange sequences
    do not change the returned balance. No universal king/piece values are assumed.
    """
    return sum(piece_values[p.piece_type] * (1 if p.color == color else -1)
               for p in board.piece_map().values())
