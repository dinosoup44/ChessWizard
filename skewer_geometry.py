"""Skewer V1 geometry policy over shared slider-line observations; no I/O."""
from dataclasses import dataclass
import chess
from board_analysis import SliderLine, direct_slider_lines, slider_directions

SCREENER_VERSION = "1"
PIECE_VALUES = {chess.PAWN:100, chess.KNIGHT:300, chess.BISHOP:300,
                chess.ROOK:500, chess.QUEEN:900, chess.KING:0}


@dataclass(frozen=True)
class Skewer:
    line: SliderLine
    skewer_type: str


@dataclass(frozen=True)
class SkewerMove:
    move_uci: str
    move_san: str
    fen_after: str
    skewers: tuple[Skewer, ...]


def skewers_from(board, source):
    found = []
    for line in direct_slider_lines(board,source):
        a,f,r = line.attacker,line.front,line.rear
        if f.color == a.color or r.color == a.color or r.piece_type == chess.KING:
            continue
        if f.piece_type == chess.KING:
            # Pawn-only rear targets are excluded for V1 king skewers.
            if PIECE_VALUES[r.piece_type] >= 300:
                found.append(Skewer(line,"absolute"))
        elif f.piece_type in {chess.QUEEN,chess.ROOK} and PIECE_VALUES[f.piece_type] > PIECE_VALUES[r.piece_type]:
            found.append(Skewer(line,"relative"))
    return tuple(found)


def skewering_moves(board, played_uci=None):
    """Legal moved-slider alternatives; include slider promotions, not castling.

An already present identical contact pair is not a newly created skewer.
"""
    for move in board.legal_moves:
        if move.uci() == played_uci:
            continue
        piece = board.piece_at(move.from_square)
        if not slider_directions(move.promotion or piece.piece_type):
            continue
        old = {(s.line.front,s.line.rear,s.skewer_type) for s in skewers_from(board,move.from_square)}
        after = board.copy(stack=False)
        after.push(move)
        skewers = tuple(s for s in skewers_from(after,move.to_square)
                        if (s.line.front,s.line.rear,s.skewer_type) not in old)
        if skewers:
            yield SkewerMove(move.uci(),board.san(move),after.fen(),skewers)


def skewer_screener(row):
    try:
        board = chess.Board(row["fen_before"])
        if not board.is_valid() or row["color"] not in {"white","black"} or board.turn != (row["color"]=="white"):
            return True
        return next(skewering_moves(board,row["uci_played"]),None) is not None
    except ValueError:
        return True
