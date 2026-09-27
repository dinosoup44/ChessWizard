import sqlite3
import json


DB_NAME = "merlin.db"

TEST_GAME_ID = -1
TEST_MOVE_ID = -1
TEST_CANDIDATE_ID = -1

TEST_SOURCE = "dev"
TEST_SOURCE_GAME_ID = (
    "MERLIN_TEST_ROOK_FORK"
)


# -------------------------------------------------
# TEST POSITION
# -------------------------------------------------

# White:
#   King g1
#   Rook e1
#
# Black:
#   King g6
#   Bishop e8
#
# White to move.
#
# Solution:
#
#   Re6+ Kh7 Rxe8
#
# The rook moves up to e6 and forks:
#
#   King g6
#   Bishop e8
#
# Black moves the king away to h7.
#
# White then captures the bishop on e8.
#
# Because the king is now on h7, the rook
# survives and White genuinely wins the bishop.
#
# Puzzle ends immediately after Rxe8.

FEN_BEFORE = (
    "4b3/8/6k1/8/8/8/8/"
    "4R1K1 w - - 0 1"
)

# Pretend the player actually played Re2.
FEN_AFTER_PLAYED = (
    "4b3/8/6k1/8/8/8/"
    "4R3/6K1 b - - 1 1"
)

PLAYED_SAN = "Re2"
PLAYED_UCI = "e1e2"

SOLUTION_SAN = "Re6+"
SOLUTION_UCI = "e1e6"

SOLUTION_LINE = (
    "Re6+ Kh7 Rxe8"
)


def get_table_info(
    cursor,
    table_name
):
    cursor.execute(
        f"PRAGMA table_info({table_name})"
    )

    return cursor.fetchall()


def insert_known_columns(
    cursor,
    table_name,
    values
):
    """
    Insert only columns that actually exist
    in the current Merlin database.

    This makes the developer seed safer as
    our schema continues evolving.
    """

    table_info = get_table_info(
        cursor,
        table_name
    )

    existing_columns = {
        row[1]
        for row in table_info
    }

    insert_values = {
        key: value
        for key, value in values.items()
        if key in existing_columns
    }

    missing_required = []

    for row in table_info:

        (
            column_id,
            column_name,
            column_type,
            not_null,
            default_value,
            primary_key
        ) = row

        if primary_key:
            continue

        if (
            not_null
            and default_value is None
            and column_name
            not in insert_values
        ):
            missing_required.append(
                column_name
            )

    if missing_required:

        raise RuntimeError(
            f"Cannot seed {table_name}. "
            f"Required columns missing: "
            f"{missing_required}"
        )

    columns = list(
        insert_values.keys()
    )

    placeholders = ", ".join(
        "?"
        for _ in columns
    )

    column_sql = ", ".join(
        columns
    )

    sql = (
        f"INSERT INTO {table_name} "
        f"({column_sql}) "
        f"VALUES ({placeholders})"
    )

    cursor.execute(
        sql,
        [
            insert_values[column]
            for column in columns
        ]
    )


def remove_existing_test_data(
    cursor
):
    """
    Makes the script rerunnable.

    Any previous training attempts against
    developer candidate -1 are also removed.
    """

    cursor.execute("""
        DELETE FROM training_attempts
        WHERE candidate_id = ?
    """, (
        TEST_CANDIDATE_ID,
    ))

    cursor.execute("""
        DELETE FROM tactic_episode_members
        WHERE candidate_id = ?
    """, (
        TEST_CANDIDATE_ID,
    ))

    cursor.execute("""
        DELETE FROM tactic_episodes
        WHERE primary_candidate_id = ?
           OR game_id = ?
    """, (
        TEST_CANDIDATE_ID,
        TEST_GAME_ID,
    ))

    cursor.execute("""
        DELETE FROM engine_analysis
        WHERE move_id = ?
    """, (
        TEST_MOVE_ID,
    ))

    cursor.execute("""
        DELETE FROM tactic_candidates
        WHERE candidate_id = ?
           OR move_id = ?
    """, (
        TEST_CANDIDATE_ID,
        TEST_MOVE_ID,
    ))

    cursor.execute("""
        DELETE FROM moves
        WHERE move_id = ?
           OR game_id = ?
    """, (
        TEST_MOVE_ID,
        TEST_GAME_ID,
    ))

    cursor.execute("""
        DELETE FROM games
        WHERE game_id = ?
    """, (
        TEST_GAME_ID,
    ))


