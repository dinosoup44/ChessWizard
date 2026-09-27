import sqlite3
import chess
from collections import defaultdict


DB_NAME = "merlin.db"

# A new candidate must be reasonably close to the
# most recent candidate already in an episode.
MAX_LINK_PLY_GAP = 8

# Also prevent transitive chains from growing into
# extremely long "episodes."
MAX_EPISODE_SPAN = 12

# Reference values from our previous reports.
# These are DISPLAY ONLY and do not affect grouping.
V1_REFERENCE_EPISODES = 397
V2_REFERENCE_EPISODES = 379


def square_name(square):
    if square is None:
        return None

    return chess.square_name(square)


def piece_name(piece):
    if piece is None:
        return None

    names = {
        chess.PAWN: "pawn",
        chess.KNIGHT: "knight",
        chess.BISHOP: "bishop",
        chess.ROOK: "rook",
        chess.QUEEN: "queen",
        chess.KING: "king",
    }

    return names.get(
        piece.piece_type,
        "unknown"
    )


def load_candidates(connection):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            tc.candidate_id,
            tc.move_id,
            tc.solution_move_san,
            tc.solution_move_uci,
            tc.solution_line,
            tc.detector_version,

            m.game_id,
            m.ply_number,
            m.move_number,
            m.color,
            m.san_played,
            m.uci_played,
            m.fen_before,

            g.source,
            g.source_game_id,
            g.white_username,
            g.black_username,
            g.result,
            g.time_control

        FROM tactic_candidates tc

        INNER JOIN moves m
            ON m.move_id = tc.move_id

        INNER JOIN games g
            ON g.game_id = m.game_id

        WHERE tc.tactic_type = 'missed_mate'

        ORDER BY
            m.game_id,
            m.ply_number
    """)

    return cursor.fetchall()


def parse_solution_line(fen, solution_line):
    result = {
        "valid": False,

        "first_move_uci": None,
        "first_from": None,
        "first_to": None,
        "first_piece": None,

        "mate_move_uci": None,
        "mate_from": None,
        "mate_to": None,
        "mate_piece": None,

        "opponent_king_start": None,
        "opponent_king_end": None,

        "plies_to_mate": None,
    }

    if not fen:
        return result

    try:
        board = chess.Board(fen)
    except ValueError:
        return result

    player_color = board.turn
    opponent_color = not player_color

    result["opponent_king_start"] = square_name(
        board.king(opponent_color)
    )

    if not solution_line:
        return result

    tokens = solution_line.split()

    for index, san in enumerate(tokens):
        try:
            move = board.parse_san(san)
        except ValueError:
            return result

        moving_piece = board.piece_at(
            move.from_square
        )

        if index == 0:
            result["first_move_uci"] = (
                move.uci()
            )

            result["first_from"] = square_name(
                move.from_square
            )

            result["first_to"] = square_name(
                move.to_square
            )

            result["first_piece"] = piece_name(
                moving_piece
            )

        board.push(move)

        if board.is_checkmate():
            result["mate_move_uci"] = (
                move.uci()
            )

            result["mate_from"] = square_name(
                move.from_square
            )

            result["mate_to"] = square_name(
                move.to_square
            )

            result["mate_piece"] = piece_name(
                moving_piece
            )

            result["opponent_king_end"] = (
                square_name(
                    board.king(
                        opponent_color
                    )
                )
            )

            result["plies_to_mate"] = (
                index + 1
            )

            result["valid"] = True

            return result

    return result


def build_candidate(row):
    (
        candidate_id,
        move_id,
        solution_move_san,
        solution_move_uci,
        solution_line,
        detector_version,

        game_id,
        ply_number,
        move_number,
        color,
        san_played,
        uci_played,
        fen_before,

        source,
        source_game_id,
        white_username,
        black_username,
        result,
        time_control
    ) = row

    fingerprint = parse_solution_line(
        fen_before,
        solution_line
    )

    return {
        "candidate_id": candidate_id,
        "move_id": move_id,

        "game_id": game_id,
        "ply_number": ply_number,
        "move_number": move_number,

        "color": color,

        "played_san": san_played,
        "played_uci": uci_played,

        "solution_move_san":
            solution_move_san,

        "solution_move_uci":
            solution_move_uci,

        "solution_line":
            solution_line,

        "detector_version":
            detector_version,

        "source":
            source,

        "source_game_id":
            source_game_id,

        "white_username":
            white_username,

        "black_username":
            black_username,

        "result":
            result,

        "time_control":
            time_control,

        "fingerprint":
            fingerprint,
    }


def strong_tactical_match(a, b):
    """
    V3 deliberately requires a STRONG tactical anchor.

    Weak similarities such as:
        same king square
        same attacking piece type
        same line length

    are NOT enough anymore.

    Returns:

        matched, score, reason
    """

    fa = a["fingerprint"]
    fb = b["fingerprint"]

    # --------------------------------------------------
    # ANCHOR 1
    # Exact same first winning move.
    #
    # Example:
    #   Nc5#
    #   Nc5#
    # --------------------------------------------------

    if (
        fa["first_move_uci"]
        and fa["first_move_uci"]
        == fb["first_move_uci"]
    ):
        return (
            True,
            100,
            "exact same first winning move"
        )

    # --------------------------------------------------
    # ANCHOR 2
    # Exact same final mating move.
    #
    # The attack may begin differently but still
    # resolve through exactly the same mating move.
    # --------------------------------------------------

    if (
        fa["mate_move_uci"]
        and fa["mate_move_uci"]
        == fb["mate_move_uci"]
    ):
        return (
            True,
            90,
            "exact same mating move"
        )

    # --------------------------------------------------
    # ANCHOR 3
    # Same tactical geometry.
    #
    # Example:
    #
    #   queen -> c7
    #   queen mates -> c7
    #
    # Even if the queen started from a different square,
    # this can represent the same recurring mating idea.
    #
    # We require BOTH the first attack pattern AND
    # final mating pattern to agree.
    # --------------------------------------------------

    same_first_pattern = (
        fa["first_piece"]
        and fb["first_piece"]
        and fa["first_piece"]
        == fb["first_piece"]
        and fa["first_to"]
        and fa["first_to"]
        == fb["first_to"]
    )

    same_mate_pattern = (
        fa["mate_piece"]
        and fb["mate_piece"]
        and fa["mate_piece"]
        == fb["mate_piece"]
        and fa["mate_to"]
        and fa["mate_to"]
        == fb["mate_to"]
    )

    if (
        same_first_pattern
        and same_mate_pattern
    ):
        return (
            True,
            80,
            "same attack and mating geometry"
        )

    return (
        False,
        0,
        None
    )


def can_join_episode(
    candidate,
    episode
):
    """
    V3 grouping rule:

    1. Same game.
    2. Close to the last candidate.
    3. Episode cannot become too long.
    4. Candidate must strongly match the EARLIEST
       candidate in the episode.

    Matching against the earliest candidate is
    intentional.

    It prevents:

        A matches B
        B matches C

    from automatically grouping A + B + C when
    A and C are actually different tactical ideas.
    """

    anchor = episode[0]
    last = episode[-1]

    if (
        candidate["game_id"]
        != anchor["game_id"]
    ):
        return (
            False,
            0,
            None
        )

    link_gap = (
        candidate["ply_number"]
        - last["ply_number"]
    )

    if link_gap > MAX_LINK_PLY_GAP:
        return (
            False,
            0,
            None
        )

    episode_span = (
        candidate["ply_number"]
        - anchor["ply_number"]
    )

    if episode_span > MAX_EPISODE_SPAN:
        return (
            False,
            0,
            None
        )

    return strong_tactical_match(
        anchor,
        candidate
    )


def build_episodes(candidates):
    by_game = defaultdict(list)

    for candidate in candidates:
        by_game[
            candidate["game_id"]
        ].append(candidate)

    episodes = []

    for game_candidates in (
        by_game.values()
    ):
        game_candidates.sort(
            key=lambda x:
            x["ply_number"]
        )

        game_episodes = []

        for candidate in game_candidates:

            best_episode = None
            best_score = -1
            best_reason = None

            for episode in game_episodes:

                (
                    matched,
                    score,
                    reason
                ) = can_join_episode(
                    candidate,
                    episode["candidates"]
                )

                if (
                    matched
                    and score > best_score
                ):
                    best_episode = episode
                    best_score = score
                    best_reason = reason

            if best_episode is None:
                game_episodes.append({
                    "candidates": [
                        candidate
                    ],
                    "match_reasons": {},
                })

            else:
                best_episode[
                    "candidates"
                ].append(
                    candidate
                )

                best_episode[
                    "match_reasons"
                ][
                    candidate[
                        "candidate_id"
                    ]
                ] = best_reason

        episodes.extend(
            game_episodes
        )

    episodes.sort(
        key=lambda episode: (
            episode[
                "candidates"
            ][0]["game_id"],

            episode[
                "candidates"
            ][0]["ply_number"]
        )
    )

    return episodes


def print_fingerprint(candidate):
    fp = candidate["fingerprint"]

    print(
        "    Fingerprint:"
    )

    print(
        f"      First attack: "
        f"{fp['first_piece']} "
        f"{fp['first_from']}"
        f"->{fp['first_to']}"
    )

    print(
        f"      Mate move: "
        f"{fp['mate_piece']} "
        f"{fp['mate_from']}"
        f"->{fp['mate_to']}"
    )

    print(
        f"      Enemy king: "
        f"{fp['opponent_king_start']}"
        f" -> "
        f"{fp['opponent_king_end']}"
    )

    print(
        f"      PV plies to mate: "
        f"{fp['plies_to_mate']}"
    )


def print_candidate(
    candidate,
    match_reason=None
):
    print(
        f"  Move "
        f"{candidate['move_number']} "
        f"{candidate['color']}: "
        f"played "
        f"{candidate['played_san']}"
    )

    print(
        f"    Best: "
        f"{candidate['solution_move_san']}"
    )

    print(
        f"    Line: "
        f"{candidate['solution_line']}"
    )

    if match_reason:
        print(
            f"    Grouped because: "
            f"{match_reason}"
        )

    print_fingerprint(
        candidate
    )


def main():
    connection = sqlite3.connect(
        DB_NAME
    )

    rows = load_candidates(
        connection
    )

    connection.close()

    if not rows:
        print(
            "No missed-mate candidates found."
        )
        return

    candidates = [
        build_candidate(row)
        for row in rows
    ]

    episodes = build_episodes(
        candidates
    )

    raw_count = len(
        candidates
    )

    episode_count = len(
        episodes
    )

    repeated_count = (
        raw_count
        - episode_count
    )

    games = {
        candidate["game_id"]
        for candidate in candidates
    }

    multi_candidate_episodes = [
        episode
        for episode in episodes
        if len(
            episode["candidates"]
        ) > 1
    ]

    parsed_lines = sum(
        1
        for candidate in candidates
        if candidate[
            "fingerprint"
        ]["valid"]
    )

    print()
    print(
        "MERLIN MISSED-MATE EPISODE ANALYSIS V3"
    )

    print(
        "--------------------------------------"
    )

    print(
        f"Raw candidates: "
        f"{raw_count}"
    )

    print(
        f"Games containing candidates: "
        f"{len(games)}"
    )

    print()

    print(
        "EPISODE COMPARISON"
    )

    print(
        "------------------"
    )

    print(
        f"V1 heuristic episodes: "
        f"{V1_REFERENCE_EPISODES}"
    )

    print(
        f"V2 tactical episodes: "
        f"{V2_REFERENCE_EPISODES}"
    )

    print(
        f"V3 strict tactical episodes: "
        f"{episode_count}"
    )

    print(
        f"V3 repeated detections: "
        f"{repeated_count}"
    )

    print(
        f"V3 multi-candidate episodes: "
        f"{len(multi_candidate_episodes)}"
    )

    print(
        f"Solution lines validated: "
        f"{parsed_lines} / {raw_count}"
    )

    print()

    if (
        V2_REFERENCE_EPISODES
        < episode_count
        < V1_REFERENCE_EPISODES
    ):
        print(
            "V3 landed between V1 and V2."
        )

        print(
            "That is the result we expected "
            "from a stricter tactical rule."
        )

    elif (
        episode_count
        == V1_REFERENCE_EPISODES
    ):
        print(
            "V3 matches the V1 episode count."
        )

    elif (
        episode_count
        == V2_REFERENCE_EPISODES
    ):
        print(
            "V3 matches the V2 episode count."
        )

    else:
        print(
            "V3 produced a different grouping "
            "range than expected."
        )

        print(
            "We should inspect the sample "
            "episodes before making anything "
            "permanent."
        )

    print()
    print(
        "LARGEST V3 EPISODES"
    )

    print(
        "-------------------"
    )

    largest = sorted(
        multi_candidate_episodes,
        key=lambda episode:
        len(
            episode["candidates"]
        ),
        reverse=True
    )

    for episode in largest[:15]:

        members = (
            episode["candidates"]
        )

        reasons = (
            episode[
                "match_reasons"
            ]
        )

        first = members[0]

        print()

        print(
            f"{first['source']} "
            f"{first['source_game_id']}"
        )

        print(
            f"{first['white_username']} "
            f"vs "
            f"{first['black_username']}"
        )

        print(
            f"Grouped detections: "
            f"{len(members)}"
        )

        print(
            f"Episode anchor: "
            f"Move "
            f"{first['move_number']} "
            f"{first['color']}"
        )

        for index, candidate in (
            enumerate(members)
        ):
            if index == 0:
                reason = (
                    "episode anchor"
                )

            else:
                reason = reasons.get(
                    candidate[
                        "candidate_id"
                    ]
                )

            print_candidate(
                candidate,
                reason
            )

    print()
    print(
        "SAMPLE SINGLE CANDIDATES"
    )

    print(
        "------------------------"
    )

    singles = [
        episode[
            "candidates"
        ][0]
        for episode in episodes
        if len(
            episode["candidates"]
        ) == 1
    ]

    for candidate in singles[:10]:

        print()

        print(
            f"{candidate['source']} "
            f"{candidate['source_game_id']}"
        )

        print_candidate(
            candidate
        )

    print()
    print(
        "NOTE"
    )

    print(
        "----"
    )

    print(
        "V3 requires a strong tactical "
        "anchor before candidates can merge."
    )

    print(
        "Weak similarities such as king "
        "location alone cannot create an "
        "episode."
    )

    print(
        "This script only reads merlin.db."
    )

    print(
        "Nothing was inserted, updated, "
        "or deleted."
    )


if __name__ == "__main__":
    main()