"""Cheap frozen membership; expensive evidence validation belongs to each batch."""
from dataclasses import dataclass
import sqlite3
from game_analysis_models import AnalysisScopeKind, GameAnalysisScope

CANONICAL_NEWEST_ORDER = "julianday(replace(substr(played_at,1,10),'.','-') || substr(played_at,11)) DESC,game_id DESC"


@dataclass(frozen=True)
class AnalysisSelection:
    """Hold newest-first IDs without decoding any proof/cache payloads.

    Args:
        game_ids: Eligible stored games in canonical played-date/ID order.
        empty_ids: Encountered records with no registered moves.
    """
    game_ids: tuple[int, ...]
    empty_ids: tuple[int, ...]


def select_analysis_games(connection: sqlite3.Connection, scope: GameAnalysisScope) -> AnalysisSelection:
    """Freeze cheap scope membership, excluding zero-row records before readiness.

    Args:
        connection: Caller-owned read connection.
        scope: Requested real-game scope; recent limits count nonempty records.

    Returns:
        IDs in canonical newest-first order and excluded empty IDs.

    Raises:
        ValueError: Explicit selection contains missing or development games.
        sqlite3.Error: Metadata could not be read.
    """
    where = ' AND game_id IN (' + ','.join('?' for _ in scope.game_ids) + ')' if scope.game_ids else ''
    rows = connection.execute("SELECT game_id,EXISTS(SELECT 1 FROM moves m WHERE m.game_id=g.game_id) "
        "FROM games g WHERE COALESCE(source,'')<>'dev'" + where + ' ORDER BY ' + CANONICAL_NEWEST_ORDER,
        scope.game_ids).fetchall()
    if scope.game_ids and {r[0] for r in rows} != set(scope.game_ids):
        raise ValueError('Selected scope contains missing or development games')
    limit = {AnalysisScopeKind.RECENT_50:50, AnalysisScopeKind.RECENT_100:100}.get(scope.kind)
    games, empty = [], []
    for gid, has_moves in rows:
        (games if has_moves else empty).append(gid)
        if limit is not None and len(games) >= limit:
            break
    return AnalysisSelection(tuple(games), tuple(empty))
