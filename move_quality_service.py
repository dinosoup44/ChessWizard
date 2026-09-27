"""One reusable move-quality evidence stage inside the existing game orchestrator."""
from __future__ import annotations
from collections.abc import Iterator
from threading import Event
from typing import Any, TYPE_CHECKING
import sqlite3
from analysis_control import check_cancelled
from evidence_errors import IncompleteLineEvidence
if TYPE_CHECKING:
    from analysis_engine import LazyScoutEngine

from candidate_lines import CandidateLineSet
from candidate_line_engine import CandidateLineGenerator
from candidate_line_repository import CandidateLineRepository
from candidate_line_service import CandidateLineService
from evaluation_service import IdentifiedEvaluationEngine
from move_quality import assess_move, compatible_lines
from move_quality_repository import MoveQualityRepository
from move_quality_settings import MoveQualitySettings


class GameMoveQualityService:
    """Generate missing exact evidence while respecting outer stage transactions.

    Args:
        connection: Caller-owned cache connection.
        shared_engine: Single worker engine; owns cancellation and process lifetime.
        settings: Unchanged shared evidence/interpretation settings.
        line_service: Optional exact-evidence provider for isolated tools/tests.
    """
    def __init__(self, connection: sqlite3.Connection, shared_engine: LazyScoutEngine,
                 settings: MoveQualitySettings = MoveQualitySettings(), *, line_service: CandidateLineService | None = None) -> None:
        """Bind shared evidence services without starting an engine.

        Args:
            connection: Caller-owned cache connection.
            shared_engine: Single worker engine with cancellation support.
            settings: Existing exact-request and interpretation settings.
            line_service: Optional evidence service for isolated tools/tests.
        """
        self.connection, self.settings = connection, settings
        self.repository = MoveQualityRepository(connection, settings)
        self.lines = line_service if line_service is not None else CandidateLineService(
            CandidateLineGenerator(IdentifiedEvaluationEngine(shared_engine, settings.generator.engine)),
            write_store=CandidateLineRepository(connection))

    def _request(self, fen: str, root_moves: tuple[str, ...] = (), cancel: Event | None = None) -> CandidateLineSet:
        owns_transaction = not self.connection.in_transaction
        try:
            lines = self.lines.candidate_lines(fen, self.settings.generator, root_moves=root_moves)
            if lines.generation_metadata.get('complete') is not True:
                raise IncompleteLineEvidence('Incomplete move-quality evidence; retry on resume')
            if not compatible_lines(lines, fen, self.settings, root_moves):
                raise ValueError('Incomplete or incompatible move-quality evidence')
            check_cancelled(cancel)
            if owns_transaction:
                self.connection.commit()
            return lines
        except BaseException:
            if owns_transaction:
                self.connection.rollback()
            raise

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
        moves = self.repository.moves(game_id)
        for index, move in enumerate(moves, 1):
            if cancel.is_set():
                break
            before = self.lines.stats.copy()
            root = self._request(move.fen, cancel=cancel)
            value = assess_move(move, root, settings=self.settings)
            if value.state == 'missing_played_evidence':
                if cancel.is_set():
                    yield {'completed':index-1, 'total':len(moves), 'quality':None,
                           **{k:self.lines.stats[k]-before[k] for k in ('cache_hits','cache_misses','engine_searches','cache_inserts')}}
                    break
                value = assess_move(move, root, self._request(move.fen, (move.played_move,), cancel), self.settings)
            yield {'completed':index, 'total':len(moves), 'quality':value,
                   **{k:self.lines.stats[k]-before[k] for k in ('cache_hits','cache_misses','engine_searches','cache_inserts')}}
