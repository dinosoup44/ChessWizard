from contextlib import redirect_stdout
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import chess
import chess.engine

from analysis_engine import DryRunEvidence
from engine_cache import get_or_analyze, get_cached_position
import migrate_engine_cache
import migrate_engine_cache_v2


class ScoutCachePromotionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name)/"test.db"
        for migration in (migrate_engine_cache,migrate_engine_cache_v2):
            with patch.object(migration,"DB_NAME",str(path)), redirect_stdout(io.StringIO()):
                migration.main()
        self.connection = sqlite3.connect(path)
        self.addCleanup(self.connection.close)
        self.scratch = sqlite3.connect(":memory:")
        self.addCleanup(self.scratch.close)
        self.engine = Mock()
        self.engine.analyse.side_effect = lambda board, limit: {
            "score":chess.engine.PovScore(chess.engine.Cp(20),chess.WHITE),
            "pv":[next(iter(board.legal_moves))],"depth":5,"nodes":10000}
        self.evidence = DryRunEvidence(self.connection,self.engine,self.scratch)

    def test_promotes_evidence_once_and_rerun_requires_no_search_or_row_change(self):
        self.evidence.position(chess.STARTING_FEN)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM engine_position_cache").fetchone()[0],0)
        self.assertEqual(self.evidence.persist_scout_cache(),1)
        cached = get_cached_position(self.connection,chess.STARTING_FEN,"tactic_scout_v1")
        self.assertEqual(cached["score_cp"],20)
        changes = self.connection.total_changes
        sequence = self.connection.execute("SELECT * FROM sqlite_sequence").fetchall()
        self.engine.reset_mock()
        with sqlite3.connect(":memory:") as next_scratch:
            second = DryRunEvidence(self.connection,self.engine,next_scratch)
            self.assertEqual(second.position(chess.STARTING_FEN)["cache_id"],cached["cache_id"])
            self.assertEqual(second.persist_scout_cache(),0)
        self.engine.analyse.assert_not_called()
        self.assertEqual(self.connection.total_changes,changes)
        self.assertEqual(self.connection.execute("SELECT * FROM sqlite_sequence").fetchall(),sequence)

    def test_promotes_only_requested_positions_and_preserves_newly_existing_cache(self):
        self.evidence.position(chess.STARTING_FEN)
        original = get_or_analyze(self.connection,self.engine,chess.STARTING_FEN,"tactic_scout_v1")
        board = chess.Board()
        board.push_uci("e2e4")
        get_or_analyze(self.scratch,self.engine,board.fen(),"tactic_scout_v1")
        changes = self.connection.total_changes
        self.assertEqual(self.evidence.persist_scout_cache(),0)
        self.assertEqual(self.connection.total_changes,changes)
        self.assertEqual(get_cached_position(self.connection,chess.STARTING_FEN,"tactic_scout_v1")["cache_id"],original["cache_id"])
        self.assertIsNone(get_cached_position(self.connection,board.fen(),"tactic_scout_v1"))

    def test_invalid_scratch_evidence_rolls_back_promotion(self):
        self.evidence.position(chess.STARTING_FEN)
        self.scratch.execute("UPDATE engine_position_cache SET score_pov='black'")
        self.scratch.commit()
        with self.assertRaises(ValueError):
            self.evidence.persist_scout_cache()
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM engine_position_cache").fetchone()[0],0)


if __name__ == "__main__":
    unittest.main()
