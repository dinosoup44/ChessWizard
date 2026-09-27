import sqlite3
import chess
import chess.engine

from engine_cache import (
    DB_NAME,
    STOCKFISH_PATH,
    get_or_analyze,
)


TEST_FEN = (
    "r1bq1rk1/1p3p2/p1np2p1/4p1R1/"
    "4Q3/3B1P2/PPPB3P/2KR4 w - - 0 16"
)

PROFILE = "tactic_quick_v1"


def print_result(label, result):
    print()
    print(label)
    print("-" * len(label))

    print(
        f"Cache hit: "
        f"{result['cache_hit']}"
    )

    print(
        f"Profile: "
        f"{result['analysis_profile']}"
    )

    print(
        f"Score POV: "
        f"{result['score_pov']}"
    )

    print(
        f"Score type: "
        f"{result['score_type']}"
    )

    print(
        f"Centipawn score: "
        f"{result['score_cp']}"
    )

    print(
        f"Mate score: "
        f"{result['mate']}"
    )

    print(
        f"Best move: "
        f"{result['best_move_san']}"
    )

    print(
        f"Best move UCI: "
        f"{result['best_move_uci']}"
    )

    print(
        f"PV: "
        f"{result['principal_variation']}"
    )

    print(
        f"Depth: "
        f"{result['depth']}"
    )

    print(
        f"Nodes: "
        f"{result['nodes']}"
    )

    print(
        f"Time ms: "
        f"{result['time_ms']}"
    )


def main():
    connection = sqlite3.connect(
        DB_NAME
    )

    engine = None

    try:
        print()
        print("MERLIN ENGINE CACHE TEST")
        print("------------------------")

        print()
        print(
            "Starting Stockfish..."
        )

        engine = (
            chess.engine.SimpleEngine.popen_uci(
                STOCKFISH_PATH
            )
        )

        print()
        print(
            "FIRST REQUEST"
        )

        print(
            "Merlin should ask Stockfish."
        )

        first = get_or_analyze(
            connection,
            engine,
            TEST_FEN,
            PROFILE
        )

        print_result(
            "FIRST RESULT",
            first
        )

        print()
        print(
            "SECOND REQUEST"
        )

        print(
            "Merlin should use SQLite."
        )

        second = get_or_analyze(
            connection,
            engine,
            TEST_FEN,
            PROFILE
        )

        print_result(
            "SECOND RESULT",
            second
        )

        print()
        print(
            "VERIFYING"
        )

        print(
            "---------"
        )

        same_cache_row = (
            first["cache_id"]
            == second["cache_id"]
        )

        first_was_new = (
            first["cache_hit"]
            is False
        )

        second_was_cached = (
            second["cache_hit"]
            is True
        )

        if (
            same_cache_row
            and first_was_new
            and second_was_cached
        ):
            print(
                "CACHE TEST PASSED!"
            )

            print(
                "First request used Stockfish."
            )

            print(
                "Second request reused "
                "the saved result."
            )

        else:
            print(
                "CACHE TEST DID NOT MATCH "
                "EXPECTED RESULTS."
            )

            print(
                f"Same cache row: "
                f"{same_cache_row}"
            )

            print(
                f"First was new: "
                f"{first_was_new}"
            )

            print(
                f"Second was cached: "
                f"{second_was_cached}"
            )

    finally:
        if engine is not None:
            engine.quit()

        connection.close()


if __name__ == "__main__":
    main()