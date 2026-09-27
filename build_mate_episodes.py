import sqlite3
import chess
from collections import defaultdict


DB_NAME = "merlin.db"

TACTIC_TYPE = "missed_mate"

# Version of the EPISODE grouping algorithm.
EPISODE_DETECTOR_VERSION = 3

# Must match the V3 test script.
MAX_LINK_PLY_GAP = 8
MAX_EPISODE_SPAN = 12


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

        WHERE tc.tactic_type = ?

        ORDER BY
            m.game_id,
            m.ply_number
    """, (TACTIC_TYPE,))

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

        "candidate_detector_version":
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
    Requires a strong tactical anchor.

    Weak similarities like:
        same king square
        same attacking piece type
        same line length

    are not enough by themselves.
    """

    fa = a["fingerprint"]
    fb = b["fingerprint"]

    # Exact same first winning move.
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

    # Exact same final mating move.
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

    # Same attacking-piece/destination geometry.
    same_first_pattern = (
        fa["first_piece"]
        and fb["first_piece"]
        and fa["first_piece"]
        == fb["first_piece"]
        and fa["first_to"]
        and fa["first_to"]
        == fb["first_to"]
    )

    # Same mating-piece/destination geometry.
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


def can_join_episode(candidate, episode):
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

    for game_candidates in by_game.values():

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

                    "match_reasons": {
                        candidate[
                            "candidate_id"
                        ]: "episode anchor"
                    },
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


def validate_candidates(candidates):
    invalid = [
        candidate
        for candidate in candidates
        if not candidate[
            "fingerprint"
        ]["valid"]
    ]

    if invalid:
        print()
        print(
            "ERROR: Some solution lines "
            "could not be validated."
        )

        for candidate in invalid[:10]:
            print(
                f"Candidate "
                f"{candidate['candidate_id']} "
                f"| game "
                f"{candidate['source_game_id']}"
            )

        raise RuntimeError(
            "Episode build stopped because "
            "candidate validation failed."
        )


def clear_existing_mate_episodes(
    connection
):
    """
    Remove only generated missed-mate episodes.

    Raw tactic_candidates are NEVER touched.
    """

    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM tactic_episode_members
        WHERE episode_id IN (
            SELECT episode_id
            FROM tactic_episodes
            WHERE tactic_type = ?
        )
    """, (TACTIC_TYPE,))

    cursor.execute("""
        DELETE FROM tactic_episodes
        WHERE tactic_type = ?
    """, (TACTIC_TYPE,))


def save_episodes(
    connection,
    episodes
):
    cursor = connection.cursor()

    total_members = 0

    for episode in episodes:

        members = episode["candidates"]
        reasons = episode["match_reasons"]

        first = members[0]
        last = members[-1]

        cursor.execute("""
            INSERT INTO tactic_episodes (
                game_id,
                tactic_type,
                primary_candidate_id,
                detector_version,
                candidate_count,
                first_ply_number,
                last_ply_number,
                episode_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            first["game_id"],
            TACTIC_TYPE,
            first["candidate_id"],
            EPISODE_DETECTOR_VERSION,
            len(members),
            first["ply_number"],
            last["ply_number"],
            "candidate",
        ))

        episode_id = cursor.lastrowid

        for sequence_order, candidate in enumerate(
            members,
            start=1
        ):

            reason = reasons.get(
                candidate["candidate_id"],
                "episode anchor"
            )

            cursor.execute("""
                INSERT INTO tactic_episode_members (
                    episode_id,
                    candidate_id,
                    sequence_order,
                    match_reason
                )
                VALUES (?, ?, ?, ?)
            """, (
                episode_id,
                candidate["candidate_id"],
                sequence_order,
                reason,
            ))

            total_members += 1

    return total_members


