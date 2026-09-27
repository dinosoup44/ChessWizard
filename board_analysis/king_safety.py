"""King-zone pressure and legal king moves, not an engine safety score."""
from dataclasses import dataclass
import chess
from .attacks import attackers
from .geometry import neighborhood
from .mobility import legal_mobility


@dataclass(frozen=True)
class KingSafety:
    color: chess.Color
    square: chess.Square
    zone: tuple[chess.Square, ...]
    checking_pieces: tuple[chess.Square, ...]
    attacked_zone: tuple[chess.Square, ...]
    pawn_shield: tuple[chess.Square, ...]
    # None means this color is not to move; empty means no legal king moves.
    legal_moves_uci: tuple[str, ...] | None


def king_safety(board: chess.Board, color: chess.Color) -> KingSafety | None:
    square = board.king(color)
    if square is None:
        return None
    zone = neighborhood(square)
    forward = 1 if color == chess.WHITE else -1
    shield = tuple(s for s in zone if chess.square_rank(s) - chess.square_rank(square) == forward
                   and board.piece_at(s) == chess.Piece(chess.PAWN, color))
    return KingSafety(color, square, zone, attackers(board, square, not color),
                      tuple(s for s in zone if board.is_attacked_by(not color, s)), shield,
                      legal_mobility(board, square).moves_uci if board.turn == color else None)
