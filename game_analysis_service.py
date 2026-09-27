"""Frontend-neutral lifecycle over the central crawler; no tactic calculations."""
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from contextlib import ExitStack, closing, contextmanager
from dataclasses import replace
from pathlib import Path
import sqlite3
import threading
import time

from analysis_completion import CompletionState, assess_preflight_completion
from data_activity import exclusive_analysis_activity, exclusive_data_activity, DataBusyError
from analysis_control import AnalysisCancelled, check_cancelled, cancellable_reads
from sqlite_transaction import SqliteTransaction
from analysis_crawler import ensure_required_tables, iter_analysis_checks, load_user_moves
from analysis_engine import LazyScoutEngine
from analysis_registry import ANALYZERS, AnalyzerDefinition
from analysis_settings import ProductionAnalysisProfile, AnalysisBatchSettings
from analysis_failures import (AnalysisFailure, FailureDisposition, ReportedAnalysisFailure,
                               classify_failure, reported_failure)
from analysis_presentation import refresh_mate_episodes
from application_paths import application_root
from game_analysis_models import (AnalysisScopeKind, GameAnalysisScope, AnalysisProgress,
                                 GameAnalysisResult, AnalysisSnapshot, CoverageProgress)
from game_analysis_repository import analysis_snapshot, iter_game_readiness, select_actionable_scope
from position_evaluation import EvaluationSettings
from evaluation_service import GameEvaluationService
from move_quality_settings import MoveQualitySettings
from move_quality_service import GameMoveQualityService

DATABASE_BUSY_TIMEOUT_SECONDS = 0.25


