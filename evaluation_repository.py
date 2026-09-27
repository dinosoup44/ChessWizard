"""Read-only actual-game timelines over the existing exact-request evidence cache."""
from collections.abc import Iterable, Sequence
from threading import Event
import sqlite3
from analysis_control import check_cancelled
from analysis_readiness import readiness_moves
from candidate_line_repository import CandidateLineRepository
from candidate_line_request import request_identity
from game_review_repository import GameReviewRepository
from position_evaluation import EvaluationSettings, PositionEvaluation, actual_positions, evaluation_from_lines

class EvaluationRepository:
    """Read derived game evidence without engine work or persistence.

    Args:
        connection: Caller-owned database connection.
        settings: Exact shared evidence profile and interpretation settings.
    """
    def __init__(self, connection: sqlite3.Connection, settings: EvaluationSettings = EvaluationSettings()) -> None:
        """Bind the read-only evidence view.

        Args:
            connection: Caller-owned SQLite connection.
            settings: Shared evidence and interpretation settings.
        """
        self.connection = connection
        self.settings = settings
        self.lines = CandidateLineRepository(connection)

    def positions(self, game_id):
        return actual_positions(game_id, GameReviewRepository(self.connection).moves(game_id))

    def timeline(self, game_id):
        memo = {}
        result = []
        for position in self.positions(game_id):
            try:
                if position.fen not in memo:
                    memo[position.fen] = self.lines.get(position.fen, request_identity(self.settings.generator))
                value = evaluation_from_lines(position, memo[position.fen], self.settings)
            except (ValueError,KeyError,TypeError):
                value = PositionEvaluation(position, provenance='invalid_cached_evidence')
            result.append(value)
        return tuple(result)

    def readiness(self, game_id):
        values = self.timeline(game_id)
        return len(values), sum(not value.complete for value in values)

    def readiness_by_game(self, game_ids: Iterable[int] | None = None, *,
                          move_rows: Sequence[sqlite3.Row] | None = None,
                          memo: dict[str, bool] | None = None, cancel: Event | None = None) -> dict[int, list[int]]:
        """Count compatible actual-position evidence only within the requested scope.

        Args:
            game_ids: Explicit game IDs, or None for all games.
            move_rows: Optional already-loaded rows from readiness_moves.
            memo: Optional snapshot-local validated FEN summaries.
            cancel: Cooperative cancellation signal.

        Returns:
            Game IDs mapped to total and pending actual-position counts.

        Raises:
            AnalysisCancelled: The caller requested Stop.
            sqlite3.Error: Database read failed.
        """
        from position_evaluation import GamePosition
        rows = readiness_moves(self.connection, game_ids) if move_rows is None else move_rows
        memo = {} if memo is None else memo
        positions, seen = [], set()
        for row in rows:
            game_id = row['game_id']
            fens = (row['fen_after'],) if game_id in seen else (row['fen_before'], row['fen_after'])
            seen.add(game_id)
            positions.extend((game_id, fen) for fen in fens)
        identity = request_identity(self.settings.generator)
        needed = {(fen, identity) for _, fen in positions if fen not in memo}
        for (fen, _), lines in self.lines.get_many(sorted(needed), cancel=cancel).items():
            check_cancelled(cancel)
            try:
                memo[fen] = evaluation_from_lines(GamePosition(0,None,0,fen,''), lines, self.settings).complete
            except (ValueError, KeyError, TypeError):
                memo[fen] = False
        counts = {}
        for game_id, fen in positions:
            count = counts.setdefault(game_id, [0,0])
            count[0] += 1
            count[1] += int(not memo[fen])
        return counts
