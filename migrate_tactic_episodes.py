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


def main():
    connection = sqlite3.connect(DB_NAME)

    try:
        cursor = connection.cursor()

        print("MERLIN TACTIC EPISODE MIGRATION")
        print("-------------------------------")

        # -------------------------------------------------
        # TACTIC EPISODES
        # -------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tactic_episodes (
                episode_id INTEGER PRIMARY KEY AUTOINCREMENT,

                game_id INTEGER NOT NULL,

                tactic_type TEXT NOT NULL,

                primary_candidate_id INTEGER NOT NULL,

                detector_version INTEGER NOT NULL,

                candidate_count INTEGER NOT NULL DEFAULT 1,

                first_ply_number INTEGER,
                last_ply_number INTEGER,

                episode_status TEXT NOT NULL DEFAULT 'candidate',

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (game_id)
                    REFERENCES games(game_id),

                FOREIGN KEY (primary_candidate_id)
                    REFERENCES tactic_candidates(candidate_id)
            )
        """)

        print("tactic_episodes table ready.")

        # -------------------------------------------------
        # EPISODE MEMBERS
        # -------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tactic_episode_members (
                episode_member_id INTEGER PRIMARY KEY AUTOINCREMENT,

                episode_id INTEGER NOT NULL,

                candidate_id INTEGER NOT NULL,

                sequence_order INTEGER NOT NULL,

                match_reason TEXT,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (episode_id)
                    REFERENCES tactic_episodes(episode_id),

                FOREIGN KEY (candidate_id)
                    REFERENCES tactic_candidates(candidate_id),

                UNIQUE (
                    episode_id,
                    candidate_id
                )
            )
        """)

        print("tactic_episode_members table ready.")

        # -------------------------------------------------
        # INDEXES
        # -------------------------------------------------

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
                idx_tactic_episodes_game_type
            ON tactic_episodes (
                game_id,
                tactic_type
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
                idx_tactic_episodes_primary_candidate
            ON tactic_episodes (
                primary_candidate_id
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
                idx_tactic_episode_members_episode
            ON tactic_episode_members (
                episode_id
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
                idx_tactic_episode_members_candidate
            ON tactic_episode_members (
                candidate_id
            )
        """)

        connection.commit()

        cursor.execute("""
            SELECT COUNT(*)
            FROM tactic_episodes
        """)

        episode_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM tactic_episode_members
        """)

        member_count = cursor.fetchone()[0]

        print()
        print("CURRENT EPISODE DATA")
        print("--------------------")

        print(
            f"Episodes: {episode_count}"
        )

        print(
            f"Episode members: {member_count}"
        )

        print()
        print("Migration complete.")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()