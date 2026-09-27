"""Geometric attacks: pinned pieces count, friendly blockers are defended.

These are not legal captures. Pawns attack diagonals, not push squares;
en-passant capture squares are not added to attack maps.
"""
from dataclasses import dataclass
from collections.abc import Iterable
import chess


@dataclass(frozen=True)
class PieceRef:
    square: chess.Square
    piece_type: chess.PieceType
    color: chess.Color


@dataclass(frozen=True)
class AttackMap:
    color: chess.Color
    # Index by target square; each entry lists source squares.
    sources_by_target: tuple[tuple[chess.Square, ...], ...]

    @property
    def attacked_squares(self) -> tuple[chess.Square, ...]:
        return tuple(s for s, sources in enumerate(self.sources_by_target) if sources)


def attacked_squares(board: chess.Board, source: chess.Square) -> tuple[chess.Square, ...]:
    return tuple(board.attacks(source))


def attackers(board: chess.Board, target: chess.Square, color: chess.Color) -> tuple[chess.Square, ...]:
    return tuple(board.attackers(color, target))


def attack_map(board: chess.Board, color: chess.Color) -> AttackMap:
    return AttackMap(color, tuple(attackers(board, square, color) for square in chess.SQUARES))


def attacked_pieces(board: chess.Board, source: chess.Square, *,
                    target_color: chess.Color | None = None,
                    piece_types: Iterable[chess.PieceType] | None = None) -> tuple[PieceRef, ...]:
    """Occupied attacked squares with caller-selected color/type filters."""
    types = None if piece_types is None else frozenset(piece_types)
    result = []
    for square in attacked_squares(board, source):
        piece = board.piece_at(square)
        if (piece is not None and (target_color is None or piece.color == target_color)
                and (types is None or piece.piece_type in types)):
            result.append(PieceRef(square, piece.piece_type, piece.color))
    return tuple(result)
