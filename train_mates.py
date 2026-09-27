import sqlite3
import random
import chess


DB_NAME = "merlin.db"


PIECE_SYMBOLS = {
    (chess.WHITE, chess.KING): "♔",
    (chess.WHITE, chess.QUEEN): "♕",
    (chess.WHITE, chess.ROOK): "♖",
    (chess.WHITE, chess.BISHOP): "♗",
    (chess.WHITE, chess.KNIGHT): "♘",
    (chess.WHITE, chess.PAWN): "♙",

    (chess.BLACK, chess.KING): "♚",
    (chess.BLACK, chess.QUEEN): "♛",
    (chess.BLACK, chess.ROOK): "♜",
    (chess.BLACK, chess.BISHOP): "♝",
    (chess.BLACK, chess.KNIGHT): "♞",
    (chess.BLACK, chess.PAWN): "♟",
}


def load_mate_episodes(connection):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            te.episode_id,
            te.candidate_count,

            tc.candidate_id,
            tc.solution_move_san,
            tc.solution_move_uci,
            tc.solution_line,

            m.move_number,
            m.ply_number,
            m.color,
            m.san_played,
            m.uci_played,
            m.fen_before,

            g.source,
            g.source_game_id,
            g.white_username,
            g.black_username,
            g.result,
            g.time_control

        FROM tactic_episodes te

        INNER JOIN tactic_candidates tc
            ON tc.candidate_id =
               te.primary_candidate_id

        INNER JOIN moves m
            ON m.move_id =
               tc.move_id

        INNER JOIN games g
            ON g.game_id =
               te.game_id

        WHERE te.tactic_type = 'missed_mate'

        ORDER BY te.episode_id
    """)

    rows = cursor.fetchall()

    episodes = []

    for row in rows:
        (
            episode_id,
            candidate_count,

            candidate_id,
            solution_move_san,
            solution_move_uci,
            solution_line,

            move_number,
            ply_number,
            color,
            san_played,
            uci_played,
            fen_before,

            source,
            source_game_id,
            white_username,
            black_username,
            result,
            time_control
        ) = row

        episodes.append({
            "episode_id": episode_id,
            "candidate_count": candidate_count,

            "candidate_id": candidate_id,

            "solution_move_san":
                solution_move_san,

            "solution_move_uci":
                solution_move_uci,

            "solution_line":
                solution_line,

            "move_number":
                move_number,

            "ply_number":
                ply_number,

            "color":
                color,

            "played_san":
                san_played,

            "played_uci":
                uci_played,

            "fen_before":
                fen_before,

            "source":
                source,

            "source_game_id":
                source_game_id,

            "white_username":
                white_username,

            "black_username":
                black_username,

            "result":
                result,

            "time_control":
                time_control,
        })

    return episodes


def start_training_attempt(
    connection,
    episode
):
    """
    Create the training row as soon as the puzzle
    is displayed.

    This means Merlin remembers even if the user
    quits the puzzle without solving it.
    """

    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO training_attempts (
            candidate_id,
            episode_id,
            tactic_type,
            result,
            move_attempts,
            hint_used,
            solution_revealed,
            started_at
        )
        VALUES (
            ?,
            ?,
            'missed_mate',
            'in_progress',
            0,
            0,
            0,
            CURRENT_TIMESTAMP
        )
    """, (
        episode["candidate_id"],
        episode["episode_id"],
    ))

    training_attempt_id = (
        cursor.lastrowid
    )

    connection.commit()

    return training_attempt_id


