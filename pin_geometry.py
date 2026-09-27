"""Pin V1 policy composed from shared ray observations; no engine or I/O."""
from dataclasses import dataclass
import chess
from board_analysis import PieceRef, ORTHOGONAL_DIRECTIONS, DIAGONAL_DIRECTIONS, ray_contacts

SCREENER_VERSION = "1"
PIECE_VALUES = {chess.PAWN: 100, chess.KNIGHT: 300, chess.BISHOP: 300,
                chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0}
SLIDER_DIRECTIONS = {
    chess.BISHOP: DIAGONAL_DIRECTIONS,
    chess.ROOK: ORTHOGONAL_DIRECTIONS,
    chess.QUEEN: ORTHOGONAL_DIRECTIONS + DIAGONAL_DIRECTIONS,
}


@dataclass(frozen=True)
class Pin:
    attacker: PieceRef
    pinned: PieceRef
    behind: PieceRef
    pin_type: str


@dataclass(frozen=True)
class PinMove:
    move_uci: str
    move_san: str
    fen_after: str
    pins: tuple[Pin, ...]


def pins_from(board, source):
    piece = board.piece_at(source)
    if piece is None:
        return ()
    found = []
    for step in SLIDER_DIRECTIONS.get(piece.piece_type, ()):
        contacts = ray_contacts(board, source, step)
        if len(contacts) < 2:
            continue
        pinned, behind = contacts[0].piece, contacts[1].piece
        if pinned.color == piece.color or behind.color == piece.color or pinned.piece_type == chess.KING:
            continue
        if behind.piece_type != chess.KING and PIECE_VALUES[behind.piece_type] <= PIECE_VALUES[pinned.piece_type]:
            continue
        found.append(Pin(PieceRef(source, piece.piece_type, piece.color), pinned, behind,
                         "absolute" if behind.piece_type == chess.KING else "relative"))
    return tuple(found)


def pinning_moves(board, played_uci=None):
    """Yield legal alternatives creating a new direct pin from the moved slider.

    Sliding promotions are included; castling/discovered stationary-rook pins
    are outside V1. Moving along an already existing identical pin is excluded.
    """
    for move in board.legal_moves:
        if move.uci() == played_uci:
            continue
        piece = board.piece_at(move.from_square)
        resulting_type = move.promotion or piece.piece_type
        if resulting_type not in SLIDER_DIRECTIONS:
            continue
        old = {(p.pinned, p.behind, p.pin_type) for p in pins_from(board, move.from_square)}
        after = board.copy(stack=False)
        after.push(move)
        new_pins = tuple(p for p in pins_from(after, move.to_square)
                         if (p.pinned, p.behind, p.pin_type) not in old)
        if new_pins:
            yield PinMove(move.uci(), board.san(move), after.fen(), new_pins)


def pin_screener(row):
    # Invalid data must proceed to validation/error, never become a static miss.
    try:
        board = chess.Board(row["fen_before"])
        if not board.is_valid() or row["color"] not in {"white", "black"}:
            return True
        if board.turn != (row["color"] == "white"):
            return True
        return next(pinning_moves(board, row["uci_played"]), None) is not None
    except ValueError:
        return True
