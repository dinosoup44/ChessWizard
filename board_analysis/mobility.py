"""Legal mobility for the actual side to move; never flip board.turn."""
from dataclasses import dataclass
import chess


@dataclass(frozen=True)
class Mobility:
    color: chess.Color
    source: chess.Square | None
    moves_uci: tuple[str, ...]
    destinations: tuple[chess.Square, ...]
    captures_uci: tuple[str, ...]

    @property
    def move_count(self) -> int:
        return len(self.moves_uci)


def legal_mobility(board: chess.Board, source: chess.Square | None = None) -> Mobility:
    """Count legal moves, retaining promotion choices and castling as moves."""
    moves = sorted((m for m in board.legal_moves if source is None or m.from_square == source), key=lambda m: m.uci())
    return Mobility(board.turn, source, tuple(m.uci() for m in moves),
                    tuple(sorted({m.to_square for m in moves})),
                    tuple(m.uci() for m in moves if board.is_capture(m)))


def capture_square(board: chess.Board, move: chess.Move) -> chess.Square | None:
    """Captured piece's square on the pre-move board; assumes a legal move.

    For en passant this differs from the destination. Does not push the move.
    """
    if not board.is_capture(move):
        return None
    if board.is_en_passant(move):
        return move.to_square + (-8 if board.turn == chess.WHITE else 8)
    return move.to_square
