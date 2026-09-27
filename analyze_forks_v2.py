import sqlite3
import json
import sys
from datetime import datetime
import chess
import chess.engine
from board_analysis import attacked_pieces, capture_square
from fork_threats import functional_fork_threats, retain_functional_forks
from exchange_presentation import build_exchange_presentation, matching_tactical_continuation

from engine_cache import (
    DB_NAME,
    STOCKFISH_PATH,
    get_or_analyze,
    score_for_color,
)


TOOL_NAME = "fork_puzzles"
TOOL_VERSION = 2

TACTIC_TYPE = "missed_fork"
DETECTOR_VERSION = 2

QUICK_PROFILE = "tactic_quick_v1"
VERIFY_PROFILE = "tactic_verify_v1"

BATCH_SIZE = 500

QUICK_MIN_GAIN_CP = 120
QUICK_MAX_DROP_FROM_BEST_CP = 300

VERIFY_MIN_GAIN_CP = 150
VERIFY_MAX_DROP_FROM_BEST_CP = 200

POST_CONVERSION_EQUAL_CP = 100
POST_CONVERSION_WINNING_CP = 150
AUDIT_PROGRESS_EVERY = 50


PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 300,
    chess.BISHOP: 300,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 10000,
}


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
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM tactic_candidates
        WHERE tactic_type = ?
          AND candidate_id > 0
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
    return [
        {"square": chess.square_name(piece.square), "piece": piece_name(piece.piece_type),
         "piece_type": piece.piece_type, "value": PIECE_VALUES[piece.piece_type]}
        for piece in attacked_pieces(board, square, target_color=not mover_color,
                                     piece_types=FORK_TARGET_TYPES)
    ]


