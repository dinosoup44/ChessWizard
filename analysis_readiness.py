"""Scoped readiness reads; exact evidence is still decoded and legally validated."""
from collections.abc import Iterable, Sequence
import sqlite3
from threading import Event
from analysis_control import check_cancelled

READINESS_GAME_BATCH = 16


def readiness_moves(connection: sqlite3.Connection, game_ids: Iterable[int] | None = None) -> list[sqlite3.Row]:
    """Load only the selected games' actual positions in replay order.

    Args:
        connection: Caller-owned read connection with sqlite3.Row row factory.
        game_ids: Explicit game IDs, or None for an unfiltered tool request.

    Returns:
        Move rows ordered by game, ply and move identity.
    """
    ids = None if game_ids is None else tuple(game_ids)
    if ids == ():
        return []
    where = '' if ids is None else ' WHERE game_id IN (' + ','.join('?' for _ in ids) + ')'
    cursor = connection.cursor()
    cursor.row_factory = sqlite3.Row
    return cursor.execute(
        'SELECT move_id,game_id,ply_number,fen_before,fen_after,uci_played,is_user_move FROM moves'
        + where + ' ORDER BY game_id,ply_number,move_id', ids or ()).fetchall()
