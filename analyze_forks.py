import sqlite3
import json
import chess
import chess.engine

from engine_cache import (
    DB_NAME,
    STOCKFISH_PATH,
    get_or_analyze,
    score_for_color,
)


TOOL_NAME = "fork_puzzles"
TOOL_VERSION = 1

TACTIC_TYPE = "missed_fork"
DETECTOR_VERSION = 1

QUICK_PROFILE = "tactic_quick_v1"
VERIFY_PROFILE = "tactic_verify_v1"

BATCH_SIZE = 500

# Quick pass is intentionally a little loose.
QUICK_MIN_GAIN_CP = 120
QUICK_MAX_DROP_FROM_BEST_CP = 300

# Deep verification is stricter.
VERIFY_MIN_GAIN_CP = 150
VERIFY_MAX_DROP_FROM_BEST_CP = 200


PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 300,
    chess.BISHOP: 300,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 10000,
}


# Ordinary pawns are not considered meaningful
# fork targets for V1.
FORK_TARGET_TYPES = {
    chess.KNIGHT,
    chess.BISHOP,
    chess.ROOK,
    chess.QUEEN,
    chess.KING,
}


def piece_name(piece_type):
    names = {
        chess.PAWN: "pawn",
        chess.KNIGHT: "knight",
        chess.BISHOP: "bishop",
        chess.ROOK: "rook",
        chess.QUEEN: "queen",
        chess.KING: "king",
    }

    return names.get(
        piece_type,
        "unknown"
    )


def ensure_analysis_run_columns(connection):
    cursor = connection.cursor()

    cursor.execute(
        "PRAGMA table_info(analysis_runs)"
    )

    columns = {
        row[1]
        for row in cursor.fetchall()
    }

    if "last_game_id" not in columns:
        cursor.execute("""
            ALTER TABLE analysis_runs
            ADD COLUMN last_game_id
                INTEGER NOT NULL DEFAULT 0
        """)

    if "last_ply_number" not in columns:
        cursor.execute("""
            ALTER TABLE analysis_runs
            ADD COLUMN last_ply_number
                INTEGER NOT NULL DEFAULT -1
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
            "No Merlin user exists."
        )

    return row[0]


def get_total_user_moves(connection):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM moves
        WHERE is_user_move = 1
    """)

    return cursor.fetchone()[0]


def find_resumable_run(
    connection,
    user_id
):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            run_id,
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
        TOOL_VERSION,
    ))

    return cursor.fetchone()


def create_analysis_run(
    connection,
    user_id,
    total_moves
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
            updated_at,
            last_game_id,
            last_ply_number
        )
        VALUES (
            ?, ?, ?, 'running',
            ?, 0, 0,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            0,
            -1
        )
    """, (
        user_id,
        TOOL_NAME,
        TOOL_VERSION,
        total_moves,
    ))

    connection.commit()

    return cursor.lastrowid


def clear_existing_fork_candidates(
    connection
):
    """
    This is a rebuildable derived layer.

    Mate candidates are untouched.
    """

    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM tactic_candidates
        WHERE tactic_type = ?
    """, (
        TACTIC_TYPE,
    ))

    connection.commit()


