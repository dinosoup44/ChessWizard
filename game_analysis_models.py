"""Portable scope and progress contracts for explicit user-started analysis."""
from dataclasses import dataclass
from enum import StrEnum


class AnalysisScopeKind(StrEnum):
    """Choose an explicit analysis scope without changing proof policy."""
    RECENT_50 = "Recent 50"
    RECENT_100 = "Recent 100"
    NEEDING = "All Missing / Continue Full History"
    NEW = "New games (no current coverage)"
    SELECTED = "Selected game"


@dataclass(frozen=True)
class GameAnalysisScope:
    """Select real games; recent scopes mean the newest eligible stored games.

    Args:
        kind: Selected, recent or progressively discovered full-history scope.
        game_ids: Optional explicit frozen membership; required for Selected.
    """
    kind: AnalysisScopeKind = AnalysisScopeKind.NEEDING
    game_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        """Validate explicit IDs without reading a database."""
        object.__setattr__(self, "kind", AnalysisScopeKind(self.kind))
        if any(type(i) is not int or i < 1 for i in self.game_ids):
            raise ValueError("Game IDs must be positive integers")
        if self.kind == AnalysisScopeKind.SELECTED and not self.game_ids:
            raise ValueError("Select a game in Game Review first")


@dataclass(frozen=True)
class GameAnalysisWork:
    """Describe one game's exact readiness or a game-local inspection failure.

    Args:
        game_id: Stored identity.
        label: Human-readable players and date.
        user_moves: Registered moves made by the selected account.
        current_checks: Compatible completed tactical checks.
        pending_checks: Checks eligible for normal analysis.
        protected_checks: Checks requiring separate reconciliation.
        presentation_pending: Missing mate presentation.
        evaluation_positions: Actual-position obligations.
        evaluation_pending: Missing exact evaluation evidence.
        quality_moves: Actual move-quality obligations.
        quality_pending: Missing exact move-quality evidence.
        registered_moves: Total legal registered moves, including the opponent.
        skip_reason: Empty-record exclusion; no analysis may run.
        readiness_error: Game-local inspection diagnostic, if any.
        readiness_error_type: Original exception type for recovery policy.
        completed_deferred_checks: Current durable conservative receipts, not tactic conclusions.
    """
    game_id: int
    label: str
    user_moves: int
    current_checks: int
    pending_checks: int
    protected_checks: int
    presentation_pending: bool = False
    evaluation_positions: int = 0
    evaluation_pending: int = 0
    quality_moves: int = 0
    quality_pending: int = 0

    registered_moves: int = 0
    skip_reason: str = ''
    readiness_error: str = ''
    readiness_error_type: str = ''
    completed_deferred_checks: int = 0

    @property
    def needs_work(self) -> bool:
        """Return whether analysis or game-local failure handling is required.

        Returns:
            False for empty records; otherwise exact pending work.
        """
        return not self.skip_reason and bool(self.readiness_error or self.pending_checks or
            self.presentation_pending or self.evaluation_pending or self.quality_pending)

    @property
    def complete(self) -> bool:
        """Return whether a nonempty game's required stages are current.

        Returns:
            True only when no pending, protected or invalid obligation remains.
        """
        return bool(self.registered_moves or self.user_moves) and not (self.needs_work or self.protected_checks or self.skip_reason)


@dataclass(frozen=True)
class AnalysisSnapshot:
    """Expose inspected readiness without implying uninspected history is complete.

    Args:
        games: Exact inspected game readiness.
        eligible_games: Cheap metadata count for the frozen scope.
        skipped_empty_ids: Records with no registered moves excluded by selection.
        scope_complete: Whether every eligible game was inspected.
    """
    games: tuple[GameAnalysisWork, ...]
    eligible_games: int = 0
    skipped_empty_ids: tuple[int, ...] = ()
    scope_complete: bool = True

    @property
    def queued(self) -> tuple[GameAnalysisWork, ...]:
        """Return inspected games needing processing.

        Returns:
            Pending inspected games only.
        """
        return tuple(g for g in self.games if g.needs_work)

    @property
    def complete_games(self) -> int:
        """Count inspected games with all required work complete.

        Returns:
            Exact completed-game count.
        """
        return sum(g.complete for g in self.games)

    @property
    def protected_checks(self) -> int:
        """Count protected checks within inspected games.

        Returns:
            Checks left for an explicitly approved reconciliation.
        """
        return sum(g.protected_checks for g in self.games)


