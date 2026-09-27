from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


DB_NAME = "merlin.db"


def create_safety_backup(database_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = database_path.with_name(
        f"merlin_before_analysis_coverage_{timestamp}.db"
    )

    source = sqlite3.connect(str(database_path))
    destination = sqlite3.connect(str(backup_path))

    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()

    return backup_path


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()

    return row is not None


def create_analysis_coverage_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_coverage (
            coverage_id INTEGER PRIMARY KEY AUTOINCREMENT,
            move_id INTEGER NOT NULL,
            analysis_type TEXT NOT NULL,
            screener_version TEXT NOT NULL DEFAULT '0',
            analyzer_version TEXT NOT NULL DEFAULT '0',
            coverage_status TEXT NOT NULL
                CHECK (
                    coverage_status IN (
                        'screened_out',
                        'analyzed_no_hit',
                        'candidate',
                        'rejected',
                        'error'
                    )
                ),
            candidate_id INTEGER,
            details_json TEXT,
            checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (move_id)
                REFERENCES moves (move_id)
                ON DELETE CASCADE,

            FOREIGN KEY (candidate_id)
                REFERENCES tactic_candidates (candidate_id)
                ON DELETE SET NULL,

            UNIQUE (move_id, analysis_type)
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_analysis_coverage_type_status
        ON analysis_coverage (
            analysis_type,
            coverage_status
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_analysis_coverage_versions
        ON analysis_coverage (
            analysis_type,
            screener_version,
            analyzer_version
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_analysis_coverage_candidate
        ON analysis_coverage (
            candidate_id
        )
        """
    )


def normalize_candidate_status(candidate_status: str | None) -> str:
    value = (candidate_status or "").strip().lower()

    if value == "rejected":
        return "rejected"

    return "candidate"


def backfill_existing_tactic_rows(
    connection: sqlite3.Connection,
) -> tuple[int, int]:
    """
    Backfill only tactic results that already exist.

    Missing tactic rows are NOT treated as proof that a move
    was analyzed and found clean.
    """

    if not table_exists(connection, "tactic_candidates"):
        return 0, 0

    rows = connection.execute(
        """
        SELECT
            tc.candidate_id,
            tc.move_id,
            tc.tactic_type,
            tc.candidate_status,
            tc.detector_version
        FROM tactic_candidates tc
        INNER JOIN moves m
            ON m.move_id = tc.move_id
        INNER JOIN games g
            ON g.game_id = m.game_id
        WHERE tc.candidate_id > 0
          AND COALESCE(g.source, '') <> 'dev'
        ORDER BY
            tc.move_id,
            tc.tactic_type,
            tc.candidate_id
        """
    ).fetchall()

    inserted_or_updated = 0
    skipped = 0

    for row in rows:
        (
            candidate_id,
            move_id,
            tactic_type,
            candidate_status,
            detector_version,
        ) = row

        if not tactic_type:
            skipped += 1
            continue

        analyzer_version = str(
            detector_version if detector_version is not None else "0"
        )

        coverage_status = normalize_candidate_status(candidate_status)

        connection.execute(
            """
            INSERT INTO analysis_coverage (
                move_id,
                analysis_type,
                screener_version,
                analyzer_version,
                coverage_status,
                candidate_id,
                details_json,
                checked_at,
                updated_at
            )
            VALUES (
                ?,
                ?,
                '0',
                ?,
                ?,
                ?,
                NULL,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (move_id, analysis_type)
            DO UPDATE SET
                analyzer_version = excluded.analyzer_version,
                coverage_status = excluded.coverage_status,
                candidate_id = excluded.candidate_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                move_id,
                tactic_type,
                analyzer_version,
                coverage_status,
                candidate_id,
            ),
        )

        inserted_or_updated += 1

    return inserted_or_updated, skipped


def verify_schema(connection: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(analysis_coverage)"
        ).fetchall()
    }

    required_columns = {
        "coverage_id",
        "move_id",
        "analysis_type",
        "screener_version",
        "analyzer_version",
        "coverage_status",
        "candidate_id",
        "details_json",
        "checked_at",
        "updated_at",
    }

    missing = required_columns - columns

    if missing:
        raise RuntimeError(
            "analysis_coverage is missing columns: "
            + ", ".join(sorted(missing))
        )

    quick_check = connection.execute("PRAGMA quick_check").fetchone()

    if quick_check is None or str(quick_check[0]).lower() != "ok":
        raise RuntimeError(
            "SQLite quick_check failed after migration."
        )


def print_summary(
    connection: sqlite3.Connection,
    backup_path: Path,
    backfilled: int,
    skipped: int,
) -> None:
    total = connection.execute(
        "SELECT COUNT(*) FROM analysis_coverage"
    ).fetchone()[0]

    print()
    print("ANALYSIS COVERAGE MIGRATION COMPLETE")
    print("====================================")
    print(f"Safety backup: {backup_path.name}")
    print(f"Coverage rows: {total:,}")
    print(f"Existing tactic rows backfilled: {backfilled:,}")

    if skipped:
        print(f"Existing tactic rows skipped: {skipped:,}")

    print()
    print("Coverage by analysis type:")

    type_rows = connection.execute(
        """
        SELECT
            analysis_type,
            COUNT(*) AS row_count
        FROM analysis_coverage
        GROUP BY analysis_type
        ORDER BY analysis_type
        """
    ).fetchall()

    if not type_rows:
        print("  (none yet)")
    else:
        for analysis_type, row_count in type_rows:
            print(f"  {analysis_type}: {row_count:,}")

    print()
    print("Coverage by status:")

    status_rows = connection.execute(
        """
        SELECT
            coverage_status,
            COUNT(*) AS row_count
        FROM analysis_coverage
        GROUP BY coverage_status
        ORDER BY coverage_status
        """
    ).fetchall()

    if not status_rows:
        print("  (none yet)")
    else:
        for coverage_status, row_count in status_rows:
            print(f"  {coverage_status}: {row_count:,}")

    print()
    print("SQLite quick_check: ok")
    print()
    print("Important:")
    print("  Only existing tactic results were backfilled.")
    print(
        "  Moves with no old tactic row were NOT marked as already analyzed."
    )
    print(
        "  The crawler will create negative coverage records as it checks them."
    )


def main() -> int:
    project_root = Path(__file__).resolve().parent
    database_path = project_root / DB_NAME

    if not database_path.exists():
        print(f"ERROR: Database not found: {database_path}")
        return 1

    print()
    print("CHESSWIZARD ANALYSIS COVERAGE MIGRATION")
    print("=======================================")
    print(f"Database: {database_path}")

    print()
    print("Creating safety backup...")

    backup_path = create_safety_backup(database_path)

    print(f"Backup created: {backup_path.name}")

    connection = sqlite3.connect(str(database_path))

    try:
        connection.execute("PRAGMA foreign_keys = ON")

        print()
        print("Creating analysis_coverage table...")

        create_analysis_coverage_table(connection)

        print("Backfilling existing tactic results...")

        backfilled, skipped = backfill_existing_tactic_rows(connection)

        verify_schema(connection)
        connection.commit()

        print_summary(
            connection,
            backup_path,
            backfilled,
            skipped,
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