def load_batch(
    connection,
    last_game_id,
    last_ply_number
):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            m.move_id,
            m.game_id,
            m.ply_number,
            m.move_number,
            m.color,
            m.san_played,
            m.uci_played,
            m.fen_before,
            m.fen_after,

            g.source,
            g.source_game_id,
            g.white_username,
            g.black_username

        FROM moves m

        INNER JOIN games g
            ON g.game_id = m.game_id

        WHERE m.is_user_move = 1

          AND (
                m.game_id > ?

                OR (
                    m.game_id = ?
                    AND m.ply_number > ?
                )
          )

        ORDER BY
            m.game_id,
            m.ply_number

        LIMIT ?
    """, (
        last_game_id,
        last_game_id,
        last_ply_number,
        BATCH_SIZE,
    ))

    return cursor.fetchall()


def get_fork_targets(
    board,
    square,
    mover_color
):
    targets = []

    for attacked_square in board.attacks(
        square
    ):
        target_piece = board.piece_at(
            attacked_square
        )

        if target_piece is None:
            continue

        if target_piece.color == mover_color:
            continue

        if (
            target_piece.piece_type
            not in FORK_TARGET_TYPES
        ):
            continue

        targets.append({
            "square":
                chess.square_name(
                    attacked_square
                ),

            "piece":
                piece_name(
                    target_piece.piece_type
                ),

            "piece_type":
                target_piece.piece_type,

            "value":
                PIECE_VALUES[
                    target_piece.piece_type
                ],
        })

    return targets


def find_geometric_forks(board):
    """
    Cheap first-stage filter.

    No Stockfish is involved here.
    """

    mover_color = board.turn

    candidates = []

    for move in list(
        board.legal_moves
    ):
        moving_piece = board.piece_at(
            move.from_square
        )

        if moving_piece is None:
            continue

        san = board.san(move)

        test_board = board.copy()
        test_board.push(move)

        # If the move itself checkmates,
        # mate detection owns this position.
        if test_board.is_checkmate():
            continue

        targets = get_fork_targets(
            test_board,
            move.to_square,
            mover_color
        )

        if len(targets) < 2:
            continue

        candidates.append({
            "move": move,
            "move_uci": move.uci(),
            "move_san": san,

            "fork_piece":
                piece_name(
                    moving_piece.piece_type
                ),

            "fork_piece_type":
                moving_piece.piece_type,

            "from_square":
                chess.square_name(
                    move.from_square
                ),

            "to_square":
                chess.square_name(
                    move.to_square
                ),

            "targets":
                targets,

            "fen_after":
                test_board.fen(),
        })

    return candidates


def comparable_score(
    engine_result,
    player_color
):
    """
    Convert Stockfish CP/mate results into one
    sortable number from the user's POV.

    Ordinary CP is unchanged.

    Winning mate is extremely positive.
    Losing mate is extremely negative.

    The exact number is only for comparison;
    it is NOT displayed as a centipawn score.
    """

    result = score_for_color(
        engine_result,
        player_color
    )

    if result["score_type"] == "mate":
        mate = result["mate"]

        if mate is None:
            return 0

        if mate > 0:
            return (
                100000
                - min(abs(mate), 99) * 100
            )

        if mate < 0:
            return (
                -100000
                + min(abs(mate), 99) * 100
            )

        return 0

    return result["score_cp"] or 0


def perspective_result(
    engine_result,
    player_color
):
    return score_for_color(
        engine_result,
        player_color
    )


def user_has_forced_mate(
    engine_result,
    player_color
):
    result = perspective_result(
        engine_result,
        player_color
    )

    return (
        result["score_type"] == "mate"
        and result["mate"] is not None
        and result["mate"] > 0
    )


def cache_result(
    connection,
    engine,
    fen,
    profile,
    cache_stats
):
    result = get_or_analyze(
        connection,
        engine,
        fen,
        profile
    )

    if result["cache_hit"]:
        cache_stats["hits"] += 1
    else:
        cache_stats["misses"] += 1

    return result


def delete_fork_candidate(
    connection,
    move_id
):
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM tactic_candidates
        WHERE move_id = ?
          AND tactic_type = ?
    """, (
        move_id,
        TACTIC_TYPE,
    ))


def format_eval(
    engine_result,
    player_color
):
    result = perspective_result(
        engine_result,
        player_color
    )

    if result["score_type"] == "mate":
        return {
            "type": "mate",
            "mate": result["mate"],
            "cp": None,
        }

    return {
        "type": "cp",
        "mate": None,
        "cp": result["score_cp"],
    }


