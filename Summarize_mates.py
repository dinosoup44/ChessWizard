import sqlite3
from collections import defaultdict


DB_NAME = "merlin.db"

# Candidates within this many plies can potentially
# belong to the same tactical episode.
#
# 6 plies = roughly 3 of the user's turns.
EPISODE_PLY_GAP = 6


def get_destination_square(uci_move):
    """
    Example:
        g5g6 -> g6
        d8c7 -> c7
        e7e8q -> e8

    Used only as a rough clue when deciding whether
    nearby missed mates may be the same tactical idea.
    """

    if not uci_move:
        return None

    if len(uci_move) < 4:
        return None

    return uci_move[2:4]


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


def build_episodes(rows):
    """
    This is intentionally a HEURISTIC report.

    We group nearby missed-mate candidates when:

    1. They are in the same game.
    2. They occur within EPISODE_PLY_GAP plies.
    3. Their suggested mating moves land on the
       same destination square.

    We are NOT writing these groups back to the
    database yet.
    """

    episodes = []

    current_episode = []

    previous_game_id = None
    previous_ply = None
    previous_destination = None

    for row in rows:
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
            source,
            source_game_id,
            white_username,
            black_username,
            result,
            time_control
        ) = row

        destination = get_destination_square(
            solution_move_uci
        )

        same_game = (
            previous_game_id == game_id
        )

        close_in_time = (
            previous_ply is not None
            and ply_number - previous_ply
            <= EPISODE_PLY_GAP
        )

        same_destination = (
            destination is not None
            and destination == previous_destination
        )

        belongs_to_current_episode = (
            current_episode
            and same_game
            and close_in_time
            and same_destination
        )

        if belongs_to_current_episode:
            current_episode.append(row)

        else:
            if current_episode:
                episodes.append(
                    current_episode
                )

            current_episode = [row]

        previous_game_id = game_id
        previous_ply = ply_number
        previous_destination = destination

    if current_episode:
        episodes.append(
            current_episode
        )

    return episodes


def main():
    connection = sqlite3.connect(DB_NAME)

    rows = load_candidates(
        connection
    )

    connection.close()

    raw_count = len(rows)

    if raw_count == 0:
        print("No missed-mate candidates found.")
        return

    games = defaultdict(list)
    sources = defaultdict(int)

    for row in rows:
        game_id = row[6]
        source = row[12]

        games[game_id].append(row)
        sources[source] += 1

    episodes = build_episodes(
        rows
    )

    multi_candidate_games = [
        candidate_rows
        for candidate_rows in games.values()
        if len(candidate_rows) > 1
    ]

    repeated_candidates = (
        raw_count - len(episodes)
    )

    print("MERLIN MISSED-MATE SUMMARY")
    print("--------------------------")
    print(
        "Raw missed-mate candidates:",
        raw_count
    )
    print(
        "Games containing missed mates:",
        len(games)
    )
    print(
        "Likely tactical episodes:",
        len(episodes)
    )
    print(
        "Likely repeated detections:",
        repeated_candidates
    )
    print(
        "Games with multiple candidates:",
        len(multi_candidate_games)
    )

    print()
    print("CANDIDATES BY SOURCE")
    print("--------------------")

    for source, count in sorted(
        sources.items()
    ):
        print(
            f"{source}: {count}"
        )

    print()
    print("TOP GAMES BY RAW MISSED-MATE COUNT")
    print("----------------------------------")

    sorted_games = sorted(
        games.values(),
        key=len,
        reverse=True
    )

    for candidate_rows in sorted_games[:15]:
        first = candidate_rows[0]

        source = first[12]
        source_game_id = first[13]
        white = first[14]
        black = first[15]

        print()
        print(
            f"{source} {source_game_id}"
        )
        print(
            f"{white} vs {black}"
        )
        print(
            "Raw candidates:",
            len(candidate_rows)
        )

        for row in candidate_rows[:10]:
            move_number = row[8]
            color = row[9]
            played = row[10]
            best = row[2]

            print(
                f"  Move {move_number} "
                f"{color}: "
                f"played {played} "
                f"| best {best}"
            )

        if len(candidate_rows) > 10:
            print(
                "  ...",
                len(candidate_rows) - 10,
                "more"
            )

    print()
    print("SAMPLE CONSOLIDATED EPISODES")
    print("----------------------------")

    shown = 0

    for episode in episodes:
        if len(episode) <= 1:
            continue

        first = episode[0]

        source = first[12]
        source_game_id = first[13]
        white = first[14]
        black = first[15]

        print()
        print(
            f"{source} {source_game_id}"
        )
        print(
            f"{white} vs {black}"
        )
        print(
            "Possible single tactical episode:",
            len(episode),
            "raw detections"
        )

        for row in episode:
            move_number = row[8]
            color = row[9]
            played = row[10]
            best = row[2]
            line = row[4]

            print(
                f"  Move {move_number} "
                f"{color}: "
                f"played {played}"
            )

            print(
                f"    Best: {best}"
            )

            print(
                f"    Line: {line}"
            )

        shown += 1

        if shown >= 10:
            break

    print()
    print("NOTE")
    print("----")
    print(
        "Episode grouping is currently heuristic only."
    )
    print(
        "Nothing in merlin.db was changed."
    )


if __name__ == "__main__":
    main()