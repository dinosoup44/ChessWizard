import sqlite3


DB_NAME = "merlin.db"


def main():
    connection = sqlite3.connect(DB_NAME)

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                te.episode_id,
                te.primary_candidate_id
            FROM tactic_episodes te
            WHERE te.tactic_type = 'missed_mate'
            ORDER BY te.episode_id
            LIMIT 1
        """)

        row = cursor.fetchone()

        if row is None:
            print("No mate episodes found.")
            return

        episode_id, candidate_id = row

        print("Using:")
        print(f"Episode ID: {episode_id}")
        print(f"Candidate ID: {candidate_id}")

        cursor.execute("""
            INSERT INTO training_attempts (
                candidate_id,
                episode_id,
                tactic_type,
                result,
                move_attempts,
                hint_used,
                solution_revealed,
                finished_at
            )
            VALUES (
                ?,
                ?,
                'missed_mate',
                'test',
                2,
                1,
                0,
                CURRENT_TIMESTAMP
            )
        """, (
            candidate_id,
            episode_id,
        ))

        test_id = cursor.lastrowid

        connection.commit()

        cursor.execute("""
            SELECT
                training_attempt_id,
                candidate_id,
                episode_id,
                tactic_type,
                result,
                move_attempts,
                hint_used,
                solution_revealed
            FROM training_attempts
            WHERE training_attempt_id = ?
        """, (test_id,))

        saved = cursor.fetchone()

        print()
        print("TEST ROW SAVED")
        print("--------------")
        print(saved)

        cursor.execute("""
            DELETE FROM training_attempts
            WHERE training_attempt_id = ?
        """, (test_id,))

        connection.commit()

        cursor.execute("""
            SELECT COUNT(*)
            FROM training_attempts
            WHERE training_attempt_id = ?
        """, (test_id,))

        remaining = cursor.fetchone()[0]

        print()
        print("CLEANUP")
        print("-------")

        if remaining == 0:
            print("Test row deleted successfully.")
            print("Training history table works.")
        else:
            print("WARNING: Test row still exists.")

    finally:
        connection.close()


if __name__ == "__main__":
    main()