"""Read-only scoped readiness using the unchanged crawler currentness contract."""
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import replace
from game_hygiene import inspect_registered_moves
from game_analysis_selection import AnalysisSelection, select_analysis_games
import sqlite3
from threading import Event
from analysis_control import check_cancelled
from analysis_deferred_repository import DeferredCheckRepository
from analysis_crawler import coverage_decision
from analysis_registry import AnalyzerDefinition
from analysis_readiness import READINESS_GAME_BATCH, readiness_moves
from evaluation_repository import EvaluationRepository
from move_quality_repository import MoveQualityRepository
from position_evaluation import EvaluationSettings
from move_quality_settings import MoveQualitySettings
from game_analysis_models import (AnalysisSnapshot, AnalysisScopeKind, GameAnalysisScope,
                                  GameAnalysisWork, CoverageProgress)


def protected_check(previous: Mapping | sqlite3.Row | None, canonical: object) -> bool:
    """Identify rows needing explicit reconciliation rather than normal analysis.

    Args:
        previous: Existing coverage row, if any.
        canonical: Truthy when the move already has a canonical candidate.

    Returns:
        Whether the existing candidate or heavy result must be protected.
    """
    return bool(canonical or (previous is not None and (
        previous['candidate_id'] is not None or
        previous['coverage_status'] in {'candidate', 'rejected', 'analyzed_no_hit'})))


def _iter_valid_readiness(connection: sqlite3.Connection, definitions: Sequence[AnalyzerDefinition],
                        scope: GameAnalysisScope, evaluation_settings: EvaluationSettings | None = None,
                        quality_settings: MoveQualitySettings | None = None, *,
                        progress: Callable[[CoverageProgress], None] = lambda event: None,
                        cancel: Event | None = None) -> Iterator[GameAnalysisWork]:
    """Yield readiness in bounded batches, retaining exact cache/protection semantics.

    Args:
        connection: Read connection with sqlite3.Row row factory.
        definitions: Current registry entries; no specialist is executed.
        scope: Real-game scope, frozen when its IDs are read.
        evaluation_settings: Required evaluation request, or None.
        quality_settings: Required quality request, or None.
        progress: Actual games checked, emitted after each completed game.
        cancel: Cooperative stop signal.

    Yields:
        Readiness for each selected game in newest-first order.

    Raises:
        AnalysisCancelled: Caller requested Stop.
        ValueError: Selected IDs are missing or development games.
        sqlite3.Error: Database read failed.
    """
    check_cancelled(cancel)
    selected_sql = ' AND game_id IN (' + ','.join('?' for _ in scope.game_ids) + ')' if scope.game_ids else ''
    games = connection.execute("SELECT game_id,white_username,black_username,played_at FROM games "
        "WHERE COALESCE(source,'')<>'dev'" + selected_sql + " ORDER BY "
        "julianday(replace(substr(played_at,1,10),'.','-') || substr(played_at,11)) DESC,game_id DESC",
        scope.game_ids).fetchall()
    if scope.game_ids and {g['game_id'] for g in games} != set(scope.game_ids):
        raise ValueError('Selected scope contains missing or development games')
    progress(CoverageProgress(0, len(games)))
    evaluation_memo, quality_memo, decision_memo = {}, {}, {}
    checked = 0
    deferred = DeferredCheckRepository(connection)
    for offset in range(0, len(games), READINESS_GAME_BATCH):
        check_cancelled(cancel)
        batch = games[offset:offset+READINESS_GAME_BATCH]
        ids = tuple(g['game_id'] for g in batch)
        marks = ','.join('?' for _ in ids)
        moves = readiness_moves(connection, ids)
        # Coverage preview needs validity metadata, never large specialist proofs.
        coverage = {(r['move_id'], r['analysis_type']): r for r in connection.execute(
            'SELECT a.move_id,a.analysis_type,a.coverage_status,a.screener_version,a.scout_version,'
            'a.scout_config,a.analyzer_version,a.candidate_id FROM moves m JOIN analysis_coverage a '
            f'ON a.move_id=m.move_id WHERE m.game_id IN ({marks}) AND m.is_user_move=1', ids)}
        canonical = {(r[0], r[1]) for r in connection.execute(
            'SELECT c.move_id,c.tactic_type FROM moves m JOIN tactic_candidates c ON c.move_id=m.move_id '
            f'WHERE m.game_id IN ({marks})', ids)}
        presentation = {r[0] for r in connection.execute(
            'SELECT DISTINCT m.game_id FROM moves m JOIN tactic_candidates c ON c.move_id=m.move_id '
            f"WHERE m.game_id IN ({marks}) AND c.tactic_type='missed_mate' "
            "AND c.candidate_status IN ('candidate','confirmed') AND NOT EXISTS "
            "(SELECT 1 FROM tactic_episode_members em WHERE em.candidate_id=c.candidate_id) "
            "AND NOT EXISTS (SELECT 1 FROM analysis_coverage a WHERE a.move_id=c.move_id "
            "AND a.analysis_type=c.tactic_type AND a.coverage_status='rejected')", ids)}
        counts = defaultdict(lambda: [0, 0, 0, 0])
        deferred_counts = defaultdict(int)
        for move in moves:
            check_cancelled(cancel)
            if move['is_user_move'] != 1:
                continue
            count = counts[move['game_id']]
            count[0] += 1
            for definition in definitions:
                key = (move['move_id'], definition.analysis_type)
                previous = coverage.get(key)
                validity = (definition.analysis_type, *(previous[field] for field in (
                    'coverage_status','screener_version','scout_version','scout_config','analyzer_version'))) if previous else (definition.analysis_type, None)
                if validity not in decision_memo:
                    decision_memo[validity] = coverage_decision(definition, previous)
                if decision_memo[validity] == 'current':
                    count[1] += 1
                elif protected_check(previous, key in canonical):
                    count[3] += 1
                elif deferred.is_current(definition, move):
                    count[1] += 1
                    deferred_counts[move['game_id']] += 1
                else:
                    count[2] += 1
        evaluations = EvaluationRepository(connection, evaluation_settings).readiness_by_game(
            ids, move_rows=moves, memo=evaluation_memo, cancel=cancel) if evaluation_settings is not None else {}
        qualities = MoveQualityRepository(connection, quality_settings).readiness_by_game(
            ids, move_rows=moves, memo=quality_memo, cancel=cancel) if quality_settings is not None else {}
        for game in batch:
            check_cancelled(cancel)
            gid = game['game_id']
            item = GameAnalysisWork(gid,
                f"{game['white_username']} vs {game['black_username']} — {game['played_at'] or 'date unknown'}",
                *counts[gid], gid in presentation, *evaluations.get(gid, (0,0)), *qualities.get(gid, (0,0)),
                completed_deferred_checks=deferred_counts[gid])
            checked += 1
            progress(CoverageProgress(checked, len(games)))
            if scope.kind != AnalysisScopeKind.NEW or not item.current_checks:
                yield item


