"""Add explicit scout-negative coverage without reinterpreting existing rows."""
import argparse
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path


OLD_COLUMNS = (
    "coverage_id", "move_id", "analysis_type", "screener_version",
    "analyzer_version", "coverage_status", "candidate_id", "details_json",
    "checked_at", "updated_at", "scout_version",
)

CREATE_TABLE = """
    CREATE TABLE analysis_coverage_new (
        coverage_id INTEGER PRIMARY KEY AUTOINCREMENT,
        move_id INTEGER NOT NULL,
        analysis_type TEXT NOT NULL,
        screener_version TEXT NOT NULL DEFAULT '0',
        analyzer_version TEXT NOT NULL DEFAULT '0',
        coverage_status TEXT NOT NULL CHECK (coverage_status IN (
            'screened_out', 'scouted_out', 'analyzed_no_hit',
            'candidate', 'rejected', 'error'
        )),
        candidate_id INTEGER,
        details_json TEXT,
        checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        scout_version TEXT NOT NULL DEFAULT '0',
        scout_config TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (move_id) REFERENCES moves (move_id) ON DELETE CASCADE,
        FOREIGN KEY (candidate_id) REFERENCES tactic_candidates (candidate_id) ON DELETE SET NULL,
        UNIQUE (move_id, analysis_type),
        CHECK (coverage_status <> 'scouted_out' OR (
            scout_version NOT IN ('', '0') AND length(trim(scout_config)) > 0
        ))
    )
"""


def verify_integrity(connection):
    quick = connection.execute("PRAGMA quick_check").fetchall()
    if quick != [("ok",)]:
        raise RuntimeError(f"SQLite quick_check failed: {quick}")
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        raise RuntimeError(f"Foreign-key check failed: {foreign_keys[:10]}")


def schema_is_current(connection):
    schema = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='analysis_coverage'"
    ).fetchone()
    if schema is None:
        raise RuntimeError("Run the analysis coverage and scout-stage migrations first.")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(analysis_coverage)")}
    if columns == set(OLD_COLUMNS):
        return False
    if columns == {*OLD_COLUMNS, "scout_config"} and "'scouted_out'" in schema[0]:
        return True
    raise RuntimeError("Unexpected coverage schema; refusing to rebuild or discard unrecognized columns.")


def rebuild_coverage(connection):
    """Called inside one transaction with foreign keys temporarily disabled.

    Only this table is rebuilt. Copy rows before dropping the old table; restore
    its indexes/triggers and AUTOINCREMENT high-water mark after renaming.
    """
    objects = connection.execute(
        "SELECT sql FROM sqlite_master WHERE tbl_name='analysis_coverage' "
        "AND type IN ('index','trigger') AND sql IS NOT NULL ORDER BY type,name"
    ).fetchall()
    sequence = connection.execute(
        "SELECT seq FROM sqlite_sequence WHERE name='analysis_coverage'"
    ).fetchone()
    columns = ", ".join(OLD_COLUMNS)
    original_rows = connection.execute(
        f"SELECT {columns} FROM analysis_coverage ORDER BY coverage_id"
    ).fetchall()
    connection.execute(CREATE_TABLE)
    connection.execute(
        f"INSERT INTO analysis_coverage_new ({columns}) SELECT {columns} FROM analysis_coverage"
    )
    copied_rows = connection.execute(
        f"SELECT {columns} FROM analysis_coverage_new ORDER BY coverage_id"
    ).fetchall()
    if copied_rows != original_rows:
        raise RuntimeError("Coverage copy differs from original rows; rolling back.")
    connection.execute("DROP TABLE analysis_coverage")
    connection.execute("ALTER TABLE analysis_coverage_new RENAME TO analysis_coverage")
    for (sql,) in objects:
        connection.execute(sql)
    if sequence is not None:
        connection.execute("UPDATE sqlite_sequence SET seq=? WHERE name='analysis_coverage'", sequence)
    if connection.execute(
        f"SELECT {columns} FROM analysis_coverage ORDER BY coverage_id"
    ).fetchall() != original_rows:
        raise RuntimeError("Coverage rows changed during rebuild; rolling back.")


def migrate(database_path):
    database_path = Path(database_path).resolve(strict=True)
    backup_path = database_path.with_name(
        f"{database_path.stem}_before_scout_rejection_{datetime.now():%Y%m%d_%H%M%S_%f}.db"
    )
    with closing(sqlite3.connect(database_path.as_uri() + "?mode=rw", uri=True)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        schema_is_current(connection)
        verify_integrity(connection)
        with closing(sqlite3.connect(backup_path)) as backup:
            connection.backup(backup)
            verify_integrity(backup)
        print(f"Verified SQLite safety backup: {backup_path}", flush=True)
        # SQLite's documented table-rebuild procedure: foreign_keys must be
        # disabled outside the transaction, then checked before committing.
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("BEGIN IMMEDIATE")
        try:
            changed = not schema_is_current(connection)
            if changed:
                rebuild_coverage(connection)
            verify_integrity(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys=ON")
        verify_integrity(connection)
        print("Added scouted_out and scout_config." if changed else "Schema already current; no changes.")
        for status, count in connection.execute(
            "SELECT coverage_status,COUNT(*) FROM analysis_coverage GROUP BY coverage_status ORDER BY coverage_status"
        ):
            print(f"  {status}: {count:,}")
        print("All original coverage fields preserved; no negative results backfilled.")
        print("SQLite quick_check: ok; foreign_key_check: ok")
    return backup_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(__file__).resolve().parent / "merlin.db")
    migrate(parser.parse_args().db)
