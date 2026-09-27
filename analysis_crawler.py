from __future__ import annotations
import threading
from collections.abc import Iterator
from typing import Any

import argparse
import json
import sqlite3
import subprocess
import time
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

import chess
import chess.engine
from time_class import TIME_CLASSES, require_time_class_schema
from analysis_scout import (
    SCOUT_ENGINE_OPTIONS, ScoutEvidence, ScoutResult,
)
from engine_cache import STOCKFISH_PATH, PositionEngine


DB_NAME = "merlin.db"

DEFAULT_LAST_GAMES = 500


from analysis_registry import ANALYZERS, AnalyzerDefinition
from tactic_screeners import fork_screener, is_light_fork_shape


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preview ChessWizard's incremental analysis plan. "
            "Default is read-only. --scout runs bounded Stockfish searches and caches evidence only."
        )
    )

    scope = parser.add_mutually_exclusive_group()

    scope.add_argument(
        "--last-games",
        type=int,
        default=DEFAULT_LAST_GAMES,
        metavar="N",
        help=(
            "Use the most recently imported N real games. "
            f"Default: {DEFAULT_LAST_GAMES}"
        ),
    )

    scope.add_argument(
        "--all-games",
        action="store_true",
        help="Use every real imported game.",
    )
    scope.add_argument("--validation-scope-500", action="store_true",
                       help="Use the exact 500 game IDs saved in reports/scout_preview_500.json.")

    parser.add_argument(
        "--source",
        choices=("lichess", "chesscom"),
        help="Optional source filter.",
    )

    parser.add_argument(
        "--analysis",
        action="append",
        choices=tuple(ANALYZERS),
        help=(
            "Limit preview or a saved-scope heavy validation to one analysis type. "
            "May be supplied more than once."
        ),
    )

    parser.add_argument("--time-class", action="append", choices=TIME_CLASSES,
                        help="Filter before selecting the last N games; repeat to include multiple classes.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--scout", action="store_true",
                        help="Measure light scout queues and known-candidate recall; cache engine evidence only.")
    mode.add_argument("--negative-preview", action="store_true",
                      help="Dry-run the negative-only writer; no live database changes, including engine cache.")
    mode.add_argument("--write-negatives", action="store_true",
                      help="Write negatives only after backup. Use at most 10 recent games or the saved 500-game validation scope.")
    mode.add_argument("--heavy-test-10", action="store_true",
                      help="Process only pending heavy checks in the original saved 10-game validation scope.")
    mode.add_argument("--heavy-validation-500", action="store_true",
                      help="Process only pending heavy checks in the exact saved 500-game validation scope.")
    parser.add_argument("--report", type=Path, help="Write preview metrics to a JSON file.")
    parser.add_argument("--refresh-no-hits-from", metavar="VERSION",
                        help="Explicitly refresh only stale no-hit coverage from this heavy version; saved 10- or 500-game heavy mode and one analyzer required.")

    parser.add_argument(
        "--show-examples",
        type=int,
        default=5,
        metavar="N",
        help="Show up to N example moves per work bucket. Default: 5.",
    )

    parser.add_argument("--discovery-scope", type=Path, help="Explicit saved experiment scope; uses its opt-in registry entry.")
    args = parser.parse_args()
    if args.discovery_scope and (args.scout or args.write_negatives or args.negative_preview or args.heavy_test_10 or args.heavy_validation_500 or args.all_games or args.source or args.time_class or args.analysis or args.validation_scope_500):
        parser.error("--discovery-scope cannot be mixed with other modes or filters.")
    if args.refresh_no_hits_from is not None and (not (args.heavy_test_10 or args.heavy_validation_500) or not args.analysis or len(set(args.analysis)) != 1
                                                 or not args.refresh_no_hits_from.strip()):
        parser.error("--refresh-no-hits-from requires --heavy-test-10 or --heavy-validation-500 and exactly one --analysis.")
    if args.heavy_validation_500:
        if args.all_games or args.source or args.time_class or args.last_games != DEFAULT_LAST_GAMES:
            parser.error("--heavy-validation-500 uses only the saved 500-game IDs and cannot be combined with other scopes/filters.")
        args.validation_scope_500 = True
    if args.heavy_test_10 and (args.all_games or args.validation_scope_500 or args.source or args.time_class
                              or args.last_games not in (10,DEFAULT_LAST_GAMES)):
        parser.error("--heavy-test-10 uses only the original saved 10-game scope and cannot be combined with other scopes/filters.")
    if args.validation_scope_500 and (args.source or args.time_class or (args.analysis and not (args.negative_preview or args.heavy_validation_500))):
        parser.error("The saved validation scope cannot be combined with source, time-class, or analysis filters.")
    if args.write_negatives and not args.validation_scope_500 and (args.all_games or not 1 <= args.last_games <= 10):
        parser.error("--write-negatives requires --last-games 1..10 or --validation-scope-500.")
    return args


