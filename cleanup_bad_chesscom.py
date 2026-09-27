import sqlite3


DB_NAME = "merlin.db"


def main():
    connection = sqlite3.connect(DB_NAME)
    cursor = connection.cursor()

    cursor.execute("""
        SELECT game_id
        FROM games
        WHERE source = 'chesscom'
          AND source_game_id = 'Chess.com'
    """)

    rows = cursor.fetchall()
    game_ids = [row[0] for row in rows]

    moves_deleted = 0
    games_deleted = 0

    for game_id in game_ids:
        cursor.execute("""
            DELETE FROM moves
            WHERE game_id = ?
        """, (game_id,))

        moves_deleted += cursor.rowcount

        cursor.execute("""
            DELETE FROM games
            WHERE game_id = ?
        """, (game_id,))

        games_deleted += cursor.rowcount

    connection.commit()
    connection.close()

    print("Chess.com cleanup complete!")
    print("Bad games removed:", games_deleted)
    print("Associated moves removed:", moves_deleted)


if __name__ == "__main__":
    main()