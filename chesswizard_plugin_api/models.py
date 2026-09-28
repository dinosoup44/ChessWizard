"""Immutable API V1 values. Facts describe a position, never tactical proof."""
from dataclasses import dataclass
from typing import Literal

API_VERSION = "1.0.0"
Color = Literal["white", "black"]
Piece = Literal["pawn", "knight", "bishop", "rook", "queen", "king"]


@dataclass(frozen=True, slots=True)
class PositionContext:
    """Identify an explicitly supplied position without exposing user storage.

    Args:
        request_id: Opaque invocation identifier echoed in the response.
        fen: Full six-field standard-chess FEN.
    """
    request_id: str
    fen: str


@dataclass(frozen=True, slots=True)
class SquareFact:
    """Describe one occupied square.

    Args:
        square: Algebraic square name.
        color: Piece owner.
        piece: Piece type; no tactical annotation.
    """
    square: str
    color: Color
    piece: Piece


@dataclass(frozen=True, slots=True)
class MaterialCount:
    """Count one piece type for one color, including zero counts.

    Args:
        color: Piece owner.
        piece: Piece type.
        count: Nonnegative integral count.
    """
    color: Color
    piece: Piece
    count: int


@dataclass(frozen=True, slots=True)
class MaterialFacts:
    """Return bounded factual evidence for precisely one input position.

    Args:
        request_id: Unchanged request identifier.
        fen: Unchanged input FEN.
        squares: Immutable occupied-square evidence.
        counts: All twelve color/piece count combinations.
    """
    request_id: str
    fen: str
    squares: tuple[SquareFact, ...]
    counts: tuple[MaterialCount, ...]