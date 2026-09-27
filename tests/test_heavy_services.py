from collections import Counter
from contextlib import closing
from dataclasses import replace
from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import chess

from analysis_crawler import ANALYZERS, coverage_decision, parse_args
from analysis_engine import PositionAnalysisService
from heavy_adapters import HeavyResult, fork_adapter, mate_adapter, dispatch_heavy, FORK_ROW_FIELDS
from heavy_repository import save_heavy_result
from migrate_analysis_scout_rejection import CREATE_TABLE
import analyze_mates as mates
import analyze_forks_v2 as forks
from analysis_scope import validation_scope_ids
from heavy_dispatch import run_heavy_scope


class ValidationScopeTests(unittest.TestCase):
    def test_10_game_mode_allows_tactic_filter_without_changing_scope(self):
        with patch("sys.argv",["crawler","--heavy-test-10","--analysis","missed_pin"]):
            args = parse_args()
        self.assertEqual(args.analysis,["missed_pin"])
        self.assertTrue(args.heavy_test_10)
        self.assertFalse(args.validation_scope_500)
        for extra in (["--all-games"],["--validation-scope-500"],["--last-games","11"],["--source","lichess"]):
            with patch("sys.argv",["crawler","--heavy-test-10","--analysis","missed_pin",*extra]), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parse_args()

    def test_500_mode_uses_saved_scope_and_rejects_broader_or_filtered_scopes(self):
        with patch("sys.argv",["crawler","--heavy-validation-500"]):
            self.assertTrue(parse_args().validation_scope_500)
        with patch("sys.argv",["crawler","--heavy-validation-500","--analysis","missed_pin"]):
            args = parse_args()
            self.assertTrue(args.validation_scope_500)
            self.assertEqual(args.analysis,["missed_pin"])
        for arguments in (["--all-games"],["--last-games","501"],["--source","lichess"],
                          ["--time-class","blitz"],["--heavy-test-10"]):
            with self.subTest(arguments=arguments), patch("sys.argv",["crawler","--heavy-validation-500",*arguments]), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parse_args()

    def test_dispatch_rejects_changed_scope_before_database_or_engine_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"reports").mkdir()
            ids = list(range(1,501))
            (root/"reports"/"scout_preview_500.json").write_text(json.dumps({"games":500,"game_ids":ids}))
            self.assertEqual(validation_scope_ids(root),ids)
            connection = Mock(total_changes=0)
            with self.assertRaises(ValueError):
                run_heavy_scope(connection,[],[],[*ids[:-1],501],root/"test.db",coverage_decision,validation_scope=True)
            connection.execute.assert_not_called()

    def test_dispatch_rejects_out_of_scope_moves_before_backup(self):
        connection = Mock(total_changes=0)
        connection.execute.return_value = [(1,)]
        with patch("heavy_dispatch.validation_scope_ids",return_value=[1]), patch("heavy_dispatch.create_backup") as backup:
            with self.assertRaises(ValueError):
                run_heavy_scope(connection,[],[{"move_id":2}],[1],Path("test.db"),coverage_decision,validation_scope=True)
            backup.assert_not_called()


def move_row(fen=chess.STARTING_FEN, played="e2e4", move_id=1):
    board = chess.Board(fen)
    move = chess.Move.from_uci(played)
    row = {"move_id":move_id,"game_id":1,"ply_number":1,"move_number":board.fullmove_number,
           "color":"white" if board.turn else "black", "san_played":board.san(move),
           "uci_played":played,"fen_before":fen,"source":"chesscom","source_game_id":"fixture",
           "white_username":"white","black_username":"black"}
    board.push(move)
    row["fen_after"] = board.fen()
    return row


def candidate_payload(version=2):
    return {"candidate_status":"candidate","confidence":0.9,"detector_version":version,
            "solution_move_uci":"d2d4","solution_move_san":"d4","solution_line":"d4 d5",
            "notes":"fixture","metadata_json":"{}"}