def verify_database(connection):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM tactic_episodes
        WHERE tactic_type = ?
    """, (TACTIC_TYPE,))

    episode_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM tactic_episode_members tem

        INNER JOIN tactic_episodes te
            ON te.episode_id =
               tem.episode_id

        WHERE te.tactic_type = ?
    """, (TACTIC_TYPE,))

    member_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM tactic_candidates
        WHERE tactic_type = ?
    """, (TACTIC_TYPE,))

    candidate_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(DISTINCT tem.candidate_id)

        FROM tactic_episode_members tem

        INNER JOIN tactic_episodes te
            ON te.episode_id =
               tem.episode_id

        WHERE te.tactic_type = ?
    """, (TACTIC_TYPE,))

    distinct_members = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM tactic_episodes
        WHERE tactic_type = ?
          AND candidate_count > 1
    """, (TACTIC_TYPE,))

    multi_candidate_episodes = (
        cursor.fetchone()[0]
    )

    cursor.execute("""
        SELECT
            COALESCE(
                SUM(candidate_count - 1),
                0
            )
        FROM tactic_episodes
        WHERE tactic_type = ?
    """, (TACTIC_TYPE,))

    repeated_detections = (
        cursor.fetchone()[0]
    )

    return {
        "episodes": episode_count,
        "members": member_count,
        "candidates": candidate_count,
        "distinct_members": distinct_members,
        "multi_candidate_episodes":
            multi_candidate_episodes,
        "repeated_detections":
            repeated_detections,
    }


def main():
    connection = sqlite3.connect(
        DB_NAME
    )

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    try:
        print()
        print(
            "MERLIN MATE EPISODE BUILDER"
        )

        print(
            "---------------------------"
        )

        rows = load_candidates(
            connection
        )

        print(
            f"Raw missed-mate candidates: "
            f"{len(rows)}"
        )

        candidates = [
            build_candidate(row)
            for row in rows
        ]

        print(
            "Validating solution lines..."
        )

        validate_candidates(
            candidates
        )

        print(
            f"Validated: "
            f"{len(candidates)} / "
            f"{len(candidates)}"
        )

        print(
            "Building V3 tactical episodes..."
        )

        episodes = build_episodes(
            candidates
        )

        repeated = (
            len(candidates)
            - len(episodes)
        )

        multi = sum(
            1
            for episode in episodes
            if len(
                episode["candidates"]
            ) > 1
        )

        print(
            f"Episodes built in memory: "
            f"{len(episodes)}"
        )

        print(
            f"Repeated detections: "
            f"{repeated}"
        )

        print(
            f"Multi-candidate episodes: "
            f"{multi}"
        )

        print()
        print(
            "Writing episodes to database..."
        )

        clear_existing_mate_episodes(
            connection
        )

        member_count = save_episodes(
            connection,
            episodes
        )

        connection.commit()

        print(
            "Database write complete."
        )

        print()
        print(
            "VERIFYING DATABASE"
        )

        print(
            "------------------"
        )

        results = verify_database(
            connection
        )

        print(
            f"Raw candidates: "
            f"{results['candidates']}"
        )

        print(
            f"Stored episodes: "
            f"{results['episodes']}"
        )

        print(
            f"Stored memberships: "
            f"{results['members']}"
        )

        print(
            f"Distinct candidates represented: "
            f"{results['distinct_members']}"
        )

        print(
            f"Repeated detections consolidated: "
            f"{results['repeated_detections']}"
        )

        print(
            f"Multi-candidate episodes: "
            f"{results['multi_candidate_episodes']}"
        )

        print()

        expected_ok = (
            results["episodes"]
            == len(episodes)

            and results["members"]
            == len(candidates)

            and results[
                "distinct_members"
            ]
            == len(candidates)
        )

        if expected_ok:
            print(
                "EPISODE BUILD VERIFIED!"
            )

            print(
                "Every missed-mate candidate "
                "belongs to exactly one stored "
                "episode."
            )

        else:
            print(
                "WARNING: Verification counts "
                "do not match."
            )

            print(
                "Review the database before "
                "continuing."
            )

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()