def ensure_required_tables(connection: sqlite3.Connection) -> None:
    required = {
        "games",
        "moves",
        "tactic_candidates",
        "analysis_coverage",
    }

    existing = {
        row[0]
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()
    }

    missing = required - existing

    if missing:
        raise RuntimeError(
            "Missing required table(s): "
            + ", ".join(sorted(missing))
            + ". Run the coverage migration first."
        )

    columns = {row[1] for row in connection.execute("PRAGMA table_info(analysis_coverage)")}
    if not {"scout_version", "scout_config"} <= columns:
        raise RuntimeError("Run migrate_analysis_scout_rejection.py before using the crawler.")


def get_selected_game_ids(
    connection: sqlite3.Connection,
    args: argparse.Namespace,
) -> list[int]:
    if getattr(args, "heavy_test_10", False):
        from heavy_dispatch import heavy_test_game_ids
        ids = heavy_test_game_ids(Path(__file__).resolve().parent)
        placeholders = ",".join("?" for _ in ids)
        found = {r[0] for r in connection.execute(
            f"SELECT game_id FROM games WHERE game_id IN ({placeholders}) AND COALESCE(source,'')<>'dev'",ids)}
        if found != set(ids):
            raise ValueError("The saved heavy test scope contains missing/development games")
        return ids
    if getattr(args, "validation_scope_500", False):
        from analysis_scope import validation_scope_ids
        game_ids = validation_scope_ids(Path(__file__).resolve().parent)
        placeholders = ",".join("?" for _ in game_ids)
        found = {r[0] for r in connection.execute(
            f"SELECT game_id FROM games WHERE game_id IN ({placeholders}) AND COALESCE(source,'')<>'dev'",game_ids)}
        if found != set(game_ids):
            raise ValueError("Saved validation scope contains missing or development games")
        return game_ids
    where_parts = [
        "COALESCE(source, '') <> 'dev'",
    ]
    params: list[object] = []

    if args.source:
        where_parts.append(
            "source = ?"
        )
        params.append(
            args.source
        )

    if getattr(args, "time_class", None):
        require_time_class_schema(connection)
        placeholders = ",".join("?" for _ in args.time_class)
        where_parts.append(f"time_class IN ({placeholders})")
        params.extend(args.time_class)

    where_sql = (
        " AND ".join(where_parts)
    )

    if args.all_games:
        rows = connection.execute(
            f"""
            SELECT game_id
            FROM games
            WHERE {where_sql}
            ORDER BY game_id
            """,
            params,
        ).fetchall()

        return [
            row[0]
            for row in rows
        ]

    if args.last_games is None or args.last_games < 1:
        raise ValueError(
            "--last-games must be at least 1."
        )

    rows = connection.execute(
        f"""
        SELECT game_id
        FROM games
        WHERE {where_sql}
        ORDER BY game_id DESC
        LIMIT ?
        """,
        [
            *params,
            args.last_games,
        ],
    ).fetchall()

    return sorted(
        row[0]
        for row in rows
    )


def load_user_moves(
    connection: sqlite3.Connection,
    game_ids: list[int],
) -> list[sqlite3.Row]:
    if not game_ids:
        return []

    placeholders = ",".join(
        "?"
        for _ in game_ids
    )

    query = f"""
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
          AND m.game_id IN (
              {placeholders}
          )

        ORDER BY
            m.game_id,
            m.ply_number
    """

    return connection.execute(
        query,
        game_ids,
    ).fetchall()


