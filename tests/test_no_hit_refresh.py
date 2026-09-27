from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from analysis_crawler import ANALYZERS, coverage_decision, parse_args
from analysis_planner import plan_stale_no_hits
from analysis_results import HeavyResult
from heavy_dispatch import run_heavy_scope
from heavy_repository import save_heavy_result
from tactical_opportunities import TacticalOpportunity
import test_heavy_services as fixtures


class RefreshTests(unittest.TestCase):
    setUp = fixtures.RepositoryTests.setUp

    def seed(self):
        self.definition = ANALYZERS["missed_pin"]
        self.c.executescript("""
            ALTER TABLE moves ADD COLUMN game_id INTEGER;
            ALTER TABLE moves ADD COLUMN is_user_move INTEGER DEFAULT 1;
            ALTER TABLE moves ADD COLUMN uci_played TEXT DEFAULT 'e2e4';
            UPDATE moves SET game_id=move_id;
            INSERT INTO moves(move_id,game_id) VALUES(3,11);
            CREATE TABLE games(game_id INTEGER PRIMARY KEY,source TEXT);
            INSERT INTO tactic_candidates(candidate_id,move_id,tactic_type,candidate_status,detector_version,metadata_json)
              VALUES(42,2,'missed_pin','candidate',1,'{"original":true}');
            INSERT INTO training_attempts VALUES(1,42);
        """)
        self.c.executemany("INSERT INTO games VALUES(?,'chesscom')", [(i,) for i in range(1,12)])
        for move_id,status,candidate_id in ((1,"analyzed_no_hit",None),(2,"candidate",42),(3,"analyzed_no_hit",None)):
            self.c.execute("INSERT INTO analysis_coverage(move_id,analysis_type,coverage_status,analyzer_version,screener_version,scout_version,scout_config,candidate_id) VALUES(?,'missed_pin',?,'1','1','1',?,?)",
                           (move_id,status,self.definition.scout_config(),candidate_id))
        self.c.commit()
        self.rows = [fixtures.move_row(move_id=i) for i in (1,2)]
        return self

    def test_cli_requires_exact_saved_heavy_mode_and_one_analyzer(self):
        valid = ["crawler","--heavy-test-10","--analysis","missed_pin","--refresh-no-hits-from","1"]
        with patch("sys.argv", valid):
            self.assertEqual(parse_args().refresh_no_hits_from, "1")
        with patch("sys.argv", ["crawler","--heavy-validation-500","--analysis","missed_pin","--refresh-no-hits-from","1"]):
            args = parse_args()
            self.assertEqual(args.refresh_no_hits_from,"1")
            self.assertTrue(args.validation_scope_500)
        for args in (["--refresh-no-hits-from","1"],
                     ["--validation-scope-500","--analysis","missed_pin","--refresh-no-hits-from","1"],
                     ["--heavy-validation-500","--all-games","--analysis","missed_pin","--refresh-no-hits-from","1"],
                     ["--heavy-validation-500","--source","lichess","--analysis","missed_pin","--refresh-no-hits-from","1"],
                     ["--heavy-validation-500","--analysis","missed_pin","--analysis","missed_mate","--refresh-no-hits-from","1"],
                     ["--heavy-test-10","--analysis","missed_pin","--analysis","missed_mate","--refresh-no-hits-from","1"],
                     ["--heavy-test-10","--all-games","--analysis","missed_pin","--refresh-no-hits-from","1"]):
            with patch("sys.argv",["crawler",*args]), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parse_args()

    def test_plan_only_source_version_no_hits_with_current_upstream(self):
        self.seed()
        plan = plan_stale_no_hits(self.c,[self.definition],self.rows,coverage_decision,"1")
        self.assertEqual(plan["pending_heavy_checks"],[{"move_id":1,"analysis_type":"missed_pin"}])
        self.assertEqual(plan["protected_candidate_ids_in_scope"],[42])
        self.assertEqual(plan["static_scout_work"],0)
        self.c.execute("UPDATE analysis_coverage SET scout_config='different' WHERE move_id=1")
        self.c.commit()
        plan = plan_stale_no_hits(self.c,[self.definition],self.rows,coverage_decision,"1")
        self.assertEqual(plan["pending_heavy_checks"],[])
        self.assertEqual(len(plan["errors"]),1)

    def test_atomic_guard_blocks_candidate_arriving_after_plan(self):
        self.seed()
        self.c.execute("INSERT INTO tactic_candidates(move_id,tactic_type,detector_version) VALUES(1,'missed_pin',1)")
        self.c.commit()
        before = self.c.total_changes
        with self.assertRaises(ValueError):
            save_heavy_result(self.c,self.definition,self.rows[0],HeavyResult("candidate",fixtures.candidate_payload()),
                              {(1,"missed_pin")},coverage_decision,expected_no_hit_version="1")
        self.assertEqual(self.c.total_changes,before)

    def test_atomic_guard_blocks_version_or_config_drift_and_reconciliation(self):
        self.seed()
        for overrides in ({"reconcile_stale":True}, {"expected_no_hit_version":"0"}):
            with self.assertRaises(ValueError):
                save_heavy_result(self.c,self.definition,self.rows[0],HeavyResult("analyzed_no_hit"),
                                  {(1,"missed_pin")},coverage_decision,**{"expected_no_hit_version":"1",**overrides})
        self.c.execute("UPDATE analysis_coverage SET scout_config='changed' WHERE move_id=1")
        self.c.commit()
        with self.assertRaises(ValueError):
            save_heavy_result(self.c,self.definition,self.rows[0],HeavyResult("analyzed_no_hit"),
                              {(1,"missed_pin")},coverage_decision,expected_no_hit_version="1")

    def test_error_remains_retryable_and_is_not_completed_refresh(self):
        self.seed()
        save_heavy_result(self.c,self.definition,self.rows[0],HeavyResult("error",details={"message":"temporary"}),
                          {(1,"missed_pin")},coverage_decision,expected_no_hit_version="1")
        coverage = self.c.execute("SELECT * FROM analysis_coverage WHERE move_id=1").fetchone()
        self.assertEqual(coverage_decision(self.definition,coverage),"retry")
        plan = plan_stale_no_hits(self.c,[self.definition],self.rows,coverage_decision,"1")
        self.assertEqual(plan["analyzers"]["missed_pin"]["retryable_errors_not_selected"],1)
        self.assertEqual(plan["analyzers"]["missed_pin"]["current"],0)

    def test_controlled_write_backup_protection_and_identical_noop_rerun(self):
        self.seed()
        result = HeavyResult("candidate",fixtures.candidate_payload(),opportunity=TacticalOpportunity())
        original = dict(self.c.execute("SELECT * FROM tactic_candidates WHERE candidate_id=42").fetchone())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"test.db"
            with patch("heavy_dispatch.heavy_test_game_ids",return_value=list(range(1,11))), \
                 patch("heavy_dispatch.plan_negatives",side_effect=AssertionError("Static/scout planning forbidden")), \
                 patch("heavy_dispatch.dispatch_heavy",return_value=result) as dispatch, redirect_stdout(io.StringIO()):
                report = run_heavy_scope(self.c,[self.definition],self.rows,list(range(1,11)),path,coverage_decision,
                    refresh_from_version="1",preflight_path=Path(directory)/"preflight.json")
                self.assertTrue(Path(report["backup"]).exists())
                self.assertEqual(report["analyzers"]["missed_pin"]["attempted"],1)
                self.assertEqual(report["new_candidate_ids"],[43])
                self.assertEqual(report["coverage_counts"],{"before":3,"after":3})
                self.assertEqual(report["candidate_audit_records"][0]["opportunity"]["proof"]["played_move_uci"],"e2e4")
                self.assertEqual(dict(self.c.execute("SELECT * FROM tactic_candidates WHERE candidate_id=42").fetchone()),original)
                dispatch.reset_mock()
                rerun = run_heavy_scope(self.c,[self.definition],self.rows,list(range(1,11)),path,coverage_decision,refresh_from_version="1")
                dispatch.assert_not_called()
                self.assertEqual(rerun["database_row_changes"],0)
                self.assertEqual(rerun["new_candidate_ids"],[])
                self.assertTrue(rerun["sequences_unchanged"])
                self.assertTrue(rerun["all_existing_candidates_unchanged"])

    def test_service_rejects_wrong_saved_500_ids_before_database_access(self):
        self.seed()
        connection = Mock(total_changes=0)
        with patch("heavy_dispatch.validation_scope_ids",return_value=list(range(1,501))), self.assertRaises(ValueError):
            run_heavy_scope(connection,[self.definition],[],list(range(2,502)),Path("test.db"),coverage_decision,
                            validation_scope=True,refresh_from_version="1")
        connection.execute.assert_not_called()

    def test_saved_500_refresh_uses_same_protected_pipeline_and_noop_rerun(self):
        self.seed()
        ids = list(range(1,501))
        self.c.execute("UPDATE moves SET game_id=501 WHERE move_id=3")
        self.c.executemany("INSERT INTO games VALUES(?,'chesscom')",[(i,) for i in range(12,502)])
        self.c.commit()
        original = dict(self.c.execute("SELECT * FROM tactic_candidates WHERE candidate_id=42").fetchone())
        with tempfile.TemporaryDirectory() as directory, \
             patch("heavy_dispatch.validation_scope_ids",return_value=ids), \
             patch("heavy_dispatch.plan_negatives",side_effect=AssertionError("No screening/scouting")), \
             patch("heavy_dispatch.dispatch_heavy",return_value=HeavyResult("analyzed_no_hit")) as dispatch, \
             redirect_stdout(io.StringIO()):
            path = Path(directory)/"test.db"
            first = run_heavy_scope(self.c,[self.definition],self.rows,ids,path,coverage_decision,
                                    validation_scope=True,refresh_from_version="1")
            self.assertTrue(Path(first["backup"]).exists())
            self.assertEqual(first["analyzers"]["missed_pin"]["analyzed_no_hit"],1)
            self.assertEqual(dict(self.c.execute("SELECT * FROM tactic_candidates WHERE candidate_id=42").fetchone()),original)
            self.assertEqual(self.c.execute("SELECT analyzer_version FROM analysis_coverage WHERE move_id=3").fetchone()[0],"1")
            dispatch.reset_mock()
            second = run_heavy_scope(self.c,[self.definition],self.rows,ids,path,coverage_decision,
                                     validation_scope=True,refresh_from_version="1")
            dispatch.assert_not_called()
            self.assertEqual(second["database_row_changes"],0)
            self.assertTrue(second["sequences_unchanged"])


if __name__ == "__main__":
    unittest.main()
