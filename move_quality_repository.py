"""Read-only derived move metrics over the existing candidate-line cache."""
from collections.abc import Iterable, Sequence
from threading import Event
import sqlite3
from analysis_control import check_cancelled
from analysis_readiness import readiness_moves
from candidate_line_repository import CandidateLineRepository
from candidate_line_request import request_identity
from game_review_repository import GameReviewRepository
from move_quality import GameQuality, assess_move, compatible_lines, quality_moves
from move_quality_settings import MoveQualitySettings


class MoveQualityRepository:
    """Read derived game evidence without engine work or persistence.

    Args:
        connection: Caller-owned database connection.
        settings: Exact shared evidence profile and interpretation settings.
    """
    def __init__(self, connection: sqlite3.Connection, settings: MoveQualitySettings = MoveQualitySettings()) -> None:
        """Bind the read-only evidence view.

        Args:
            connection: Caller-owned SQLite connection.
            settings: Shared evidence and interpretation settings.
        """
        self.connection, self.settings = connection, settings
        self.lines = CandidateLineRepository(connection)

    def moves(self, game_id):
        return quality_moves(game_id, GameReviewRepository(self.connection).moves(game_id))

    def get_lines(self, fen, root_moves=()):
        try:
            return self.lines.get(fen, request_identity(self.settings.generator, root_moves))
        except (ValueError, KeyError, TypeError):
            return None

    def assess(self, move):
        root = self.get_lines(move.fen)
        value = assess_move(move, root, settings=self.settings)
        if value.state == 'missing_played_evidence':
            value = assess_move(move, root, self.get_lines(move.fen, (move.played_move,)), self.settings)
        return value

    def game(self, game_id, user_color):
        return GameQuality(tuple(self.assess(move) for move in self.moves(game_id)), user_color)

    def readiness_by_game(self, game_ids: Iterable[int], *, move_rows: Sequence[sqlite3.Row] | None = None,
                          memo: dict | None = None, cancel: Event | None = None) -> dict[int, list[int]]:
        """Count root/played evidence obligations without changing quality policy.

        Args:
            game_ids: Exact games to inspect.
            move_rows: Optional already-loaded rows from readiness_moves.
            memo: Optional snapshot-local exact-request summaries.
            cancel: Cooperative stop signal.

        Returns:
            Game IDs mapped to total and pending move counts. Contradictory but
            complete evidence remains complete, matching the existing contract.

        Raises:
            AnalysisCancelled: The caller requested Stop.
            sqlite3.Error: Database read failed.
        """
        rows = readiness_moves(self.connection, game_ids) if move_rows is None else move_rows
        memo = {} if memo is None else memo
        identity = self.settings.raw_identity
        roots = {(r['fen_before'], identity) for r in rows if (r['fen_before'], identity) not in memo}
        for (fen, key), lines in self.lines.get_many(sorted(roots), cancel=cancel).items():
            memo[fen, key] = (frozenset(line.move_uci for line in lines.lines)
                             if compatible_lines(lines, fen, self.settings) else None)
        restricted = {}
        identities = {}
        for row in rows:
            check_cancelled(cancel)
            fen, played = row['fen_before'], row['uci_played']
            root = memo[fen, identity]
            if root and played not in root:
                if played not in identities:
                    identities[played] = request_identity(self.settings.generator, (played,))
                key = identities[played]
                if (fen, key) not in memo:
                    restricted[fen, key] = played
        for (fen, key), lines in self.lines.get_many(sorted(restricted), cancel=cancel).items():
            memo[fen, key] = compatible_lines(lines, fen, self.settings, (restricted[fen,key],))
        result = {}
        for row in rows:
            fen, played = row['fen_before'], row['uci_played']
            root = memo[fen, identity]
            ready = root is not None and (not root or played in root)
            if root and not ready:
                ready = memo[fen, identities[played]]
            count = result.setdefault(row['game_id'], [0, 0])
            count[0] += 1
            count[1] += int(not ready)
        return result
