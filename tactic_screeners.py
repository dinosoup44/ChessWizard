from __future__ import annotations
import sqlite3
import chess
from board_analysis import attacked_pieces

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 300,
    chess.BISHOP: 300,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 10000,
}

FORK_TARGET_TYPES = {
    chess.KNIGHT,
    chess.BISHOP,
    chess.ROOK,
    chess.QUEEN,
    chess.KING,
}


def enemy_targets_after_move(
    board_after: chess.Board,
    destination_square: chess.Square,
    player_color: chess.Color,
) -> list[dict]:
    attacker = board_after.piece_at(
        destination_square
    )

    if (
        attacker is None
        or attacker.color != player_color
    ):
        return []

    return [
        {"square": chess.square_name(piece.square), "piece_type": piece.piece_type,
         "value": PIECE_VALUES[piece.piece_type]}
        for piece in attacked_pieces(board_after, destination_square,
                                     target_color=not player_color, piece_types=FORK_TARGET_TYPES)
    ]


def is_light_fork_shape(
    board: chess.Board,
    move: chess.Move,
    player_color: chess.Color,
) -> bool:
    moving_piece = board.piece_at(
        move.from_square
    )

    if (
        moving_piece is None
        or moving_piece.color != player_color
    ):
        return False

    board_after = board.copy(
        stack=False
    )

    try:
        board_after.push(
            move
        )

    except AssertionError:
        return False

    targets = enemy_targets_after_move(
        board_after,
        move.to_square,
        player_color,
    )

    if len(targets) < 2:
        return False

    # Fork V2 accepts any two non-pawn targets, including two minor
    # pieces. Requiring a rook/king silently lost real historical forks.
    return True


def fork_screener(
    row: sqlite3.Row,
) -> bool:
    fen_before = row[
        "fen_before"
    ]

    played_uci = row[
        "uci_played"
    ]

    color_text = (
        row["color"]
        or ""
    ).lower()

    player_color = (
        chess.WHITE
        if color_text == "white"
        else chess.BLACK
    )

    try:
        board = chess.Board(
            fen_before
        )

    except ValueError:
        return True

    if board.turn != player_color:
        return True

    for move in board.legal_moves:
        if (
            played_uci
            and move.uci() == played_uci
        ):
            continue

        if is_light_fork_shape(
            board,
            move,
            player_color,
        ):
            return True

    return False