def main():

    connection = sqlite3.connect(
        DB_NAME
    )

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    try:

        cursor = connection.cursor()

        print()
        print(
            "MERLIN DEV TEST PUZZLE"
        )

        print(
            "----------------------"
        )

        # -----------------------------------------
        # USER / ACCOUNT
        # -----------------------------------------

        cursor.execute("""
            SELECT user_id
            FROM users
            ORDER BY user_id
            LIMIT 1
        """)

        user_row = cursor.fetchone()

        if user_row is None:

            raise RuntimeError(
                "No Merlin user exists."
            )

        user_id = user_row[0]

        cursor.execute("""
            SELECT account_id
            FROM chess_accounts
            WHERE user_id = ?
            ORDER BY account_id
            LIMIT 1
        """, (
            user_id,
        ))

        account_row = (
            cursor.fetchone()
        )

        account_id = (
            account_row[0]
            if account_row
            else None
        )

        # -----------------------------------------
        # CLEAR OLD COPY
        # -----------------------------------------

        remove_existing_test_data(
            cursor
        )

        # -----------------------------------------
        # TEST GAME
        # -----------------------------------------

        game_values = {
            "game_id":
                TEST_GAME_ID,

            "user_id":
                user_id,

            "account_id":
                account_id,

            "source":
                TEST_SOURCE,

            "source_game_id":
                TEST_SOURCE_GAME_ID,

            "lichess_game_id":
                None,

            "played_at":
                "2026-01-01 00:00:00",

            "white_username":
                "ExampleUser",

            "black_username":
                "Merlin Test",

            "user_color":
                "white",

            "white_rating":
                None,

            "black_rating":
                None,

            "result":
                "*",

            "termination":
                "developer_test",

            "time_control":
                "test",

            "rated":
                0,

            "variant":
                "standard",

            "raw_pgn":
                None,
        }

        insert_known_columns(
            cursor,
            "games",
            game_values
        )

        # -----------------------------------------
        # TEST MOVE
        # -----------------------------------------

        move_values = {
            "move_id":
                TEST_MOVE_ID,

            "game_id":
                TEST_GAME_ID,

            "ply_number":
                1,

            "move_number":
                1,

            "color":
                "white",

            "is_user_move":
                1,

            "fen_before":
                FEN_BEFORE,

            "fen_after":
                FEN_AFTER_PLAYED,

            "san_played":
                PLAYED_SAN,

            "uci_played":
                PLAYED_UCI,
        }

        insert_known_columns(
            cursor,
            "moves",
            move_values
        )

        # -----------------------------------------
        # FORK METADATA
        # -----------------------------------------

        metadata = {
            "detector":
                "developer_test",

            "developer_test":
                True,

            "fork_piece":
                "rook",

            "fork_from":
                "e1",

            "fork_to":
                "e6",

            "targets": [
                {
                    "piece":
                        "bishop",

                    "piece_type":
                        3,

                    "square":
                        "e8",

                    "value":
                        300,
                },

                {
                    "piece":
                        "king",

                    "piece_type":
                        6,

                    "square":
                        "g6",

                    "value":
                        10000,
                },
            ],

            "played_move":
                PLAYED_SAN,

            "evaluation_before": {
                "type":
                    "cp",

                "cp":
                    300,

                "mate":
                    None,
            },

            "evaluation_after_played": {
                "type":
                    "cp",

                "cp":
                    0,

                "mate":
                    None,
            },

            "evaluation_after_fork": {
                "type":
                    "cp",

                "cp":
                    300,

                "mate":
                    None,
            },

            "gain_vs_played_cp":
                300,

            "drop_from_best_cp":
                0,

            "avoids_forced_mate":
                False,

            "realization": {
                "opponent_reply":
                    "Kh7",

                "conversion_move":
                    "Rxe8",

                "won_piece":
                    "bishop",

                "won_square":
                    "e8",
            },
        }

        # -----------------------------------------
        # TEST CANDIDATE
        # -----------------------------------------

        candidate_values = {
            "candidate_id":
                TEST_CANDIDATE_ID,

            "move_id":
                TEST_MOVE_ID,

            "tactic_type":
                "missed_fork",

            "candidate_status":
                "candidate",

            "confidence":
                1.0,

            "detector_version":
                999,

            "solution_move_uci":
                SOLUTION_UCI,

            "solution_move_san":
                SOLUTION_SAN,

            "solution_line":
                SOLUTION_LINE,

            "notes":
                (
                    "Developer test puzzle. "
                    "Simple rook fork used for "
                    "UI and training testing."
                ),

            "metadata_json":
                json.dumps(
                    metadata,
                    sort_keys=True
                ),
        }

        insert_known_columns(
            cursor,
            "tactic_candidates",
            candidate_values
        )

        connection.commit()

        # -----------------------------------------
        # VERIFY
        # -----------------------------------------

        cursor.execute("""
            SELECT
                tc.candidate_id,
                g.source,
                g.source_game_id,
                m.fen_before,
                tc.solution_move_san,
                tc.solution_line

            FROM tactic_candidates tc

            INNER JOIN moves m
                ON m.move_id =
                    tc.move_id

            INNER JOIN games g
                ON g.game_id =
                    m.game_id

            WHERE tc.candidate_id = ?
        """, (
            TEST_CANDIDATE_ID,
        ))

        row = cursor.fetchone()

        print()
        print(
            "Test puzzle created."
        )

        print()
        print(
            f"Candidate ID: "
            f"{row[0]}"
        )

        print(
            f"Source: "
            f"{row[1]}"
        )

        print(
            f"Game: "
            f"{row[2]}"
        )

        print()
        print(
            "Puzzle:"
        )

        print(
            "1. Re6+ Kh7"
        )

        print(
            "2. Rxe8"
        )

        print()
        print(
            "White wins the bishop "
            "and the rook survives."
        )

        print()
        print(
            "This should appear as "
            "Puzzle #1 in Merlin."
        )

        print()
        print(
            "Seed complete."
        )

    except Exception:

        connection.rollback()
        raise

    finally:

        connection.close()


if __name__ == "__main__":
    main()