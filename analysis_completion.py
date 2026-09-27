"""Classify obligation outcomes without authorizing persistence or chess claims."""
from dataclasses import dataclass
from enum import StrEnum
from analysis_failures import AnalysisFailure, FailureDisposition


class CompletionState(StrEnum):
    """Separate evaluated obligations from retryable work and execution failures."""
    COMPLETE_DECISION = 'complete_decision'
    COMPLETE_DEFERRED = 'complete_deferred'
    INCOMPLETE_RETRYABLE = 'incomplete_retryable'
    FAILED_RECOVERABLE = 'failed_recoverable'
    FAILED_FATAL = 'failed_fatal'


@dataclass(frozen=True)
class CompletionAssessment:
    """Describe completion semantics independently of durable coverage.

    Args:
        state: Logical outcome under the evaluated contract, not a coverage status.
        reason: Exact diagnostic or approved predicate identifier.
        invalidation: Dependencies that require evaluating the obligation again.
    """
    state: CompletionState
    reason: str
    invalidation: str = ''


# Only predicates already proved by the opt-in preflight qualify. An arbitrary
# label, absent evidence, or an exception cannot establish terminal uncertainty.
_STABLE_PREFLIGHT = {
    ('cached_quick_rejected', 'every_geometric_alternative_fails_current_cached_quick_policy'):
        'move, analyzer/screener/scout/preflight policy, exact raw request and evidence',
    ('mate_deferred', 'current_quick_baseline_requires_material_mate_deferral'):
        'move, analyzer/screener/scout/preflight policy, exact baseline evidence',
    ('played_checkmate', 'actual_played_move_delivered_checkmate'):
        'move, terminal board fact, analyzer/screener/scout/preflight policy',
    ('already_owned', 'every_geometric_alternative_has_another_canonical_owner'):
        'move, analyzer/screener/scout/preflight policy, live canonical ownership',
}


def assess_preflight_completion(disposition: str, reason: str) -> CompletionAssessment:
    """Classify a predicate successfully evaluated by the existing preflight.

    This is a reporting contract, never permission to skip readiness or write
    negative coverage. Durable reuse additionally requires dependency validation.

    Args:
        disposition: Structured disposition returned by the registered preflight.
        reason: Exact predicate identifier produced with its provenance.

    Returns:
        Stable conservative completion only for approved complete predicates;
        unknown, mixed, missing and failed evidence remains retryable.
    """
    dependency = _STABLE_PREFLIGHT.get((disposition, reason))
    return CompletionAssessment(
        CompletionState.COMPLETE_DEFERRED if dependency else CompletionState.INCOMPLETE_RETRYABLE,
        reason or 'unclassified_planning_defer', dependency or '')


def assess_decision_completion(status: str, *, current: bool) -> CompletionAssessment:
    """Classify existing durable decisions using the caller's currentness check.

    Args:
        status: Existing coverage status; no new status is inferred from details.
        current: Whether shared version/configuration checks passed.

    Returns:
        Completed decision for current positive/negative coverage, else retryable.
    """
    completed = current and status in {'candidate', 'rejected', 'screened_out', 'scouted_out', 'analyzed_no_hit'}
    return CompletionAssessment(CompletionState.COMPLETE_DECISION if completed else
                                CompletionState.INCOMPLETE_RETRYABLE, status)


def assess_failure_completion(failure: AnalysisFailure | None = None) -> CompletionAssessment:
    """Keep incomplete evidence and cancellation retryable without inventing scores.

    Args:
        failure: Classified execution failure; None represents cancellation.

    Returns:
        Retryable uncertainty/cancellation or the existing recoverable/fatal state.
    """
    if failure is None:
        return CompletionAssessment(CompletionState.INCOMPLETE_RETRYABLE, 'cancelled')
    states = {FailureDisposition.DEFERRED: CompletionState.INCOMPLETE_RETRYABLE,
              FailureDisposition.RECOVERABLE: CompletionState.FAILED_RECOVERABLE,
              FailureDisposition.FATAL: CompletionState.FAILED_FATAL}
    return CompletionAssessment(states[failure.disposition], failure.error_type)
