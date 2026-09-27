import sqlite3


DB_NAME = "merlin.db"


def column_exists(
    cursor,
    table_name,
    column_name
):
    cursor.execute(
        f"PRAGMA table_info({table_name})"
    )

    columns = {
        row[1]
        for row in cursor.fetchall()
    }

    return column_name in columns


def main():
    connection = sqlite3.connect(
        DB_NAME
    )

    try:
        cursor = connection.cursor()

        print()
        print(
            "MERLIN TRAINING HISTORY V2 MIGRATION"
        )

        print(
            "------------------------------------"
        )

        if not column_exists(
            cursor,
            "training_attempts",
            "wrong_move_attempts"
        ):

            cursor.execute("""
                ALTER TABLE training_attempts

                ADD COLUMN wrong_move_attempts
                    INTEGER NOT NULL DEFAULT 0
            """)

            print()
            print(
                "Added wrong_move_attempts."
            )

        else:

            print()
            print(
                "wrong_move_attempts "
                "already exists."
            )

        connection.commit()

        cursor.execute("""
            SELECT COUNT(*)
            FROM training_attempts
        """)

        attempt_count = (
            cursor.fetchone()[0]
        )

        print()
        print(
            f"Existing training attempts: "
            f"{attempt_count}"
        )

        print()
        print(
            "Training History V2 ready."
        )

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