import sqlite3


DB_NAME = "merlin.db"


def main():
    connection = sqlite3.connect(DB_NAME)
    cursor = connection.cursor()

    cursor.execute("""
        SELECT move_id
        FROM tactic_candidates
        WHERE tactic_type = 'missed_mate'
    """)

    move_ids = [row[0] for row in cursor.fetchall()]

    candidate_count = len(move_ids)

    cursor.execute("""
        DELETE FROM tactic_candidates
        WHERE tactic_type = 'missed_mate'
    """)

    engine_rows_deleted = 0

    if move_ids:
        placeholders = ",".join("?" for _ in move_ids)

        cursor.execute(
            f"""
            DELETE FROM engine_analysis
            WHERE move_id IN ({placeholders})
            """,
            move_ids
        )

        engine_rows_deleted = cursor.rowcount

    connection.commit()
    connection.close()

    print("Mate test cleanup complete!")
    print("Missed-mate candidates removed:", candidate_count)
    print("Engine-analysis rows removed:", engine_rows_deleted)


if __name__ == "__main__":
    main()