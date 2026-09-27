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
        print("MERLIN ENGINE CACHE V2 MIGRATION")
        print("--------------------------------")

        if not column_exists(
            cursor,
            "engine_position_cache",
            "score_pov"
        ):
            cursor.execute("""
                ALTER TABLE engine_position_cache
                ADD COLUMN score_pov TEXT
                    NOT NULL
                    DEFAULT 'white'
            """)

            print(
                "Added score_pov column."
            )

        else:
            print(
                "score_pov column already exists."
            )

        connection.commit()

        cursor.execute("""
            SELECT COUNT(*)
            FROM engine_position_cache
        """)

        count = cursor.fetchone()[0]

        print()
        print(
            f"Cached positions: {count}"
        )

        print(
            "Cache score convention: WHITE POV"
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