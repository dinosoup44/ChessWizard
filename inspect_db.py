import sqlite3


DB_NAME = "merlin.db"


def table_exists(cursor, table_name):
    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
    """, (table_name,))

    return cursor.fetchone() is not None


def get_count(cursor, table_name):
    cursor.execute(
        f"SELECT COUNT(*) FROM {table_name}"
    )

    return cursor.fetchone()[0]


def main():
    connection = sqlite3.connect(DB_NAME)

    try:
        cursor = connection.cursor()

        print()
        print("MERLIN DATABASE SUMMARY")
        print("-----------------------")

        # -------------------------------------------------
        # USERS
        # -------------------------------------------------

        user_count = (
            get_count(cursor, "users")
            if table_exists(cursor, "users")
            else 0
        )

        print(f"Users: {user_count}")

        # -------------------------------------------------
        # CHESS ACCOUNTS
        # -------------------------------------------------

        account_count = (
            get_count(cursor, "chess_accounts")
            if table_exists(cursor, "chess_accounts")
            else 0
        )

        print(
            f"Chess accounts: {account_count}"
        )

        # -------------------------------------------------
        # GAMES
        # -------------------------------------------------

        game_count = (
            get_count(cursor, "games")
            if table_exists(cursor, "games")
            else 0
        )

        print(
            f"Total games: {game_count}"
        )

        # -------------------------------------------------
        # MOVES
        # -------------------------------------------------

        if table_exists(cursor, "moves"):

            move_count = get_count(
                cursor,
                "moves"
            )

            cursor.execute("""
                SELECT COUNT(*)
                FROM moves
                WHERE is_user_move = 1
            """)

            user_move_count = (
                cursor.fetchone()[0]
            )

        else:
            move_count = 0
            user_move_count = 0

        print(
            f"Total moves: {move_count}"
        )

        print(
            f"User moves: {user_move_count}"
        )

        # -------------------------------------------------
        # ENGINE ANALYSIS
        # -------------------------------------------------

        engine_analysis_count = (
            get_count(
                cursor,
                "engine_analysis"
            )
            if table_exists(
                cursor,
                "engine_analysis"
            )
            else 0
        )

        print(
            f"Engine analysis rows: "
            f"{engine_analysis_count}"
        )

        # -------------------------------------------------
        # TACTIC CANDIDATES
        # -------------------------------------------------

        candidate_count = (
            get_count(
                cursor,
                "tactic_candidates"
            )
            if table_exists(
                cursor,
                "tactic_candidates"
            )
            else 0
        )

        print(
            f"Tactic candidates: "
            f"{candidate_count}"
        )

        # -------------------------------------------------
        # TACTIC EPISODES
        # -------------------------------------------------

        episode_count = (
            get_count(
                cursor,
                "tactic_episodes"
            )
            if table_exists(
                cursor,
                "tactic_episodes"
            )
            else 0
        )

        print(
            f"Tactical episodes: "
            f"{episode_count}"
        )

        # -------------------------------------------------
        # EPISODE MEMBERSHIPS
        # -------------------------------------------------

        episode_member_count = (
            get_count(
                cursor,
                "tactic_episode_members"
            )
            if table_exists(
                cursor,
                "tactic_episode_members"
            )
            else 0
        )

        print(
            f"Episode memberships: "
            f"{episode_member_count}"
        )

        # -------------------------------------------------
        # ANALYSIS RUNS
        # -------------------------------------------------

        analysis_run_count = (
            get_count(
                cursor,
                "analysis_runs"
            )
            if table_exists(
                cursor,
                "analysis_runs"
            )
            else 0
        )

        print(
            f"Analysis runs: "
            f"{analysis_run_count}"
        )

        # -------------------------------------------------
        # TRAINING ATTEMPTS
        # -------------------------------------------------

        training_attempt_count = (
            get_count(
                cursor,
                "training_attempts"
            )
            if table_exists(
                cursor,
                "training_attempts"
            )
            else 0
        )

        print(
            f"Training attempts: "
            f"{training_attempt_count}"
        )

        # -------------------------------------------------
        # GAMES BY SOURCE
        # -------------------------------------------------

        print()
        print("GAMES BY SOURCE")
        print("---------------")

        if table_exists(cursor, "games"):

            cursor.execute("""
                SELECT
                    source,
                    COUNT(*)
                FROM games
                GROUP BY source
                ORDER BY source
            """)

            rows = cursor.fetchall()

            if rows:
                for source, count in rows:
                    print(
                        f"{source}: {count}"
                    )
            else:
                print("None")

        else:
            print("None")

        # -------------------------------------------------
        # CHESS ACCOUNTS
        # -------------------------------------------------

        print()
        print("CHESS ACCOUNTS")
        print("--------------")

        if table_exists(
            cursor,
            "chess_accounts"
        ):

            cursor.execute("""
                SELECT
                    account_id,
                    source,
                    username,
                    created_at
                FROM chess_accounts
                ORDER BY account_id
            """)

            rows = cursor.fetchall()

            if rows:
                for row in rows:
                    print(row)
            else:
                print("None")

        else:
            print("None")

        # -------------------------------------------------
        # TACTIC CANDIDATES BY TYPE
        # -------------------------------------------------

        print()
        print("TACTIC CANDIDATES BY TYPE")
        print("-------------------------")

        if table_exists(
            cursor,
            "tactic_candidates"
        ):

            cursor.execute("""
                SELECT
                    tactic_type,
                    COUNT(*)
                FROM tactic_candidates
                GROUP BY tactic_type
                ORDER BY tactic_type
            """)

            rows = cursor.fetchall()

            if rows:
                for tactic_type, count in rows:
                    print(
                        f"{tactic_type}: "
                        f"{count}"
                    )
            else:
                print("None")

        else:
            print("None")

        # -------------------------------------------------
        # EPISODES BY TYPE
        # -------------------------------------------------

        print()
        print("EPISODES BY TYPE")
        print("----------------")

        if table_exists(
            cursor,
            "tactic_episodes"
        ):

            cursor.execute("""
                SELECT
                    tactic_type,
                    COUNT(*)
                FROM tactic_episodes
                GROUP BY tactic_type
                ORDER BY tactic_type
            """)

            rows = cursor.fetchall()

            if rows:
                for tactic_type, count in rows:
                    print(
                        f"{tactic_type}: "
                        f"{count}"
                    )
            else:
                print("None")

        else:
            print("None")

        # -------------------------------------------------
        # EPISODE SIZE BREAKDOWN
        # -------------------------------------------------

        print()
        print("EPISODE SIZE BREAKDOWN")
        print("----------------------")

        if table_exists(
            cursor,
            "tactic_episodes"
        ):

            cursor.execute("""
                SELECT
                    candidate_count,
                    COUNT(*)
                FROM tactic_episodes
                GROUP BY candidate_count
                ORDER BY candidate_count
            """)

            rows = cursor.fetchall()

            if rows:
                for candidate_count, episodes in rows:

                    label = (
                        "candidate"
                        if candidate_count == 1
                        else "candidates"
                    )

                    print(
                        f"{candidate_count} "
                        f"{label}: "
                        f"{episodes} episodes"
                    )
            else:
                print("None")

        else:
            print("None")

        # -------------------------------------------------
        # TRAINING HISTORY
        # -------------------------------------------------

        print()
        print("TRAINING HISTORY")
        print("----------------")

        if table_exists(
            cursor,
            "training_attempts"
        ):

            cursor.execute("""
                SELECT COUNT(*)
                FROM training_attempts
            """)

            total_training = (
                cursor.fetchone()[0]
            )

            cursor.execute("""
                SELECT COUNT(*)
                FROM training_attempts
                WHERE result = 'solved'
            """)

            solved = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*)
                FROM training_attempts
                WHERE result = 'revealed'
            """)

            revealed = (
                cursor.fetchone()[0]
            )

            cursor.execute("""
                SELECT COUNT(*)
                FROM training_attempts
                WHERE result = 'quit'
            """)

            quit_count = (
                cursor.fetchone()[0]
            )

            cursor.execute("""
                SELECT COUNT(*)
                FROM training_attempts
                WHERE result = 'in_progress'
            """)

            in_progress = (
                cursor.fetchone()[0]
            )

            cursor.execute("""
                SELECT COUNT(*)
                FROM training_attempts
                WHERE hint_used = 1
            """)

            hint_count = (
                cursor.fetchone()[0]
            )

            cursor.execute("""
                SELECT COUNT(*)
                FROM training_attempts
                WHERE solution_revealed = 1
            """)

            solution_reveal_count = (
                cursor.fetchone()[0]
            )

            cursor.execute("""
                SELECT COUNT(*)
                FROM training_attempts
                WHERE result = 'solved'
                  AND move_attempts = 1
                  AND hint_used = 0
                  AND solution_revealed = 0
            """)

            first_try_clean = (
                cursor.fetchone()[0]
            )

            cursor.execute("""
                SELECT AVG(move_attempts)
                FROM training_attempts
                WHERE result = 'solved'
            """)

            average_attempts = (
                cursor.fetchone()[0]
            )

            print(
                f"Total attempts: "
                f"{total_training}"
            )

            print(
                f"Solved: {solved}"
            )

            print(
                f"First-try, no-hint solves: "
                f"{first_try_clean}"
            )

            print(
                f"Solutions revealed: "
                f"{revealed}"
            )

            print(
                f"Quit before solving: "
                f"{quit_count}"
            )

            print(
                f"In progress: "
                f"{in_progress}"
            )

            print(
                f"Hints used: "
                f"{hint_count}"
            )

            print(
                f"Solution reveal flag: "
                f"{solution_reveal_count}"
            )

            if average_attempts is not None:
                print(
                    f"Average legal attempts "
                    f"on solved puzzles: "
                    f"{average_attempts:.2f}"
                )

            # ---------------------------------------------
            # RESULTS BREAKDOWN
            # ---------------------------------------------

            print()
            print("TRAINING RESULTS BY STATUS")
            print("--------------------------")

            cursor.execute("""
                SELECT
                    result,
                    COUNT(*)
                FROM training_attempts
                GROUP BY result
                ORDER BY result
            """)

            rows = cursor.fetchall()

            if rows:
                for result, count in rows:
                    print(
                        f"{result}: {count}"
                    )
            else:
                print("None")

            # ---------------------------------------------
            # MOST RECENT ATTEMPTS
            # ---------------------------------------------

            if total_training > 0:

                print()
                print("RECENT TRAINING ATTEMPTS")
                print("------------------------")

                cursor.execute("""
                    SELECT
                        training_attempt_id,
                        candidate_id,
                        episode_id,
                        result,
                        move_attempts,
                        hint_used,
                        solution_revealed,
                        started_at,
                        finished_at
                    FROM training_attempts
                    ORDER BY training_attempt_id DESC
                    LIMIT 10
                """)

                rows = cursor.fetchall()

                for row in rows:
                    (
                        training_attempt_id,
                        candidate_id,
                        episode_id,
                        result,
                        move_attempts,
                        hint_used,
                        solution_revealed,
                        started_at,
                        finished_at
                    ) = row

                    print()
                    print(
                        f"Attempt "
                        f"{training_attempt_id}"
                    )

                    print(
                        f"  Candidate: "
                        f"{candidate_id}"
                    )

                    print(
                        f"  Episode: "
                        f"{episode_id}"
                    )

                    print(
                        f"  Result: "
                        f"{result}"
                    )

                    print(
                        f"  Legal moves tried: "
                        f"{move_attempts}"
                    )

                    print(
                        f"  Hint used: "
                        f"{bool(hint_used)}"
                    )

                    print(
                        f"  Solution revealed: "
                        f"{bool(solution_revealed)}"
                    )

                    print(
                        f"  Started: "
                        f"{started_at}"
                    )

                    print(
                        f"  Finished: "
                        f"{finished_at}"
                    )

        else:
            print(
                "training_attempts table "
                "does not exist."
            )

        # -------------------------------------------------
        # ANALYSIS RUN HISTORY
        # -------------------------------------------------

        if table_exists(
            cursor,
            "analysis_runs"
        ):

            print()
            print("ANALYSIS RUNS")
            print("-------------")

            cursor.execute("""
                SELECT
                    run_id,
                    tool_name,
                    tool_version,
                    status,
                    moves_total,
                    moves_scanned,
                    candidates_found,
                    started_at,
                    finished_at
                FROM analysis_runs
                ORDER BY run_id
            """)

            rows = cursor.fetchall()

            if rows:
                for row in rows:
                    (
                        run_id,
                        tool_name,
                        tool_version,
                        status,
                        moves_total,
                        moves_scanned,
                        candidates_found,
                        started_at,
                        finished_at
                    ) = row

                    print()
                    print(
                        f"Run {run_id}: "
                        f"{tool_name} "
                        f"v{tool_version}"
                    )

                    print(
                        f"  Status: "
                        f"{status}"
                    )

                    print(
                        f"  Moves: "
                        f"{moves_scanned} / "
                        f"{moves_total}"
                    )

                    print(
                        f"  Candidates found: "
                        f"{candidates_found}"
                    )

                    print(
                        f"  Started: "
                        f"{started_at}"
                    )

                    print(
                        f"  Finished: "
                        f"{finished_at}"
                    )

            else:
                print("None")

        print()
        print("DATABASE CHECK COMPLETE")
        print("-----------------------")

    finally:
        connection.close()


if __name__ == "__main__":
    main()