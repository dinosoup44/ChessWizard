"""Structural piece safety facts, without exchange evaluation or tactic labels."""
from dataclasses import dataclass
import chess
from .attacks import PieceRef, attackers


@dataclass(frozen=True)
class PieceSafety:
    piece: PieceRef
    attackers: tuple[chess.Square, ...]
    defenders: tuple[chess.Square, ...]
    absolutely_pinned: bool
    pin_line: tuple[chess.Square, ...]

    @property
    def attacked_and_undefended(self) -> bool:
        """Geometric observation only; pinned attackers/defenders still count."""
        return bool(self.attackers) and not self.defenders


def piece_safety(board: chess.Board, square: chess.Square) -> PieceSafety | None:
    piece = board.piece_at(square)
    if piece is None:
        return None
    pinned = board.is_pinned(piece.color, square)
    return PieceSafety(PieceRef(square, piece.piece_type, piece.color),
                       attackers(board, square, not piece.color), attackers(board, square, piece.color),
                       pinned, tuple(board.pin(piece.color, square)) if pinned else ())
