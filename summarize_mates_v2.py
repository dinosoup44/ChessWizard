import sqlite3
import chess
from collections import defaultdict


DB_NAME = "merlin.db"

# Candidates farther apart than this are automatically
# treated as separate tactical episodes.
#
# 8 plies = roughly 4 turns by the user.
MAX_EPISODE_PLY_GAP = 8


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
    """
    Replays Merlin's stored Stockfish solution line.

    Returns useful information about the mating sequence.
    """

    result = {
        "valid": False,
        "moves": [],
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
            break

        moving_piece = board.piece_at(
            move.from_square
        )

        move_info = {
            "san": san,
            "uci": move.uci(),
            "from": square_name(
                move.from_square
            ),
            "to": square_name(
                move.to_square
            ),
            "piece": piece_name(
                moving_piece
            ),
        }

        result["moves"].append(
            move_info
        )

        if index == 0:
            result["first_move_uci"] = move.uci()
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
            result["mate_move_uci"] = move.uci()
            result["mate_from"] = square_name(
                move.from_square
            )
            result["mate_to"] = square_name(
                move.to_square
            )
            result["mate_piece"] = piece_name(
                moving_piece
            )

            result["opponent_king_end"] = square_name(
                board.king(opponent_color)
            )

            result["plies_to_mate"] = (
                index + 1
            )

            result["valid"] = True
            return result

    # Line parsed successfully enough to be useful,
    # even if checkmate was not reached.
    if result["moves"]:
        result["valid"] = True

    result["opponent_king_end"] = square_name(
        board.king(opponent_color)
    )

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
        "solution_move_san": solution_move_san,
        "solution_move_uci": solution_move_uci,
        "solution_line": solution_line,
        "detector_version": detector_version,
        "source": source,
        "source_game_id": source_game_id,
        "white_username": white_username,
        "black_username": black_username,
        "result": result,
        "time_control": time_control,
        "fingerprint": fingerprint,
    }


def same_tactical_idea(a, b):
    """
    Conservative comparison.

    Candidates must already be:
        - from the same game
        - reasonably close together

    Then we look for evidence that they represent
    the same mating idea.
    """

    fa = a["fingerprint"]
    fb = b["fingerprint"]

    score = 0

    # Strongest clue:
    # exactly the same first Stockfish move.
    if (
        a["solution_move_uci"]
        and a["solution_move_uci"]
        == b["solution_move_uci"]
    ):
        score += 5

    # Same first move reconstructed from the PV.
    if (
        fa["first_move_uci"]
        and fa["first_move_uci"]
        == fb["first_move_uci"]
    ):
        score += 5

    # Same first destination square.
    if (
        fa["first_to"]
        and fa["first_to"]
        == fb["first_to"]
    ):
        score += 2

    # Same type of piece begins the attack.
    if (
        fa["first_piece"]
        and fa["first_piece"]
        == fb["first_piece"]
    ):
        score += 1

    # Same actual mating move.
    if (
        fa["mate_move_uci"]
        and fa["mate_move_uci"]
        == fb["mate_move_uci"]
    ):
        score += 5

    # Same mating square.
    if (
        fa["mate_to"]
        and fa["mate_to"]
        == fb["mate_to"]
    ):
        score += 3

    # Same mating piece.
    if (
        fa["mate_piece"]
        and fa["mate_piece"]
        == fb["mate_piece"]
    ):
        score += 1

    # Same enemy king location at the beginning.
    if (
        fa["opponent_king_start"]
        and fa["opponent_king_start"]
        == fb["opponent_king_start"]
    ):
        score += 1

    # Same enemy king location at mate.
    if (
        fa["opponent_king_end"]
        and fa["opponent_king_end"]
        == fb["opponent_king_end"]
    ):
        score += 2

    # Require meaningful evidence.
    return score >= 5


def candidates_can_group(a, b):
    if a["game_id"] != b["game_id"]:
        return False

    ply_gap = abs(
        a["ply_number"] -
        b["ply_number"]
    )

    if ply_gap > MAX_EPISODE_PLY_GAP:
        return False

    return same_tactical_idea(
        a,
        b
    )


