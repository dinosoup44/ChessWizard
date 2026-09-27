import sqlite3
import chess
from game_import_pgn import split_pgn_games, played_timestamp
from game_import_http import open_text, read_text
from urllib.parse import quote, urlencode, urlparse
from time_class import classify_time_control, require_time_class_schema


DB_NAME = "merlin.db"
SOURCE = "lichess"


def get_or_create_merlin_user(connection, username):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT user_id
        FROM users
        WHERE lichess_username = ?
    """, (username,))

    row = cursor.fetchone()

    if row:
        return row[0]

    cursor.execute("""
        INSERT INTO users (
            lichess_username
        )
        VALUES (?)
    """, (username,))

    connection.commit()

    return cursor.lastrowid


def get_or_create_chess_account(connection, user_id, username):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT account_id
        FROM chess_accounts
        WHERE source = ?
          AND username = ?
    """, (
        SOURCE,
        username
    ))

    row = cursor.fetchone()

    if row:
        return row[0]

    cursor.execute("""
        INSERT INTO chess_accounts (
            user_id,
            source,
            username
        )
        VALUES (?, ?, ?)
    """, (
        user_id,
        SOURCE,
        username
    ))

    connection.commit()

    return cursor.lastrowid


def download_games(username, max_games=50, *, stream=False):
    parameters = {"ongoing": "false", "finished": "true", "sort": "dateDesc"}
    if max_games is not None:
        parameters["max"] = max_games
    url = "https://lichess.org/api/games/user/" + quote(username, safe="") + "?" + urlencode(parameters)
    return open_text(url) if stream else read_text(url)


def get_source_game_id(game):
    explicit = game.headers.get("GameId")
    if explicit:
        return explicit
    site = urlparse(game.headers.get("Site", ""))
    parts = site.path.strip("/").split("/")
    if site.hostname == "lichess.org" and parts and len(parts[0]) == 8 and parts[0].isalnum():
        return parts[0]
    return None

def game_exists(connection, source_game_id):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT game_id
        FROM games
        WHERE source = ?
          AND source_game_id = ?
    """, (
        SOURCE,
        source_game_id
    ))

    return cursor.fetchone() is not None


def import_single_game(
    connection: sqlite3.Connection,
    user_id: int,
    account_id: int,
    username: str,
    game: chess.pgn.Game,
    raw_pgn: str
) -> bool:
    """Normalize one provider game without committing the caller's transaction.

    Args:
        connection: Caller-owned writable database.
        user_id: Existing local user.
        account_id: Existing provider account.
        username: Imported account name.
        game: Parsed provider PGN.
        raw_pgn: Original provider text.

    Returns:
        True if inserted; False for duplicate, empty or unsupported records.

    Raises:
        sqlite3.Error: Schema or persistence failed.
    """
    from game_import_pgn import has_legal_move
    if not has_legal_move(game):
        return False
    require_time_class_schema(connection)
    source_game_id = get_source_game_id(game)

    if not source_game_id:
        print("Skipping game with no GameId.")
        return False

    if game_exists(connection, source_game_id):
        return False

    cursor = connection.cursor()

    white_username = game.headers.get("White")
    black_username = game.headers.get("Black")

    if white_username and white_username.lower() == username.lower():
        user_color = "white"
    elif black_username and black_username.lower() == username.lower():
        user_color = "black"
    else:
        print(
            f"Skipping {source_game_id}: "
            f"{username} was not found in the game."
        )
        return False

    cursor.execute("""
        INSERT INTO games (
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
            time_class,
            rated,
            variant,
            raw_pgn
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        account_id,
        SOURCE,
        source_game_id,

        # Keep the old Lichess field populated for now.
        # We can remove it later after every script
        # has been converted to the new model.
        source_game_id,

        played_timestamp(game.headers),
        white_username,
        black_username,
        user_color,
        game.headers.get("WhiteElo"),
        game.headers.get("BlackElo"),
        game.headers.get("Result"),
        game.headers.get("Termination"),
        game.headers.get("TimeControl"),
        classify_time_control(SOURCE, headers=game.headers),
        1 if "rated" in game.headers.get("Event", "").lower() else 0,
        game.headers.get("Variant"),
        raw_pgn
    ))

    game_id = cursor.lastrowid

    board = game.board()
    ply_number = 0

    for move in game.mainline_moves():
        ply_number += 1

        move_number = board.fullmove_number
        color = "white" if board.turn == chess.WHITE else "black"
        is_user_move = 1 if color == user_color else 0

        fen_before = board.fen()
        san_played = board.san(move)
        uci_played = move.uci()

        board.push(move)

        fen_after = board.fen()

        cursor.execute("""
            INSERT INTO moves (
                game_id,
                ply_number,
                move_number,
                color,
                is_user_move,
                fen_before,
                fen_after,
                san_played,
                uci_played
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            game_id,
            ply_number,
            move_number,
            color,
            is_user_move,
            fen_before,
            fen_after,
            san_played,
            uci_played
        ))

    return True


def sync_games(
    connection,
    user_id,
    account_id,
    username,
    max_games=50
):
    print()
    print(
        f"Downloading up to {max_games} "
        f"recent Lichess games..."
    )

    pgn_text = download_games(
        username,
        max_games
    )

    downloaded_count = 0
    imported_count = 0
    skipped_count = 0

    for game, raw_pgn in split_pgn_games(pgn_text):
        downloaded_count += 1

        imported = import_single_game(
            connection,
            user_id,
            account_id,
            username,
            game,
            raw_pgn
        )

        if imported:
            imported_count += 1

            print(
                "Imported:",
                game.headers.get("GameId"),
                "-",
                game.headers.get("White"),
                "vs",
                game.headers.get("Black")
            )

        else:
            skipped_count += 1

    connection.commit()

    cursor = connection.cursor()

    cursor.execute("""
        UPDATE chess_accounts
        SET last_sync_at = CURRENT_TIMESTAMP
        WHERE account_id = ?
    """, (
        account_id,
    ))

    connection.commit()

    print()
    print("Lichess sync complete!")
    print("Games downloaded:", downloaded_count)
    print("New games imported:", imported_count)
    print("Already known / skipped:", skipped_count)


def main():
    username = input(
        "Enter your Lichess username: "
    ).strip()

    connection = sqlite3.connect(DB_NAME)

    try:
        user_id = get_or_create_merlin_user(
            connection,
            username
        )

        account_id = get_or_create_chess_account(
            connection,
            user_id,
            username
        )

        sync_games(
            connection,
            user_id,
            account_id,
            username,
            max_games=50
        )

    finally:
        connection.close()


if __name__ == "__main__":
    main()
