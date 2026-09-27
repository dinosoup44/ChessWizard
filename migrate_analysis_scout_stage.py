from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


DB_NAME = "merlin.db"


def create_safety_backup(database_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = database_path.with_name(
        f"merlin_before_scout_stage_{timestamp}.db"
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


def table_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    return {
        row[1]
        for row in connection.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
    }


def ensure_analysis_coverage_exists(
    connection: sqlite3.Connection,
) -> None:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'analysis_coverage'
        """
    ).fetchone()

    if row is None:
        raise RuntimeError(
            "analysis_coverage does not exist. "
            "Run migrate_analysis_coverage.py first."
        )


def add_scout_stage(
    connection: sqlite3.Connection,
) -> bool:
    columns = table_columns(
        connection,
        "analysis_coverage",
    )

    if "scout_version" in columns:
        return False

    connection.execute(
        """
        ALTER TABLE analysis_coverage
        ADD COLUMN scout_version TEXT
            NOT NULL DEFAULT '0'
        """
    )

    return True


def rebuild_version_index(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        DROP INDEX IF EXISTS
            idx_analysis_coverage_versions
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
            idx_analysis_coverage_versions
        ON analysis_coverage (
            analysis_type,
            screener_version,
            scout_version,
            analyzer_version
        )
        """
    )


def verify(
    connection: sqlite3.Connection,
) -> None:
    columns = table_columns(
        connection,
        "analysis_coverage",
    )

    if "scout_version" not in columns:
        raise RuntimeError(
            "Migration failed: scout_version was not created."
        )

    result = connection.execute(
        "PRAGMA quick_check"
    ).fetchone()

    if (
        result is None
        or str(result[0]).lower() != "ok"
    ):
        raise RuntimeError(
            "SQLite quick_check failed."
        )


def main() -> int:
    project_root = Path(__file__).resolve().parent
    database_path = project_root / DB_NAME

    if not database_path.exists():
        print(
            f"ERROR: Database not found: {database_path}"
        )
        return 1

    print()
    print("CHESSWIZARD SCOUT-STAGE MIGRATION")
    print("=================================")
    print(f"Database: {database_path}")

    print()
    print("Creating safety backup...")

    backup_path = create_safety_backup(
        database_path
    )

    print(
        f"Backup created: {backup_path.name}"
    )

    connection = sqlite3.connect(
        str(database_path)
    )

    try:
        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        ensure_analysis_coverage_exists(
            connection
        )

        changed = add_scout_stage(
            connection
        )

        rebuild_version_index(
            connection
        )

        verify(
            connection
        )

        connection.commit()

        row_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM analysis_coverage
            """
        ).fetchone()[0]

        scout_zero_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM analysis_coverage
            WHERE scout_version = '0'
            """
        ).fetchone()[0]

        print()
        print("SCOUT-STAGE MIGRATION COMPLETE")
        print("==============================")

        if changed:
            print(
                "Added: analysis_coverage.scout_version"
            )
        else:
            print(
                "scout_version already existed; "
                "no column change needed."
            )

        print(
            "Version index now tracks:"
        )
        print(
            "  analysis_type"
        )
        print(
            "  screener_version"
        )
        print(
            "  scout_version"
        )
        print(
            "  analyzer_version"
        )

        print()
        print(
            f"Coverage rows preserved: "
            f"{row_count:,}"
        )
        print(
            f"Legacy/current rows with scout_version 0: "
            f"{scout_zero_count:,}"
        )
        print(
            "SQLite quick_check: ok"
        )

        print()
        print("Meaning:")
        print(
            "  screener_version = cheap Python/chess filter"
        )
        print(
            "  scout_version    = light engine filter"
        )
        print(
            "  analyzer_version = heavy specialist"
        )
        print()
        print(
            "Existing fork/mate candidates remain current "
            "because their heavy analyzer versions are unchanged."
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
