import sqlite3


DB_NAME = "merlin.db"


def main():
    connection = sqlite3.connect(DB_NAME)
    cursor = connection.cursor()

    print("Creating analysis_runs table...")
    print()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS analysis_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,

            tool_name TEXT NOT NULL,
            tool_version INTEGER NOT NULL DEFAULT 1,

            status TEXT NOT NULL DEFAULT 'pending',

            moves_total INTEGER NOT NULL DEFAULT 0,
            moves_scanned INTEGER NOT NULL DEFAULT 0,
            candidates_found INTEGER NOT NULL DEFAULT 0,

            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
                REFERENCES users(user_id)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_analysis_runs_user_tool
        ON analysis_runs (
            user_id,
            tool_name,
            tool_version
        )
    """)

    connection.commit()

    cursor.execute("""
        SELECT COUNT(*)
        FROM analysis_runs
    """)

    count = cursor.fetchone()[0]

    connection.close()

    print("analysis_runs table ready!")
    print("Existing analysis runs:", count)


if __name__ == "__main__":
    main()