@dataclass(frozen=True)
class AnalysisProgress:
    """Describe real worker progress; active-stage counters are provisional.

    Args:
        message: Current operation in plain language.
        games_queued: Frozen queue length.
        games_visited: Games whose processing has finished.
        game_id: Active internal game ID, if analysis has begun.
        game_label: Human-readable game identity.
        analyzer: Current evaluation/quality/tactical/presentation stage.
        checks_processed: Finished tactical checks in committed or active stages.
        candidates_created: Candidates in committed or active stages.
        errors: Observed retryable failures.
        elapsed_seconds: Monotonic elapsed worker time.
        evaluation_completed: Positions visited in the active game's evaluation stage.
        evaluation_total: Actual positions in that game.
        quality_completed: Moves visited in its quality stage.
        quality_total: Actual moves in that game.
        phase: Coverage preparation or game analysis.
        coverage_checked: Games whose required evidence has been inspected.
        coverage_total: Frozen coverage scope size.
        batch_index: One-based batch number.
        batch_count: Number of metadata windows in the frozen scope.
        batch_start: One-based first eligible game in this window.
        batch_end: Last eligible game in this window.
        scope_total: Total eligible games, not an invented pending-work count.
        games_inspected: Games finished or skipped in this run, independent of outcome.
        batch_completed: Complete games in this window, including already current.
        overall_completed: Complete games among inspected windows.
        games_deferred: Games left incomplete by uncertainty/planning deferral.
        recoverable_errors: Game-local failures; later games can continue.
        fatal_errors: Unsafe system failures; the run stops.
    """
    message: str
    games_queued: int = 0
    games_visited: int = 0
    game_id: int | None = None
    game_label: str = ""
    analyzer: str = ""
    checks_processed: int = 0
    candidates_created: int = 0
    errors: int = 0
    elapsed_seconds: float = 0
    evaluation_completed: int = 0
    evaluation_total: int = 0
    quality_completed: int = 0
    quality_total: int = 0
    phase: str = "Analyzing games"
    coverage_checked: int = 0
    coverage_total: int = 0
    batch_index: int = 0
    batch_count: int = 0
    batch_start: int = 0
    batch_end: int = 0
    scope_total: int = 0
    games_inspected: int = 0
    batch_completed: int = 0
    overall_completed: int = 0
    games_deferred: int = 0
    recoverable_errors: int = 0
    fatal_errors: int = 0


@dataclass(frozen=True)
class CoverageProgress:
    """Report real completed-game coverage counts.

    Args:
        checked: Games whose required stages have been inspected.
        total: Frozen selected-game count.
    """
    checked: int
    total: int

    @property
    def percent(self) -> float:
        """Return the fraction inspected as a percentage.

        Returns:
            A percentage, with an empty scope considered fully inspected.
        """
        return 100 * self.checked / self.total if self.total else 100.0


