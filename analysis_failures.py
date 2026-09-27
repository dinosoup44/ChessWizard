"""Portable failure policy for game-local recovery and safe system shutdown."""
from dataclasses import dataclass
from enum import StrEnum
import sqlite3
import chess.engine
from evidence_errors import IncompleteLineEvidence, EngineIdentityMismatch


class FailureDisposition(StrEnum):
    """Describe whether the worker may safely proceed to another game."""
    DEFERRED = 'deferred'
    RECOVERABLE = 'recoverable'
    FATAL = 'fatal'


@dataclass(frozen=True)
class AnalysisFailure:
    """Retain a game-local diagnostic without persisting a chess conclusion.

    Args:
        disposition: Continue/defer/stop policy.
        error_type: Original exception type, including adapter-reported failures.
        message: Original diagnostic.
    """
    disposition: FailureDisposition
    error_type: str
    message: str


class ReportedAnalysisFailure(Exception):
    """Unwind the active stage when an adapter reports a structured failure.

    Args:
        failure: Original classified diagnostic, preserved across rollback.
    """
    def __init__(self, failure: AnalysisFailure) -> None:
        """Bind the diagnostic to the stage-unwind exception.

        Args:
            failure: Failure whose disposition the orchestrator must honor.
        """
        self.failure = failure
        super().__init__(failure.message)


FATAL_ERROR_NAMES = frozenset({'EngineIdentityMismatch', 'DatabaseError', 'OperationalError', 'IntegrityError',
    'ProgrammingError', 'DataError', 'InterfaceError', 'InternalError',
    'FileNotFoundError', 'PermissionError', 'EngineTerminatedError', 'EngineError',
    'TimeoutError', 'OSError', 'AssertionError', 'MemoryError', 'SystemError'})


def reported_failure(error_type: str, message: str) -> AnalysisFailure:
    """Classify a specialist diagnostic without fabricating evidence.

    Args:
        error_type: Original type retained by the shared adapter.
        message: Original explanation.

    Returns:
        Deferred uncertainty, game-local recovery, or a fatal system failure.
    """
    disposition = (FailureDisposition.DEFERRED if error_type == 'IncompleteLineEvidence'
                   else FailureDisposition.FATAL if error_type in FATAL_ERROR_NAMES
                   else FailureDisposition.RECOVERABLE)
    return AnalysisFailure(disposition, error_type, message)


def classify_failure(error: Exception) -> AnalysisFailure:
    """Determine whether another game can be processed safely.

    Args:
        error: Exception after the active transaction has rolled back.

    Returns:
        A diagnostic retaining the exception type and safe recovery policy.
    """
    if isinstance(error, ReportedAnalysisFailure):
        return error.failure
    if isinstance(error, IncompleteLineEvidence):
        disposition = FailureDisposition.DEFERRED
    elif isinstance(error, (EngineIdentityMismatch, sqlite3.Error, OSError, chess.engine.EngineError,
                            AssertionError, MemoryError, SystemError)):
        disposition = FailureDisposition.FATAL
    else:
        disposition = FailureDisposition.RECOVERABLE
    return AnalysisFailure(disposition, type(error).__name__, str(error))
