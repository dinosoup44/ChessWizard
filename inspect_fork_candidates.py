import sqlite3
import json
from collections import Counter


DB_NAME = "merlin.db"


def main():
    connection = sqlite3.connect(DB_NAME)

    try:
        cursor = connection.cursor()

        print()
        print("MERLIN FORK CANDIDATE INSPECTOR")
        print("-------------------------------")

        # -------------------------------------------------
        # BASIC COUNTS
        # -------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*)
            FROM tactic_candidates
            WHERE tactic_type = 'missed_fork'
        """)

        fork_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(DISTINCT move_id)
            FROM tactic_candidates
            WHERE tactic_type = 'missed_fork'
        """)

        distinct_moves = cursor.fetchone()[0]

        print()
        print("BASIC COUNTS")
        print("------------")

        print(
            f"Missed-fork candidates: "
            f"{fork_count}"
        )

        print(
            f"Distinct moves represented: "
            f"{distinct_moves}"
        )

        # -------------------------------------------------
        # ANALYSIS RUN
        # -------------------------------------------------

        cursor.execute("""
            SELECT
                run_id,
                status,
                moves_total,
                moves_scanned,
                candidates_found,
                last_game_id,
                last_ply_number,
                started_at,
                finished_at,
                updated_at
            FROM analysis_runs
            WHERE tool_name = 'fork_puzzles'
            ORDER BY run_id DESC
            LIMIT 1
        """)

        run = cursor.fetchone()

        print()
        print("FORK ANALYSIS RUN")
        print("-----------------")

        if run:
            (
                run_id,
                status,
                moves_total,
                moves_scanned,
                candidates_found,
                last_game_id,
                last_ply_number,
                started_at,
                finished_at,
                updated_at
            ) = run

            print(
                f"Run ID: {run_id}"
            )

            print(
                f"Status: {status}"
            )

            print(
                f"Moves scanned: "
                f"{moves_scanned:,} / "
                f"{moves_total:,}"
            )

            print(
                f"Candidates found: "
                f"{candidates_found:,}"
            )

            print(
                f"Resume cursor: "
                f"game {last_game_id}, "
                f"ply {last_ply_number}"
            )

            print(
                f"Started: {started_at}"
            )

            print(
                f"Updated: {updated_at}"
            )

            print(
                f"Finished: {finished_at}"
            )

        else:
            print(
                "No fork analyzer run found."
            )

        # -------------------------------------------------
        # CACHE COUNTS
        # -------------------------------------------------

        cursor.execute("""
            SELECT
                analysis_profile,
                COUNT(*)
            FROM engine_position_cache
            GROUP BY analysis_profile
            ORDER BY analysis_profile
        """)

        rows = cursor.fetchall()

        print()
        print("ENGINE CACHE")
        print("------------")

        if rows:
            for profile, count in rows:
                print(
                    f"{profile}: "
                    f"{count:,}"
                )
        else:
            print("Empty")

        # -------------------------------------------------
        # LOAD FORK METADATA
        # -------------------------------------------------

        cursor.execute("""
            SELECT
                tc.candidate_id,
                tc.move_id,
                tc.solution_move_san,
                tc.solution_move_uci,
                tc.solution_line,
                tc.confidence,
                tc.notes,
                tc.metadata_json,

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

        rows = cursor.fetchall()

        improvements = []
        fork_pieces = Counter()
        target_types = Counter()

        parsed = []

        for row in rows:
            (
                candidate_id,
                move_id,
                solution_move_san,
                solution_move_uci,
                solution_line,
                confidence,
                notes,
                metadata_json,

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

            gain = metadata.get(
                "gain_vs_played_cp_equivalent"
            )

            if gain is not None:
                improvements.append(gain)

            fork_piece = metadata.get(
                "fork_piece"
            )

            if fork_piece:
                fork_pieces[
                    fork_piece
                ] += 1

            for target in metadata.get(
                "targets",
                []
            ):
                target_name = target.get(
                    "piece"
                )

                if target_name:
                    target_types[
                        target_name
                    ] += 1

            parsed.append({
                "candidate_id":
                    candidate_id,

                "move_id":
                    move_id,

                "solution_move_san":
                    solution_move_san,

                "solution_move_uci":
                    solution_move_uci,

                "solution_line":
                    solution_line,

                "confidence":
                    confidence,

                "notes":
                    notes,

                "metadata":
                    metadata,

                "move_number":
                    move_number,

                "color":
                    color,

                "played_san":
                    played_san,

                "source":
                    source,

                "source_game_id":
                    source_game_id,

                "white_username":
                    white_username,

                "black_username":
                    black_username,
            })

        # -------------------------------------------------
        # IMPROVEMENT STATS
        # -------------------------------------------------

        print()
        print("IMPROVEMENT STATS")
        print("-----------------")

        if improvements:
            improvements.sort()

            average = (
                sum(improvements)
                / len(improvements)
            )

            print(
                f"Minimum improvement: "
                f"{improvements[0] / 100:.2f} pawns"
            )

            print(
                f"Average improvement: "
                f"{average / 100:.2f} pawns"
            )

            print(
                f"Maximum improvement: "
                f"{improvements[-1] / 100:.2f} pawns"
            )

            print(
                f"At least 1.5 pawns: "
                f"{sum(1 for x in improvements if x >= 150)}"
            )

            print(
                f"At least 3 pawns: "
                f"{sum(1 for x in improvements if x >= 300)}"
            )

            print(
                f"At least 5 pawns: "
                f"{sum(1 for x in improvements if x >= 500)}"
            )

        else:
            print(
                "No improvement data found."
            )

        # -------------------------------------------------
        # FORK PIECES
        # -------------------------------------------------

        print()
        print("FORKS BY ATTACKING PIECE")
        print("------------------------")

        for piece, count in (
            fork_pieces.most_common()
        ):
            print(
                f"{piece}: {count}"
            )

        print()
        print("TARGETS BEING FORKED")
        print("--------------------")

        for piece, count in (
            target_types.most_common()
        ):
            print(
                f"{piece}: {count}"
            )

        # -------------------------------------------------
        # SAMPLE CANDIDATES
        # -------------------------------------------------

        print()
        print("SAMPLE MISSED FORKS")
        print("-------------------")

        for item in parsed[:25]:
            metadata = item[
                "metadata"
            ]

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
                f"{item['white_username']} "
                f"vs "
                f"{item['black_username']}"
            )

            print(
                f"Move "
                f"{item['move_number']} "
                f"{item['color']}"
            )

            print(
                f"Played: "
                f"{item['played_san']}"
            )

            print(
                f"Fork: "
                f"{item['solution_move_san']}"
            )

            print(
                f"Fork UCI: "
                f"{item['solution_move_uci']}"
            )

            print(
                f"Forking piece: "
                f"{metadata.get('fork_piece')} "
                f"{metadata.get('fork_from')}"
                f"->{metadata.get('fork_to')}"
            )

            targets = metadata.get(
                "targets",
                []
            )

            if targets:
                target_text = ", ".join(
                    f"{target.get('piece')} "
                    f"on {target.get('square')}"
                    for target in targets
                )

                print(
                    f"Targets: "
                    f"{target_text}"
                )

            before = metadata.get(
                "evaluation_before"
            )

            played = metadata.get(
                "evaluation_after_played"
            )

            fork = metadata.get(
                "evaluation_after_fork"
            )

            print(
                f"Eval before: {before}"
            )

            print(
                f"Eval after played move: "
                f"{played}"
            )

            print(
                f"Eval after fork: "
                f"{fork}"
            )

            gain = metadata.get(
                "gain_vs_played_cp_equivalent"
            )

            if gain is not None:
                print(
                    f"Improvement: "
                    f"{gain / 100:.2f} pawns"
                )

            print(
                f"PV: "
                f"{item['solution_line']}"
            )

        print()
        print("NOTE")
        print("----")
        print(
            "This inspector is read-only."
        )

        print(
            "Nothing was changed in merlin.db."
        )

    finally:
        connection.close()


if __name__ == "__main__":
    main()