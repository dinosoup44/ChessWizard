import sqlite3


DB_NAME = "merlin.db"


def column_exists(cursor, table_name, column_name):
    cursor.execute(
        f"PRAGMA table_info({table_name})"
    )

    columns = [
        row[1]
        for row in cursor.fetchall()
    ]

    return column_name in columns


def main():
    connection = sqlite3.connect(DB_NAME)

    try:
        cursor = connection.cursor()

        print()
        print("MERLIN FORK SUPPORT MIGRATION")
        print("-----------------------------")

        if not column_exists(
            cursor,
            "tactic_candidates",
            "metadata_json"
        ):
            cursor.execute("""
                ALTER TABLE tactic_candidates
                ADD COLUMN metadata_json TEXT
            """)

            print(
                "Added metadata_json to "
                "tactic_candidates."
            )

        else:
            print(
                "metadata_json already exists."
            )

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
                idx_tactic_candidates_type_version
            ON tactic_candidates (
                tactic_type,
                detector_version
            )
        """)

        connection.commit()

        print()
        print("Fork support ready.")
        print("Migration complete.")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()