def _iter_scope_readiness(connection: sqlite3.Connection, definitions: Sequence[AnalyzerDefinition],
                        scope: GameAnalysisScope, evaluation_settings: EvaluationSettings | None = None,
                        quality_settings: MoveQualitySettings | None = None, *,
                        progress: Callable[[CoverageProgress], None] = lambda event: None,
                        cancel: Event | None = None) -> Iterator[GameAnalysisWork]:
    """Inspect bounded groups, isolating malformed games before exact proof reads.

    Args:
        connection: Caller-owned sqlite3.Row connection.
        definitions: Unchanged registered analyzer definitions.
        scope: Frozen or requested real-game scope.
        evaluation_settings: Required exact evaluation policy, or None.
        quality_settings: Required exact quality policy, or None.
        progress: Completed readiness counts on the caller's thread.
        cancel: Cooperative Stop signal.

    Yields:
        Exact readiness or a typed-by-name game-local inspection diagnostic.
        Zero-row records are excluded; records with no legal moves are skipped.

    Raises:
        AnalysisCancelled: Stop was requested.
        ValueError: Explicit IDs are missing/development games.
        sqlite3.Error: The database itself cannot safely be read.
    """
    selection = select_analysis_games(connection, scope)
    ids = selection.game_ids
    progress(CoverageProgress(0, len(ids)))
    checked = 0
    for offset in range(0, len(ids), READINESS_GAME_BATCH):
        check_cancelled(cancel)
        batch = ids[offset:offset+READINESS_GAME_BATCH]
        rows = readiness_moves(connection, batch)
        grouped = defaultdict(list)
        for row in rows:
            grouped[row['game_id']].append(row)
        health = {gid:inspect_registered_moves(grouped[gid]) for gid in batch}
        valid = tuple(gid for gid in batch if not health[gid].empty and not health[gid].problem)
        resolved = {}
        if valid:
            selected = GameAnalysisScope(AnalysisScopeKind.SELECTED, valid)
            try:
                resolved = {g.game_id:g for g in _iter_valid_readiness(connection, definitions, selected,
                    evaluation_settings, quality_settings, cancel=cancel)}
            except (ValueError, KeyError, TypeError):
                # A malformed game must not hide later games in the same read batch.
                for gid in valid:
                    try:
                        item = next(_iter_valid_readiness(connection, definitions,
                            GameAnalysisScope(AnalysisScopeKind.SELECTED,(gid,)),
                            evaluation_settings, quality_settings, cancel=cancel))
                    except (ValueError, KeyError, TypeError) as error:
                        item = GameAnalysisWork(gid, f'Game {gid}', 0,0,0,0,
                            readiness_error=str(error), readiness_error_type=type(error).__name__)
                    resolved[gid] = item
        for gid in batch:
            check_cancelled(cancel)
            condition = health[gid]
            if condition.empty:
                item = GameAnalysisWork(gid, f'Game {gid}',0,0,0,0,skip_reason='zero legal registered moves')
            elif condition.problem:
                item = GameAnalysisWork(gid, f'Game {gid}',0,0,0,0,
                    readiness_error=condition.problem, readiness_error_type='ValueError')
            else:
                item = resolved[gid]
            item = replace(item, registered_moves=condition.legal)
            checked += 1
            progress(CoverageProgress(checked, len(ids)))
            if scope.kind != AnalysisScopeKind.NEW or not item.current_checks:
                yield item


