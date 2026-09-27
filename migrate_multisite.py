import sqlite3


DB_NAME = "merlin.db"


def column_exists(cursor, table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")

    columns = cursor.fetchall()

    for column in columns:
        if column[1] == column_name:
            return True

    return False


def main():
    connection = sqlite3.connect(DB_NAME)
    cursor = connection.cursor()

    print("Starting Merlin multi-site database migration...")
    print()

    # ---------------------------------------------------------
    # 1. Create chess_accounts
    #
    # One Merlin user can eventually have:
    #
    #   Lichess   -> ExampleUser
    #   Chess.com -> SomeOtherUsername
    #
    # ---------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chess_accounts (
            account_id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,

            source TEXT NOT NULL,
            username TEXT NOT NULL,

            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_sync_at TEXT,

            UNIQUE (source, username),

            FOREIGN KEY (user_id)
                REFERENCES users(user_id)
        )
    """)

    # ---------------------------------------------------------
    # 2. Convert existing Lichess users into chess_accounts
    # ---------------------------------------------------------

    cursor.execute("""
        SELECT
            user_id,
            lichess_username,
            last_sync_at
        FROM users
        WHERE lichess_username IS NOT NULL
    """)

    existing_users = cursor.fetchall()

    for user_id, lichess_username, last_sync_at in existing_users:

        cursor.execute("""
            INSERT OR IGNORE INTO chess_accounts (
                user_id,
                source,
                username,
                last_sync_at
            )
            VALUES (?, ?, ?, ?)
        """, (
            user_id,
            "lichess",
            lichess_username,
            last_sync_at
        ))

    # ---------------------------------------------------------
    # 3. Add source-neutral fields to games
    # ---------------------------------------------------------

    if not column_exists(cursor, "games", "account_id"):
        cursor.execute("""
            ALTER TABLE games
            ADD COLUMN account_id INTEGER
        """)

        print("Added games.account_id")

    if not column_exists(cursor, "games", "source"):
        cursor.execute("""
            ALTER TABLE games
            ADD COLUMN source TEXT
        """)

        print("Added games.source")

    if not column_exists(cursor, "games", "source_game_id"):
        cursor.execute("""
            ALTER TABLE games
            ADD COLUMN source_game_id TEXT
        """)

        print("Added games.source_game_id")

    # ---------------------------------------------------------
    # 4. Backfill existing Lichess games
    # ---------------------------------------------------------

    cursor.execute("""
        UPDATE games
        SET
            source = 'lichess',
            source_game_id = lichess_game_id
        WHERE source IS NULL
           OR source_game_id IS NULL
    """)

    # Attach each existing game to its corresponding
    # Lichess chess_accounts record.

    cursor.execute("""
        UPDATE games
        SET account_id = (
            SELECT ca.account_id
            FROM chess_accounts ca
            WHERE ca.user_id = games.user_id
              AND ca.source = 'lichess'
        )
        WHERE account_id IS NULL
    """)

    # ---------------------------------------------------------
    # 5. Create source-neutral duplicate protection
    #
    # Lichess game ABC123 and Chess.com game ABC123
    # are allowed to coexist because the sources differ.
    # ---------------------------------------------------------

    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS
        idx_games_source_game_id
        ON games (
            source,
            source_game_id
        )
    """)

    connection.commit()

    # ---------------------------------------------------------
    # 6. Show results
    # ---------------------------------------------------------

    print()
    print("CHESS ACCOUNTS")
    print("--------------")

    cursor.execute("""
        SELECT
            account_id,
            user_id,
            source,
            username,
            last_sync_at
        FROM chess_accounts
        ORDER BY account_id
    """)

    for row in cursor.fetchall():
        print(row)

    print()
    print("GAMES BY SOURCE")
    print("---------------")

    cursor.execute("""
        SELECT
            source,
            COUNT(*)
        FROM games
        GROUP BY source
    """)

    for row in cursor.fetchall():
        print(row[0], ":", row[1])

    print()
    print("Migration complete!")

    connection.close()


if __name__ == "__main__":
    main()