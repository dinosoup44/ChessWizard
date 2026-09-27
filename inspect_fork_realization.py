import sqlite3
import json
import chess
from collections import Counter, defaultdict


DB_NAME = "merlin.db"


PIECE_TYPES = {
    "pawn": chess.PAWN,
    "knight": chess.KNIGHT,
    "bishop": chess.BISHOP,
    "rook": chess.ROOK,
    "queen": chess.QUEEN,
    "king": chess.KING,
}


def get_capture_square(board, move):
    """
    Return the square containing the captured piece
    BEFORE the move is pushed.
    """

    if not board.is_capture(move):
        return None

    if board.is_en_passant(move):

        if board.turn == chess.WHITE:
            return move.to_square - 8

        return move.to_square + 8

    return move.to_square


def load_candidates(connection):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            tc.candidate_id,
            tc.solution_move_uci,
            tc.solution_move_san,
            tc.solution_line,
            tc.metadata_json,

            m.fen_before,
            m.move_number,
            m.color,
            m.san_played,

            g.source,
            g.source_game_id,
            g.white_username,
            g.black_username

        FROM tactic_candidates tc

        INNER JOIN moves m
            ON m.move_id = tc.move_id

        INNER JOIN games g
            ON g.game_id = m.game_id

        WHERE tc.tactic_type = 'missed_fork'

        ORDER BY tc.candidate_id
    """)

    return cursor.fetchall()


def build_targets(metadata):
    targets = []

    for item in metadata.get(
        "targets",
        []
    ):
        square_name = item.get(
            "square"
        )

        piece_name = item.get(
            "piece"
        )

        if not square_name:
            continue

        if piece_name not in PIECE_TYPES:
            continue

        try:
            square = chess.parse_square(
                square_name
            )

        except ValueError:
            continue

        targets.append({
            "square": square,
            "piece_name": piece_name,
            "piece_type":
                PIECE_TYPES[piece_name],
        })

    return targets


def move_target_if_needed(
    targets,
    move
):
    """
    If the opponent saves one of the forked
    pieces, follow that target to its new square.
    """

    for target in targets:

        if (
            target["square"]
            == move.from_square
        ):
            target["square"] = (
                move.to_square
            )

            break


def captured_target(
    board,
    move,
    targets
):
    capture_square = (
        get_capture_square(
            board,
            move
        )
    )

    if capture_square is None:
        return None

    captured_piece = board.piece_at(
        capture_square
    )

    if captured_piece is None:
        return None

    for target in targets:

        if (
            target["square"]
            == capture_square

            and target["piece_type"]
            == captured_piece.piece_type
        ):
            return target

    return None


def classify_candidate(
    fen_before,
    solution_move_uci,
    solution_line,
    metadata
):
    """
    Strict V1 fork-realization test.

    A high-confidence fork should normally look like:

        fork move
        opponent responds / saves one target
        forking piece captures another target

    This deliberately favors PRECISION over recall.
    """

    result = {
        "classification": None,
        "detail": None,
    }

    try:
        board = chess.Board(
            fen_before
        )

    except ValueError:
        result["classification"] = (
            "invalid_fen"
        )

        return result

    if not solution_line:
        result["classification"] = (
            "missing_line"
        )

        return result

    tokens = solution_line.split()

    if not tokens:
        result["classification"] = (
            "missing_line"
        )

        return result

    targets = build_targets(
        metadata
    )

    if len(targets) < 2:
        result["classification"] = (
            "invalid_targets"
        )

        return result

    # -------------------------------------------------
    # FORK MOVE
    # -------------------------------------------------

    try:
        fork_move = board.parse_san(
            tokens[0]
        )

    except ValueError:
        result["classification"] = (
            "parse_error"
        )

        result["detail"] = (
            "Could not parse fork move."
        )

        return result

    if (
        solution_move_uci
        and fork_move.uci()
        != solution_move_uci
    ):
        result["classification"] = (
            "first_move_mismatch"
        )

        return result

    fork_piece_before = (
        board.piece_at(
            fork_move.from_square
        )
    )

    if fork_piece_before is None:
        result["classification"] = (
            "missing_fork_piece"
        )

        return result

    fork_piece_type = (
        fork_piece_before.piece_type
    )

    fork_color = (
        fork_piece_before.color
    )

    board.push(
        fork_move
    )

    fork_square = (
        fork_move.to_square
    )

    # -------------------------------------------------
    # NO OPPONENT RESPONSE IN PV
    # -------------------------------------------------

    if len(tokens) < 2:
        result["classification"] = (
            "no_opponent_reply"
        )

        return result

    # -------------------------------------------------
    # OPPONENT RESPONSE
    # -------------------------------------------------

    try:
        opponent_move = board.parse_san(
            tokens[1]
        )

    except ValueError:
        result["classification"] = (
            "parse_error"
        )

        result["detail"] = (
            "Could not parse opponent reply."
        )

        return result

    captured_square = (
        get_capture_square(
            board,
            opponent_move
        )
    )

    # If the fork piece is immediately taken,
    # this is not a high-confidence fork for V1.
    if captured_square == fork_square:

        result["classification"] = (
            "fork_piece_captured_immediately"
        )

        result["detail"] = tokens[1]

        return result

    move_target_if_needed(
        targets,
        opponent_move
    )

    board.push(
        opponent_move
    )

    fork_piece_after_reply = (
        board.piece_at(
            fork_square
        )
    )

    if (
        fork_piece_after_reply is None

        or fork_piece_after_reply.color
        != fork_color

        or fork_piece_after_reply.piece_type
        != fork_piece_type
    ):
        result["classification"] = (
            "fork_piece_gone"
        )

        return result

    # -------------------------------------------------
    # USER'S NEXT MOVE
    # -------------------------------------------------

    if len(tokens) < 3:
        result["classification"] = (
            "no_conversion_move"
        )

        return result

    try:
        conversion_move = (
            board.parse_san(
                tokens[2]
            )
        )

    except ValueError:
        result["classification"] = (
            "parse_error"
        )

        result["detail"] = (
            "Could not parse conversion move."
        )

        return result

    # High-confidence classic fork:
    # the SAME piece now takes one of the
    # original fork targets.
    if (
        conversion_move.from_square
        == fork_square
    ):
        target = captured_target(
            board,
            conversion_move,
            targets
        )

        if target is not None:

            result["classification"] = (
                "converted_next_move"
            )

            result["detail"] = (
                f"{tokens[2]} wins "
                f"{target['piece_name']} "
                f"on "
                f"{chess.square_name(target['square'])}"
            )

            return result

        if board.is_capture(
            conversion_move
        ):
            result["classification"] = (
                "fork_piece_captures_other"
            )

            result["detail"] = (
                tokens[2]
            )

            return result

        result["classification"] = (
            "fork_piece_moves_without_conversion"
        )

        result["detail"] = (
            tokens[2]
        )

        return result

    # The engine chose another piece instead of
    # cashing in the fork immediately.
    #
    # This may still be a good tactic, but it is
    # not strong enough evidence for our strict
    # Fork V2 detector.
    result["classification"] = (
        "other_move_before_conversion"
    )

    result["detail"] = (
        tokens[2]
    )

    return result


def contains_mate_eval(metadata):
    evaluations = [
        metadata.get(
            "evaluation_before"
        ),
        metadata.get(
            "evaluation_after_played"
        ),
        metadata.get(
            "evaluation_after_fork"
        ),
    ]

    for evaluation in evaluations:

        if not isinstance(
            evaluation,
            dict
        ):
            continue

        if evaluation.get(
            "type"
        ) == "mate":
            return True

    return False


def main():
    connection = sqlite3.connect(
        DB_NAME
    )

    try:
        rows = load_candidates(
            connection
        )

    finally:
        connection.close()

    print()
    print(
        "MERLIN FORK REALIZATION INSPECTOR"
    )

    print(
        "---------------------------------"
    )

    print(
        f"Fork candidates inspected: "
        f"{len(rows):,}"
    )

    classifications = Counter()

    samples = defaultdict(
        list
    )

    mate_eval_count = 0

    for row in rows:
        (
            candidate_id,
            solution_move_uci,
            solution_move_san,
            solution_line,
            metadata_json,

            fen_before,
            move_number,
            color,
            played_san,

            source,
            source_game_id,
            white_username,
            black_username
        ) = row

        try:
            metadata = json.loads(
                metadata_json
            )

        except Exception:
            metadata = {}

        if contains_mate_eval(
            metadata
        ):
            mate_eval_count += 1

        result = classify_candidate(
            fen_before,
            solution_move_uci,
            solution_line,
            metadata
        )

        classification = result[
            "classification"
        ]

        classifications[
            classification
        ] += 1

        if len(
            samples[classification]
        ) < 6:

            samples[
                classification
            ].append({
                "candidate_id":
                    candidate_id,

                "source":
                    source,

                "source_game_id":
                    source_game_id,

                "players":
                    (
                        f"{white_username} "
                        f"vs "
                        f"{black_username}"
                    ),

                "move":
                    (
                        f"{move_number} "
                        f"{color}"
                    ),

                "played":
                    played_san,

                "fork":
                    solution_move_san,

                "line":
                    solution_line,

                "detail":
                    result[
                        "detail"
                    ],
            })

    print()
    print(
        "REALIZATION RESULTS"
    )

    print(
        "-------------------"
    )

    for classification, count in (
        classifications.most_common()
    ):
        print(
            f"{classification}: "
            f"{count:,}"
        )

    converted = classifications.get(
        "converted_next_move",
        0
    )

    rejected = (
        len(rows)
        - converted
    )

    print()
    print(
        "STRICT FORK V2 ESTIMATE"
    )

    print(
        "-----------------------"
    )

    print(
        f"High-confidence converted forks: "
        f"{converted:,}"
    )

    print(
        f"Candidates rejected / uncertain: "
        f"{rejected:,}"
    )

    if rows:
        percent = (
            converted
            / len(rows)
            * 100
        )

        print(
            f"Strict survival rate: "
            f"{percent:.1f}%"
        )

    print()
    print(
        "MATE-EQUIVALENT COMPARISONS"
    )

    print(
        "---------------------------"
    )

    print(
        f"Candidates involving a mate "
        f"evaluation: "
        f"{mate_eval_count:,}"
    )

    print(
        "These should NOT be displayed "
        "as a pawn-value improvement."
    )

    # -------------------------------------------------
    # SAMPLE GROUPS
    # -------------------------------------------------

    interesting_groups = [
        "converted_next_move",

        "fork_piece_captured_immediately",

        "fork_piece_moves_without_conversion",

        "other_move_before_conversion",

        "fork_piece_captures_other",
    ]

    for classification in (
        interesting_groups
    ):
        group = samples.get(
            classification,
            []
        )

        if not group:
            continue

        print()
        print(
            classification.upper()
        )

        print(
            "-" * len(
                classification
            )
        )

        for item in group:

            print()

            print(
                f"Candidate "
                f"{item['candidate_id']}"
            )

            print(
                f"{item['source']} "
                f"{item['source_game_id']}"
            )

            print(
                item["players"]
            )

            print(
                f"Move: "
                f"{item['move']}"
            )

            print(
                f"Played: "
                f"{item['played']}"
            )

            print(
                f"Fork: "
                f"{item['fork']}"
            )

            print(
                f"PV: "
                f"{item['line']}"
            )

            print(
                f"Classification detail: "
                f"{item['detail']}"
            )

    print()
    print("NOTE")
    print("----")

    print(
        "This test uses existing saved "
        "Stockfish lines only."
    )

    print(
        "Stockfish was NOT started."
    )

    print(
        "Nothing was changed in merlin.db."
    )


if __name__ == "__main__":
    main()