def update_training_attempt(
    connection,
    training_attempt_id,
    move_attempts,
    hint_used,
    solution_revealed,
    result=None,
    finished=False
):
    """
    Persist progress as the puzzle is played.

    That makes training history resilient even
    if Merlin is interrupted.
    """

    cursor = connection.cursor()

    if finished:
        cursor.execute("""
            UPDATE training_attempts

            SET
                move_attempts = ?,
                hint_used = ?,
                solution_revealed = ?,
                result = ?,
                finished_at = CURRENT_TIMESTAMP

            WHERE training_attempt_id = ?
        """, (
            move_attempts,
            int(hint_used),
            int(solution_revealed),
            result,
            training_attempt_id,
        ))

    else:
        cursor.execute("""
            UPDATE training_attempts

            SET
                move_attempts = ?,
                hint_used = ?,
                solution_revealed = ?

            WHERE training_attempt_id = ?
        """, (
            move_attempts,
            int(hint_used),
            int(solution_revealed),
            training_attempt_id,
        ))

    connection.commit()


def piece_display(piece):
    if piece is None:
        return "·"

    return PIECE_SYMBOLS.get(
        (
            piece.color,
            piece.piece_type
        ),
        "?"
    )


def print_board(
    board,
    player_color
):
    """
    Show the board from the user's perspective.
    """

    if player_color == chess.WHITE:

        files = list(
            range(0, 8)
        )

        ranks = list(
            range(7, -1, -1)
        )

        file_labels = [
            "a", "b", "c", "d",
            "e", "f", "g", "h"
        ]

    else:

        files = list(
            range(7, -1, -1)
        )

        ranks = list(
            range(0, 8)
        )

        file_labels = [
            "h", "g", "f", "e",
            "d", "c", "b", "a"
        ]

    print()

    print(
        "      "
        + "   ".join(file_labels)
    )

    print()

    for rank_index in ranks:
        rank_label = rank_index + 1

        row = []

        for file_index in files:

            square = chess.square(
                file_index,
                rank_index
            )

            piece = board.piece_at(
                square
            )

            row.append(
                piece_display(piece)
            )

        print(
            f" {rank_label}    "
            + "   ".join(row)
            + f"    {rank_label}"
        )

        print()

    print(
        "      "
        + "   ".join(file_labels)
    )

    print()


def print_piece_legend():
    print("PIECES")
    print("------")

    print(
        "White: "
        "♔ King  "
        "♕ Queen  "
        "♖ Rook  "
        "♗ Bishop  "
        "♘ Knight  "
        "♙ Pawn"
    )

    print(
        "Black: "
        "♚ King  "
        "♛ Queen  "
        "♜ Rook  "
        "♝ Bishop  "
        "♞ Knight  "
        "♟ Pawn"
    )

    print()


def parse_user_move(
    board,
    text
):
    """
    Accept either SAN:

        Bxf2+
        Qh7#
        Rxg6+

    or UCI:

        c5f2
        g6h7
        g5g6
    """

    text = text.strip()

    if not text:
        return None

    # Try SAN first.
    try:
        return board.parse_san(
            text
        )

    except ValueError:
        pass

    # Then try UCI.
    try:
        move = chess.Move.from_uci(
            text.lower()
        )

        if move in board.legal_moves:
            return move

    except ValueError:
        pass

    return None


def show_solution(episode):
    print()
    print("SOLUTION")
    print("--------")

    print(
        f"Best move: "
        f"{episode['solution_move_san']}"
    )

    print(
        f"Winning line: "
        f"{episode['solution_line']}"
    )

    print()

    print(
        f"In the actual game you played: "
        f"{episode['played_san']}"
    )

    if episode["candidate_count"] > 1:
        print(
            f"This mating opportunity appeared "
            f"{episode['candidate_count']} times "
            f"during the game."
        )

    print()


def give_hint(
    board,
    episode
):
    best_uci = episode[
        "solution_move_uci"
    ]

    if not best_uci:
        print()
        print(
            "Merlin's crystal ball "
            "is cloudy on this one."
        )
        print()

        return

    try:
        best_move = (
            chess.Move.from_uci(
                best_uci
            )
        )

    except ValueError:
        print()
        print(
            "Merlin could not create "
            "a hint for this puzzle."
        )
        print()

        return

    piece = board.piece_at(
        best_move.from_square
    )

    if piece is None:
        print()
        print(
            "Merlin could not locate "
            "the winning piece."
        )
        print()

        return

    piece_name = chess.piece_name(
        piece.piece_type
    )

    from_square = (
        chess.square_name(
            best_move.from_square
        )
    )

    print()
    print("HINT")
    print("----")

    print(
        f"Move the {piece_name} "
        f"on {from_square}."
    )

    print()


