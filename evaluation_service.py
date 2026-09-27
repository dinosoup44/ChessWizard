"""Actual-position evidence composed into caller-owned atomic analysis stages."""
from __future__ import annotations
from collections.abc import Iterator
from threading import Event
from typing import Any, TYPE_CHECKING
import chess.engine
from analysis_settings import EngineSettings
import sqlite3
from analysis_control import check_cancelled
from evidence_errors import IncompleteLineEvidence, EngineIdentityMismatch
if TYPE_CHECKING:
    from analysis_engine import LazyScoutEngine

from candidate_line_engine import CandidateLineGenerator
from candidate_line_repository import CandidateLineRepository
from candidate_line_service import CandidateLineService
from evaluation_repository import EvaluationRepository
from position_evaluation import EvaluationSettings, evaluation_from_lines

class IdentifiedEvaluationEngine:
    """Verify running-engine identity before evidence can reach persistence.

    Args:
        shared_engine: Worker-owned shared engine boundary.
        settings: Required raw-engine identity/settings.
    """
    def __init__(self, shared_engine: LazyScoutEngine, settings: EngineSettings) -> None:
        """Bind the shared engine and exact expected identity.

        Args:
            shared_engine: Worker engine with cancellation support.
            settings: Expected identity from the shared settings model.
        """
        self.shared_engine = shared_engine
        self.settings = settings

    def analyse(self, *args: Any, **kwargs: Any) -> chess.engine.InfoDict | list[chess.engine.InfoDict]:
        """Request engine information and reject a mismatched engine identity.

        Args:
            args: Exact board and search limit passed to the shared engine.
            kwargs: Exact MultiPV, options and root restrictions.

        Returns:
            Unmodified engine information after identity verification.

        Raises:
            EngineIdentityMismatch: The engine cannot satisfy the configured identity.
            AnalysisCancelled: Stop interrupted the shared request.
        """
        result = self.shared_engine.analyse(*args, **kwargs)
        actual = self.shared_engine.engine.id.get('name', '')
        expected = f'{self.settings.engine_name} {self.settings.engine_version}'
        if actual != expected and not actual.startswith(expected + ' '):
            raise EngineIdentityMismatch('Running engine does not match evaluation profile identity')
        return result

class GameEvaluationService:
    """Generate missing exact evidence while respecting outer stage transactions.

    Args:
        connection: Caller-owned cache connection.
        shared_engine: Single worker engine; owns cancellation and process lifetime.
        settings: Unchanged shared evidence/interpretation settings.
        line_service: Optional exact-evidence provider for isolated tools/tests.
    """
    def __init__(self, connection: sqlite3.Connection, shared_engine: LazyScoutEngine,
                 settings: EvaluationSettings = EvaluationSettings(), *, line_service: CandidateLineService | None = None) -> None:
        """Bind shared evidence services without starting an engine.

        Args:
            connection: Caller-owned cache connection.
            shared_engine: Single worker engine with cancellation support.
            settings: Existing exact-request and interpretation settings.
            line_service: Optional evidence service for isolated tools/tests.
        """
        self.connection = connection
        self.settings = settings
        self.repository = EvaluationRepository(connection, settings)
        self.lines = line_service if line_service is not None else CandidateLineService(
            CandidateLineGenerator(IdentifiedEvaluationEngine(shared_engine, settings.generator.engine)),
            write_store=CandidateLineRepository(connection))

    def run(self, game_id: int, cancel: Event) -> Iterator[dict[str, Any]]:
        """Yield validated progress; an outer transaction owns stage durability.

        Args:
            game_id: Exact real game being processed.
            cancel: Stop signal; incomplete requests are never committed.

        Yields:
            Progress records containing completed evidence and request counters.

        Raises:
            AnalysisCancelled: Stop interrupted a request or preceded its commit.
            IncompleteLineEvidence: Evidence is insufficient; the unfinished stage remains retryable.
            ValueError: Stored moves/evidence fail the existing validation contract.
            sqlite3.Error: Cache persistence failed.
        """
        positions = self.repository.positions(game_id)
        for index, position in enumerate(positions, 1):
            if cancel.is_set():
                break
            before = self.lines.stats.copy()
            owns_transaction = not self.connection.in_transaction
            try:
                lines = self.lines.candidate_lines(position.fen, self.settings.generator)
                value = evaluation_from_lines(position, lines, self.settings)
                if not value.complete:
                    raise IncompleteLineEvidence('Incomplete position evaluation; retry on resume')
                check_cancelled(cancel)
                if owns_transaction:
                    self.connection.commit()
            except BaseException:
                if owns_transaction:
                    self.connection.rollback()
                raise
            yield {'completed':index, 'total':len(positions), 'evaluation':value,
                   **{k:self.lines.stats[k]-before[k] for k in ('cache_hits','cache_misses','engine_searches','cache_inserts')}}
