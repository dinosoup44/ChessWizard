import sqlite3


DB_NAME = "merlin.db"


def main():
    connection = sqlite3.connect(DB_NAME)

    try:
        cursor = connection.cursor()

        print()
        print("MERLIN ENGINE CACHE MIGRATION")
        print("-----------------------------")

        # -------------------------------------------------
        # ENGINE POSITION CACHE
        # -------------------------------------------------
        #
        # One row = one Stockfish evaluation of one
        # exact chess position.
        #
        # This is deliberately separate from
        # engine_analysis.
        #
        # engine_analysis:
        #     historical detector-specific evidence
        #
        # engine_position_cache:
        #     reusable Stockfish knowledge
        # -------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS engine_position_cache (
                cache_id
                    INTEGER PRIMARY KEY AUTOINCREMENT,

                fen
                    TEXT NOT NULL,

                engine_name
                    TEXT NOT NULL,

                engine_version
                    TEXT NOT NULL,

                analysis_profile
                    TEXT NOT NULL,

                analysis_version
                    INTEGER NOT NULL DEFAULT 1,

                limit_type
                    TEXT NOT NULL,

                limit_value
                    INTEGER NOT NULL,

                side_to_move
                    TEXT NOT NULL,

                score_type
                    TEXT NOT NULL,

                score_cp
                    INTEGER,

                mate
                    INTEGER,

                best_move_uci
                    TEXT,

                best_move_san
                    TEXT,

                principal_variation
                    TEXT,

                depth
                    INTEGER,

                seldepth
                    INTEGER,

                nodes
                    INTEGER,

                time_ms
                    INTEGER,

                analyzed_at
                    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                CHECK (
                    side_to_move IN (
                        'white',
                        'black'
                    )
                ),

                CHECK (
                    score_type IN (
                        'cp',
                        'mate'
                    )
                ),

                UNIQUE (
                    fen,
                    engine_name,
                    engine_version,
                    analysis_profile,
                    analysis_version,
                    limit_type,
                    limit_value
                )
            )
        """)

        print(
            "engine_position_cache table ready."
        )

        # -------------------------------------------------
        # INDEXES
        # -------------------------------------------------

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
                idx_engine_cache_fen
            ON engine_position_cache (
                fen
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
                idx_engine_cache_profile
            ON engine_position_cache (
                analysis_profile,
                analysis_version
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
                idx_engine_cache_engine
            ON engine_position_cache (
                engine_name,
                engine_version
            )
        """)

        connection.commit()

        # -------------------------------------------------
        # VERIFY
        # -------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*)
            FROM engine_position_cache
        """)

        cache_count = cursor.fetchone()[0]

        print()
        print("CURRENT CACHE DATA")
        print("------------------")

        print(
            f"Cached positions: "
            f"{cache_count}"
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