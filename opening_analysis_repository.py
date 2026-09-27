"""Read-only game context and explicit user-history scoping for opening analysis."""
from collections.abc import Iterable
import sqlite3
from opening_analysis_models import OpeningGameContext


class OpeningAnalysisRepository:
    """Read metadata from a caller-owned snapshot without schema or data writes.

    Args:
        connection: Read-only transaction owned by the application service.
    """
    def __init__(self, connection: sqlite3.Connection) -> None:
        """Bind the supplied snapshot.

        Args:
            connection: Caller-owned read-only connection.
        """
        self.connection = connection

    def scope(self, game_ids: Iterable[int] | None, user_id: int | None) -> tuple[tuple[int, ...], int | None]:
        """Resolve one owner's real history, or preserve an explicit ID scope.

        Args:
            game_ids: Explicit IDs, or None for the selected owner's real history.
            user_id: Owner identity; inferred only if the selected scope has one owner.

        Returns:
            Deduplicated IDs and resolved owner; an empty scope may have no owner.

        Raises:
            ValueError: IDs are invalid or multiple owners require disambiguation.
        """
        if user_id is not None and (type(user_id) is not int or user_id <= 0):
            raise ValueError('Use a positive stored user ID.')
        ids = None if game_ids is None else tuple(dict.fromkeys(game_ids))
        if ids is not None and any(type(gid) is not int or gid <= 0 for gid in ids):
            raise ValueError('Use positive database-local game IDs.')
        rows = tuple(self.connection.execute("SELECT game_id,user_id FROM games WHERE COALESCE(source,'')<>'dev' ORDER BY game_id"))
        selected = None if ids is None else set(ids)
        if user_id is None:
            owners = {row[1] for row in rows if row[1] is not None and (selected is None or row[0] in selected)}
            if len(owners) > 1:
                raise ValueError('Choose a stored user ID when the scope contains multiple owners.')
            user_id = next(iter(owners), None)
        if ids is None:
            ids = tuple(row[0] for row in rows if row[1] == user_id)
        return ids, user_id

    def context(self, game_id: int) -> OpeningGameContext:
        """Read source metadata without inferring ownership from player names.

        Args:
            game_id: Database-local identifier.

        Returns:
            Recorded game metadata, normalizing unknown color to None.

        Raises:
            ValueError: The game does not exist.
        """
        row = self.connection.execute('''SELECT game_id,user_id,source,source_game_id,
            played_at,white_username,black_username,user_color,result,time_control,time_class
            FROM games WHERE game_id=?''', (game_id,)).fetchone()
        if row is None:
            raise ValueError('Game not found in this database.')
        values = list(row)
        values[7] = values[7] if values[7] in ('white', 'black') else None
        return OpeningGameContext(*values)
