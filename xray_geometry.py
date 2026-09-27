"""X-ray V1 selection policy over shared board observations; no I/O."""
from dataclasses import replace
import chess
from board_analysis import direct_slider_lines, new_slider_move_lines

SCREENER_VERSION = "1"
PIECE_VALUES = {chess.PAWN:100, chess.KNIGHT:300, chess.BISHOP:300,
                chess.ROOK:500, chess.QUEEN:900, chess.KING:0}


def plausible_xray(line):
    a, f, r = line.attacker, line.front, line.rear
    if r.color == a.color or r.piece_type == chess.KING or PIECE_VALUES[r.piece_type] < 300:
        return False
    if f.piece_type == chess.KING:
        return False
    # More valuable enemy front targets belong to the skewer family. A less
    # valuable enemy blocker can also be pinned; causality is decided in proof.
    return f.color == a.color or PIECE_VALUES[f.piece_type] <= PIECE_VALUES[r.piece_type]


def xrays_from(board, source):
    return tuple(line for line in direct_slider_lines(board, source) if plausible_xray(line))


def xray_moves(board, played_uci=None):
    for choice in new_slider_move_lines(board, played_uci):
        lines = tuple(line for line in choice.lines if plausible_xray(line))
        if lines:
            yield replace(choice, lines=lines)


def xray_screener(row):
    try:
        board = chess.Board(row["fen_before"])
        if not board.is_valid() or row["color"] not in {"white", "black"} or board.turn != (row["color"] == "white"):
            return True  # Invalid inputs must reach validation/error, not coverage.
        return next(xray_moves(board, row["uci_played"]), None) is not None
    except ValueError:
        return True