class GameAnalysisService:
    """Own scoped preparation, engine lifetime and atomic analysis stages.

    Args:
        database_path: Existing profile database; never bootstrapped by this service.
        definitions: Registered specialists, or an explicit subset for isolated tools.
        engine_root: Application root containing the configured engine.
        evaluation_settings: Existing evaluation policy; None disables this stage.
        quality_settings: Existing move-quality policy; None disables this stage.
        batch_settings: Shared workload partition settings; no evidence-policy impact.
    """
    profile = ProductionAnalysisProfile()

    def __init__(self, database_path: str | Path, *, definitions: Iterable[AnalyzerDefinition] | None = None,
                 engine_root: str | Path | None = None, evaluation_settings: EvaluationSettings | None = EvaluationSettings(),
                 quality_settings: MoveQualitySettings | None = MoveQualitySettings(),
                 batch_settings: AnalysisBatchSettings = AnalysisBatchSettings()) -> None:
        """Bind the existing profile and shared analyzer services.

        Args:
            database_path: Existing profile database.
            definitions: Optional explicit registry subset.
            engine_root: Application directory containing Stockfish.
            evaluation_settings: Shared evaluation policy, or None to disable.
            quality_settings: Shared quality policy, or None to disable.
            batch_settings: Maximum games inspected before each processing window.
        """
        self.batch_settings = batch_settings
        self.evaluation_settings = evaluation_settings
        self.quality_settings = quality_settings
        self.database_path = Path(database_path).resolve()
        self.definitions = tuple(ANALYZERS.values()) if definitions is None else tuple(definitions)
        self.engine_root = Path(engine_root) if engine_root is not None else application_root()

    def _connect(self, mode: str) -> sqlite3.Connection:
        db = sqlite3.connect(self.database_path.as_uri() + '?mode=' + mode, uri=True, timeout=DATABASE_BUSY_TIMEOUT_SECONDS)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        if mode == 'ro':
            db.execute('PRAGMA query_only=ON')
        return db

    def preview(self, scope: GameAnalysisScope = GameAnalysisScope(), *,
                progress: Callable[[CoverageProgress], None] = lambda event: None,
                cancel: threading.Event | None = None) -> AnalysisSnapshot:
        """Inspect exact readiness without engine work, locks, migrations or writes.

        Args:
            scope: Requested real games.
            progress: Coverage counts emitted on the calling worker thread.
            cancel: Optional cooperative cancellation event.

        Returns:
            Readiness for at most the first batch. Recent scopes first scan exact
            readiness until their actionable limit is filled; other scopes keep cheap
            progressive preparation. Uninspected selected batches remain explicit.

        Raises:
            AnalysisCancelled: Preparation was cancelled.
            ValueError: Scope includes missing/development games.
            sqlite3.Error: The database cannot be read.
        """
        with closing(self._connect('ro')) as db, cancellable_reads(db, cancel):
            ensure_required_tables(db)
            selection = select_actionable_scope(db, self.definitions, scope, self.evaluation_settings,
                                                self.quality_settings, progress=progress, cancel=cancel)
            ids = selection.game_ids[:self.batch_settings.batch_size]
            if not ids:
                return AnalysisSnapshot((), 0, selection.empty_ids)
            frozen = GameAnalysisScope(scope.kind, ids)
            snapshot = analysis_snapshot(db, self.definitions, frozen, self.evaluation_settings,
                                         self.quality_settings, progress=progress, cancel=cancel)
            return replace(snapshot, eligible_games=len(selection.game_ids), skipped_empty_ids=selection.empty_ids,
                           scope_complete=len(ids) == len(selection.game_ids))

    def has_incomplete_work(self, *, cancel: threading.Event | None = None) -> bool:
        """Detect unfinished work in the background, stopping at the first match.

        This is a scheduler-free startup foundation; it never starts analysis.

        Args:
            cancel: Optional cancellation event owned by the frontend.

        Returns:
            Whether any real game needs additional work.

        Raises:
            AnalysisCancelled: Detection was cancelled.
            sqlite3.Error: The profile cannot be read.
        """
        with closing(self._connect('ro')) as db, cancellable_reads(db, cancel):
            ensure_required_tables(db)
            return any(game.needs_work for game in iter_game_readiness(
                db, self.definitions, GameAnalysisScope(), self.evaluation_settings, self.quality_settings, cancel=cancel))

    def run(self, scope: GameAnalysisScope = GameAnalysisScope(), *,
            progress: Callable[[AnalysisProgress], None] = lambda event: None,
            cancel: threading.Event | None = None) -> GameAnalysisResult:
        """Process one explicit scope with a single engine and per-database ownership.

        Args:
            scope: Real games to inspect; membership is frozen at preparation.
            progress: Worker-thread notifications; must not call UI widgets.
            cancel: Stop signal; rolls back only the active unfinished stage.

        Returns:
            Durable counts, attempted engine cost, per-game deferrals and failures.
            Busy databases return an error result immediately.
        """
        cancel = cancel if cancel is not None else threading.Event()
        try:
            check_cancelled(cancel)
            with exclusive_analysis_activity(self.database_path), exclusive_data_activity(self.database_path):
                return self._run(scope, progress, cancel)
        except AnalysisCancelled:
            return GameAnalysisResult(cancelled=True, queue_complete=False)
        except (DataBusyError, OSError) as error:
            return GameAnalysisResult(errors=1, fatal_errors=1, details=(str(error),), queue_complete=False)

    def _run(self, scope: GameAnalysisScope, progress: Callable[[AnalysisProgress], None],
             cancel: threading.Event) -> GameAnalysisResult:
        started = time.monotonic()
        counts: Counter = Counter()
        details: list[str] = []
        states = {}
        inspected_ids: set[int] = set()
        stable_pending_ids: set[int] = set()
        queued_ids: set[int] = set()
        scope_ids: tuple[int, ...] = ()
        batch_ids: tuple[int, ...] = ()
        batch_index = prepared = changes = 0
        engine = game = None
        fatal = False
        batch_size = self.batch_settings.batch_size
        selection_ready = False

        def fail(failure: AnalysisFailure, stage_name: str) -> None:
            nonlocal fatal
            disposition = failure.disposition
            prefix = f'Game {game.game_id}, ' if game is not None else ''
            details.append(f'{prefix}{stage_name}: {disposition.value}: {failure.error_type}: {failure.message}')
            if disposition == FailureDisposition.DEFERRED:
                return
            counts['errors'] += 1
            counts['fatal_errors' if disposition == FailureDisposition.FATAL else 'recoverable_errors'] += 1
            fatal = fatal or disposition == FailureDisposition.FATAL

        def status(message: str, analyzer: str = '', *, phase: str = 'Analyzing games',
                   coverage_event: CoverageProgress | None = None) -> None:
            progress(AnalysisProgress(message=message, games_queued=len(queued_ids),
                games_visited=counts['games_visited'], game_id=game.game_id if game else None,
                game_label=game.label if game else '', analyzer=analyzer,
                checks_processed=counts['checks_processed'], candidates_created=counts['candidates_created'],
                errors=counts['errors'], elapsed_seconds=time.monotonic()-started,
                evaluation_completed=counts['evaluation_completed'], evaluation_total=counts['evaluation_total'],
                quality_completed=counts['quality_completed'], quality_total=counts['quality_total'], phase=phase,
                coverage_checked=coverage_event.checked if coverage_event else 0,
                coverage_total=coverage_event.total if coverage_event else 0,
                batch_index=batch_index, batch_count=(len(scope_ids)+batch_size-1)//batch_size,
                batch_start=(batch_index-1)*batch_size+1 if batch_ids else 0,
                batch_end=min(batch_index*batch_size,len(scope_ids)), scope_total=len(scope_ids),
                batch_completed=sum(states[gid].complete for gid in batch_ids if gid in states),
                overall_completed=sum(g.complete for g in states.values()),
                games_deferred=counts['games_deferred'], recoverable_errors=counts['recoverable_errors'],
                fatal_errors=counts['fatal_errors'], games_inspected=len(inspected_ids)))

        def coverage(event: CoverageProgress) -> None:
            status('Checking this batchâ€™s analysis coverage', phase='Checking analysis coverage', coverage_event=event)

        @contextmanager
        def stage(name: str) -> Iterator[None]:
            nonlocal changes, current_stage
            check_cancelled(cancel)
            current_stage = name
            before, detail_count = counts.copy(), len(details)
            changed_before = db.total_changes
            status(name, name)
            try:
                with SqliteTransaction(db, cancel):
                    yield
            except BaseException:
                counts.clear()
                counts.update(before)
                del details[detail_count:]
                raise
            else:
                changes += db.total_changes - changed_before

        try:
            with ExitStack() as stack:
                db = stack.enter_context(closing(self._connect('rw')))
                ensure_required_tables(db)
                with cancellable_reads(db, cancel):
                    selection = select_actionable_scope(db, self.definitions, scope, self.evaluation_settings,
                                                        self.quality_settings, progress=coverage, cancel=cancel)
                scope_ids = selection.game_ids
                selection_ready = True
                counts['games_invalid'] = len(selection.empty_ids)
                details.extend(f'Game {gid}: skipped: zero registered moves' for gid in selection.empty_ids)
                engine = LazyScoutEngine(stack, self.engine_root, cancel)
                for offset in range(0, len(scope_ids), batch_size):
                    check_cancelled(cancel)
                    batch_index = offset//batch_size+1
                    batch_ids = scope_ids[offset:offset+batch_size]
                    game = None
                    with cancellable_reads(db, cancel):
                        snapshot = analysis_snapshot(db, self.definitions, GameAnalysisScope(scope.kind, batch_ids),
                            self.evaluation_settings, self.quality_settings, progress=coverage, cancel=cancel)
                    prepared += len(batch_ids)
                    states.update((g.game_id,g) for g in snapshot.games)
                    queued_ids.update(g.game_id for g in snapshot.queued)
                    counts['games_skipped'] += snapshot.complete_games
                    inspected_ids.update(g.game_id for g in snapshot.games if not g.needs_work)
                    for skipped in snapshot.games:
                        if skipped.skip_reason:
                            counts['games_invalid'] += 1
                            details.append(f'Game {skipped.game_id}: skipped: {skipped.skip_reason}')
                    status('Preparing this batchâ€™s analysis queue')
                    for game in snapshot.queued:
                        check_cancelled(cancel)
                        current_stage = 'Readiness'
                        stable_before = counts['stable_deferred_checks']
                        game_defer_reasons: Counter = Counter()
                        counts['evaluation_completed'] = counts['quality_completed'] = 0
                        counts['evaluation_total'] = game.evaluation_positions
                        counts['quality_total'] = game.quality_moves
                        try:
                            if game.readiness_error:
                                raise ReportedAnalysisFailure(reported_failure(game.readiness_error_type, game.readiness_error))
                            if self.evaluation_settings is not None and game.evaluation_pending:
                                with stage('Position evaluation'):
                                    for event in GameEvaluationService(db, engine, self.evaluation_settings).run(game.game_id, cancel):
                                        counts['positions_evaluated'] += 1
                                        counts['evaluation_completed'] = event['completed']
                                        for key,target in (('cache_hits','evaluation_cache_hits'),('engine_searches','evaluation_searches'),('cache_inserts','evaluation_inserts')):
                                            counts[target] += event[key]
                                        status(f"Position evaluation {event['completed']} / {event['total']}", 'Position evaluation')
                                states[game.game_id] = replace(states[game.game_id], evaluation_pending=0)
                            check_cancelled(cancel)
                            if self.quality_settings is not None and game.quality_pending:
                                with stage('Move quality'):
                                    for event in GameMoveQualityService(db, engine, self.quality_settings).run(game.game_id, cancel):
                                        counts['quality_moves_processed'] += int(event['quality'] is not None)
                                        counts['quality_completed'] = event['completed']
                                        for key,target in (('cache_hits','quality_cache_hits'),('engine_searches','quality_searches'),('cache_inserts','quality_inserts')):
                                            counts[target] += event[key]
                                        status(f"Move quality {event['completed']} / {event['total']}", 'Move quality')
                                states[game.game_id] = replace(states[game.game_id], quality_pending=0)
                            check_cancelled(cancel)
                            if game.pending_checks:
                                with stage('Tactical analyzers'):
                                    moves = load_user_moves(db, [game.game_id])
                                    for event in iter_analysis_checks(db, self.definitions, moves, engine, cancel):
                                        if event['phase'] == 'start':
                                            status(f"Analyzing move {event['move_id']}", event['analyzer'])
                                            continue
                                        if event['state'] == 'error':
                                            error = event['details']
                                            raise ReportedAnalysisFailure(reported_failure(
                                                error.get('error_type','AnalysisError'),
                                                f"Move {event['move_id']}, {event['analyzer']}: {error.get('message','Analysis failed')}"))
                                        counts['checks_processed'] += 1
                                        counts[event['state']] += 1
                                        if event['state'] in {'deferred', 'complete_deferred'}:
                                            evidence = event['details']
                                            assessment = assess_preflight_completion(evidence.get('disposition', ''), evidence.get('reason', ''))
                                            stable = assessment.state == CompletionState.COMPLETE_DEFERRED
                                            counts['stable_deferred_checks' if stable else 'retryable_deferred_checks'] += 1
                                            game_defer_reasons[(event['analyzer'], assessment.reason, assessment.state.value)] += 1
                                        counts['cache_hits'] += event['cache_hits']
                                        counts['cache_misses'] += event['cache_misses']
                                        if event['action'] == 'candidate_created':
                                            counts['candidates_created'] += 1
                                        status('Check finished', event['analyzer'])
                            check_cancelled(cancel)
                            with stage('Tactical presentation'):
                                refresh_mate_episodes(db, game.game_id)
                            current_stage = 'Readiness after completed stages'
                            with cancellable_reads(db, cancel):
                                refreshed = analysis_snapshot(db, self.definitions,
                                    GameAnalysisScope(AnalysisScopeKind.SELECTED,(game.game_id,)),
                                    self.evaluation_settings, self.quality_settings, cancel=cancel)
                            states[game.game_id] = refreshed.games[0]
                            if states[game.game_id].readiness_error:
                                value = states[game.game_id]
                                raise ReportedAnalysisFailure(reported_failure(value.readiness_error_type,value.readiness_error))
                        except Exception as error:
                            if current_stage == 'Tactical analyzers':
                                game_defer_reasons.clear()
                            failure = classify_failure(error)
                            fail(failure, current_stage)
                            states[game.game_id] = replace(states[game.game_id],
                                readiness_error=failure.message, readiness_error_type=failure.error_type)
                            if failure.disposition == FailureDisposition.DEFERRED:
                                counts['games_deferred'] += 1
                        else:
                            if states[game.game_id].needs_work:
                                counts['games_deferred'] += 1
                        state = states[game.game_id]
                        stable_count = counts['stable_deferred_checks'] - stable_before
                        if (state.pending_checks and state.pending_checks == stable_count
                                and not (state.readiness_error or state.evaluation_pending or state.quality_pending
                                         or state.presentation_pending or state.protected_checks)):
                            stable_pending_ids.add(game.game_id)
                        for (analyzer, reason, disposition), count in sorted(game_defer_reasons.items()):
                            details.append(f'Game {game.game_id}, {analyzer}: {count} {disposition}: {reason}')
                        counts['games_visited'] += 1
                        inspected_ids.add(game.game_id)
                        status('Game processing finished')
                        if fatal:
                            break
                    if fatal:
                        break
                    counts['batches_completed'] += 1
                    status('Batch completed; saved games are available in Review', phase='Batch completed')
        except AnalysisCancelled:
            pass
        except Exception as error:
            failure = classify_failure(error)
            # Preparation/lifecycle failures cannot be assigned to a recoverable game.
            fail(replace(failure, disposition=FailureDisposition.FATAL), 'Worker lifecycle')
        final = AnalysisSnapshot(tuple(states.values()))
        completed_ids = {g.game_id for g in final.games if g.complete}
        return GameAnalysisResult(games_queued=len(queued_ids), games_visited=counts['games_visited'],
            games_completed=len(queued_ids & completed_ids), games_skipped=counts['games_skipped'],
            games_remaining=len(final.queued), protected_checks=final.protected_checks,
            checks_processed=counts['checks_processed'], candidates_created=counts['candidates_created'],
            screened_out=counts['screened_out'], scouted_out=counts['scouted_out'], analyzed_no_hit=counts['analyzed_no_hit'],
            deferred=counts['deferred'], errors=counts['errors'], details=tuple(details), cancelled=cancel.is_set(),
            elapsed_seconds=time.monotonic()-started, cache_hits=counts['cache_hits'], cache_misses=counts['cache_misses'],
            engine_searches=engine.searches if engine else 0, database_changes=changes,
            positions_evaluated=counts['positions_evaluated'], evaluation_cache_hits=counts['evaluation_cache_hits'],
            evaluation_searches=counts['evaluation_searches'], evaluation_inserts=counts['evaluation_inserts'],
            quality_moves_processed=counts['quality_moves_processed'], quality_cache_hits=counts['quality_cache_hits'],
            quality_searches=counts['quality_searches'], quality_inserts=counts['quality_inserts'],
            queue_complete=selection_ready and prepared == len(scope_ids), games_deferred=counts['games_deferred'],
            games_invalid=counts['games_invalid'], recoverable_errors=counts['recoverable_errors'],
            fatal_errors=counts['fatal_errors'], batches_completed=counts['batches_completed'], scope_total=len(scope_ids),
            games_inspected=len(inspected_ids), games_waiting_deferred_coverage=len(stable_pending_ids),
            stable_deferred_checks=counts['stable_deferred_checks'], retryable_deferred_checks=counts['retryable_deferred_checks'],
            completed_deferred_checks=counts['complete_deferred'],
            games_completed_with_deferrals=sum(g.complete and g.completed_deferred_checks > 0 for g in final.games))
