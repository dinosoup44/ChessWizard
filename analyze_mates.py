import sqlite3
import chess
import chess.engine


DB_NAME = "merlin.db"

STOCKFISH_PATH = (
    r"Engines\Stockfish\stockfish-windows-x86-64-avx2"
    r"\stockfish\stockfish-windows-x86-64-avx2.exe"
)

# ---------------------------------------------------------
# Mate analyzer settings
# ---------------------------------------------------------

TOOL_NAME = "mate_puzzles"
TOOL_VERSION = 3
ANALYSIS_VERSION = 2

MATE_LIMIT = 3

# Quick pass:
# Most positions only get this much engine work.
QUICK_DEPTH = 10

# Verification pass:
# Only positions that look like mate candidates get this.
VERIFY_DEPTH = 18

# Number of user moves fetched from SQLite at a time.
BATCH_SIZE = 500


# ---------------------------------------------------------
# Database helpers
# ---------------------------------------------------------

def column_exists(cursor, table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")

    for column in cursor.fetchall():
        if column[1] == column_name:
            return True

    return False


def prepare_analysis_runs_table(connection):
    """
    Adds resume-position fields to analysis_runs if they
    do not already exist.

    This lets Merlin remember exactly where he stopped.
    """

    cursor = connection.cursor()

    if not column_exists(
        cursor,
        "analysis_runs",
        "last_game_id"
    ):
        cursor.execute("""
            ALTER TABLE analysis_runs
            ADD COLUMN last_game_id INTEGER
        """)

    if not column_exists(
        cursor,
        "analysis_runs",
        "last_ply_number"
    ):
        cursor.execute("""
            ALTER TABLE analysis_runs
            ADD COLUMN last_ply_number INTEGER
        """)

    connection.commit()


def get_user_id(connection):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT user_id
        FROM users
        ORDER BY user_id
        LIMIT 1
    """)

    row = cursor.fetchone()

    if row is None:
        raise RuntimeError(
            "No Merlin user exists in the database."
        )

    return row[0]


def count_user_moves(connection, user_id):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM moves m
        INNER JOIN games g
            ON g.game_id = m.game_id
        WHERE m.is_user_move = 1
          AND g.user_id = ?
    """, (user_id,))

    return cursor.fetchone()[0]


def find_resumable_run(
    connection,
    user_id
):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            run_id,
            moves_total,
            moves_scanned,
            candidates_found,
            last_game_id,
            last_ply_number
        FROM analysis_runs
        WHERE user_id = ?
          AND tool_name = ?
          AND tool_version = ?
          AND status IN (
              'running',
              'paused'
          )
        ORDER BY run_id DESC
        LIMIT 1
    """, (
        user_id,
        TOOL_NAME,
        TOOL_VERSION
    ))

    return cursor.fetchone()


def remove_old_mate_results(connection):
    """
    Version 3 fixes our evaluation point-of-view logic.

    Older missed-mate candidates are therefore considered
    unverified and are removed before the first v3 scan.
    """

    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM tactic_candidates
        WHERE tactic_type = 'missed_mate'
          AND detector_version < ?
    """, (
        TOOL_VERSION,
    ))

    removed = cursor.rowcount

    connection.commit()

    return removed


def create_analysis_run(
    connection,
    user_id,
    moves_total
):
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO analysis_runs (
            user_id,
            tool_name,
            tool_version,
            status,
            moves_total,
            moves_scanned,
            candidates_found,
            started_at,
            updated_at
        )
        VALUES (
            ?,
            ?,
            ?,
            'running',
            ?,
            0,
            0,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
    """, (
        user_id,
        TOOL_NAME,
        TOOL_VERSION,
        moves_total
    ))

    connection.commit()

    return cursor.lastrowid


def update_run(
    connection,
    run_id,
    moves_scanned,
    candidates_found,
    last_game_id,
    last_ply_number,
    status="running"
):
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE analysis_runs
        SET
            status = ?,
            moves_scanned = ?,
            candidates_found = ?,
            last_game_id = ?,
            last_ply_number = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE run_id = ?
    """, (
        status,
        moves_scanned,
        candidates_found,
        last_game_id,
        last_ply_number,
        run_id
    ))

    connection.commit()


