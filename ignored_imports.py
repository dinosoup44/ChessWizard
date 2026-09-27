"""Optional additive import suppression; existing databases never migrate on read."""
import sqlite3

SCHEMA = """CREATE TABLE ignored_import_games (
    source TEXT NOT NULL CHECK(source IN ('chesscom','lichess')),
    source_game_id TEXT NOT NULL CHECK(length(trim(source_game_id)) > 0),
    ignored_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(source, source_game_id)
)"""


def available(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ignored_import_games'").fetchone() is not None


def is_ignored(db, source, identity):
    return available(db) and db.execute(
        "SELECT 1 FROM ignored_import_games WHERE source=? AND source_game_id=?",
        (source, identity)).fetchone() is not None


def migrate_ignored_imports(db):
    """Explicit additive migration; caller must first approve/verify its safety backup."""
    if db.in_transaction:
        raise ValueError("Migration requires its own transaction")
    db.execute("BEGIN IMMEDIATE")
    try:
        if not available(db):
            db.execute(SCHEMA)
        columns = tuple(r[1] for r in db.execute("PRAGMA table_info(ignored_import_games)"))
        actual = db.execute("SELECT sql FROM sqlite_master WHERE name='ignored_import_games'").fetchone()[0]
        if columns != ("source", "source_game_id", "ignored_at") or actual != SCHEMA:
            raise ValueError("Unexpected ignored-import schema; migration stopped")
        if db.execute("PRAGMA quick_check").fetchall() != [("ok",)] or db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Migration integrity validation failed")
        db.commit()
    except Exception:
        db.rollback()
        raise
