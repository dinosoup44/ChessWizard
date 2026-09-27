"""Occupancy along lines; callers assign pin, skewer, or pattern meaning."""
from dataclasses import dataclass
import chess
from .attacks import PieceRef
from .geometry import between_squares, direction, ray_squares, ORTHOGONAL_DIRECTIONS, DIAGONAL_DIRECTIONS


@dataclass(frozen=True)
class LineRelationship:
    source: chess.Square
    target: chess.Square
    step: tuple[int, int] | None
    between: tuple[chess.Square, ...]
    blockers: tuple[PieceRef, ...]

    @property
    def clear(self) -> bool:
        return self.step is not None and not self.blockers


@dataclass(frozen=True)
class RayContact:
    piece: PieceRef
    intervening: tuple[PieceRef, ...]


def line_relationship(board: chess.Board, source: chess.Square, target: chess.Square) -> LineRelationship:
    between = between_squares(source, target)
    blockers = tuple(PieceRef(s, p.piece_type, p.color) for s in between if (p := board.piece_at(s)))
    return LineRelationship(source, target, direction(source, target), between, blockers)


def ray_contacts(board: chess.Board, source: chess.Square, step: tuple[int, int]) -> tuple[RayContact, ...]:
    """Every occupied square along a ray, including beyond blockers.

    Intervening pieces describe x-ray geometry, not an attack or legal move.
    Endpoints need not contain a slider; piece movement policy belongs to callers.
    """
    seen, contacts = [], []
    for square in ray_squares(source, step):
        piece = board.piece_at(square)
        if piece is not None:
            ref = PieceRef(square, piece.piece_type, piece.color)
            contacts.append(RayContact(ref, tuple(seen)))
            seen.append(ref)
    return tuple(contacts)


def slider_directions(piece_type):
    """Movement directions only; no value, color or tactical interpretation."""
    return {chess.BISHOP: DIAGONAL_DIRECTIONS, chess.ROOK: ORTHOGONAL_DIRECTIONS,
            chess.QUEEN: ORTHOGONAL_DIRECTIONS + DIAGONAL_DIRECTIONS}.get(piece_type, ())


@dataclass(frozen=True)
class SliderLine:
    attacker: PieceRef
    front: PieceRef
    rear: PieceRef
    step: tuple[int, int]


@dataclass(frozen=True)
class SliderMoveLines:
    move_uci: str
    move_san: str
    fen_after: str
    lines: tuple[SliderLine, ...]


def new_slider_move_lines(board, played_uci=None):
    """Legal moved-slider lines with new contact pairs; no tactical policy.

    Includes slider promotions. Castling and stationary/discovered sliders are
    deliberately outside this interface. The caller's board is never modified.
    """
    for move in board.legal_moves:
        if move.uci() == played_uci or board.is_castling(move):
            continue
        if not slider_directions(move.promotion or board.piece_type_at(move.from_square)):
            continue
        old = {(line.front, line.rear) for line in direct_slider_lines(board, move.from_square)}
        after = board.copy(stack=False)
        after.push(move)
        lines = tuple(line for line in direct_slider_lines(after, move.to_square)
                      if (line.front, line.rear) not in old)
        if lines:
            yield SliderMoveLines(move.uci(), board.san(move), after.fen(), lines)


def direct_slider_lines(board: chess.Board, source: chess.Square) -> tuple[SliderLine, ...]:
    """The first two occupied contacts on each slider ray, including friendly ones.

    No intervening occupant is skipped. Callers decide whether a contact pair
    describes a pin, skewer, ordinary blocker, or potential x-ray relationship.
    """
    piece = board.piece_at(source)
    if piece is None:
        return ()
    attacker = PieceRef(source, piece.piece_type, piece.color)
    lines = []
    for step in slider_directions(piece.piece_type):
        contacts = ray_contacts(board, source, step)
        if len(contacts) >= 2:
            lines.append(SliderLine(attacker, contacts[0].piece, contacts[1].piece, step))
    return tuple(lines)