def build_episodes(candidates):
    """
    Builds connected tactical groups.

    This allows:

        A matches B
        B matches C

    to become one episode even if A and C are
    somewhat different as the attack evolves.
    """

    by_game = defaultdict(list)

    for candidate in candidates:
        by_game[
            candidate["game_id"]
        ].append(candidate)

    episodes = []

    for game_candidates in by_game.values():

        unassigned = set(
            range(len(game_candidates))
        )

        while unassigned:
            start_index = min(unassigned)

            episode_indices = {
                start_index
            }

            unassigned.remove(
                start_index
            )

            changed = True

            while changed:
                changed = False

                for index in list(
                    unassigned
                ):
                    candidate = (
                        game_candidates[index]
                    )

                    for existing_index in (
                        episode_indices
                    ):
                        existing = (
                            game_candidates[
                                existing_index
                            ]
                        )

                        if candidates_can_group(
                            candidate,
                            existing
                        ):
                            episode_indices.add(
                                index
                            )

                            unassigned.remove(
                                index
                            )

                            changed = True
                            break

            episode = [
                game_candidates[index]
                for index in sorted(
                    episode_indices
                )
            ]

            episode.sort(
                key=lambda x:
                x["ply_number"]
            )

            episodes.append(
                episode
            )

    episodes.sort(
        key=lambda episode: (
            episode[0]["game_id"],
            episode[0]["ply_number"]
        )
    )

    return episodes


def print_candidate(candidate):
    fingerprint = (
        candidate["fingerprint"]
    )

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

    print(
        "    Fingerprint:"
    )

    print(
        f"      First attack: "
        f"{fingerprint['first_piece']} "
        f"{fingerprint['first_from']}"
        f"->{fingerprint['first_to']}"
    )

    print(
        f"      Mate move: "
        f"{fingerprint['mate_piece']} "
        f"{fingerprint['mate_from']}"
        f"->{fingerprint['mate_to']}"
    )

    print(
        f"      Enemy king: "
        f"{fingerprint['opponent_king_start']}"
        f" -> "
        f"{fingerprint['opponent_king_end']}"
    )

    print(
        f"      PV plies to mate: "
        f"{fingerprint['plies_to_mate']}"
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
        raw_count -
        episode_count
    )

    games = {
        candidate["game_id"]
        for candidate in candidates
    }

    multi_candidate_episodes = [
        episode
        for episode in episodes
        if len(episode) > 1
    ]

    parsed_lines = sum(
        1
        for candidate in candidates
        if candidate[
            "fingerprint"
        ]["valid"]
    )

    mate_lines = sum(
        1
        for candidate in candidates
        if candidate[
            "fingerprint"
        ]["mate_move_uci"]
        is not None
    )

    print()
    print(
        "MERLIN MISSED-MATE EPISODE ANALYSIS V2"
    )
    print(
        "--------------------------------------"
    )

    print(
        f"Raw candidates: {raw_count}"
    )

    print(
        f"Games containing candidates: "
        f"{len(games)}"
    )

    print(
        f"V1 heuristic episodes: 397"
    )

    print(
        f"V2 tactical episodes: "
        f"{episode_count}"
    )

    print(
        f"V2 repeated detections: "
        f"{repeated_count}"
    )

    print(
        f"Multi-candidate episodes: "
        f"{len(multi_candidate_episodes)}"
    )

    print(
        f"Solution lines parsed: "
        f"{parsed_lines} / {raw_count}"
    )

    print(
        f"Lines reaching checkmate: "
        f"{mate_lines} / {raw_count}"
    )

    print()
    print(
        "LARGEST V2 EPISODES"
    )
    print(
        "-------------------"
    )

    largest = sorted(
        multi_candidate_episodes,
        key=len,
        reverse=True
    )

    for episode in largest[:15]:
        first = episode[0]

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
            f"{len(episode)}"
        )

        for candidate in episode:
            print_candidate(
                candidate
            )

    print()
    print(
        "SAMPLE SINGLE CANDIDATES"
    )
    print(
        "------------------------"
    )

    singles = [
        episode[0]
        for episode in episodes
        if len(episode) == 1
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
        "This script only reads merlin.db."
    )

    print(
        "No candidates or episodes were "
        "written, changed, or deleted."
    )


if __name__ == "__main__":
    main()