def finish_run(
    connection,
    run_id,
    moves_scanned,
    candidates_found,
    last_game_id,
    last_ply_number
):
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE analysis_runs
        SET
            status = 'complete',
            moves_scanned = ?,
            candidates_found = ?,
            last_game_id = ?,
            last_ply_number = ?,
            finished_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE run_id = ?
    """, (
        moves_scanned,
        candidates_found,
        last_game_id,
        last_ply_number,
        run_id
    ))

    connection.commit()


# ---------------------------------------------------------
# Move batching
#
# Games are processed in game_id order, but within each
# game Merlin scans backward from the end toward the start.
# ---------------------------------------------------------

def get_move_batch(
    connection,
    user_id,
    last_game_id,
    last_ply_number
):
    cursor = connection.cursor()

    if last_game_id is None:
        cursor.execute("""
            SELECT
                m.move_id,
                m.game_id,
                m.ply_number,
                m.move_number,
                m.color,
                m.fen_before,
                m.fen_after,
                m.san_played,
                m.uci_played,
                g.source,
                g.source_game_id
            FROM moves m
            INNER JOIN games g
                ON g.game_id = m.game_id
            WHERE m.is_user_move = 1
              AND g.user_id = ?
            ORDER BY
                m.game_id ASC,
                m.ply_number DESC
            LIMIT ?
        """, (
            user_id,
            BATCH_SIZE
        ))

    else:
        cursor.execute("""
            SELECT
                m.move_id,
                m.game_id,
                m.ply_number,
                m.move_number,
                m.color,
                m.fen_before,
                m.fen_after,
                m.san_played,
                m.uci_played,
                g.source,
                g.source_game_id
            FROM moves m
            INNER JOIN games g
                ON g.game_id = m.game_id
            WHERE m.is_user_move = 1
              AND g.user_id = ?
              AND (
                    m.game_id > ?
                    OR (
                        m.game_id = ?
                        AND m.ply_number < ?
                    )
                  )
            ORDER BY
                m.game_id ASC,
                m.ply_number DESC
            LIMIT ?
        """, (
            user_id,
            last_game_id,
            last_game_id,
            last_ply_number,
            BATCH_SIZE
        ))

    return cursor.fetchall()


# ---------------------------------------------------------
# Stockfish helpers
# ---------------------------------------------------------

def color_from_text(color):
    if color == "white":
        return chess.WHITE

    return chess.BLACK


def analyze_position(
    engine,
    fen,
    player_color,
    depth
):
    board = chess.Board(fen)

    info = engine.analyse(
        board,
        chess.engine.Limit(
            depth=depth
        )
    )

    # IMPORTANT:
    #
    # Always evaluate from the user's color,
    # NOT simply whoever is currently to move.
    score = info["score"].pov(
        player_color
    )

    mate_distance = score.mate()

    best_move_uci = None
    best_move_san = None
    principal_variation = []

    pv = info.get("pv", [])

    if pv:
        best_move = pv[0]

        best_move_uci = best_move.uci()

        try:
            best_move_san = board.san(
                best_move
            )
        except ValueError:
            best_move_san = None

        pv_board = board.copy()

        for move in pv:
            try:
                san = pv_board.san(move)

                principal_variation.append(
                    san
                )

                pv_board.push(move)

            except ValueError:
                break

    return {
        "board": board,
        "info": info,
        "score": score,
        "mate_distance": mate_distance,
        "best_move_uci": best_move_uci,
        "best_move_san": best_move_san,
        "principal_variation": (
            " ".join(
                principal_variation
            )
        )
    }


def is_positive_mate_within_limit(
    mate_distance
):
    if mate_distance is None:
        return False

    if mate_distance <= 0:
        return False

    return mate_distance <= MATE_LIMIT


def analyze_single_move(row, analyze_fen):
    """Mate V3's decision sequence for one move, with no persistence or crawl.

    analyze_fen(fen, player_color, depth) returns player-POV mate_distance,
    best_move_uci/san and principal_variation. The crawler supplies a cached
    implementation rather than the legacy direct Stockfish wrapper.
    """
    color = color_from_text(row["color"])
    quick = analyze_fen(row["fen_before"], color, QUICK_DEPTH)
    if not is_positive_mate_within_limit(quick["mate_distance"]):
        return {"candidate": None, "reason": "quick_search_no_mate_within_limit"}
    before = analyze_fen(row["fen_before"], color, VERIFY_DEPTH)
    if not is_positive_mate_within_limit(before["mate_distance"]):
        return {"candidate": None, "reason": "deep_search_no_mate_within_limit"}
    if chess.Board(row["fen_after"]).is_checkmate():
        return {"candidate": None, "reason": "played_move_delivered_checkmate"}
    after = analyze_fen(row["fen_after"], color, VERIFY_DEPTH)
    if after["mate_distance"] is not None and after["mate_distance"] > 0:
        return {"candidate": None, "reason": "played_move_kept_forced_mate"}
    return {"reason": "forced_mate_lost", "candidate": {
        "candidate_status": "confirmed", "confidence": 1.0,
        "detector_version": TOOL_VERSION,
        "solution_move_uci": before["best_move_uci"],
        "solution_move_san": before["best_move_san"],
        "solution_line": before["principal_variation"],
        "notes": f"Forced mate in {before['mate_distance']} was lost.",
        "metadata_json": None,
    }}


# ---------------------------------------------------------
# Stored analysis
# ---------------------------------------------------------

def save_engine_analysis(
    connection,
    move_id,
    before_result,
    after_result
):
    cursor = connection.cursor()

    # Avoid duplicate v2 analysis rows
    # if a candidate is reprocessed.
    cursor.execute("""
        DELETE FROM engine_analysis
        WHERE move_id = ?
          AND engine_name = 'Stockfish'
          AND analysis_version = ?
    """, (
        move_id,
        ANALYSIS_VERSION
    ))

    before_info = before_result["info"]

    before_score = (
        before_result["score"]
    )

    after_score = (
        after_result["score"]
    )

    score_cp_before = (
        before_score.score()
    )

    score_cp_after = (
        after_score.score()
    )

    mate_before = (
        before_result[
            "mate_distance"
        ]
    )

    mate_after = (
        after_result[
            "mate_distance"
        ]
    )

    if mate_before is not None:
        score_type = "mate"
    else:
        score_type = "cp"

    cursor.execute("""
        INSERT INTO engine_analysis (
            move_id,
            engine_name,
            engine_version,
            analysis_version,
            depth,
            seldepth,
            nodes,
            score_type,
            score_cp_before,
            mate_before,
            best_move_uci,
            best_move_san,
            principal_variation,
            score_cp_after,
            mate_after
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?
        )
    """, (
        move_id,
        "Stockfish",
        "18",
        ANALYSIS_VERSION,
        before_info.get("depth"),
        before_info.get("seldepth"),
        before_info.get("nodes"),
        score_type,
        score_cp_before,
        mate_before,
        before_result[
            "best_move_uci"
        ],
        before_result[
            "best_move_san"
        ],
        before_result[
            "principal_variation"
        ],
        score_cp_after,
        mate_after
    ))


def delete_missed_mate_candidate(
    connection,
    move_id
):
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM tactic_candidates
        WHERE move_id = ?
          AND tactic_type = 'missed_mate'
    """, (
        move_id,
    ))