def get_coverage(
    connection: sqlite3.Connection,
    move_id: int,
    analysis_type: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            coverage_id,
            move_id,
            analysis_type,
            screener_version,
            scout_version,
            scout_config,
            analyzer_version,
            coverage_status,
            candidate_id,
            checked_at,
            updated_at

        FROM analysis_coverage

        WHERE move_id = ?
          AND analysis_type = ?
        """,
        (
            move_id,
            analysis_type,
        ),
    ).fetchone()


def coverage_decision(
    definition: AnalyzerDefinition,
    coverage: sqlite3.Row | None,
) -> str:
    """Stage-aware validity; positive/rejected heavy evidence is independent
    of upstream filters. This planner does not write any coverage records.
    """
    if coverage is None:
        return "needs_screen"
    if "analysis_type" in coverage.keys() and coverage["analysis_type"] != definition.analysis_type:
        return "needs_screen"
    status = coverage["coverage_status"]
    if status == "error":
        return "retry"
    screener_matches = str(coverage["screener_version"]) == definition.screener_version
    analyzer_matches = str(coverage["analyzer_version"]) == definition.analyzer_version
    if status in {"candidate", "rejected"}:
        return "current" if analyzer_matches else "needs_reanalysis"
    if status == "screened_out":
        return "current" if definition.has_safe_screener and screener_matches else "needs_screen"
    if status in {"scouted_out", "analyzed_no_hit"}:
        if not screener_matches:
            return "needs_screen"
        scout_matches = (
            str(coverage["scout_version"]) == definition.scout_version
            and bool(coverage["scout_config"])
            and coverage["scout_config"] == definition.scout_config()
        )
        if not scout_matches:
            return "needs_scout"
        if status == "analyzed_no_hit" and not analyzer_matches:
            return "needs_reanalysis"
        return "current"
    return "needs_screen"


def screen_move(
    definition: AnalyzerDefinition,
    row: sqlite3.Row,
) -> str:
    return "heavy_candidate" if definition.screener(row) else "screened_out"


def move_description(
    row: sqlite3.Row,
) -> str:
    source = row[
        "source"
    ]

    source_game_id = row[
        "source_game_id"
    ]

    move_number = row[
        "move_number"
    ]

    color = row[
        "color"
    ]

    san = row[
        "san_played"
    ]

    return (
        f"{source} {source_game_id} | "
        f"Move {move_number} {color} | "
        f"played {san}"
    )


def print_examples(
    title: str,
    rows: list[sqlite3.Row],
    limit: int,
) -> None:
    if not rows or limit <= 0:
        return

    print()
    print(title)

    for row in rows[:limit]:
        print(
            "  "
            + move_description(
                row
            )
        )


def preview_analyzer(
    connection: sqlite3.Connection,
    definition: AnalyzerDefinition,
    moves: list[sqlite3.Row],
    example_limit: int,
) -> None:
    current = []
    needs_screen = []
    screened_out = []
    heavy_candidates = []
    needs_reanalysis = []
    retry = []
    needs_scout = []

    for row in moves:
        coverage = get_coverage(
            connection,
            row[
                "move_id"
            ],
            definition.analysis_type,
        )

        decision = coverage_decision(
            definition,
            coverage,
        )

        if decision == "current":
            current.append(
                row
            )
            continue

        if decision == "needs_reanalysis":
            needs_reanalysis.append(
                row
            )
            continue

        if decision == "retry":
            retry.append(
                row
            )
            continue

        if decision == "needs_scout":
            needs_scout.append(row)
            continue

        needs_screen.append(
            row
        )

        screen_result = screen_move(
            definition,
            row,
        )

        if screen_result == "screened_out":
            screened_out.append(
                row
            )

        else:
            heavy_candidates.append(
                row
            )

    print()
    print(
        definition.label.upper()
    )
    print(
        "-" * len(
            definition.label
        )
    )
    print(
        f"Analysis type: "
        f"{definition.analysis_type}"
    )
    print(
        f"Screener version: "
        f"{definition.screener_version}"
    )
    print(
        f"Heavy analyzer version: "
        f"{definition.analyzer_version}"
    )
    print(
        f"Moves in selected scope: "
        f"{len(moves):,}"
    )
    print(
        f"Already current: "
        f"{len(current):,}"
    )
    print(
        f"Need screening: "
        f"{len(needs_screen):,}"
    )
    print(
        f"Cheap screen says no heavy work: "
        f"{len(screened_out):,}"
    )
    print(
        f"Would send to heavy analyzer: "
        f"{len(heavy_candidates):,}"
    )
    print(
        f"Need analyzer-version refresh: "
        f"{len(needs_reanalysis):,}"
    )
    print(
        f"Retry previous errors: "
        f"{len(retry):,}"
    )
    print(f"Need scout-version/configuration refresh: {len(needs_scout):,}")

    print_examples(
        "Example heavy-analyzer queue:",
        heavy_candidates,
        example_limit,
    )

    print_examples(
        "Example analyzer-version refresh queue:",
        needs_reanalysis,
        example_limit,
    )

    return {
        "moves": len(moves), "current": len(current),
        "needs_screen": len(needs_screen), "screened_out": len(screened_out),
        "before_scout": len(heavy_candidates),
        "needs_reanalysis": len(needs_reanalysis), "retry": len(retry),
        "needs_scout": len(needs_scout),
    }


def preview_with_scout(connection, definitions, moves, evidence, example_limit):
    """Walk the selected moves once and dispatch registered screeners/scouts.

Also evaluate existing active candidates to measure false negatives. Their
coverage and candidate records stay untouched regardless of scout results.
"""
    coverage_by_key = {
        (row["move_id"], row["analysis_type"]): row
        for row in connection.execute("SELECT * FROM analysis_coverage")
    }
    known_keys = {
        (row[0], row[1]) for row in connection.execute(
            "SELECT move_id, tactic_type FROM tactic_candidates "
            "WHERE candidate_status <> 'rejected'"
        )
    }
    metrics = {definition.analysis_type: Counter() for definition in definitions}
    examples = {definition.analysis_type: [] for definition in definitions}
    audit_misses = {definition.analysis_type: [] for definition in definitions}
    errors = []
    started = time.monotonic()
    for index, row in enumerate(moves, 1):
        for definition in definitions:
            key = (row["move_id"], definition.analysis_type)
            counts = metrics[definition.analysis_type]
            decision = coverage_decision(definition, coverage_by_key.get(key))
            counts[decision] += 1
            known = key in known_keys
            if known:
                counts["known_candidates"] += 1
            if decision == "current" and not known:
                continue
            try:
                screened_out = decision != "needs_scout" and screen_move(definition, row) == "screened_out"
                result = (ScoutResult(False, "static_screen") if screened_out
                          else definition.scout(row, evidence))
                if known:
                    if result.send_to_heavy:
                        counts["known_passed"] += 1
                    else:
                        counts["known_missed"] += 1
                        audit_misses[definition.analysis_type].append({
                            "move_id": row["move_id"], "reason": result.reason,
                            "description": move_description(row),
                        })
                if decision == "current":
                    continue
                if screened_out:
                    counts["screened_out"] += 1
                else:
                    counts["before_scout"] += 1
                    if result.send_to_heavy:
                        counts["heavy"] += 1
                        if len(examples[definition.analysis_type]) < example_limit:
                            examples[definition.analysis_type].append(row)
                    else:
                        counts["scout_filtered"] += 1
            except (ValueError, chess.engine.EngineError, TimeoutError) as exc:
                counts["errors"] += 1
                if known:
                    counts["known_errors"] += 1
                errors.append({"move_id": row["move_id"], "analysis_type": definition.analysis_type,
                               "message": str(exc)})
                # Engine failure cannot be a negative result. Abort and allow rerun.
                if isinstance(exc, (chess.engine.EngineError, TimeoutError)):
                    raise
        if index % 500 == 0:
            print(f"Scouted {index:,}/{len(moves):,} moves ({time.monotonic() - started:.1f}s)", flush=True)

    for definition in definitions:
        counts = metrics[definition.analysis_type]
        print(f"\n{definition.label.upper()}")
        print(f"Already current: {counts['current']:,}")
        print(f"Static screened out: {counts['screened_out']:,}")
        print(f"Queue before scout: {counts['before_scout']:,}")
        print(f"Scout filtered (unproven negatives): {counts['scout_filtered']:,}")
        print(f"Proposed heavy queue: {counts['heavy']:,}")
        print(f"Errors requiring retry: {counts['errors']:,}")
        print(f"Known candidates retained by proposed pipeline: {counts['known_passed']:,}/{counts['known_candidates']:,}")
        print(f"Known candidates missed: {counts['known_missed']:,}; audit errors: {counts['known_errors']:,}")
        print_examples("Example heavy queue:", examples[definition.analysis_type], example_limit)
    print("\nScout evidence reuse:", dict(evidence.stats))
    print("Scout negatives are experimental; no candidate or coverage changes were made.")
    return {"analyzers": metrics, "known_candidate_misses": audit_misses,
            "errors": errors, "engine_cache": dict(evidence.stats),
            "elapsed_seconds": round(time.monotonic() - started, 2)}


def main() -> int:
    args = parse_args()
    if args.discovery_scope:
        from analysis_discovery import run_discovery
        root=Path(__file__).resolve().parent
        run_discovery(root/DB_NAME,args.discovery_scope.resolve(),
                      (args.report or root/"reports/fork_second_500_summary.json").resolve())
        return 0

    project_root = Path(
        __file__
    ).resolve().parent

    database_path = (
        project_root
        / DB_NAME
    )

    if not database_path.exists():
        print(
            f"ERROR: Database not found: "
            f"{database_path}"
        )
        return 1

    connection = sqlite3.connect(database_path.as_uri() + ("?mode=rw" if args.scout or args.write_negatives or args.heavy_test_10 or args.heavy_validation_500 else "?mode=ro"), uri=True)

    connection.row_factory = (
        sqlite3.Row
    )

    try:
        ensure_required_tables(
            connection
        )

        game_ids = get_selected_game_ids(
            connection,
            args,
        )

        moves = load_user_moves(
            connection,
            game_ids,
        )

        selected_types = (
            args.analysis
            if args.analysis
            else list(
                ANALYZERS
            )
        )

        print()
        print(
            "CHESSWIZARD ANALYSIS CRAWLER"
        )
        print(
            "============================"
        )
        print("Mode: CONTROLLED HEAVY VALIDATION (500 GAMES)" if args.heavy_validation_500 else
              "Mode: CONTROLLED HEAVY TEST (10 GAMES)" if args.heavy_test_10 else
              "Mode: NEGATIVE WRITES ONLY" if args.write_negatives else "Mode: PREVIEW ONLY")
        if args.heavy_test_10 or args.heavy_validation_500:
            print("Registry specialists process only pending checks in the exact saved scope after backup.")
        elif args.write_negatives:
            print("Dry-run and verified backup precede writes. Only static/scout negatives may be saved.")
            print("Heavy analyzers are disabled; existing heavy results and training history are protected.")
        elif args.negative_preview:
            print("Negative-write dry run; live database is read-only. Cache misses use temporary engine evidence.")
        elif args.scout:
            print("Light Stockfish scout; writes reusable engine cache evidence only.")
            print("Candidates, training history, and coverage will not change.")
        else:
            print("No Stockfish analysis will run. No database rows will be changed.")
        print()

        if args.heavy_test_10:
            scope_text = "Original saved 10-game validation scope (exact game IDs)"
        elif args.validation_scope_500:
            scope_text = "Saved 500-game validation scope (exact game IDs)"
        elif args.all_games:
            scope_text = (
                "All real games"
            )

        else:
            scope_text = (
                f"Last "
                f"{args.last_games:,} "
                f"real games"
            )

        if args.source:
            scope_text += (
                f" from "
                f"{args.source}"
            )

        print(
            f"Scope: {scope_text}"
        )

        if args.heavy_test_10 or args.heavy_validation_500:
            from heavy_dispatch import run_heavy_scope
            audit_path = args.report or project_root/"reports"/"heavy_validation.json"
            report = run_heavy_scope(connection,[ANALYZERS[name] for name in dict.fromkeys(selected_types)],moves,game_ids,database_path,coverage_decision,
                                     validation_scope=args.heavy_validation_500,
                                     preflight_path=audit_path.with_name(audit_path.stem+"_preflight.json"),
                                     refresh_from_version=args.refresh_no_hits_from)
            if args.report:
                args.report.parent.mkdir(parents=True,exist_ok=True)
                args.report.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
                print(f"Report: {args.report.resolve()}")
            return 1 if report["errors"] else 0

        if args.negative_preview or args.write_negatives:
            if args.time_class:
                print("Time classes: " + ", ".join(args.time_class))
            from negative_coverage import run_negative_scope
            report = run_negative_scope(
                connection, [ANALYZERS[name] for name in dict.fromkeys(selected_types)],
                moves, game_ids, database_path, coverage_decision, apply=args.write_negatives,
                validation_scope=args.validation_scope_500,
            )
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(report,indent=2) + "\n",encoding="utf-8")
                print(f"Report: {args.report.resolve()}")
            return 1 if report.get("errors") else 0
        if args.time_class:
            print("Time classes: " + ", ".join(args.time_class))
        print(
            f"Games selected: "
            f"{len(game_ids):,}"
        )
        print(
            f"User moves selected: "
            f"{len(moves):,}"
        )

        if args.scout:
            # Restrict writes even if a future scout accidentally issues other SQL.
            def authorize(action, table, column, db_name, trigger):
                if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}:
                    return sqlite3.SQLITE_OK if table in {"engine_position_cache", "sqlite_sequence"} else sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            connection.set_authorizer(authorize)
            with ExitStack() as stack:
                engine = stack.enter_context(chess.engine.SimpleEngine.popen_uci(
                    str(project_root / STOCKFISH_PATH),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                ))
                engine.configure(SCOUT_ENGINE_OPTIONS)
                report = preview_with_scout(
                    connection, [ANALYZERS[name] for name in dict.fromkeys(selected_types)],
                    moves, ScoutEvidence(connection, engine), args.show_examples,
                )
        else:
            report = {"analyzers": {
                name: preview_analyzer(connection, ANALYZERS[name], moves, args.show_examples)
                for name in dict.fromkeys(selected_types)
            }}
        report.update({"games": len(game_ids), "moves": len(moves), "scout": args.scout,
                       "source": args.source, "time_classes": args.time_class,
                       "game_ids": game_ids, "selection_order": "import_order",
                       "versions": {name: {"screener": ANALYZERS[name].screener_version,
                                           "scout": ANALYZERS[name].scout_version,
                                           "scout_config": json.loads(ANALYZERS[name].scout_config()),
                                           "analyzer": ANALYZERS[name].analyzer_version}
                                    for name in selected_types}})
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(f"Report: {args.report.resolve()}")

        print()
        print(
            "PREVIEW COMPLETE"
        )
        print(
            "================"
        )
        print(
            "This is the work planner only."
        )
        print(
            "It proves what Merlin can skip, "
            "screen cheaply, or queue for heavy analysis."
        )
        print()
        print("Review queue size and known-candidate recall before enabling negative coverage or heavy dispatch.")

    finally:
        connection.close()

    return 0



def iter_analysis_checks(connection: sqlite3.Connection, definitions: list[AnalyzerDefinition] | tuple[AnalyzerDefinition, ...],
                         moves: list[sqlite3.Row], engine: PositionEngine, cancel: threading.Event) -> Iterator[dict[str, Any]]:
    """Dispatch specific checks through the unchanged registry and repositories.

    Args:
        connection: Caller-owned connection; a stage may enclose all checks.
        definitions: Registered single-position specialists.
        moves: Exact authorized user-move rows.
        engine: Shared engine/cache boundary; never a standalone launcher.
        cancel: Stop signal checked before persistence and between units.

    Yields:
        Start/finished events with result, persistence action, cache counters and
        preflight provenance. Durable defers are distinct from tactic decisions.

    Raises:
        AnalysisCancelled: Stop interrupted an in-progress unit.
        sqlite3.Error: Persistence failed; the caller must roll back its stage.
    """
    from analysis_control import check_cancelled
    from analysis_planner import plan_negatives
    from analysis_results import HeavyResult
    from analysis_safety import write_authorizer
    from heavy_adapters import dispatch_heavy
    from heavy_repository import save_heavy_result
    from negative_coverage import apply_negatives
    from game_analysis_repository import protected_check
    from analysis_deferred_repository import DeferredCheckRepository

    deferred = DeferredCheckRepository(connection)
    for row in moves:
        evidence = ScoutEvidence(connection, engine)
        for definition in definitions:
            if cancel.is_set():
                return
            key = (row['move_id'], definition.analysis_type)
            previous = connection.execute('SELECT * FROM analysis_coverage WHERE move_id=? AND analysis_type=?', key).fetchone()
            canonical = connection.execute('SELECT 1 FROM tactic_candidates WHERE move_id=? AND tactic_type=?', key).fetchone()
            if coverage_decision(definition, previous) == 'current' or protected_check(previous, canonical):
                continue
            if deferred.is_current(definition, row):
                continue
            yield {'phase': 'start', 'move_id': key[0], 'analyzer': definition.label}
            cache_before = Counter(evidence.stats)
            stats = Counter()
            planning_details = {}
            try:
                connection.set_authorizer(write_authorizer())
                try:
                    plans, plan = plan_negatives(connection, [definition], [row], evidence, coverage_decision,
                        existing={key: previous} if previous is not None else {}, tactic_keys=set())
                finally:
                    connection.set_authorizer(None)
                check_cancelled(cancel)
                if plan['errors']:
                    result = HeavyResult('error', details={'stage': 'planning', 'message': plan['errors'][0]['message'], 'error_type': plan['errors'][0].get('error_type', 'AnalysisError')})
                    saved = save_heavy_result(connection, definition, row, result, {key}, coverage_decision, preserve_existing=True)
                elif plans:
                    written = apply_negatives(connection, plans, [row['game_id']], {definition.analysis_type}, validate_integrity=False)
                    saved = {'state': plans[0]['coverage_status'], 'action': 'negative' if written['inserted'] or written['updated'] else 'unchanged'}
                    result = None
                elif plan['pending_heavy_checks']:
                    result = dispatch_heavy(definition, connection, engine, row, stats)
                    check_cancelled(cancel)
                    saved = save_heavy_result(connection, definition, row, result, {key}, coverage_decision, preserve_existing=True)
                else:
                    result = None
                    saved = {'state': 'deferred', 'action': 'none'}
                    records = plan.get('existing_evidence_preflight', {}).get('records', [])
                    planning_details = next((record for record in records
                        if (record['move_id'], record['analysis_type']) == key), {})
                    stored = deferred.save(definition, row, planning_details, {key}, cancel=cancel)
                    if stored.completed:
                        saved = {'state': 'complete_deferred', 'action': 'deferred_' + stored.action}
            except sqlite3.Error:
                connection.rollback()
                raise
            except Exception as error:
                result = HeavyResult('error', details={'stage': 'planning', 'message': str(error), 'error_type': type(error).__name__})
                saved = save_heavy_result(connection, definition, row, result, {key}, coverage_decision, preserve_existing=True)
            scout_stats = Counter(evidence.stats) - cache_before
            yield {'phase': 'done', 'move_id': key[0], 'analyzer': definition.label, **saved,
                'details': result.details if result is not None else planning_details,
                'cache_hits': scout_stats['database_hits'] + scout_stats['memory_hits'] + stats['hits'],
                'cache_misses': scout_stats['engine_searches'] + stats['misses']}

if __name__ == "__main__":
    raise SystemExit(
        main()
    )

