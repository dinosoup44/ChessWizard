"""Factual registered-move validation, independent of chess analysis and UI."""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import sqlite3
import chess


@dataclass(frozen=True)
class RegisteredMoveHealth:
    """Describe whether a stored game can enter normal analysis.

    Args:
        registered: Number of registered move rows.
        legal: Number of locally legal registered moves with valid starting boards.
        problem: First invalid transition/history diagnostic, or an empty string.
    """
    registered: int
    legal: int
    problem: str = ''

    @property
    def empty(self) -> bool:
        """Return whether the game has zero legal registered moves.

        Returns:
            True for absent rows or a record containing no legal registered move.
        """
        return self.legal == 0


def inspect_registered_moves(rows: Sequence[Mapping | sqlite3.Row]) -> RegisteredMoveHealth:
    """Validate stored transitions without consulting PGN, caches or an engine.

    Args:
        rows: One game's moves in ply order, including FENs and played UCI.

    Returns:
        Legal/registered counts and the first malformed-history diagnostic.
        A short game with one legal move is valid, regardless of user color.
    """
    legal = 0
    problem = ''
    previous = None
    for index, row in enumerate(rows, 1):
        try:
            board = chess.Board(row['fen_before'])
            move = chess.Move.from_uci(row['uci_played'])
            if not board.is_valid() or move not in board.legal_moves:
                raise ValueError('illegal registered move or invalid board')
            legal += 1
            if row['ply_number'] != index or (previous is not None and previous != board.fen()):
                raise ValueError('noncontiguous registered history')
            board.push(move)
            if board.fen() != row['fen_after']:
                raise ValueError('registered move does not match its resulting FEN')
        except (ValueError, TypeError, KeyError) as error:
            problem = problem or f"Move {row['move_id']}: {error}"
        previous = row['fen_after']
    return RegisteredMoveHealth(len(rows), legal, problem)
