import sqlite3


DB_NAME = "merlin.db"


def main():
    connection = sqlite3.connect(DB_NAME)

    # Enforce our foreign-key rules during the migration.
    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    try:
        cursor = connection.cursor()

        print()
        print("MERLIN TRAINING HISTORY MIGRATION")
        print("---------------------------------")

        # -------------------------------------------------
        # TRAINING ATTEMPTS
        # -------------------------------------------------
        #
        # One row represents one time the user was shown
        # a puzzle.
        #
        # candidate_id is the permanent anchor.
        #
        # episode_id is useful, but is allowed to become
        # NULL if tactical episodes are rebuilt later.
        # -------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS training_attempts (
                training_attempt_id
                    INTEGER PRIMARY KEY AUTOINCREMENT,

                candidate_id
                    INTEGER NOT NULL,

                episode_id
                    INTEGER,

                tactic_type
                    TEXT NOT NULL,

                result
                    TEXT NOT NULL,

                move_attempts
                    INTEGER NOT NULL DEFAULT 0,

                hint_used
                    INTEGER NOT NULL DEFAULT 0,

                solution_revealed
                    INTEGER NOT NULL DEFAULT 0,

                started_at
                    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                finished_at
                    TEXT,

                created_at
                    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (candidate_id)
                    REFERENCES tactic_candidates(candidate_id),

                FOREIGN KEY (episode_id)
                    REFERENCES tactic_episodes(episode_id)
                    ON DELETE SET NULL
            )
        """)

        print(
            "training_attempts table ready."
        )

        # -------------------------------------------------
        # INDEXES
        # -------------------------------------------------

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
                idx_training_attempts_candidate
            ON training_attempts (
                candidate_id
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
                idx_training_attempts_episode
            ON training_attempts (
                episode_id
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
                idx_training_attempts_tactic
            ON training_attempts (
                tactic_type
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
                idx_training_attempts_finished
            ON training_attempts (
                finished_at
            )
        """)

        connection.commit()

        # -------------------------------------------------
        # VERIFY
        # -------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*)
            FROM training_attempts
        """)

        attempt_count = (
            cursor.fetchone()[0]
        )

        print()
        print("CURRENT TRAINING DATA")
        print("---------------------")

        print(
            f"Training attempts: "
            f"{attempt_count}"
        )

        print()
        print(
            "Migration complete."
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()