class CalculationTests(unittest.TestCase):
    def test_fork_realization_and_candidate_build_are_pure(self):
        row = move_row("r3k3/8/8/3N4/8/8/8/4K3 w - - 0 1","e1f1")
        requests = []
        def position(fen,profile):
            requests.append((fen,profile))
            board = chess.Board(fen)
            pv = "Kf7 Nxa8" if board.piece_at(chess.C7) == chess.Piece(chess.KNIGHT,chess.WHITE) else ""
            return {"score_type":"cp","score_cp":-200 if fen==row["fen_after"] else 300,
                    "mate":None,"principal_variation":pv}
        with patch.object(forks,"save_fork_payload",side_effect=AssertionError("legacy persistence forbidden")), patch.object(forks,"delete_fork_candidate",side_effect=AssertionError("deletion forbidden")):
            result = fork_adapter(row,type("Positions",(),{"position":staticmethod(position)})())
        self.assertEqual(result.state,"candidate")
        self.assertEqual(result.candidate["solution_move_uci"],"d5c7")
        self.assertEqual(result.candidate["solution_line"],"Nc7+ Kf7 Nxa8")
        self.assertIn("tactic_verify_v1",{profile for fen,profile in requests})
        self.assertEqual(json.loads(result.candidate["metadata_json"])["realization"]["won_piece"],"rook")

    def test_fork_no_geometry_needs_no_engine(self):
        positions = Mock()
        result = fork_adapter(move_row(),positions)
        self.assertEqual(result.state,"analyzed_no_hit")
        positions.position.assert_not_called()

    def test_mate_uses_same_black_pov_after_played_move_and_shared_profiles(self):
        row = move_row("4k3/8/8/8/8/8/8/4K3 b - - 0 1","e8f8")
        def position(fen,profile):
            return {"score_pov":"white","score_type":"mate" if fen==row["fen_before"] else "cp",
                    "mate":-2 if fen==row["fen_before"] else None,"score_cp":0,
                    "cache_id":1,"best_move_uci":"e8d8","best_move_san":"Kd8","principal_variation":"Kd8"}
        positions = Mock()
        positions.position.side_effect = position
        result = mate_adapter(row,positions)
        self.assertEqual(result.state,"candidate")
        self.assertEqual(result.candidate["detector_version"],3)
        self.assertEqual([call.args[1] for call in positions.position.call_args_list],
                         ["tactic_quick_v1","tactic_verify_v1","tactic_verify_v1"])

    def test_mate_still_available_even_beyond_limit_is_not_missed(self):
        evaluator = Mock(side_effect=[{"mate_distance":2},{"mate_distance":2},{"mate_distance":10}])
        result = mates.analyze_single_move(move_row(),evaluator)
        self.assertIsNone(result["candidate"])
        self.assertEqual(result["reason"],"played_move_kept_forced_mate")

    def test_mate_played_checkmate_does_not_request_after_analysis(self):
        row = move_row("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1","f7g7")
        evaluator = Mock(return_value={"mate_distance":1})
        self.assertIsNone(mates.analyze_single_move(row,evaluator)["candidate"])
        self.assertEqual(evaluator.call_count,2)

    def test_quick_and_deep_mate_rejections(self):
        for scores in ([None],[2,None],[-2]):
            evaluator = Mock(side_effect=[{"mate_distance":score} for score in scores])
            self.assertIsNone(mates.analyze_single_move(move_row(),evaluator)["candidate"])

    def test_engine_service_reuses_cache_and_counts_misses(self):
        stats = Counter()
        service = PositionAnalysisService(None,None,stats)
        cached = {"cache_hit":True,"score_pov":"white","score_type":"cp","score_cp":50,"cache_id":1}
        with patch("analysis_engine.get_or_analyze",return_value=cached) as get:
            self.assertEqual(service.position("fen","tactic_verify_v1")["score_cp"],50)
            get.assert_called_once_with(None,None,"fen","tactic_verify_v1")
        self.assertEqual(stats["hits"],1)
        with patch("analysis_engine.get_or_analyze",return_value={**cached,"cache_hit":False}):
            service.position("fen","tactic_verify_v1")
        self.assertEqual(stats["misses"],1)

    def test_boundary_converts_failure_to_error_and_blocks_candidate_writes(self):
        with closing(sqlite3.connect(":memory:")) as c:
            c.execute("CREATE TABLE tactic_candidates(id INTEGER)")
            def dangerous(row,positions):
                positions.connection.execute("INSERT INTO tactic_candidates VALUES(1)")
            definition = replace(ANALYZERS["missed_fork"],heavy=dangerous)
            self.assertEqual(dispatch_heavy(definition,c,None,move_row(),Counter()).state,"error")
            self.assertEqual(c.execute("SELECT COUNT(*) FROM tactic_candidates").fetchone()[0],0)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(":memory:")
        self.addCleanup(self.c.close)
        self.c.row_factory = sqlite3.Row
        self.c.executescript("""
            CREATE TABLE moves(move_id INTEGER PRIMARY KEY);
            INSERT INTO moves VALUES(1),(2);
            CREATE TABLE tactic_candidates(candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,move_id INTEGER,tactic_type TEXT,
                candidate_status TEXT,confidence REAL,detector_version INTEGER,solution_move_uci TEXT,solution_move_san TEXT,
                solution_line TEXT,notes TEXT,metadata_json TEXT,created_at TEXT DEFAULT 'original',reviewed_at TEXT);
            CREATE TABLE training_attempts(id INTEGER PRIMARY KEY,candidate_id INTEGER REFERENCES tactic_candidates(candidate_id));
        """)
        self.c.execute(CREATE_TABLE.replace("analysis_coverage_new","analysis_coverage"))
        self.c.commit()
        self.definition = ANALYZERS["missed_fork"]
        self.allowed = {(1,"missed_fork")}

    def save(self,result,**options):
        return save_heavy_result(self.c,self.definition,move_row(),result,self.allowed,coverage_decision,**options)

    def test_candidate_insert_atomic_coverage_and_idempotence(self):
        result = HeavyResult("candidate",candidate_payload())
        saved = self.save(result)
        self.assertEqual(saved["action"],"candidate_created")
        first = dict(self.c.execute("SELECT * FROM analysis_coverage").fetchone())
        sequence = [tuple(r) for r in self.c.execute("SELECT * FROM sqlite_sequence")]
        self.assertEqual(self.save(result)["action"],"unchanged")
        self.assertEqual(dict(self.c.execute("SELECT * FROM analysis_coverage").fetchone()),first)
        self.assertEqual([tuple(r) for r in self.c.execute("SELECT * FROM sqlite_sequence")],sequence)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM tactic_candidates").fetchone()[0],1)

    def seed_old_candidate(self):
        self.c.execute("INSERT INTO tactic_candidates(candidate_id,move_id,tactic_type,candidate_status,detector_version,metadata_json) VALUES(42,1,'missed_fork','candidate',1,'{}')")
        self.c.execute("INSERT INTO training_attempts VALUES(1,42)")
        self.c.commit()

    def test_matching_canonical_id_updated_in_place_with_training_preserved(self):
        self.seed_old_candidate()
        saved = self.save(HeavyResult("candidate",candidate_payload()))
        self.assertEqual(saved["candidate_id"],42)
        self.assertEqual(saved["action"],"candidate_updated")
        self.assertEqual(tuple(self.c.execute("SELECT candidate_id,created_at FROM tactic_candidates").fetchone()),(42,"original"))
        self.assertEqual(tuple(self.c.execute("SELECT * FROM training_attempts").fetchone()),(1,42))

    def test_no_hit_and_error_mapping(self):
        self.assertEqual(self.save(HeavyResult("error",details={"message":"temporary"}))["state"],"error")
        row = self.c.execute("SELECT * FROM analysis_coverage").fetchone()
        self.assertEqual(coverage_decision(self.definition,row),"retry")
        self.save(HeavyResult("analyzed_no_hit"))
        row = self.c.execute("SELECT * FROM analysis_coverage").fetchone()
        self.assertEqual(coverage_decision(self.definition,row),"current")
        self.assertIsNone(row["candidate_id"])

    def test_current_candidate_cannot_be_downgraded(self):
        self.save(HeavyResult("candidate",candidate_payload()))
        self.assertEqual(self.save(HeavyResult("analyzed_no_hit"))["action"],"unchanged")
        self.assertEqual(self.c.execute("SELECT coverage_status FROM analysis_coverage").fetchone()[0],"candidate")

    def test_stale_no_hit_requires_explicit_reconciliation_and_keeps_id(self):
        self.seed_old_candidate()
        self.assertEqual(self.save(HeavyResult("analyzed_no_hit"))["action"],"protected")
        saved = self.save(HeavyResult("analyzed_no_hit",details={"reason":"new_version_no_hit"}),reconcile_stale=True)
        self.assertEqual(saved["state"],"rejected")
        self.assertEqual(saved["candidate_id"],42)
        self.assertEqual(self.c.execute("SELECT candidate_id FROM training_attempts").fetchone()[0],42)

    def test_failure_rolls_back_candidate_insert_and_scope_guard(self):
        with self.assertRaises(ValueError):
            save_heavy_result(self.c,self.definition,move_row(move_id=2),HeavyResult("candidate",candidate_payload()),self.allowed,coverage_decision)
        self.c.executescript("CREATE TRIGGER fail_coverage BEFORE INSERT ON analysis_coverage BEGIN SELECT RAISE(ABORT,'test failure'); END;")
        with self.assertRaises(sqlite3.IntegrityError):
            self.save(HeavyResult("candidate",candidate_payload()))
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM tactic_candidates").fetchone()[0],0)


if __name__ == "__main__":
    unittest.main()
