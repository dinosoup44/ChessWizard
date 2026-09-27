import sqlite3
import re
import chess
from game_import_pgn import split_pgn_games, played_timestamp
from game_import_http import open_text, read_text, read_json
from urllib.parse import quote, urlparse
from time_class import classify_time_control, require_time_class_schema


DB_NAME = "merlin.db"
SOURCE = "chesscom"


def get_merlin_user(connection):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT user_id
        FROM users
        ORDER BY user_id
        LIMIT 1
    """)

    row = cursor.fetchone()

    if row is None:
        raise RuntimeError(
            "No Merlin user exists yet. "
            "Import a Lichess account first."
        )

    return row[0]


def get_or_create_chess_account(
    connection,
    user_id,
    username
):
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


def get_archive_urls(username):
    url = "https://api.chess.com/pub/player/" + quote(username, safe="") + "/games/archives"
    data = read_json(url)
    if not isinstance(data, dict) or not isinstance(data.get("archives"), list):
        raise ValueError("The source returned an unexpected archive list")
    archives = data["archives"]
    prefix = "/pub/player/" + username.casefold() + "/games/"
    for archive in archives:
        if not isinstance(archive, str):
            raise ValueError("Invalid archive URL")
        parsed = urlparse(archive)
        monthly_path = re.fullmatch(re.escape(prefix) + r"[0-9]{4}/(?:0[1-9]|1[0-2])", parsed.path.casefold())
        if parsed.scheme != "https" or parsed.netloc != "api.chess.com" or not monthly_path or parsed.query or parsed.fragment:
            raise ValueError("Unexpected source archive URL")
    return sorted(set(archives))


def download_archive_pgn(archive_url, *, stream=False):
    url = archive_url + "/pgn"
    return open_text(url) if stream else read_text(url)

def get_source_game_id(game):
    link = game.headers.get("Link", "")

    if link:
        return link.rstrip("/").split("/")[-1]

    site = game.headers.get("Site", "")

    if "chess.com/game/" in site.lower():
        return site.rstrip("/").split("/")[-1]

    return None


def game_exists(
    connection,
    source_game_id
):
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
        print("Skipping game with no usable game ID.")
        return False

    if game_exists(
        connection,
        source_game_id
    ):
        return False

    white_username = game.headers.get("White")
    black_username = game.headers.get("Black")

    if (
        white_username
        and white_username.lower() == username.lower()
    ):
        user_color = "white"

    elif (
        black_username
        and black_username.lower() == username.lower()
    ):
        user_color = "black"

    else:
        print(
            f"Skipping {source_game_id}: "
            f"{username} not found in game."
        )
        return False

    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO games (
            user_id,
            account_id,
            source,
            source_game_id,
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        account_id,
        SOURCE,
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
        1 if "rated" in game.headers.get(
            "Event",
            ""
        ).lower() else 0,
        game.headers.get("Variant"),
        raw_pgn
    ))

    game_id = cursor.lastrowid

    board = game.board()
    ply_number = 0

    for move in game.mainline_moves():
        ply_number += 1

        move_number = board.fullmove_number

        color = (
            "white"
            if board.turn == chess.WHITE
            else "black"
        )

        is_user_move = (
            1
            if color == user_color
            else 0
        )

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


def sync_chesscom(
    connection,
    user_id,
    account_id,
    username
):
    print()
    print(
        f"Looking up Chess.com archives for "
        f"{username}..."
    )

    archive_urls = get_archive_urls(
        username
    )

    print(
        "Archive months found:",
        len(archive_urls)
    )

    imported_count = 0
    skipped_count = 0
    downloaded_count = 0

    # Newest months first.
    for archive_url in reversed(archive_urls):

        month_label = "/".join(
            archive_url.rstrip("/").split("/")[-2:]
        )

        print()
        print("Downloading:", month_label)

        pgn_text = download_archive_pgn(
            archive_url
        )

        for game, raw_pgn in split_pgn_games(
            pgn_text
        ):
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
                    "  Imported:",
                    get_source_game_id(game),
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
    print("CHESS.COM SYNC COMPLETE")
    print("-----------------------")
    print(
        "Games downloaded:",
        downloaded_count
    )
    print(
        "New games imported:",
        imported_count
    )
    print(
        "Already known / skipped:",
        skipped_count
    )


def main():
    username = input(
        "Enter your Chess.com username: "
    ).strip()

    connection = sqlite3.connect(
        DB_NAME
    )

    try:
        user_id = get_merlin_user(
            connection
        )

        account_id = (
            get_or_create_chess_account(
                connection,
                user_id,
                username
            )
        )

        sync_chesscom(
            connection,
            user_id,
            account_id,
            username
        )

    finally:
        connection.close()


if __name__ == "__main__":
    main()