@dataclass(frozen=True)
class GameAnalysisResult:
    """Summarize durable work and attempted engine cost after the worker exits.

    Args:
        games_queued: Initial queue length.
        games_visited: Games whose processing finished.
        games_completed: Initially queued games now fully current.
        games_skipped: Already complete games.
        games_remaining: Known unfinished games in the prepared scope.
        protected_checks: Stale heavy/canonical results left protected.
        checks_processed: Tactical checks retained after rollback.
        candidates_created: New durable canonical candidates.
        screened_out: Completed static rejections.
        scouted_out: Completed scout rejections.
        analyzed_no_hit: Completed heavy no-hits.
        deferred: Planning-only deferred checks.
        errors: Recorded failures; cancellation itself is not an error.
        details: Per-game deferral/error/skip explanations.
        cancelled: Whether Stop was requested.
        elapsed_seconds: Monotonic worker duration.
        cache_hits: Tactical evidence reused by retained stages.
        cache_misses: Tactical evidence generated by retained stages.
        engine_searches: All attempted searches, including aborted-stage cost.
        database_changes: Changes committed by completed stages only.
        positions_evaluated: Evaluation positions in retained stages.
        evaluation_cache_hits: Evaluation evidence reused by retained stages.
        evaluation_searches: Evaluation searches in retained stages.
        evaluation_inserts: Evaluation cache inserts retained.
        quality_moves_processed: Quality moves in retained stages.
        quality_cache_hits: Quality evidence reused by retained stages.
        quality_searches: Quality searches in retained stages.
        quality_inserts: Quality cache inserts retained.
        queue_complete: Whether all scope windows were inspected; False means remaining work is unknown.
        games_deferred: Visited games still incomplete due to uncertainty/planning.
        games_invalid: Empty/invalid records skipped without analysis.
        recoverable_errors: Per-game failures after rollback; processing continued.
        fatal_errors: System failures requiring a safe stop.
        batches_completed: Fully visited scope windows.
        scope_total: Eligible stored games in the frozen scope.
        games_inspected: Finished/skipped games, including unresolved outcomes.
        games_waiting_deferred_coverage: Games blocked only by proven stable planning outcomes.
        stable_deferred_checks: Checks satisfying an approved conservative preflight predicate.
        retryable_deferred_checks: Planning checks without a terminal completion contract.
        completed_deferred_checks: Durable conservative receipts written/reused during this run.
        games_completed_with_deferrals: Complete scope games having current conservative receipts.
    """
    games_queued: int = 0
    games_visited: int = 0
    games_completed: int = 0
    games_skipped: int = 0
    games_remaining: int = 0
    protected_checks: int = 0
    checks_processed: int = 0
    candidates_created: int = 0
    screened_out: int = 0
    scouted_out: int = 0
    analyzed_no_hit: int = 0
    deferred: int = 0
    errors: int = 0
    details: tuple[str, ...] = ()
    cancelled: bool = False
    elapsed_seconds: float = 0
    cache_hits: int = 0
    cache_misses: int = 0
    engine_searches: int = 0
    database_changes: int = 0
    positions_evaluated: int = 0
    evaluation_cache_hits: int = 0
    evaluation_searches: int = 0
    evaluation_inserts: int = 0
    quality_moves_processed: int = 0
    quality_cache_hits: int = 0
    quality_searches: int = 0
    quality_inserts: int = 0
    queue_complete: bool = True
    games_deferred: int = 0
    games_invalid: int = 0
    recoverable_errors: int = 0
    fatal_errors: int = 0
    batches_completed: int = 0
    scope_total: int = 0
    games_inspected: int = 0

    games_waiting_deferred_coverage: int = 0
    stable_deferred_checks: int = 0
    retryable_deferred_checks: int = 0
    completed_deferred_checks: int = 0
    games_completed_with_deferrals: int = 0

    @property
    def progress_percent(self) -> float:
        """Return run inspection progress, independent of chess completion.

        Returns:
            Inspected fraction; stopped/failed runs retain partial progress.
        """
        return (min(100.0, 100 * self.games_inspected / self.scope_total) if self.scope_total
                else 100.0 if self.queue_complete and not self.cancelled and not self.fatal_errors else 0.0)

    @property
    def remaining_explanation(self) -> str:
        """Describe unresolved bookkeeping separately from actionable work.

        Returns:
            Concise outcome text suitable for any frontend.
        """
        retryable = max(0, self.games_remaining - self.games_waiting_deferred_coverage)
        parts = []
        if self.games_waiting_deferred_coverage:
            parts.append(f'{self.games_waiting_deferred_coverage:,} games await durable coverage for conservative deferrals')
        if retryable:
            parts.append(f'{retryable:,} games need retryable work (reasons below)')
        if self.protected_checks:
            parts.append(f'{self.protected_checks:,} protected stale checks need separate review')
        if not self.queue_complete:
            parts.append('older/uninspected work is not counted')
        return '; '.join(parts)

    def summary(self) -> str:
        """Format durable results without claiming an unfinished count is zero.

        Returns:
            A human-readable summary including per-game failure details.
        """
        lines = [f"Games inspected: {self.games_inspected:,} / {self.scope_total:,}",
                 f"Games awaiting deferred-coverage support: {self.games_waiting_deferred_coverage:,}",
                 f"Still needing retryable work: {max(0, self.games_remaining-self.games_waiting_deferred_coverage):,}",
                 f"Actual positions processed: {self.positions_evaluated:,}",
                 f"Evaluation cache hits / searches: {self.evaluation_cache_hits:,} / {self.evaluation_searches:,}",
                 f"Move quality processed: {self.quality_moves_processed:,}",
                 f"Move quality cache hits / searches: {self.quality_cache_hits:,} / {self.quality_searches:,}",
                 f"Games completed: {self.games_completed:,}",
                 f"Games already complete: {self.games_skipped:,}",
                 f"Complete with conservative deferrals (scope): {self.games_completed_with_deferrals:,}",
                 f"Durable deferred checks completed this run: {self.completed_deferred_checks:,}",
                 f"Visited games left incomplete: {self.games_deferred:,}",
                 f"Games skipped as invalid/empty: {self.games_invalid:,}",
                 f"Recoverable errors: {self.recoverable_errors:,}",
                 f"Fatal errors: {self.fatal_errors:,}",
                 f"Batches completed: {self.batches_completed:,}",
                 (f"Games still needing work: {self.games_remaining:,}" if self.queue_complete else "Games still needing work: Not counted (coverage check unfinished)"),
                 f"Analyzer checks processed: {self.checks_processed:,}",
                 f"New tactical candidates: {self.candidates_created:,}",
                 f"Deferred checks: {self.deferred:,} (stable: {self.stable_deferred_checks:,}; retryable/unclassified: {self.retryable_deferred_checks:,})", f"Protected stale checks: {self.protected_checks:,}",
                 f"Errors: {self.errors:,}", f"Elapsed: {self.elapsed_seconds:.1f} seconds"]
        return "\n".join(lines + list(self.details))