def save_fork_candidate(
    connection,
    move_id,
    fork,
    played_san,
    before_result,
    played_result,
    fork_result,
    player_color,
    gain,
    drop_from_best
):
    cursor = connection.cursor()

    delete_fork_candidate(
        connection,
        move_id
    )

    pv = fork_result[
        "principal_variation"
    ]

    if pv:
        solution_line = (
            f"{fork['move_san']} {pv}"
        )
    else:
        solution_line = (
            fork["move_san"]
        )

    metadata = {
        "detector": "fork_v1",

        "fork_piece":
            fork["fork_piece"],

        "fork_from":
            fork["from_square"],

        "fork_to":
            fork["to_square"],

        "targets":
            fork["targets"],

        "played_move":
            played_san,

        "evaluation_before":
            format_eval(
                before_result,
                player_color
            ),

        "evaluation_after_played":
            format_eval(
                played_result,
                player_color
            ),

        "evaluation_after_fork":
            format_eval(
                fork_result,
                player_color
            ),

        "gain_vs_played_cp_equivalent":
            gain,

        "drop_from_best_cp_equivalent":
            drop_from_best,

        "quick_profile":
            QUICK_PROFILE,

        "verify_profile":
            VERIFY_PROFILE,
    }

    confidence = min(
        1.0,
        0.75 + (
            max(gain, 0)
            / 2000.0
        )
    )

    notes = (
        "Verified geometric fork. "
        f"Fork improves the user's "
        f"evaluation by approximately "
        f"{gain / 100:.2f} pawns "
        f"versus the move actually played."
    )

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
            notes,
            metadata_json
        )
        VALUES (
            ?,
            ?,
            'candidate',
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?
        )
    """, (
        move_id,
        TACTIC_TYPE,
        confidence,
        DETECTOR_VERSION,
        fork["move_uci"],
        fork["move_san"],
        solution_line,
        notes,
        json.dumps(
            metadata,
            sort_keys=True
        ),
    ))


def update_run(
    connection,
    run_id,
    status,
    moves_scanned,
    candidates_found,
    last_game_id,
    last_ply_number,
    finished=False
):
    cursor = connection.cursor()

    if finished:
        cursor.execute("""
            UPDATE analysis_runs
            SET
                status = ?,
                moves_scanned = ?,
                candidates_found = ?,
                last_game_id = ?,
                last_ply_number = ?,
                updated_at = CURRENT_TIMESTAMP,
                finished_at = CURRENT_TIMESTAMP
            WHERE run_id = ?
        """, (
            status,
            moves_scanned,
            candidates_found,
            last_game_id,
            last_ply_number,
            run_id,
        ))

    else:
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
            run_id,
        ))

    connection.commit()


def main():
    connection = sqlite3.connect(
        DB_NAME
    )

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    engine = None

    ensure_analysis_run_columns(
        connection
    )

    user_id = get_user_id(
        connection
    )

    total_moves = get_total_user_moves(
        connection
    )

    resumable = find_resumable_run(
        connection,
        user_id
    )

    if resumable:
        (
            run_id,
            moves_scanned,
            candidates_found,
            last_game_id,
            last_ply_number
        ) = resumable

        print()
        print(
            "Resuming existing Fork Analyzer run."
        )

    else:
        clear_existing_fork_candidates(
            connection
        )

        run_id = create_analysis_run(
            connection,
            user_id,
            total_moves
        )

        moves_scanned = 0
        candidates_found = 0
        last_game_id = 0
        last_ply_number = -1

        print()
        print(
            "Created new Fork Analyzer run."
        )

    cache_stats = {
        "hits": 0,
        "misses": 0,
    }

    geometry_positions = 0
    geometry_moves = 0
    actual_forks_played = 0
    quick_survivors = 0
    deep_verified = 0

    try:
        print(
            "Starting Stockfish..."
        )

        engine = (
            chess.engine.SimpleEngine.popen_uci(
                STOCKFISH_PATH
            )
        )

        print()
        print("MERLIN FORK ANALYZER")
        print("--------------------")

        print(
            f"Total user moves: "
            f"{total_moves:,}"
        )

        print(
            f"Already scanned: "
            f"{moves_scanned:,}"
        )

        print(
            f"Quick profile: "
            f"{QUICK_PROFILE}"
        )

        print(
            f"Verification profile: "
            f"{VERIFY_PROFILE}"
        )

        print()

        while True:
            rows = load_batch(
                connection,
                last_game_id,
                last_ply_number
            )

            if not rows:
                break

            for row in rows:
                (
                    move_id,
                    game_id,
                    ply_number,
                    move_number,
                    color,
                    san_played,
                    uci_played,
                    fen_before,
                    fen_after,

                    source,
                    source_game_id,
                    white_username,
                    black_username
                ) = row

                last_game_id = game_id
                last_ply_number = (
                    ply_number
                )

                player_color = (
                    chess.WHITE
                    if color == "white"
                    else chess.BLACK
                )

                try:
                    board = chess.Board(
                        fen_before
                    )

                except ValueError:
                    continue

                if board.turn != player_color:
                    continue

                forks = find_geometric_forks(
                    board
                )

                if not forks:
                    continue

                geometry_positions += 1
                geometry_moves += len(forks)

                # If the player actually chose one of
                # the geometric fork moves, don't call
                # this a missed-fork position in V1.
                if any(
                    fork["move_uci"]
                    == uci_played
                    for fork in forks
                ):
                    actual_forks_played += 1

                    delete_fork_candidate(
                        connection,
                        move_id
                    )

                    continue

                before_quick = cache_result(
                    connection,
                    engine,
                    fen_before,
                    QUICK_PROFILE,
                    cache_stats
                )

                actual_quick = cache_result(
                    connection,
                    engine,
                    fen_after,
                    QUICK_PROFILE,
                    cache_stats
                )

                # Mate opportunities belong to the
                # mate detector, not Fork V1.
                if user_has_forced_mate(
                    before_quick,
                    player_color
                ):
                    continue

                if user_has_forced_mate(
                    actual_quick,
                    player_color
                ):
                    continue

                before_quick_value = (
                    comparable_score(
                        before_quick,
                        player_color
                    )
                )

                actual_quick_value = (
                    comparable_score(
                        actual_quick,
                        player_color
                    )
                )

                promising = []

                for fork in forks:

                    fork_quick = cache_result(
                        connection,
                        engine,
                        fork["fen_after"],
                        QUICK_PROFILE,
                        cache_stats
                    )

                    # If this is actually a mating move,
                    # let the mate detector own it.
                    if user_has_forced_mate(
                        fork_quick,
                        player_color
                    ):
                        continue

                    fork_quick_value = (
                        comparable_score(
                            fork_quick,
                            player_color
                        )
                    )

                    quick_gain = (
                        fork_quick_value
                        - actual_quick_value
                    )

                    quick_drop = (
                        before_quick_value
                        - fork_quick_value
                    )

                    if (
                        quick_gain
                        < QUICK_MIN_GAIN_CP
                    ):
                        continue

                    if (
                        quick_drop
                        > QUICK_MAX_DROP_FROM_BEST_CP
                    ):
                        continue

                    promising.append({
                        "fork": fork,

                        "quick_result":
                            fork_quick,

                        "quick_gain":
                            quick_gain,

                        "quick_drop":
                            quick_drop,
                    })

                if not promising:
                    delete_fork_candidate(
                        connection,
                        move_id
                    )

                    continue

                quick_survivors += 1

                # -------------------------------------
                # DEEP VERIFICATION
                # -------------------------------------

                before_deep = cache_result(
                    connection,
                    engine,
                    fen_before,
                    VERIFY_PROFILE,
                    cache_stats
                )

                actual_deep = cache_result(
                    connection,
                    engine,
                    fen_after,
                    VERIFY_PROFILE,
                    cache_stats
                )

                if user_has_forced_mate(
                    before_deep,
                    player_color
                ):
                    continue

                if user_has_forced_mate(
                    actual_deep,
                    player_color
                ):
                    continue

                before_deep_value = (
                    comparable_score(
                        before_deep,
                        player_color
                    )
                )

                actual_deep_value = (
                    comparable_score(
                        actual_deep,
                        player_color
                    )
                )

                verified = []

                for item in promising:
                    fork = item["fork"]

                    fork_deep = cache_result(
                        connection,
                        engine,
                        fork["fen_after"],
                        VERIFY_PROFILE,
                        cache_stats
                    )

                    if user_has_forced_mate(
                        fork_deep,
                        player_color
                    ):
                        continue

                    fork_deep_value = (
                        comparable_score(
                            fork_deep,
                            player_color
                        )
                    )

                    deep_gain = (
                        fork_deep_value
                        - actual_deep_value
                    )

                    deep_drop = (
                        before_deep_value
                        - fork_deep_value
                    )

                    if (
                        deep_gain
                        < VERIFY_MIN_GAIN_CP
                    ):
                        continue

                    if (
                        deep_drop
                        > VERIFY_MAX_DROP_FROM_BEST_CP
                    ):
                        continue

                    verified.append({
                        "fork": fork,

                        "result":
                            fork_deep,

                        "gain":
                            deep_gain,

                        "drop":
                            deep_drop,

                        "value":
                            fork_deep_value,
                    })

                if not verified:
                    delete_fork_candidate(
                        connection,
                        move_id
                    )

                    continue

                # Keep the strongest verified fork
                # for this position in V1.
                best = max(
                    verified,
                    key=lambda x: (
                        x["value"],
                        x["gain"]
                    )
                )

                save_fork_candidate(
                    connection,
                    move_id,
                    best["fork"],
                    san_played,
                    before_deep,
                    actual_deep,
                    best["result"],
                    player_color,
                    best["gain"],
                    best["drop"]
                )

                candidates_found += 1
                deep_verified += 1

                targets = ", ".join(
                    f"{target['piece']} "
                    f"on {target['square']}"
                    for target
                    in best["fork"]["targets"]
                )

                print()
                print(
                    "*** MISSED FORK FOUND ***"
                )

                print(
                    f"{source} "
                    f"{source_game_id}"
                )

                print(
                    f"Move "
                    f"{move_number} "
                    f"{color}"
                )

                print(
                    f"Played: "
                    f"{san_played}"
                )

                print(
                    f"Fork: "
                    f"{best['fork']['move_san']}"
                )

                print(
                    f"Forking piece: "
                    f"{best['fork']['fork_piece']} "
                    f"{best['fork']['from_square']}"
                    f"->{best['fork']['to_square']}"
                )

                print(
                    f"Targets: {targets}"
                )

                print(
                    f"Improvement vs played: "
                    f"{best['gain'] / 100:.2f} pawns"
                )

            moves_scanned += len(rows)

            update_run(
                connection,
                run_id,
                "running",
                moves_scanned,
                candidates_found,
                last_game_id,
                last_ply_number
            )

            percent = (
                moves_scanned
                / total_moves
                * 100
            )

            print()
            print(
                f"Progress: "
                f"{moves_scanned:,} / "
                f"{total_moves:,} "
                f"({percent:.1f}%)"
            )

            print(
                f"Missed forks found: "
                f"{candidates_found:,}"
            )

            print(
                f"Cache hits / misses: "
                f"{cache_stats['hits']:,} / "
                f"{cache_stats['misses']:,}"
            )

        update_run(
            connection,
            run_id,
            "complete",
            moves_scanned,
            candidates_found,
            last_game_id,
            last_ply_number,
            finished=True
        )

        connection.commit()

        print()
        print("FORK ANALYSIS COMPLETE")
        print("----------------------")

        print(
            f"User moves scanned: "
            f"{moves_scanned:,}"
        )

        print(
            f"Positions with geometric forks: "
            f"{geometry_positions:,}"
        )

        print(
            f"Geometric fork moves found: "
            f"{geometry_moves:,}"
        )

        print(
            f"Positions where a fork was played: "
            f"{actual_forks_played:,}"
        )

        print(
            f"Quick-pass survivors: "
            f"{quick_survivors:,}"
        )

        print(
            f"Verified missed forks saved: "
            f"{candidates_found:,}"
        )

        print(
            f"Cache hits: "
            f"{cache_stats['hits']:,}"
        )

        print(
            f"Cache misses: "
            f"{cache_stats['misses']:,}"
        )

    except KeyboardInterrupt:
        print()
        print()
        print(
            "Fork analysis paused."
        )

        print(
            "Progress has been saved."
        )

        update_run(
            connection,
            run_id,
            "paused",
            moves_scanned,
            candidates_found,
            last_game_id,
            last_ply_number
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        if engine is not None:
            engine.quit()

        connection.close()


if __name__ == "__main__":
    main()