def play_puzzle(
    connection,
    episode
):
    try:
        board = chess.Board(
            episode["fen_before"]
        )

    except ValueError:
        print(
            "ERROR: Invalid puzzle position."
        )

        return "invalid"

    player_color = (
        chess.WHITE
        if episode["color"] == "white"
        else chess.BLACK
    )

    # -------------------------------------------------
    # TRAINING STATE
    # -------------------------------------------------

    move_attempts = 0
    hint_used = False
    solution_revealed = False

    training_attempt_id = (
        start_training_attempt(
            connection,
            episode
        )
    )

    # -------------------------------------------------
    # PUZZLE DISPLAY
    # -------------------------------------------------

    print()
    print("=" * 54)
    print("MERLIN'S MATE CHALLENGE")
    print("=" * 54)

    print()

    print(
        f"{episode['white_username']} "
        f"vs "
        f"{episode['black_username']}"
    )

    print(
        f"Source: "
        f"{episode['source']}"
    )

    print(
        f"Game: "
        f"{episode['source_game_id']}"
    )

    print(
        f"Move: "
        f"{episode['move_number']} "
        f"{episode['color']}"
    )

    side_to_move = (
        "White"
        if board.turn == chess.WHITE
        else "Black"
    )

    print()
    print(
        f"{side_to_move} to move."
    )

    print(
        "Find the forced mating move."
    )

    print(
        f"Board shown from "
        f"{episode['color'].capitalize()}'s "
        f"perspective."
    )

    print_board(
        board,
        player_color
    )

    # -------------------------------------------------
    # INPUT LOOP
    # -------------------------------------------------

    while True:

        answer = input(
            "Your move "
            "(SAN or UCI, "
            "H hint, S solution, "
            "Q quit): "
        ).strip()

        command = answer.lower()

        # ---------------------------------------------
        # QUIT
        # ---------------------------------------------

        if command == "q":

            update_training_attempt(
                connection,
                training_attempt_id,
                move_attempts,
                hint_used,
                solution_revealed,
                result="quit",
                finished=True
            )

            return "quit"

        # ---------------------------------------------
        # REVEAL SOLUTION
        # ---------------------------------------------

        if command == "s":

            solution_revealed = True

            update_training_attempt(
                connection,
                training_attempt_id,
                move_attempts,
                hint_used,
                solution_revealed,
                result="revealed",
                finished=True
            )

            show_solution(
                episode
            )

            return "continue"

        # ---------------------------------------------
        # HINT
        # ---------------------------------------------

        if command == "h":

            hint_used = True

            update_training_attempt(
                connection,
                training_attempt_id,
                move_attempts,
                hint_used,
                solution_revealed
            )

            give_hint(
                board,
                episode
            )

            continue

        # ---------------------------------------------
        # CHESS MOVE
        # ---------------------------------------------

        user_move = parse_user_move(
            board,
            answer
        )

        if user_move is None:

            print()
            print(
                "I couldn't understand that "
                "as a legal move."
            )

            print()
            print(
                "UCI example:"
            )

            print(
                "c5f2 means:"
            )

            print(
                "move the piece FROM c5 TO f2"
            )

            print()
            print(
                "SAN example:"
            )

            print(
                "Bxf2+ means:"
            )

            print(
                "bishop captures on f2 "
                "with check"
            )

            print()

            # Illegal / malformed input does NOT
            # count as a chess attempt.

            continue

        # This is a genuine legal chess move.
        move_attempts += 1

        update_training_attempt(
            connection,
            training_attempt_id,
            move_attempts,
            hint_used,
            solution_revealed
        )

        user_uci = user_move.uci()

        correct_uci = episode[
            "solution_move_uci"
        ]

        # ---------------------------------------------
        # CORRECT
        # ---------------------------------------------

        if user_uci == correct_uci:

            user_san = board.san(
                user_move
            )

            update_training_attempt(
                connection,
                training_attempt_id,
                move_attempts,
                hint_used,
                solution_revealed,
                result="solved",
                finished=True
            )

            print()
            print(
                f"CORRECT! {user_san}"
            )

            print(
                "The wizard approves. 🧙"
            )

            print()

            if (
                move_attempts == 1
                and not hint_used
            ):
                print(
                    "Solved on the first try "
                    "with no hint!"
                )

                print()

            elif hint_used:
                print(
                    f"Solved in "
                    f"{move_attempts} legal "
                    f"move attempt(s), "
                    f"with a hint."
                )

                print()

            else:
                print(
                    f"Solved in "
                    f"{move_attempts} legal "
                    f"move attempt(s)."
                )

                print()

            show_solution(
                episode
            )

            return "continue"

        # ---------------------------------------------
        # WRONG LEGAL MOVE
        # ---------------------------------------------

        user_san = board.san(
            user_move
        )

        print()
        print(
            f"{user_san} is legal, "
            "but it is not Merlin's "
            "winning move."
        )

        print(
            "Try again, or enter H "
            "for a hint."
        )

        print()