def save_missed_mate_candidate(
    connection,
    move_id,
    before_result
):
    # First eliminate any stale result
    # for this move.
    delete_missed_mate_candidate(
        connection,
        move_id
    )

    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO tactic_candidates (
            move_id,
            tactic_type,
            candidate_status,
            confidence,
            detector_version,
            solution_move_uci,
            solution_move_san,
            solution_line,
            notes
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
    """, (
        move_id,
        "missed_mate",
        "confirmed",
        1.0,
        TOOL_VERSION,
        before_result[
            "best_move_uci"
        ],
        before_result[
            "best_move_san"
        ],
        before_result[
            "principal_variation"
        ],
        (
            "Forced mate in "
            f"{before_result['mate_distance']} "
            "was lost."
        )
    ))


# ---------------------------------------------------------
# Main analyzer
# ---------------------------------------------------------

def main():
    connection = sqlite3.connect(
        DB_NAME
    )

    prepare_analysis_runs_table(
        connection
    )

    user_id = get_user_id(
        connection
    )

    total_user_moves = count_user_moves(
        connection,
        user_id
    )

    resumable_run = find_resumable_run(
        connection,
        user_id
    )

    if resumable_run:
        (
            run_id,
            moves_total,
            moves_scanned,
            candidates_found,
            last_game_id,
            last_ply_number
        ) = resumable_run

        print("Resuming Mate Analyzer.")
        print(
            "Previously scanned:",
            moves_scanned
        )

    else:
        removed = remove_old_mate_results(
            connection
        )

        if removed:
            print(
                "Removed",
                removed,
                "older mate-detector result(s)."
            )
            print()

        moves_total = total_user_moves
        moves_scanned = 0
        candidates_found = 0
        last_game_id = None
        last_ply_number = None

        run_id = create_analysis_run(
            connection,
            user_id,
            moves_total
        )

        print("Created new Mate Analyzer run.")

    print()
    print("Starting Stockfish...")

    engine = (
        chess.engine.SimpleEngine.popen_uci(
            STOCKFISH_PATH
        )
    )

    quick_hits = 0
    verified_mates = 0
    played_checkmates = 0

    try:
        print()
        print("MERLIN MATE ANALYZER")
        print("--------------------")
        print(
            "Total user moves:",
            moves_total
        )
        print(
            "Already scanned:",
            moves_scanned
        )
        print(
            "Quick depth:",
            QUICK_DEPTH
        )
        print(
            "Verification depth:",
            VERIFY_DEPTH
        )
        print(
            "Mate limit:",
            MATE_LIMIT
        )
        print()

        while True:
            batch = get_move_batch(
                connection,
                user_id,
                last_game_id,
                last_ply_number
            )

            if not batch:
                break

            for row in batch:
                (
                    move_id,
                    game_id,
                    ply_number,
                    move_number,
                    color,
                    fen_before,
                    fen_after,
                    san_played,
                    uci_played,
                    source,
                    source_game_id
                ) = row

                player_color = color_from_text(
                    color
                )

                # ---------------------------------------------
                # PASS 1
                # Cheap scan.
                # ---------------------------------------------

                quick_result = analyze_position(
                    engine,
                    fen_before,
                    player_color,
                    QUICK_DEPTH
                )

                quick_mate = quick_result[
                    "mate_distance"
                ]

                if is_positive_mate_within_limit(
                    quick_mate
                ):
                    quick_hits += 1

                    print()
                    print(
                        f"POSSIBLE MATE: "
                        f"{source} "
                        f"{source_game_id}"
                    )

                    print(
                        f"Move {move_number} "
                        f"{color} "
                        f"{san_played}"
                    )

                    print(
                        "Quick scan:",
                        f"mate in {quick_mate}"
                    )

                    # -----------------------------------------
                    # PASS 2
                    # Deep verification before we trust it.
                    # -----------------------------------------

                    before_result = (
                        analyze_position(
                            engine,
                            fen_before,
                            player_color,
                            VERIFY_DEPTH
                        )
                    )

                    mate_before = (
                        before_result[
                            "mate_distance"
                        ]
                    )

                    if (
                        is_positive_mate_within_limit(
                            mate_before
                        )
                    ):
                        verified_mates += 1

                        print(
                            "Verified:",
                            f"mate in {mate_before}"
                        )

                        after_board = chess.Board(
                            fen_after
                        )

                        # -------------------------------------
                        # Actual played move delivered mate.
                        # -------------------------------------

                        if after_board.is_checkmate():
                            played_checkmates += 1

                            delete_missed_mate_candidate(
                                connection,
                                move_id
                            )

                            print(
                                "Played move delivered "
                                "checkmate."
                            )

                            print(
                                "Not a missed mate."
                            )

                        else:
                            # IMPORTANT:
                            # Evaluate AFTER from the SAME
                            # player's point of view.
                            after_result = (
                                analyze_position(
                                    engine,
                                    fen_after,
                                    player_color,
                                    VERIFY_DEPTH
                                )
                            )

                            mate_after = (
                                after_result[
                                    "mate_distance"
                                ]
                            )

                            save_engine_analysis(
                                connection,
                                move_id,
                                before_result,
                                after_result
                            )

                            # User had forced mate before,
                            # but does not have a positive
                            # forced mate afterward.
                            if (
                                mate_after is None
                                or mate_after <= 0
                            ):
                                save_missed_mate_candidate(
                                    connection,
                                    move_id,
                                    before_result
                                )

                                candidates_found += 1

                                print(
                                    "*** MISSED MATE FOUND ***"
                                )

                                print(
                                    "Played:",
                                    san_played
                                )

                                print(
                                    "Best:",
                                    before_result[
                                        "best_move_san"
                                    ]
                                )

                                print(
                                    "Line:",
                                    before_result[
                                        "principal_variation"
                                    ]
                                )

                            else:
                                # Mate still exists.
                                # Make sure an old false
                                # candidate is removed.
                                delete_missed_mate_candidate(
                                    connection,
                                    move_id
                                )

                                print(
                                    "Mate still exists "
                                    "after played move:",
                                    mate_after
                                )

                moves_scanned += 1

                last_game_id = game_id
                last_ply_number = ply_number

            # ---------------------------------------------
            # Commit once per batch.
            #
            # If Merlin is interrupted, at worst this batch
            # gets repeated. No thousands of moves are lost.
            # ---------------------------------------------

            update_run(
                connection,
                run_id,
                moves_scanned,
                candidates_found,
                last_game_id,
                last_ply_number,
                status="running"
            )

            percent = (
                moves_scanned
                / moves_total
                * 100
            )

            print()
            print(
                f"Progress: "
                f"{moves_scanned:,}"
                f" / "
                f"{moves_total:,}"
                f" "
                f"({percent:.1f}%)"
            )

            print(
                "Missed mates found:",
                candidates_found
            )

        finish_run(
            connection,
            run_id,
            moves_scanned,
            candidates_found,
            last_game_id,
            last_ply_number
        )

        print()
        print("MATE ANALYSIS COMPLETE")
        print("----------------------")
        print(
            "User moves scanned:",
            f"{moves_scanned:,}"
        )
        print(
            "Quick mate hits:",
            quick_hits
        )
        print(
            "Verified mate positions:",
            verified_mates
        )
        print(
            "Checkmates actually played:",
            played_checkmates
        )
        print(
            "Missed mates saved:",
            candidates_found
        )

    except KeyboardInterrupt:
        print()
        print()
        print("Mate analysis paused by user.")

        update_run(
            connection,
            run_id,
            moves_scanned,
            candidates_found,
            last_game_id,
            last_ply_number,
            status="paused"
        )

        print(
            "Progress saved at:",
            f"{moves_scanned:,}",
            "moves."
        )

        print(
            "Run analyze_mates.py again "
            "to resume."
        )

    finally:
        engine.quit()
        connection.close()


if __name__ == "__main__":
    main()
