import sqlite3
from collections import Counter


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

        print()
        print("MERLIN ENGINE ANALYSIS INSPECTOR")
        print("--------------------------------")

        if not table_exists(
            cursor,
            "engine_analysis"
        ):
            print(
                "engine_analysis table does not exist."
            )
            return

        # -------------------------------------------------
        # BASIC COUNTS
        # -------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*)
            FROM engine_analysis
        """)

        total_rows = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(DISTINCT move_id)
            FROM engine_analysis
        """)

        distinct_moves = cursor.fetchone()[0]

        duplicate_rows = (
            total_rows - distinct_moves
        )

        print()
        print("BASIC COUNTS")
        print("------------")

        print(
            f"Total engine-analysis rows: "
            f"{total_rows}"
        )

        print(
            f"Distinct moves analyzed: "
            f"{distinct_moves}"
        )

        print(
            f"Additional rows beyond "
            f"one-per-move: "
            f"{duplicate_rows}"
        )

        # -------------------------------------------------
        # ENGINE / VERSION
        # -------------------------------------------------

        print()
        print("ROWS BY ENGINE")
        print("--------------")

        cursor.execute("""
            SELECT
                engine_name,
                engine_version,
                COUNT(*)
            FROM engine_analysis
            GROUP BY
                engine_name,
                engine_version
            ORDER BY
                engine_name,
                engine_version
        """)

        rows = cursor.fetchall()

        if rows:
            for (
                engine_name,
                engine_version,
                count
            ) in rows:

                print(
                    f"{engine_name} "
                    f"{engine_version}: "
                    f"{count}"
                )
        else:
            print("None")

        # -------------------------------------------------
        # ANALYSIS VERSION
        # -------------------------------------------------

        print()
        print("ROWS BY ANALYSIS VERSION")
        print("------------------------")

        cursor.execute("""
            SELECT
                analysis_version,
                COUNT(*)
            FROM engine_analysis
            GROUP BY analysis_version
            ORDER BY analysis_version
        """)

        rows = cursor.fetchall()

        if rows:
            for version, count in rows:
                print(
                    f"Version {version}: "
                    f"{count}"
                )
        else:
            print("None")

        # -------------------------------------------------
        # DEPTH
        # -------------------------------------------------

        print()
        print("ROWS BY DEPTH")
        print("-------------")

        cursor.execute("""
            SELECT
                depth,
                COUNT(*)
            FROM engine_analysis
            GROUP BY depth
            ORDER BY depth
        """)

        rows = cursor.fetchall()

        if rows:
            for depth, count in rows:
                print(
                    f"Depth {depth}: "
                    f"{count}"
                )
        else:
            print("None")

        # -------------------------------------------------
        # SCORE TYPES
        # -------------------------------------------------

        print()
        print("SCORE DATA")
        print("----------")

        cursor.execute("""
            SELECT
                score_type,
                COUNT(*)
            FROM engine_analysis
            GROUP BY score_type
            ORDER BY score_type
        """)

        rows = cursor.fetchall()

        if rows:
            for score_type, count in rows:
                print(
                    f"{score_type}: "
                    f"{count}"
                )
        else:
            print("None")

        # -------------------------------------------------
        # BEFORE / AFTER VALUES
        # -------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*)
            FROM engine_analysis
            WHERE score_cp_before IS NOT NULL
        """)

        cp_before = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM engine_analysis
            WHERE score_cp_after IS NOT NULL
        """)

        cp_after = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM engine_analysis
            WHERE mate_before IS NOT NULL
        """)

        mate_before = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM engine_analysis
            WHERE mate_after IS NOT NULL
        """)

        mate_after = cursor.fetchone()[0]

        print()
        print("POSITION VALUES")
        print("---------------")

        print(
            f"Centipawn before: "
            f"{cp_before}"
        )

        print(
            f"Centipawn after: "
            f"{cp_after}"
        )

        print(
            f"Mate before: "
            f"{mate_before}"
        )

        print(
            f"Mate after: "
            f"{mate_after}"
        )

        # -------------------------------------------------
        # BEST MOVE / PV
        # -------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*)
            FROM engine_analysis
            WHERE best_move_uci IS NOT NULL
              AND TRIM(best_move_uci) <> ''
        """)

        best_uci_count = (
            cursor.fetchone()[0]
        )

        cursor.execute("""
            SELECT COUNT(*)
            FROM engine_analysis
            WHERE best_move_san IS NOT NULL
              AND TRIM(best_move_san) <> ''
        """)

        best_san_count = (
            cursor.fetchone()[0]
        )

        cursor.execute("""
            SELECT COUNT(*)
            FROM engine_analysis
            WHERE principal_variation IS NOT NULL
              AND TRIM(principal_variation) <> ''
        """)

        pv_count = cursor.fetchone()[0]

        print()
        print("ENGINE DETAIL COVERAGE")
        print("----------------------")

        print(
            f"Rows with best move UCI: "
            f"{best_uci_count}"
        )

        print(
            f"Rows with best move SAN: "
            f"{best_san_count}"
        )

        print(
            f"Rows with principal variation: "
            f"{pv_count}"
        )

        # -------------------------------------------------
        # WORK / PERFORMANCE DATA
        # -------------------------------------------------

        cursor.execute("""
            SELECT
                COUNT(nodes),
                MIN(nodes),
                MAX(nodes),
                AVG(nodes)
            FROM engine_analysis
            WHERE nodes IS NOT NULL
        """)

        (
            node_rows,
            min_nodes,
            max_nodes,
            avg_nodes
        ) = cursor.fetchone()

        cursor.execute("""
            SELECT
                COUNT(time_ms),
                MIN(time_ms),
                MAX(time_ms),
                AVG(time_ms)
            FROM engine_analysis
            WHERE time_ms IS NOT NULL
        """)

        (
            time_rows,
            min_time,
            max_time,
            avg_time
        ) = cursor.fetchone()

        print()
        print("ENGINE WORK DATA")
        print("----------------")

        print(
            f"Rows with node counts: "
            f"{node_rows}"
        )

        if node_rows:
            print(
                f"Nodes min / avg / max: "
                f"{min_nodes} / "
                f"{avg_nodes:.0f} / "
                f"{max_nodes}"
            )

        print(
            f"Rows with timing data: "
            f"{time_rows}"
        )

        if time_rows:
            print(
                f"Time ms min / avg / max: "
                f"{min_time} / "
                f"{avg_time:.1f} / "
                f"{max_time}"
            )

        # -------------------------------------------------
        # ANALYSIS ROWS PER MOVE
        # -------------------------------------------------

        cursor.execute("""
            SELECT
                move_id,
                COUNT(*) AS row_count
            FROM engine_analysis
            GROUP BY move_id
        """)

        counts = cursor.fetchall()

        distribution = Counter(
            row_count
            for move_id, row_count in counts
        )

        print()
        print("ANALYSIS ROWS PER MOVE")
        print("----------------------")

        for row_count in sorted(
            distribution
        ):
            move_count = distribution[
                row_count
            ]

            print(
                f"{row_count} row(s): "
                f"{move_count} moves"
            )

        # -------------------------------------------------
        # MOST-ANALYZED MOVES
        # -------------------------------------------------

        print()
        print("MOST-ANALYZED MOVES")
        print("-------------------")

        cursor.execute("""
            SELECT
                ea.move_id,
                COUNT(*) AS analysis_count,

                m.game_id,
                m.move_number,
                m.color,
                m.san_played,

                g.source,
                g.source_game_id

            FROM engine_analysis ea

            INNER JOIN moves m
                ON m.move_id = ea.move_id

            INNER JOIN games g
                ON g.game_id = m.game_id

            GROUP BY
                ea.move_id,
                m.game_id,
                m.move_number,
                m.color,
                m.san_played,
                g.source,
                g.source_game_id

            ORDER BY
                analysis_count DESC,
                ea.move_id

            LIMIT 15
        """)

        rows = cursor.fetchall()

        if rows:
            for row in rows:
                (
                    move_id,
                    analysis_count,
                    game_id,
                    move_number,
                    color,
                    san_played,
                    source,
                    source_game_id
                ) = row

                print(
                    f"Move ID {move_id}: "
                    f"{analysis_count} analyses "
                    f"| {source} "
                    f"{source_game_id} "
                    f"| move {move_number} "
                    f"{color} "
                    f"{san_played}"
                )
        else:
            print("None")

        # -------------------------------------------------
        # CACHE-READINESS SUMMARY
        # -------------------------------------------------

        print()
        print("CACHE READINESS")
        print("---------------")

        if total_rows == 0:
            print(
                "No engine data exists yet."
            )

        else:
            coverage_percent = (
                distinct_moves
                / 96576
                * 100
            )

            print(
                f"Existing engine data covers "
                f"{distinct_moves:,} distinct "
                f"user moves."
            )

            print(
                f"That is approximately "
                f"{coverage_percent:.2f}% "
                f"of the current 96,576 "
                f"user moves."
            )

            if duplicate_rows > 0:
                print(
                    "Multiple analysis rows exist "
                    "for some moves."
                )

                print(
                    "We need to distinguish "
                    "analysis settings/version "
                    "before treating this table "
                    "as a reusable cache."
                )

            else:
                print(
                    "Current data is one row "
                    "per analyzed move."
                )

        print()
        print("ENGINE ANALYSIS CHECK COMPLETE")
        print("------------------------------")

    finally:
        connection.close()


if __name__ == "__main__":
    main()