def find_geometric_forks(board):
    mover_color = board.turn

    candidates = []

    for move in list(
        board.legal_moves
    ):
        san = board.san(move)

        test_board = board.copy()
        test_board.push(move)

        if test_board.is_checkmate():
            continue

        fork_piece = test_board.piece_at(
            move.to_square
        )

        if fork_piece is None:
            continue

        targets = get_fork_targets(
            test_board,
            move.to_square,
            mover_color
        )

        if len(targets) < 2:
            continue

        candidates.append({
            "move_uci":
                move.uci(),

            "move_san":
                san,

            "fork_piece":
                piece_name(
                    fork_piece.piece_type
                ),

            "fork_piece_type":
                fork_piece.piece_type,

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


def perspective_result(
    engine_result,
    player_color
):
    return score_for_color(
        engine_result,
        player_color
    )


def is_winning_mate(
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


def is_losing_mate(
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
        and result["mate"] < 0
    )


def comparable_score(
    engine_result,
    player_color
):
    result = perspective_result(
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
                - min(
                    abs(mate),
                    99
                ) * 100
            )

        if mate < 0:
            return (
                -100000
                + min(
                    abs(mate),
                    99
                ) * 100
            )

        return 0

    return result["score_cp"] or 0


def cache_result(
    connection,
    engine,
    fen,
    profile,
    stats
):
    result = get_or_analyze(
        connection,
        engine,
        fen,
        profile
    )

    if result["cache_hit"]:
        stats["hits"] += 1
    else:
        stats["misses"] += 1

    return result


def get_capture_square(
    board,
    move
):
    """Compatibility wrapper; shared primitive owns capture geometry."""
    return capture_square(board, move)


def verify_fork_realization(
    fen_before,
    fork,
    fork_result
):
    """
    Strict fork definition:

    fork move
        ↓
    opponent best reply
        ↓
    same forking piece captures
    one of the original fork targets
        ↓
    return the exact post-conversion FEN

    The post-conversion FEN is important because
    Merlin now verifies the position again AFTER
    the target has been captured.
    """

    board = chess.Board(
        fen_before
    )

    fork_move = chess.Move.from_uci(
        fork["move_uci"]
    )

    if fork_move not in board.legal_moves:
        return None

    threats = functional_fork_threats(board, fork_move)
    if not threats.valid:
        return None

    board.push(
        fork_move
    )

    fork_square = (
        fork_move.to_square
    )

    fork_piece = board.piece_at(
        fork_square
    )

    if fork_piece is None:
        return None

    fork_color = fork_piece.color
    fork_piece_type = (
        fork_piece.piece_type
    )

    targets = []

    for target in fork["targets"]:
        if chess.parse_square(target["square"]) not in threats.legal_targets:
            continue
        targets.append({
            "square":
                chess.parse_square(
                    target["square"]
                ),

            "piece":
                target["piece"],

            "piece_type":
                target["piece_type"],
        })

    pv = (
        fork_result[
            "principal_variation"
        ]
        or ""
    )

    tokens = pv.split()

    if len(tokens) < 2:
        return None

    # ---------------------------------------------
    # OPPONENT BEST RESPONSE
    # ---------------------------------------------

    try:
        opponent_move = (
            board.parse_san(
                tokens[0]
            )
        )

    except ValueError:
        return None

    captured_square = (
        get_capture_square(
            board,
            opponent_move
        )
    )

    # Opponent simply takes the supposed
    # forking piece.
    if captured_square == fork_square:
        return None

    # If one of the fork targets moves,
    # follow it to its new square.
    for target in targets:

        if (
            target["square"]
            == opponent_move.from_square
        ):
            target["square"] = (
                opponent_move.to_square
            )

            break

    board.push(
        opponent_move
    )

    surviving_piece = (
        board.piece_at(
            fork_square
        )
    )

    if surviving_piece is None:
        return None

    if (
        surviving_piece.color
        != fork_color
    ):
        return None

    if (
        surviving_piece.piece_type
        != fork_piece_type
    ):
        return None

    # ---------------------------------------------
    # USER'S NEXT MOVE / CONVERSION
    # ---------------------------------------------

    try:
        conversion_move = (
            board.parse_san(
                tokens[1]
            )
        )

    except ValueError:
        return None

    # Must be the SAME forking piece.
    if (
        conversion_move.from_square
        != fork_square
    ):
        return None

    capture_square = (
        get_capture_square(
            board,
            conversion_move
        )
    )

    if capture_square is None:
        return None

    captured_piece = board.piece_at(
        capture_square
    )

    if captured_piece is None:
        return None

    matched_target = None

    for target in targets:

        if (
            target["square"]
            == capture_square

            and target["piece_type"]
            == captured_piece.piece_type
        ):
            matched_target = target
            break

    if matched_target is None:
        return None

    board.push(
        conversion_move
    )

    return {
        "opponent_reply":
            tokens[0],

        "conversion_move":
            tokens[1],

        # Kept as won_piece / won_square for
        # backward compatibility with the UI.
        # The UI can later display this as
        # "captures" rather than always "wins".
        "won_piece":
            matched_target["piece"],

        "won_square":
            chess.square_name(
                capture_square
            ),

        "fen_after_conversion":
            board.fen(),
    }


def post_conversion_metrics(
    before_result,
    played_result,
    conversion_result,
    player_color
):
    """
    Compare the position AFTER the fork has
    actually converted against both:

    - the move the user really played
    - the original position before the mistake

    This prevents Merlin from celebrating a
    temporary capture that immediately collapses
    back to equality or a losing position.
    """

    before_value = comparable_score(
        before_result,
        player_color
    )

    played_value = comparable_score(
        played_result,
        player_color
    )

    conversion_value = comparable_score(
        conversion_result,
        player_color
    )

    return {
        "before_value":
            before_value,

        "played_value":
            played_value,

        "conversion_value":
            conversion_value,

        "gain_vs_played":
            conversion_value
            - played_value,

        "drop_from_best":
            before_value
            - conversion_value,
    }


def post_conversion_is_valid(
    before_result,
    played_result,
    conversion_result,
    player_color
):
    """
    Final fork quality gate.

    The converted position must still provide the
    same meaningful improvement Merlin required
    when it first accepted the fork.
    """

    if is_losing_mate(
        conversion_result,
        player_color
    ):
        return False, None

    metrics = post_conversion_metrics(
        before_result,
        played_result,
        conversion_result,
        player_color
    )

    if (
        metrics["gain_vs_played"]
        < VERIFY_MIN_GAIN_CP
    ):
        return False, metrics

    if (
        metrics["drop_from_best"]
        > VERIFY_MAX_DROP_FROM_BEST_CP
    ):
        return False, metrics

    return True, metrics


def classify_fork_outcome(
    played_result,
    conversion_result,
    player_color
):
    """
    Give Merlin a teaching-oriented label for
    the FINAL converted position.
    """

    played = perspective_result(
        played_result,
        player_color
    )

    conversion = perspective_result(
        conversion_result,
        player_color
    )

    played_is_losing_mate = (
        played["score_type"] == "mate"
        and played["mate"] is not None
        and played["mate"] < 0
    )

    conversion_is_losing_mate = (
        conversion["score_type"] == "mate"
        and conversion["mate"] is not None
        and conversion["mate"] < 0
    )

    if (
        played_is_losing_mate
        and not conversion_is_losing_mate
    ):
        return "saving_fork"

    if (
        conversion["score_type"] == "mate"
        and conversion["mate"] is not None
        and conversion["mate"] > 0
    ):
        return "winning_fork"

    conversion_cp = conversion["score_cp"]
    played_cp = played["score_cp"]

    if conversion_cp is not None:

        if (
            abs(conversion_cp)
            <= POST_CONVERSION_EQUAL_CP

            and played_cp is not None
            and played_cp
            < -POST_CONVERSION_EQUAL_CP
        ):
            return "equalizing_fork"

        if (
            conversion_cp
            >= POST_CONVERSION_WINNING_CP
        ):
            return "winning_fork"

    return "improving_fork"


def outcome_label(outcome):
    labels = {
        "saving_fork":
            "Saving fork",

        "equalizing_fork":
            "Equalizing fork",

        "winning_fork":
            "Winning fork",

        "improving_fork":
            "Improving fork",
    }

    return labels.get(
        outcome,
        "Verified fork"
    )


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


def build_fork_candidate(
    played_san,
    fork,
    realization,
    before_result,
    played_result,
    fork_result,
    conversion_result,
    player_color
):
    before_eval = format_eval(
        before_result,
        player_color
    )

    played_eval = format_eval(
        played_result,
        player_color
    )

    fork_eval = format_eval(
        fork_result,
        player_color
    )

    conversion_eval = format_eval(
        conversion_result,
        player_color
    )

    metrics = post_conversion_metrics(
        before_result,
        played_result,
        conversion_result,
        player_color
    )

    outcome = classify_fork_outcome(
        played_result,
        conversion_result,
        player_color
    )

    avoids_forced_mate = (
        outcome == "saving_fork"
    )

    gain_cp = None

    if (
        played_eval["type"] == "cp"
        and conversion_eval["type"] == "cp"
    ):
        gain_cp = (
            conversion_eval["cp"]
            - played_eval["cp"]
        )

    drop_from_best_cp = None

    if (
        before_eval["type"] == "cp"
        and conversion_eval["type"] == "cp"
    ):
        drop_from_best_cp = (
            before_eval["cp"]
            - conversion_eval["cp"]
        )

    # Fork puzzles end when the tactical idea
    # converts. Do not make the trainee reproduce
    # an arbitrary 15-20 ply Stockfish continuation.
    solution_line = (
        f"{fork['move_san']} "
        f"{realization['opponent_reply']} "
        f"{realization['conversion_move']}"
    )

    metadata = {
        "detector":
            "fork_v2_post_conversion",

        "post_conversion_version":
            1,

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
            before_eval,

        "evaluation_after_played":
            played_eval,

        "evaluation_after_fork":
            fork_eval,

        "evaluation_after_conversion":
            conversion_eval,

        # Backward-compatible field now reflects
        # the final post-conversion position.
        "gain_vs_played_cp":
            gain_cp,

        "drop_from_best_cp":
            drop_from_best_cp,

        "post_conversion_gain_score":
            metrics["gain_vs_played"],

        "post_conversion_drop_score":
            metrics["drop_from_best"],

        "outcome_classification":
            outcome,

        "avoids_forced_mate":
            avoids_forced_mate,

        "realization":
            realization,

        "quick_profile":
            QUICK_PROFILE,

        "verify_profile":
            VERIFY_PROFILE,
    }

    if avoids_forced_mate:
        confidence = 0.98

        notes = (
            "Verified saving fork avoids a "
            "forced mate and converts by "
            f"capturing the "
            f"{realization['won_piece']}."
        )

    else:
        gain_pawns = (
            gain_cp / 100
            if gain_cp is not None
            else 0
        )

        confidence = min(
            0.99,
            0.80
            + max(
                gain_pawns,
                0
            ) / 25
        )

        if outcome == "equalizing_fork":
            notes = (
                "Verified equalizing fork "
                "recovers an approximately "
                "equal position after conversion "
                "and captures the "
                f"{realization['won_piece']}."
            )

        elif outcome == "winning_fork":
            notes = (
                "Verified winning fork leaves "
                "the user with a winning "
                "advantage after conversion "
                "and captures the "
                f"{realization['won_piece']}."
            )

        else:
            notes = (
                "Verified fork improves "
                "the user's position by "
                f"{gain_pawns:.2f} pawns "
                "versus the move played, "
                "measured after conversion, "
                "and captures the "
                f"{realization['won_piece']}."
            )

    return {
        "candidate_status": "candidate", "confidence": confidence,
        "detector_version": DETECTOR_VERSION,
        "solution_move_uci": fork["move_uci"], "solution_move_san": fork["move_san"],
        "solution_line": solution_line, "notes": notes,
        "metadata_json": json.dumps(metadata, sort_keys=True),
    }


def save_fork_payload(connection, move_id, payload):
    """Legacy CLI persistence only. Central crawler must never call this."""
    delete_fork_candidate(connection, move_id)
    connection.execute("""
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
        payload["confidence"],
        DETECTOR_VERSION,
        payload["solution_move_uci"],
        payload["solution_move_san"],
        payload["solution_line"],
        payload["notes"],
        payload["metadata_json"],
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
                updated_at =
                    CURRENT_TIMESTAMP,
                finished_at =
                    CURRENT_TIMESTAMP
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
                updated_at =
                    CURRENT_TIMESTAMP
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


def analyze_single_move(row, analyze_fen):
    """Calculate one Fork V2 result using analyze_fen(fen, profile).

    This public specialist interface has no database/engine handle and never
    saves a candidate. Engine evidence is supplied by the caller's service.
    """
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
        return None

    if board.turn != player_color:
        return None

    forks = retain_functional_forks(board, find_geometric_forks(board))

    if not forks:
        return None

    # A played geometric-only shape must not suppress a real missed Fork.
    if any(
        fork["move_uci"]
        == uci_played
        for fork in forks
    ):
        return None

    before_quick = analyze_fen(fen_before, QUICK_PROFILE)

    actual_quick = analyze_fen(fen_after, QUICK_PROFILE)

    # Fork detector should not compete with
    # positions where the user already had
    # a forced mate.
    if (
        perspective_result(
            before_quick,
            player_color
        )["score_type"]
        == "mate"
    ):
        return None

    if is_winning_mate(
        actual_quick,
        player_color
    ):
        return None

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

        fork_quick = analyze_fen(fork["fen_after"], QUICK_PROFILE)

        # If the fork itself gives the user
        # a forced mate, the mate detector
        # owns that puzzle.
        if (
            perspective_result(
                fork_quick,
                player_color
            )["score_type"]
            == "mate"
        ):
            continue

        fork_value = comparable_score(
            fork_quick,
            player_color
        )

        gain = (
            fork_value
            - actual_quick_value
        )

        drop = (
            before_quick_value
            - fork_value
        )

        if gain < QUICK_MIN_GAIN_CP:
            continue

        if (
            drop
            > QUICK_MAX_DROP_FROM_BEST_CP
        ):
            continue

        promising.append(
            fork
        )

    if not promising:
        return None

    # ---------------------------------------------
    # DEEP VERIFICATION
    # ---------------------------------------------

    before_deep = analyze_fen(fen_before, VERIFY_PROFILE)

    actual_deep = analyze_fen(fen_after, VERIFY_PROFILE)

    if (
        perspective_result(
            before_deep,
            player_color
        )["score_type"]
        == "mate"
    ):
        return None

    if is_winning_mate(
        actual_deep,
        player_color
    ):
        return None

    before_value = comparable_score(
        before_deep,
        player_color
    )

    actual_value = comparable_score(
        actual_deep,
        player_color
    )

    verified = []

    for fork in promising:

        fork_deep = analyze_fen(fork["fen_after"], VERIFY_PROFILE)

        # Fork puzzles remain non-mating
        # tactical puzzles at the first move.
        if (
            perspective_result(
                fork_deep,
                player_color
            )["score_type"]
            == "mate"
        ):
            continue

        fork_value = comparable_score(
            fork_deep,
            player_color
        )

        gain = (
            fork_value
            - actual_value
        )

        drop = (
            before_value
            - fork_value
        )

        if gain < VERIFY_MIN_GAIN_CP:
            continue

        if (
            drop
            > VERIFY_MAX_DROP_FROM_BEST_CP
        ):
            continue

        realization = (
            verify_fork_realization(
                fen_before,
                fork,
                fork_deep
            )
        )

        if realization is None:
            continue

        # -----------------------------------------
        # NEW: POST-CONVERSION VERIFICATION
        # -----------------------------------------

        conversion_deep = analyze_fen(realization[
                "fen_after_conversion"
            ], VERIFY_PROFILE)

        valid_after_conversion, metrics = (
            post_conversion_is_valid(
                before_deep,
                actual_deep,
                conversion_deep,
                player_color
            )
        )

        if not valid_after_conversion:
            continue

        outcome = classify_fork_outcome(
            actual_deep,
            conversion_deep,
            player_color
        )

        verified.append({
            "fork":
                fork,

            "result":
                fork_deep,

            "conversion_result":
                conversion_deep,

            "gain":
                metrics["gain_vs_played"],

            "value":
                metrics["conversion_value"],

            "realization":
                realization,

            "outcome":
                outcome,
        })

    if not verified:
        return None

    # Choose the fork that leaves the user with
    # the best FINAL converted position.
    best = max(
        verified,
        key=lambda x: (
            x["value"],
            x["gain"]
        )
    )

    candidate = build_fork_candidate(
        san_played,
        best["fork"],
        best["realization"],
        before_deep,
        actual_deep,
        best["result"],
        best["conversion_result"],
        player_color
    )

    metadata = json.loads(candidate["metadata_json"])
    metadata["functional_threat_version"] = best["fork"]["functional_threat_version"]
    continuation = matching_tactical_continuation(fen_before, candidate["solution_line"],
        best["result"].get("principal_variation"))
    presentation_source = "tactic_verify_v1:matched_tactical_pv" if continuation else "tactic_verify_v1:post_conversion"
    if continuation is None:
        continuation = best["conversion_result"].get("principal_variation") or ""
    try:
        detail = build_exchange_presentation(fen_before, candidate["solution_line"],
            continuation, evidence_source=presentation_source)
    except ValueError:
        # Optional display evidence cannot turn an admitted tactic into an error.
        detail = build_exchange_presentation(fen_before, candidate["solution_line"], "",
            evidence_source="invalid_post_conversion_presentation_evidence")
    metadata["exchange_presentation"] = detail.to_dict()
    candidate["metadata_json"] = json.dumps(metadata, sort_keys=True)

    return {
        "candidate": candidate,
        "source":
            source,

        "source_game_id":
            source_game_id,

        "move_number":
            move_number,

        "color":
            color,

        "played":
            san_played,

        "fork":
            best["fork"]["move_san"],

        "fork_piece":
            best["fork"]["fork_piece"],

        "fork_from":
            best["fork"]["from_square"],

        "fork_to":
            best["fork"]["to_square"],

        "targets":
            best["fork"]["targets"],

        "realization":
            best["realization"],

        "outcome":
            best["outcome"],

        "before":
            format_eval(
                before_deep,
                player_color
            ),

        "played_eval":
            format_eval(
                actual_deep,
                player_color
            ),

        "fork_eval":
            format_eval(
                best["result"],
                player_color
            ),

        "conversion_eval":
            format_eval(
                best["conversion_result"],
                player_color
            ),
    }


def analyze_position(connection, engine, row, cache_stats):
    """Legacy full-scan entry point; retains its historical persistence."""
    result = analyze_single_move(row, lambda fen, profile: cache_result(connection, engine, fen, profile, cache_stats))
    if result is not None:
        save_fork_payload(connection, row[0], result["candidate"])
    return result


def print_candidate(result):
    print()
    print(
        "*** VERIFIED MISSED FORK ***"
    )

    print(
        f"{result['source']} "
        f"{result['source_game_id']}"
    )

    print(
        f"Move "
        f"{result['move_number']} "
        f"{result['color']}"
    )

    print(
        f"Played: "
        f"{result['played']}"
    )

    print(
        f"Fork: "
        f"{result['fork']}"
    )

    print(
        f"Forking piece: "
        f"{result['fork_piece']} "
        f"{result['fork_from']}"
        f"->{result['fork_to']}"
    )

    target_text = ", ".join(
        f"{target['piece']} "
        f"on {target['square']}"
        for target
        in result["targets"]
    )

    print(
        f"Targets: "
        f"{target_text}"
    )

    realization = (
        result[
            "realization"
        ]
    )

    print(
        f"Conversion: "
        f"{realization['conversion_move']} "
        f"captures "
        f"{realization['won_piece']} "
        f"on "
        f"{realization['won_square']}"
    )

    print(
        f"Outcome: "
        f"{outcome_label(result['outcome'])}"
    )

    played_eval = (
        result[
            "played_eval"
        ]
    )

    conversion_eval = (
        result[
            "conversion_eval"
        ]
    )

    if (
        played_eval["type"] == "mate"
        and played_eval["mate"] is not None
        and played_eval["mate"] < 0
    ):
        print(
            "Played position: forced mate loss"
        )

    elif played_eval["type"] == "cp":
        print(
            f"Played evaluation: "
            f"{played_eval['cp'] / 100:+.2f}"
        )

    if conversion_eval["type"] == "mate":
        print(
            f"After conversion: "
            f"mate {conversion_eval['mate']}"
        )

    else:
        print(
            f"After conversion: "
            f"{conversion_eval['cp'] / 100:+.2f}"
        )

    if (
        played_eval["type"] == "cp"
        and conversion_eval["type"] == "cp"
    ):
        gain = (
            conversion_eval["cp"]
            - played_eval["cp"]
        )

        print(
            f"Improvement vs played: "
            f"{gain / 100:.2f} pawns"
        )


def load_existing_v2_fork_candidates(
    connection
):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            tc.candidate_id,
            tc.move_id,
            tc.solution_move_uci,
            tc.metadata_json,

            m.color,
            m.fen_before,
            m.fen_after,
            m.san_played,

            g.source,
            g.source_game_id

        FROM tactic_candidates tc

        INNER JOIN moves m
            ON m.move_id = tc.move_id

        INNER JOIN games g
            ON g.game_id = m.game_id

        WHERE tc.tactic_type = ?
          AND tc.detector_version = 2
          AND tc.candidate_id > 0

        ORDER BY tc.candidate_id
    """, (
        TACTIC_TYPE,
    ))

    return cursor.fetchall()


def rebuild_candidate_positions(
    fen_before,
    fork_uci,
    realization
):
    """
    Rebuild the fork and conversion positions
    from an already-saved V2 candidate.
    """

    board = chess.Board(
        fen_before
    )

    fork_move = chess.Move.from_uci(
        fork_uci
    )

    if fork_move not in board.legal_moves:
        return None

    board.push(
        fork_move
    )

    fork_fen = board.fen()

    try:
        opponent_move = board.parse_san(
            realization[
                "opponent_reply"
            ]
        )

    except (
        KeyError,
        ValueError
    ):
        return None

    board.push(
        opponent_move
    )

    try:
        conversion_move = board.parse_san(
            realization[
                "conversion_move"
            ]
        )

    except (
        KeyError,
        ValueError
    ):
        return None

    board.push(
        conversion_move
    )

    return {
        "fork_fen":
            fork_fen,

        "conversion_fen":
            board.fen(),
    }



def create_pre_apply_backup(connection):
    """
    Create a full SQLite backup before changing any
    existing tactic candidate rows.
    """

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    backup_path = (
        "merlin_before_fork_post_conversion_apply_"
        f"{timestamp}.db"
    )

    backup_connection = sqlite3.connect(
        backup_path
    )

    try:
        connection.backup(
            backup_connection
        )

    finally:
        backup_connection.close()

    return backup_path


def rejection_reason(
    before_result,
    played_result,
    conversion_result,
    player_color,
    metrics
):
    if is_losing_mate(
        conversion_result,
        player_color
    ):
        return (
            "Post-conversion verification rejected "
            "this fork because the converted "
            "position still leaves the user in a "
            "forced mate loss."
        )

    if metrics is None:
        return (
            "Post-conversion verification rejected "
            "this fork because the final tactical "
            "result could not be validated."
        )

    gain = metrics["gain_vs_played"]
    drop = metrics["drop_from_best"]

    if gain < VERIFY_MIN_GAIN_CP:
        return (
            "Post-conversion verification rejected "
            "this fork because the final position "
            f"improves by only {gain / 100:.2f} "
            "pawns versus the move played, below "
            f"Merlin's {VERIFY_MIN_GAIN_CP / 100:.2f} "
            "pawn minimum."
        )

    if drop > VERIFY_MAX_DROP_FROM_BEST_CP:
        return (
            "Post-conversion verification rejected "
            "this fork because the final position "
            f"is {drop / 100:.2f} pawns worse than "
            "the original position, beyond Merlin's "
            f"{VERIFY_MAX_DROP_FROM_BEST_CP / 100:.2f} "
            "pawn tolerance."
        )

    return (
        "Post-conversion verification rejected "
        "this fork because it failed the final "
        "quality gate."
    )


def update_existing_candidate_in_place(
    connection,
    candidate_id,
    played_san,
    fork,
    realization,
    before_result,
    played_result,
    fork_result,
    conversion_result,
    player_color
):
    """
    Update a previously accepted V2 candidate while
    preserving candidate_id so training history keeps
    its permanent anchor.
    """

    cursor = connection.cursor()

    before_eval = format_eval(
        before_result,
        player_color
    )

    played_eval = format_eval(
        played_result,
        player_color
    )

    fork_eval = format_eval(
        fork_result,
        player_color
    )

    conversion_eval = format_eval(
        conversion_result,
        player_color
    )

    valid, metrics = post_conversion_is_valid(
        before_result,
        played_result,
        conversion_result,
        player_color
    )

    if not valid:
        reason = rejection_reason(
            before_result,
            played_result,
            conversion_result,
            player_color,
            metrics
        )

        try:
            existing_metadata = json.loads(
                fork.get("existing_metadata_json")
                or "{}"
            )

        except json.JSONDecodeError:
            existing_metadata = {}

        existing_metadata[
            "post_conversion_version"
        ] = 1

        existing_metadata[
            "post_conversion_valid"
        ] = False

        existing_metadata[
            "evaluation_after_conversion"
        ] = conversion_eval

        existing_metadata[
            "post_conversion_rejection_reason"
        ] = reason

        if metrics is not None:
            existing_metadata[
                "post_conversion_gain_score"
            ] = metrics["gain_vs_played"]

            existing_metadata[
                "post_conversion_drop_score"
            ] = metrics["drop_from_best"]

        cursor.execute("""
            UPDATE tactic_candidates
            SET
                candidate_status = 'rejected',
                notes = ?,
                metadata_json = ?
            WHERE candidate_id = ?
        """, (
            reason,
            json.dumps(
                existing_metadata,
                sort_keys=True
            ),
            candidate_id,
        ))

        return {
            "valid": False,
            "outcome": None,
            "reason": reason,
        }

    outcome = classify_fork_outcome(
        played_result,
        conversion_result,
        player_color
    )

    avoids_forced_mate = (
        outcome == "saving_fork"
    )

    gain_cp = None

    if (
        played_eval["type"] == "cp"
        and conversion_eval["type"] == "cp"
    ):
        gain_cp = (
            conversion_eval["cp"]
            - played_eval["cp"]
        )

    drop_from_best_cp = None

    if (
        before_eval["type"] == "cp"
        and conversion_eval["type"] == "cp"
    ):
        drop_from_best_cp = (
            before_eval["cp"]
            - conversion_eval["cp"]
        )

    solution_line = (
        f"{fork['move_san']} "
        f"{realization['opponent_reply']} "
        f"{realization['conversion_move']}"
    )

    metadata = {
        "detector":
            "fork_v2_post_conversion",

        "post_conversion_version":
            1,

        "post_conversion_valid":
            True,

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
            before_eval,

        "evaluation_after_played":
            played_eval,

        "evaluation_after_fork":
            fork_eval,

        "evaluation_after_conversion":
            conversion_eval,

        "gain_vs_played_cp":
            gain_cp,

        "drop_from_best_cp":
            drop_from_best_cp,

        "post_conversion_gain_score":
            metrics["gain_vs_played"],

        "post_conversion_drop_score":
            metrics["drop_from_best"],

        "outcome_classification":
            outcome,

        "avoids_forced_mate":
            avoids_forced_mate,

        "realization":
            realization,

        "quick_profile":
            QUICK_PROFILE,

        "verify_profile":
            VERIFY_PROFILE,
    }

    if avoids_forced_mate:
        confidence = 0.98

        notes = (
            "Verified saving fork avoids a "
            "forced mate and converts by "
            f"capturing the "
            f"{realization['won_piece']}."
        )

    else:
        gain_pawns = (
            gain_cp / 100
            if gain_cp is not None
            else 0
        )

        confidence = min(
            0.99,
            0.80
            + max(
                gain_pawns,
                0
            ) / 25
        )

        if outcome == "equalizing_fork":
            notes = (
                "Verified equalizing fork "
                "recovers an approximately "
                "equal position after conversion "
                "and captures the "
                f"{realization['won_piece']}."
            )

        elif outcome == "winning_fork":
            notes = (
                "Verified winning fork leaves "
                "the user with a winning "
                "advantage after conversion "
                "and captures the "
                f"{realization['won_piece']}."
            )

        else:
            notes = (
                "Verified fork improves "
                "the user's position by "
                f"{gain_pawns:.2f} pawns "
                "versus the move played, "
                "measured after conversion, "
                "and captures the "
                f"{realization['won_piece']}."
            )

    cursor.execute("""
        UPDATE tactic_candidates
        SET
            candidate_status = 'candidate',
            confidence = ?,
            solution_line = ?,
            notes = ?,
            metadata_json = ?
        WHERE candidate_id = ?
    """, (
        confidence,
        solution_line,
        notes,
        json.dumps(
            metadata,
            sort_keys=True
        ),
        candidate_id,
    ))

    return {
        "valid": True,
        "outcome": outcome,
        "reason": None,
    }


def apply_existing_candidates():
    """
    Apply the post-conversion safeguard to the
    EXISTING V2 fork candidates without deleting or
    recreating them.

    Candidate IDs stay unchanged so any existing
    training history remains anchored correctly.
    Candidate -1 is intentionally excluded by the
    existing candidate loader.
    """

    connection = sqlite3.connect(
        DB_NAME
    )

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    engine = None

    cache_stats = {
        "hits": 0,
        "misses": 0,
    }

    try:
        rows = load_existing_v2_fork_candidates(
            connection
        )

        print()
        print(
            "MERLIN FORK POST-CONVERSION APPLY"
        )
        print(
            "---------------------------------"
        )

        print(
            f"Existing V2 candidates: "
            f"{len(rows):,}"
        )

        if not rows:
            print(
                "No existing V2 fork candidates "
                "were found."
            )
            return

        backup_path = create_pre_apply_backup(
            connection
        )

        print()
        print(
            "Safety backup created:"
        )
        print(
            backup_path
        )

        print()
        print(
            "Starting Stockfish..."
        )

        engine = (
            chess.engine.SimpleEngine.popen_uci(
                STOCKFISH_PATH
            )
        )

        kept = 0
        rejected = 0
        rebuild_failed = 0

        outcomes = {
            "saving_fork": 0,
            "equalizing_fork": 0,
            "winning_fork": 0,
            "improving_fork": 0,
        }

        for index, row in enumerate(
            rows,
            start=1
        ):
            (
                candidate_id,
                move_id,
                fork_uci,
                metadata_json,
                color,
                fen_before,
                fen_after,
                san_played,
                source,
                source_game_id
            ) = row

            try:
                old_metadata = json.loads(
                    metadata_json
                    or "{}"
                )

            except json.JSONDecodeError:
                old_metadata = {}

            realization = old_metadata.get(
                "realization"
            )

            if not realization:
                rebuild_failed += 1
                continue

            positions = rebuild_candidate_positions(
                fen_before,
                fork_uci,
                realization
            )

            if positions is None:
                rebuild_failed += 1
                continue

            player_color = (
                chess.WHITE
                if color == "white"
                else chess.BLACK
            )

            before_result = cache_result(
                connection,
                engine,
                fen_before,
                VERIFY_PROFILE,
                cache_stats
            )

            played_result = cache_result(
                connection,
                engine,
                fen_after,
                VERIFY_PROFILE,
                cache_stats
            )

            fork_result = cache_result(
                connection,
                engine,
                positions["fork_fen"],
                VERIFY_PROFILE,
                cache_stats
            )

            conversion_result = cache_result(
                connection,
                engine,
                positions["conversion_fen"],
                VERIFY_PROFILE,
                cache_stats
            )

            fork = {
                "move_uci":
                    fork_uci,

                "move_san":
                    (
                        old_metadata.get(
                            "fork_move_san"
                        )
                        or None
                    ),

                "fork_piece":
                    old_metadata.get(
                        "fork_piece",
                        "unknown"
                    ),

                "from_square":
                    old_metadata.get(
                        "fork_from",
                        "?"
                    ),

                "to_square":
                    old_metadata.get(
                        "fork_to",
                        "?"
                    ),

                "targets":
                    old_metadata.get(
                        "targets",
                        []
                    ),

                "existing_metadata_json":
                    metadata_json,
            }

            if not fork["move_san"]:
                start_board = chess.Board(
                    fen_before
                )

                move = chess.Move.from_uci(
                    fork_uci
                )

                if move not in start_board.legal_moves:
                    rebuild_failed += 1
                    continue

                fork["move_san"] = (
                    start_board.san(
                        move
                    )
                )

            update_result = (
                update_existing_candidate_in_place(
                    connection,
                    candidate_id,
                    san_played,
                    fork,
                    realization,
                    before_result,
                    played_result,
                    fork_result,
                    conversion_result,
                    player_color
                )
            )

            if update_result["valid"]:
                kept += 1
                outcomes[
                    update_result["outcome"]
                ] += 1

            else:
                rejected += 1

            if (
                index % AUDIT_PROGRESS_EVERY
                == 0
                or index == len(rows)
            ):
                connection.commit()

                print(
                    f"Applied: "
                    f"{index:,} / "
                    f"{len(rows):,}"
                )

                print(
                    f"  Active: {kept:,}  "
                    f"Rejected: {rejected:,}  "
                    f"Rebuild failures: "
                    f"{rebuild_failed:,}"
                )

        connection.commit()

        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                candidate_status,
                COUNT(*)
            FROM tactic_candidates
            WHERE tactic_type = ?
              AND detector_version = 2
              AND candidate_id > 0
            GROUP BY candidate_status
            ORDER BY candidate_status
        """, (
            TACTIC_TYPE,
        ))

        final_statuses = cursor.fetchall()

        print()
        print(
            "APPLY RESULTS"
        )
        print(
            "-------------"
        )

        print(
            f"Active candidates: "
            f"{kept:,}"
        )

        print(
            f"Rejected candidates preserved: "
            f"{rejected:,}"
        )

        print(
            f"Could not rebuild: "
            f"{rebuild_failed:,}"
        )

        print()
        print(
            "OUTCOME CLASSIFICATIONS"
        )
        print(
            "-----------------------"
        )

        for key in (
            "winning_fork",
            "equalizing_fork",
            "saving_fork",
            "improving_fork"
        ):
            print(
                f"{outcome_label(key)}: "
                f"{outcomes[key]:,}"
            )

        print()
        print(
            "DATABASE STATUS COUNTS"
        )
        print(
            "----------------------"
        )

        for status, count in final_statuses:
            print(
                f"{status}: {count:,}"
            )

        print()
        print(
            f"Cache hits: "
            f"{cache_stats['hits']:,}"
        )

        print(
            f"Cache misses: "
            f"{cache_stats['misses']:,}"
        )

        print()
        print(
            "Existing candidate IDs were preserved."
        )

        print(
            "Developer candidate -1 was not touched."
        )

        print()
        print(
            "Post-conversion apply complete."
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        if engine is not None:
            engine.quit()

        connection.close()

def audit_existing_candidates():
    """
    READ-ONLY preview of the new safeguard.

    This intentionally does not delete, update,
    or replace any of the existing V2 fork
    candidates. It tells us how many would
    survive post-conversion verification before
    we decide to rebuild anything.
    """

    connection = sqlite3.connect(
        DB_NAME
    )

    engine = None

    cache_stats = {
        "hits": 0,
        "misses": 0,
    }

    try:
        rows = load_existing_v2_fork_candidates(
            connection
        )

        print()
        print(
            "MERLIN FORK POST-CONVERSION AUDIT"
        )
        print(
            "---------------------------------"
        )

        print(
            f"Existing V2 candidates: "
            f"{len(rows):,}"
        )

        print()
        print(
            "This audit is READ ONLY."
        )
        print(
            "No tactic candidate rows will "
            "be changed or deleted."
        )

        if not rows:
            return

        print()
        print(
            "Starting Stockfish..."
        )

        engine = (
            chess.engine.SimpleEngine.popen_uci(
                STOCKFISH_PATH
            )
        )

        kept = 0
        rejected = 0
        rebuild_failed = 0

        outcomes = {
            "saving_fork": 0,
            "equalizing_fork": 0,
            "winning_fork": 0,
            "improving_fork": 0,
        }

        examples_rejected = []

        for index, row in enumerate(
            rows,
            start=1
        ):
            (
                candidate_id,
                move_id,
                fork_uci,
                metadata_json,
                color,
                fen_before,
                fen_after,
                san_played,
                source,
                source_game_id
            ) = row

            try:
                metadata = json.loads(
                    metadata_json
                    or "{}"
                )

            except json.JSONDecodeError:
                metadata = {}

            realization = metadata.get(
                "realization"
            )

            if not realization:
                rebuild_failed += 1
                continue

            positions = rebuild_candidate_positions(
                fen_before,
                fork_uci,
                realization
            )

            if positions is None:
                rebuild_failed += 1
                continue

            player_color = (
                chess.WHITE
                if color == "white"
                else chess.BLACK
            )

            before_result = cache_result(
                connection,
                engine,
                fen_before,
                VERIFY_PROFILE,
                cache_stats
            )

            played_result = cache_result(
                connection,
                engine,
                fen_after,
                VERIFY_PROFILE,
                cache_stats
            )

            # This should normally be a cache hit
            # from the original V2 verification.
            cache_result(
                connection,
                engine,
                positions["fork_fen"],
                VERIFY_PROFILE,
                cache_stats
            )

            conversion_result = cache_result(
                connection,
                engine,
                positions["conversion_fen"],
                VERIFY_PROFILE,
                cache_stats
            )

            valid, metrics = post_conversion_is_valid(
                before_result,
                played_result,
                conversion_result,
                player_color
            )

            if valid:
                kept += 1

                outcome = classify_fork_outcome(
                    played_result,
                    conversion_result,
                    player_color
                )

                outcomes[outcome] += 1

            else:
                rejected += 1

                if len(examples_rejected) < 10:
                    examples_rejected.append({
                        "candidate_id":
                            candidate_id,

                        "source":
                            source,

                        "source_game_id":
                            source_game_id,

                        "played":
                            san_played,

                        "fork":
                            fork_uci,

                        "gain":
                            (
                                metrics[
                                    "gain_vs_played"
                                ]
                                if metrics
                                else None
                            ),

                        "drop":
                            (
                                metrics[
                                    "drop_from_best"
                                ]
                                if metrics
                                else None
                            ),
                    })

            if (
                index % AUDIT_PROGRESS_EVERY
                == 0
                or index == len(rows)
            ):
                print(
                    f"Audited: "
                    f"{index:,} / "
                    f"{len(rows):,}"
                )

        print()
        print(
            "AUDIT RESULTS"
        )
        print(
            "-------------"
        )

        print(
            f"Would keep: "
            f"{kept:,}"
        )

        print(
            f"Would reject: "
            f"{rejected:,}"
        )

        print(
            f"Could not rebuild: "
            f"{rebuild_failed:,}"
        )

        print()
        print(
            "OUTCOME CLASSIFICATIONS"
        )
        print(
            "-----------------------"
        )

        for key in (
            "winning_fork",
            "equalizing_fork",
            "saving_fork",
            "improving_fork"
        ):
            print(
                f"{outcome_label(key)}: "
                f"{outcomes[key]:,}"
            )

        print()
        print(
            f"Cache hits: "
            f"{cache_stats['hits']:,}"
        )

        print(
            f"Cache misses: "
            f"{cache_stats['misses']:,}"
        )

        if examples_rejected:
            print()
            print(
                "SAMPLE CANDIDATES THE NEW "
                "CHECK WOULD REJECT"
            )
            print(
                "--------------------------"
            )

            for example in examples_rejected:
                print()
                print(
                    f"Candidate "
                    f"{example['candidate_id']} "
                    f"{example['source']} "
                    f"{example['source_game_id']}"
                )

                print(
                    f"Played: "
                    f"{example['played']}"
                )

                print(
                    f"Fork UCI: "
                    f"{example['fork']}"
                )

                if example["gain"] is not None:
                    print(
                        f"Post-conversion gain: "
                        f"{example['gain'] / 100:.2f} "
                        "pawns"
                    )

                if example["drop"] is not None:
                    print(
                        f"Post-conversion drop "
                        f"from original: "
                        f"{example['drop'] / 100:.2f} "
                        "pawns"
                    )

        print()
        print(
            "Audit complete. Database candidate "
            "rows were not changed."
        )

    finally:
        if engine is not None:
            engine.quit()

        connection.close()


def main():
    args = sys.argv[1:]

    if "--audit-existing" in args:
        audit_existing_candidates()
        return

    if "--apply-existing" in args:
        apply_existing_candidates()
        return

    if "--full-scan" not in args:
        print()
        print("MERLIN FORK ANALYZER V2")
        print("-----------------------")
        print()
        print("No action selected.")
        print()
        print("Safe commands:")
        print("  python analyze_forks_v2.py --audit-existing")
        print("  python analyze_forks_v2.py --apply-existing")
        print()
        print("The legacy full scan is protected because it can")
        print("rebuild fork candidates. Use --full-scan only")
        print("when you intentionally want that behavior.")
        return

    connection = sqlite3.connect(
        DB_NAME
    )

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    ensure_analysis_run_columns(
        connection
    )

    engine = None

    user_id = get_user_id(
        connection
    )

    total_moves = (
        get_total_user_moves(
            connection
        )
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
            "Resuming Fork Analyzer V2."
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
            "Created new Fork Analyzer V2 run."
        )

        print(
            "Old V1 fork candidates cleared."
        )

        print(
            "Engine cache preserved."
        )

    cache_stats = {
        "hits": 0,
        "misses": 0,
    }

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
        print("MERLIN FORK ANALYZER V2")
        print("-----------------------")

        print(
            f"Total user moves: "
            f"{total_moves:,}"
        )

        print(
            f"Already scanned: "
            f"{moves_scanned:,}"
        )

        print()
        print(
            "Strict rule + post-conversion check:"
        )

        print(
            "The same forking piece must "
            "survive the opponent's best reply "
            "and then capture one of the "
            "original fork targets, and the "
            "converted position must still pass "
            "the engine quality gate."
        )

        print()

        processed_since_save = 0

        while True:

            rows = load_batch(
                connection,
                last_game_id,
                last_ply_number
            )

            if not rows:
                break

            for row in rows:

                # IMPORTANT:
                #
                # We do NOT advance the resume
                # cursor until this entire row
                # finishes successfully.
                #
                # If Ctrl+C happens inside
                # Stockfish, this position will
                # be safely retried later.

                result = analyze_position(
                    connection,
                    engine,
                    row,
                    cache_stats
                )

                if result is not None:

                    candidates_found += 1

                    print_candidate(
                        result
                    )

                # Row is now fully processed.
                last_game_id = row[1]
                last_ply_number = row[2]

                moves_scanned += 1
                processed_since_save += 1

                if (
                    processed_since_save
                    >= BATCH_SIZE
                ):

                    update_run(
                        connection,
                        run_id,
                        "running",
                        moves_scanned,
                        candidates_found,
                        last_game_id,
                        last_ply_number
                    )

                    processed_since_save = 0

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
                        f"Verified missed forks: "
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

        print()
        print(
            "FORK ANALYSIS V2 COMPLETE"
        )

        print(
            "-------------------------"
        )

        print(
            f"User moves scanned: "
            f"{moves_scanned:,}"
        )

        print(
            f"Verified missed forks: "
            f"{candidates_found:,}"
        )

        print(
            f"Cache hits this session: "
            f"{cache_stats['hits']:,}"
        )

        print(
            f"Cache misses this session: "
            f"{cache_stats['misses']:,}"
        )

    except KeyboardInterrupt:

        print()
        print()

        print(
            "Fork Analyzer V2 paused."
        )

        print(
            "The interrupted position "
            "will be retried on resume."
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