def iter_game_readiness(connection: sqlite3.Connection, definitions: Sequence[AnalyzerDefinition],
                        scope: GameAnalysisScope, evaluation_settings: EvaluationSettings | None = None,
                        quality_settings: MoveQualitySettings | None = None, *,
                        progress: Callable[[CoverageProgress], None] = lambda event: None,
                        cancel: Event | None = None) -> Iterator[GameAnalysisWork]:
    """Apply Recent limits after exact readiness and legal-game hygiene.

    Args:
        connection: Caller-owned read connection.
        definitions: Current registry; specialists are never invoked.
        scope: Requested or explicitly frozen membership.
        evaluation_settings: Required existing evaluation contract, or None.
        quality_settings: Required existing quality contract, or None.
        progress: Number of games inspected, including excluded games.
        cancel: Cooperative stop signal.

    Yields:
        Newest actionable legal games for Recent scopes, otherwise existing readiness.

    Raises:
        AnalysisCancelled: Stop was requested.
        ValueError: Explicit IDs are unavailable.
        sqlite3.Error: The database cannot be read safely.
    """
    limit={AnalysisScopeKind.RECENT_50:50,AnalysisScopeKind.RECENT_100:100}.get(scope.kind)
    requested=replace(scope,kind=AnalysisScopeKind.NEEDING) if limit else scope
    selected=0
    for item in _iter_scope_readiness(connection,definitions,requested,evaluation_settings,
                                      quality_settings,progress=progress,cancel=cancel):
        if limit and (not item.needs_work or item.skip_reason or item.readiness_error):continue
        yield item
        selected+=1
        if limit and selected>=limit:return


def select_actionable_scope(connection: sqlite3.Connection, definitions: Sequence[AnalyzerDefinition],
                            scope: GameAnalysisScope, evaluation_settings: EvaluationSettings | None = None,
                            quality_settings: MoveQualitySettings | None = None, *,
                            progress: Callable[[CoverageProgress], None] = lambda event: None,
                            cancel: Event | None = None) -> AnalysisSelection:
    """Freeze Recent 50/100 actionable IDs without changing non-Recent preparation.

    Args:
        connection: Caller-owned read connection.
        definitions: Unchanged analyzer registry.
        scope: Requested scope.
        evaluation_settings: Existing evaluation requirements.
        quality_settings: Existing move-quality requirements.
        progress: Readiness inspection progress.
        cancel: Cooperative stop signal.

    Returns:
        Newest eligible IDs; Recent scopes exclude complete, deferred and invalid games
        before counting their limit. Other scopes retain cheap progressive batching.

    Raises:
        AnalysisCancelled: Stop was requested.
        ValueError: Explicit IDs are invalid.
        sqlite3.Error: The database cannot safely be read.
    """
    recent=scope.kind in (AnalysisScopeKind.RECENT_50,AnalysisScopeKind.RECENT_100)
    selection=select_analysis_games(connection,replace(scope,kind=AnalysisScopeKind.NEEDING) if recent else scope)
    if not recent:return selection
    return AnalysisSelection(tuple(g.game_id for g in iter_game_readiness(connection,definitions,scope,
        evaluation_settings,quality_settings,progress=progress,cancel=cancel)),selection.empty_ids)


def analysis_snapshot(connection: sqlite3.Connection, definitions: Sequence[AnalyzerDefinition],
                      scope: GameAnalysisScope, evaluation_settings: EvaluationSettings | None = None,
                      quality_settings: MoveQualitySettings | None = None, *,
                      progress: Callable[[CoverageProgress], None] = lambda event: None,
                      cancel: Event | None = None) -> AnalysisSnapshot:
    """Collect exact readiness without engine requests or database writes.

    Args:
        connection: Caller-owned sqlite3.Row connection.
        definitions: Current registry entries.
        scope: Frozen real-game selection.
        evaluation_settings: Required evaluation profile, or None.
        quality_settings: Required quality profile, or None.
        progress: Callback for completed coverage checks.
        cancel: Optional cancellation event.

    Returns:
        An immutable scope snapshot.

    Raises:
        AnalysisCancelled: Preparation was cancelled.
        ValueError: Invalid selected scope.
        sqlite3.Error: Database read failed.
    """
    selection = select_analysis_games(connection, scope)
    games=tuple(iter_game_readiness(connection, definitions, scope,
        evaluation_settings, quality_settings, progress=progress, cancel=cancel))
    recent=scope.kind in (AnalysisScopeKind.RECENT_50,AnalysisScopeKind.RECENT_100)
    return AnalysisSnapshot(games, len(games) if recent else len(selection.game_ids), selection.empty_ids)
