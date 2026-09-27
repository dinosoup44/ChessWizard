"""Transaction ownership around existing game/move normalization; no analysis writes."""
import sqlite3
from uuid import uuid4
from game_import_pgn import validate_game
from ignored_imports import is_ignored


class GameImportRepository:
    def __init__(self, connection):
        self.connection = connection
        self.last_ignored = False

    def _account(self, source, username):
        row = self.connection.execute("SELECT user_id,account_id FROM chess_accounts WHERE source=? AND username=? COLLATE NOCASE ORDER BY account_id LIMIT 1", (source, username)).fetchone()
        if row:
            return row
        row = self.connection.execute("SELECT user_id FROM users ORDER BY user_id LIMIT 1").fetchone()
        if row:
            user_id = row[0]
        else:
            # Legacy NOT NULL field stores a local identity, never a fictitious remote account.
            user_id = self.connection.execute("INSERT INTO users(lichess_username) VALUES(?)", ("local:" + uuid4().hex,)).lastrowid
        account_id = self.connection.execute("INSERT INTO chess_accounts(user_id,source,username) VALUES(?,?,?)", (user_id, source, username)).lastrowid
        return user_id, account_id

    def import_game(self, provider, username, game, raw_pgn):
        self.last_ignored = False
        identity = provider.get_source_game_id(game)
        validate_game(game, username, identity, raw_pgn)
        # Lock before checking identity; a second connection cannot race check/insert.
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if is_ignored(self.connection, provider.SOURCE, identity):
                self.last_ignored = True
                return False
            if provider.game_exists(self.connection, identity):
                return False
            user_id, account_id = self._account(provider.SOURCE, username)
            if not provider.import_single_game(self.connection, user_id, account_id, username, game, raw_pgn):
                raise ValueError("Game could not be normalized")
            return True

    def completed_account(self, source, username):
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            _, account_id = self._account(source, username)
            self.connection.execute("UPDATE chess_accounts SET last_sync_at=CURRENT_TIMESTAMP WHERE account_id=?", (account_id,))


def remembered_accounts(database_path):
    connection = sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True)
    try:
        return tuple(connection.execute("SELECT source,username FROM chess_accounts WHERE source IN ('chesscom','lichess') ORDER BY last_sync_at DESC,account_id DESC"))
    finally:
        connection.close()
