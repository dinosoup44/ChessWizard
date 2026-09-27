"""Safely add and backfill games.time_class without changing any other data."""
import argparse
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from time_class import TIME_CLASSES, classify_stored_game


def quick_check(connection):
    result = connection.execute("PRAGMA quick_check").fetchall()
    if result != [("ok",)]:
        raise RuntimeError(f"SQLite quick_check failed: {result}")


def migrate(database_path):
    database_path = Path(database_path).resolve(strict=True)
    backup_path = database_path.with_name(
        f"{database_path.stem}_before_time_class_{datetime.now():%Y%m%d_%H%M%S_%f}.db"
    )
    connection = sqlite3.connect(database_path.as_uri() + "?mode=rw", uri=True)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(games)")}
        required = {"game_id", "source", "time_control", "raw_pgn"}
        if not required <= columns:
            raise RuntimeError(f"Missing games columns: {sorted(required - columns)}")
        quick_check(connection)
        with closing(sqlite3.connect(backup_path)) as backup:
            connection.backup(backup)
            quick_check(backup)
        print(f"Verified safety backup: {backup_path}", flush=True)
        connection.execute("BEGIN IMMEDIATE")
        try:
            if "time_class" not in columns:
                allowed = ", ".join(repr(value) for value in TIME_CLASSES)
                connection.execute(
                    "ALTER TABLE games ADD COLUMN time_class TEXT NOT NULL DEFAULT 'unknown' "
                    f"CHECK (time_class IN ({allowed}))"
                )
            updates = []
            for game_id, source, clock, pgn, current in connection.execute(
                "SELECT game_id, source, time_control, raw_pgn, time_class FROM games"
            ):
                # Preserve valid classifications on reruns, including future provider metadata.
                if current in TIME_CLASSES and current != "unknown":
                    continue
                label = classify_stored_game(source, clock, pgn)
                if label != current:
                    updates.append((label, game_id))
            connection.executemany("UPDATE games SET time_class = ? WHERE game_id = ?", updates)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_games_time_class_source_game "
                "ON games(time_class, source, game_id)"
            )
            quick_check(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        quick_check(connection)
        print(f"Updated games: {len(updates):,}")
        for source, label, count in connection.execute(
            "SELECT source, time_class, COUNT(*) FROM games GROUP BY source, time_class ORDER BY source, time_class"
        ):
            print(f"  {source}: {label}: {count:,}")
        print("SQLite quick_check: ok")
        return backup_path
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(__file__).resolve().parent / "merlin.db")
    migrate(parser.parse_args().db)