def print_session_summary(
    solved,
    revealed,
    quit_count
):
    total = (
        solved
        + revealed
        + quit_count
    )

    if total == 0:
        return

    print()
    print("SESSION SUMMARY")
    print("---------------")

    print(
        f"Puzzles attempted: {total}"
    )

    print(
        f"Solved: {solved}"
    )

    print(
        f"Solutions revealed: {revealed}"
    )

    print(
        f"Quit before solving: {quit_count}"
    )

    print()


def main():
    connection = sqlite3.connect(
        DB_NAME
    )

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    try:
        episodes = load_mate_episodes(
            connection
        )

        if not episodes:

            print(
                "Merlin has no mate puzzles "
                "available."
            )

            return

        random.shuffle(
            episodes
        )

        print()
        print("MERLIN")
        print("------")

        print(
            f"{len(episodes)} missed-mate "
            f"puzzles are ready."
        )

        print()

        print(
            "These positions come from "
            "your own games."
        )

        print(
            "Find the winning move "
            "that you missed."
        )

        print()

        print_piece_legend()

        puzzle_number = 0

        solved_count = 0
        revealed_count = 0
        quit_count = 0

        for episode in episodes:

            puzzle_number += 1

            print()
            print(
                f"Puzzle "
                f"{puzzle_number} / "
                f"{len(episodes)}"
            )

            result = play_puzzle(
                connection,
                episode
            )

            if result == "quit":
                quit_count += 1

                break

            # Read the final result we just saved
            # so session totals reflect the database.
            cursor = connection.cursor()

            cursor.execute("""
                SELECT result
                FROM training_attempts
                ORDER BY training_attempt_id DESC
                LIMIT 1
            """)

            final_result = (
                cursor.fetchone()[0]
            )

            if final_result == "solved":
                solved_count += 1

            elif final_result == "revealed":
                revealed_count += 1

            while True:

                answer = input(
                    "Press ENTER for another "
                    "puzzle, or Q to quit: "
                ).strip().lower()

                if answer == "q":

                    print_session_summary(
                        solved_count,
                        revealed_count,
                        quit_count
                    )

                    print(
                        "Merlin returns to "
                        "his studies."
                    )

                    return

                if answer == "":
                    break

        print_session_summary(
            solved_count,
            revealed_count,
            quit_count
        )

        print(
            "Merlin returns to his studies."
        )

    finally:
        connection.close()


if __name__ == "__main__":
    main()