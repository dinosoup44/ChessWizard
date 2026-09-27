"""Dependency-aware plans and atomic execution. No UI, engine, or historical file writes."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from analysis_deferred_schema import deferred_schema_available
from data_activity import exclusive_data_activity
from data_management_models import GameDeletionPlan, GameDeletionResult
from ignored_imports import available
from database_schema import REQUIRED_COLUMNS
from game_collection_schema import validate_schema as validate_collection_schema
from game_collection_repository import require_uncollected_games

# Explicit order also handles legacy schemas without cascading foreign keys.
DELETE_ORDER = (
    "tactic_occurrence_review_links", "tactic_occurrence_lines",
    "tactic_occurrence_legacy_candidates", "tactic_occurrence_evidence",
    "tactic_occurrences", "training_attempts", "tactic_episode_members",
    "tactic_episodes", "analysis_coverage", "engine_analysis", "tactic_candidates",
    "moves", "analysis_runs", "games")
RESET_EXTRA = ("chess_accounts", "engine_position_cache", "engine_candidate_line_cache")

OWNERSHIP_CHECKS = (
    ("occurrence move/game", "SELECT 1 FROM tactic_occurrences o LEFT JOIN moves m ON m.move_id=o.move_id WHERE m.move_id IS NULL OR m.game_id<>o.game_id"),
    ("episode primary", "SELECT 1 FROM tactic_episodes e JOIN tactic_candidates c ON c.candidate_id=e.primary_candidate_id JOIN moves m ON m.move_id=c.move_id WHERE m.game_id<>e.game_id"),
    ("episode member", "SELECT 1 FROM tactic_episode_members x JOIN tactic_episodes e USING(episode_id) JOIN tactic_candidates c USING(candidate_id) JOIN moves m ON m.move_id=c.move_id WHERE m.game_id<>e.game_id"),
    ("training episode", "SELECT 1 FROM training_attempts t JOIN tactic_episodes e USING(episode_id) JOIN tactic_candidates c ON c.candidate_id=t.candidate_id JOIN moves m ON m.move_id=c.move_id WHERE m.game_id<>e.game_id"),
    ("coverage candidate", "SELECT 1 FROM analysis_coverage a JOIN tactic_candidates c USING(candidate_id) WHERE a.move_id<>c.move_id"),
    ("occurrence candidate", "SELECT 1 FROM tactic_occurrence_legacy_candidates l JOIN tactic_occurrences o USING(occurrence_id) JOIN tactic_candidates c USING(candidate_id) WHERE o.move_id<>c.move_id"),
    ("analysis checkpoint", "SELECT 1 FROM analysis_runs a LEFT JOIN games g ON a.last_game_id=g.game_id WHERE a.last_game_id IS NOT NULL AND g.game_id IS NULL"),
)


def _delete_order(db: sqlite3.Connection) -> tuple[str, ...]:
    """Include the reviewed optional ledger before its owning moves."""
    return (('analysis_deferred_checks',) if deferred_schema_available(db) else ()) + DELETE_ORDER


def validate_integrity(db):
    if db.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("Foreign-key validation failed; operation rolled back")
    for label, sql in OWNERSHIP_CHECKS:
        if db.execute(sql + " LIMIT 1").fetchone():
            raise ValueError("Invalid " + label + " ownership; operation stopped")


class DataManagementRepository:
    """Plan and apply explicit dependency-aware user-data operations.

    Args:
        database_path: Existing profile whose optional extensions are validated.
    """
    def __init__(self, database_path: str | Path) -> None:
        """Bind a profile without opening or changing it.

        Args:
            database_path: Existing user profile database.
        """
        self.path = Path(database_path).resolve()

    def _connect(self, writable=False):
        db = sqlite3.connect(self.path.as_uri() + ("?mode=rw" if writable else "?mode=ro"), uri=True)
        db.execute("PRAGMA foreign_keys=ON")
        if not writable:
            db.execute("PRAGMA query_only=ON")
        return db

    def games(self):
        with closing(self._connect()) as db:
            return tuple(db.execute("""SELECT g.game_id,g.played_at,g.white_username,g.black_username,
                g.result,g.source,g.source_game_id,count(m.move_id) FROM games g
                LEFT JOIN moves m USING(game_id) WHERE g.source IN ('chesscom','lichess')
                GROUP BY g.game_id ORDER BY g.played_at DESC,g.game_id DESC"""))

    def ignored(self):
        with closing(self._connect()) as db:
            return tuple(db.execute("SELECT source,source_game_id,ignored_at FROM ignored_import_games ORDER BY ignored_at DESC,source,source_game_id")) if available(db) else ()

    def ignore_available(self):
        with closing(self._connect()) as db:
            return available(db)

    @staticmethod
    def _conditions(game_ids):
        ids = ",".join(str(int(i)) for i in game_ids) or "NULL"
        games = f"game_id IN ({ids})"
        moves = f"move_id IN (SELECT move_id FROM moves WHERE {games})"
        candidates = f"candidate_id IN (SELECT candidate_id FROM tactic_candidates WHERE {moves})"
        episodes = f"episode_id IN (SELECT episode_id FROM tactic_episodes WHERE {games})"
        occurrences = f"occurrence_id IN (SELECT occurrence_id FROM tactic_occurrences WHERE {games})"
        return {
            "games": games, "moves": games, "tactic_candidates": moves,
            "tactic_episodes": games, "tactic_episode_members": episodes,
            "training_attempts": candidates, "analysis_coverage": moves, "engine_analysis": moves,
            "analysis_deferred_checks": moves,
            "tactic_occurrences": games, "tactic_occurrence_evidence": occurrences,
            "tactic_occurrence_lines": occurrences, "tactic_occurrence_legacy_candidates": occurrences,
            "tactic_occurrence_review_links": occurrences,
            "analysis_runs": f"last_game_id IN ({ids})",
        }

    def _plan(self, db, game_ids, reset=False, clear_ignored=False):
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        unknown = tables - set(REQUIRED_COLUMNS) - {"sqlite_sequence", "application_metadata", "ignored_import_games", "game_collections", "game_collection_members", "analysis_deferred_checks"}
        if unknown or db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger'").fetchone():
            raise ValueError("Unreviewed schema extensions; deletion ownership must be documented first")
        if {"game_collections", "game_collection_members"} & tables:
            validate_collection_schema(db)
        validate_integrity(db)
        if any(type(i) is not int for i in game_ids):
            raise ValueError("Select valid game IDs")
        ids = tuple(sorted(set(game_ids)))
        require_uncollected_games(db, ids)
        conditions = self._conditions(ids)
        rows = db.execute("SELECT game_id,source,source_game_id FROM games WHERE " + conditions["games"] + " ORDER BY game_id").fetchall()
        if tuple(r[0] for r in rows) != ids:
            raise ValueError("Games changed or are missing; refresh the preview")
        identities = tuple((r[1], r[2]) for r in rows)
        counts = []
        digest = hashlib.sha256()
        for table in _delete_order(db) + (RESET_EXTRA if reset else ()):
            condition = "1" if reset else conditions[table]
            count = db.execute(f"SELECT count(*) FROM {table} WHERE {condition}").fetchone()[0]
            counts.append((table, count))
            # Cache payloads need not be loaded to approve an all-row reset. Game-owned
            # rows include full content so even same-count edits invalidate a preview.
            if table not in RESET_EXTRA:
                for row in db.execute(f"SELECT * FROM {table} WHERE {condition} ORDER BY rowid"):
                    digest.update(repr(row).encode())
        if reset:
            counts.append(("user_sync_dates", db.execute("SELECT count(*) FROM users WHERE last_sync_at IS NOT NULL").fetchone()[0]))
        if reset and clear_ignored and available(db):
            counts.append(("ignored_import_games", db.execute("SELECT count(*) FROM ignored_import_games").fetchone()[0]))
        digest.update(json.dumps(counts).encode())
        digest.update(repr(db.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()).encode())
        return GameDeletionPlan(str(self.path), ids, identities, tuple(counts), digest.hexdigest(), reset, clear_ignored)

    def plan_game_deletion(self, game_ids):
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            return self._plan(db, tuple(game_ids))

    def plan_reset(self, *, clear_ignored=False):
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            return self._plan(db, tuple(r[0] for r in db.execute("SELECT game_id FROM games")), True, clear_ignored)

    def execute_game_deletion(self, plan: GameDeletionPlan, *,
                              ignore_future_imports: bool = False) -> GameDeletionResult:
        """Apply an unchanged approved deletion/reset plan atomically.

        Args:
            plan: Dependency-aware preview for this database and exact game scope.
            ignore_future_imports: Also retain canonical remote identities for suppression.

        Returns:
            Counts of deleted dependencies and newly suppressed remote games.

        Raises:
            ValueError: The scope, schema, collection protection or preview changed.
            DataBusyError: Another user-data activity owns the profile.
            sqlite3.Error: Persistence failed; the transaction is rolled back.
        """
        if plan.database_path != str(self.path):
            raise ValueError("Plan belongs to another database")
        with exclusive_data_activity(self.path), closing(self._connect(True)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                fresh = self._plan(db, plan.game_ids, plan.reset, plan.clear_ignored)
                if fresh != plan:
                    raise ValueError("Data changed since preview. Refresh and confirm again.")
                if plan.reset and not any(count for _, count in plan.counts):
                    db.rollback()
                    return GameDeletionResult(plan.counts)
                if plan.reset and ignore_future_imports:
                    raise ValueError("Reset does not create ignored identities")
                added = 0
                if ignore_future_imports:
                    if not available(db):
                        raise ValueError("Ignored imports require the explicit additive migration first.")
                    if any(s not in ("chesscom", "lichess") or not i or not i.strip() for s, i in plan.identities):
                        raise ValueError("Games require canonical remote source identities")
                    for identity in plan.identities:
                        added += db.execute("INSERT INTO ignored_import_games(source,source_game_id) VALUES (?,?) ON CONFLICT DO NOTHING", identity).rowcount
                # Materialize owned row IDs before parent/child deletion changes subqueries.
                conditions = self._conditions(plan.game_ids)
                selected = {}
                for table in _delete_order(db):
                    condition = "1" if plan.reset else conditions[table]
                    selected[table] = tuple(r[0] for r in db.execute(f"SELECT rowid FROM {table} WHERE {condition}"))
                for table, rowids in selected.items():
                    db.executemany(f"DELETE FROM {table} WHERE rowid=?", ((r,) for r in rowids))
                if plan.reset:
                    for table in RESET_EXTRA:
                        db.execute(f"DELETE FROM {table}")
                    db.execute("UPDATE users SET last_sync_at=NULL WHERE last_sync_at IS NOT NULL")
                    if plan.clear_ignored and available(db):
                        db.execute("DELETE FROM ignored_import_games")
                    for table in _delete_order(db) + RESET_EXTRA:
                        if db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                            raise ValueError("Reset did not clear " + table)
                validate_integrity(db)
                if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise ValueError("Database quick_check failed")
                db.commit()
                return GameDeletionResult(plan.counts, added)
            except Exception:
                db.rollback()
                raise

    def allow_import_again(self, identities):
        with exclusive_data_activity(self.path), closing(self._connect(True)) as db:
            with db:
                db.execute("BEGIN IMMEDIATE")
                if available(db):
                    db.executemany("DELETE FROM ignored_import_games WHERE source=? AND source_game_id=?", tuple(identities))
