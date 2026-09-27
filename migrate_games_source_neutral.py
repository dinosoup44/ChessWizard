import sqlite3


DB_NAME = "merlin.db"


def main():
    connection = sqlite3.connect(DB_NAME)
    cursor = connection.cursor()

    print("Starting source-neutral games migration...")
    print()

    # SQLite cannot simply remove a NOT NULL constraint from
    # an existing column, so we rebuild the games table.
    #
    # Foreign keys are temporarily disabled because moves
    # currently point to games.game_id.

    cursor.execute("PRAGMA foreign_keys = OFF")

    try:
        cursor.execute("BEGIN TRANSACTION")

        # -----------------------------------------------------
        # Create the replacement games table.
        #
        # Important:
        # - game_id values are preserved
        # - source/source_game_id become the real identifiers
        # - lichess_game_id remains temporarily for compatibility
        #   but is now allowed to be NULL
        # -----------------------------------------------------

        cursor.execute("""
            CREATE TABLE games_new (
                game_id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,
                account_id INTEGER,

                source TEXT NOT NULL,
                source_game_id TEXT NOT NULL,

                lichess_game_id TEXT,

                played_at TEXT,

                white_username TEXT,
                black_username TEXT,
                user_color TEXT,

                white_rating INTEGER,
                black_rating INTEGER,

                result TEXT,
                termination TEXT,

                time_control TEXT,
                rated INTEGER,
                variant TEXT,

                raw_pgn TEXT,

                imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (user_id)
                    REFERENCES users(user_id),

                FOREIGN KEY (account_id)
                    REFERENCES chess_accounts(account_id),

                UNIQUE (source, source_game_id)
            )
        """)

        # -----------------------------------------------------
        # Copy all existing games.
        # -----------------------------------------------------

        cursor.execute("""
            INSERT INTO games_new (
                game_id,
                user_id,
                account_id,
                source,
                source_game_id,
                lichess_game_id,
                played_at,
                white_username,
                black_username,
                user_color,
                white_rating,
                black_rating,
                result,
                termination,
                time_control,
                rated,
                variant,
                raw_pgn,
                imported_at
            )
            SELECT
                game_id,
                user_id,
                account_id,
                source,
                source_game_id,
                lichess_game_id,
                played_at,
                white_username,
                black_username,
                user_color,
                white_rating,
                black_rating,
                result,
                termination,
                time_control,
                rated,
                variant,
                raw_pgn,
                imported_at
            FROM games
        """)

        # -----------------------------------------------------
        # Replace old table with new table.
        # -----------------------------------------------------

        cursor.execute("""
            DROP TABLE games
        """)

        cursor.execute("""
            ALTER TABLE games_new
            RENAME TO games
        """)

        # Helpful lookup indexes.

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_games_user_id
            ON games(user_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_games_account_id
            ON games(account_id)
        """)

        cursor.execute("COMMIT")

        print("Games table rebuilt successfully.")

    except Exception:
        cursor.execute("ROLLBACK")
        raise

    finally:
        cursor.execute("PRAGMA foreign_keys = ON")

    # ---------------------------------------------------------
    # Verification
    # ---------------------------------------------------------

    print()
    print("VERIFYING GAMES")
    print("---------------")

    cursor.execute("""
        SELECT
            source,
            COUNT(*)
        FROM games
        GROUP BY source
        ORDER BY source
    """)

    for source, count in cursor.fetchall():
        print(source, ":", count)

    print()
    print("VERIFYING MOVES")
    print("---------------")

    cursor.execute("""
        SELECT COUNT(*)
        FROM moves
    """)

    print("Moves still stored:", cursor.fetchone()[0])

    print()
    print("VERIFYING MATE CANDIDATES")
    print("-------------------------")

    cursor.execute("""
        SELECT COUNT(*)
        FROM tactic_candidates
        WHERE tactic_type = 'missed_mate'
    """)

    print(
        "Missed-mate candidates still stored:",
        cursor.fetchone()[0]
    )

    connection.close()

    print()
    print("Source-neutral migration complete!")


if __name__ == "__main__":
    main()