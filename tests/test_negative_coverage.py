from collections import Counter
from contextlib import redirect_stdout, closing
from dataclasses import replace
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import chess

from analysis_crawler import ANALYZERS, coverage_decision, parse_args, get_selected_game_ids
from analysis_scout import ScoutResult
from migrate_analysis_scout_rejection import CREATE_TABLE
from negative_coverage import (
    plan_negatives, apply_negatives, coverage_rows, protected_snapshot,
    write_authorizer, DryRunEvidence, run_negative_scope,
    validation_scope_ids,
)


class NegativeCoverageTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        c = self.connection
        c.row_factory = sqlite3.Row
        c.executescript("""
            CREATE TABLE games(game_id INTEGER PRIMARY KEY,source TEXT);
            INSERT INTO games VALUES(1,'chesscom'),(2,'chesscom'),(3,'dev');
            CREATE TABLE moves(move_id INTEGER PRIMARY KEY,game_id INTEGER,is_user_move INTEGER,
                               color TEXT,fen_before TEXT,fen_after TEXT,uci_played TEXT);
            CREATE TABLE tactic_candidates(candidate_id INTEGER PRIMARY KEY,move_id INTEGER,tactic_type TEXT);
            INSERT INTO tactic_candidates VALUES(30,3,'missed_fork'),(40,4,'missed_fork'),(100,10,'missed_fork');
            CREATE TABLE training_attempts(attempt_id INTEGER PRIMARY KEY,candidate_id INTEGER);
            INSERT INTO training_attempts VALUES(1,30),(2,40);
            CREATE TABLE engine_position_cache(id INTEGER PRIMARY KEY);
        """)
        c.execute(CREATE_TABLE.replace("analysis_coverage_new", "analysis_coverage"))
        board = chess.Board()
        before = board.fen()
        board.push_uci("e2e4")
        for move_id in range(1,13):
            game_id = 2 if move_id==6 else 3 if move_id==12 else 1
            c.execute("INSERT INTO moves VALUES(?,?,?,?,?,?,?)",(move_id,game_id,0 if move_id==11 else 1,"white",before,board.fen(),"e2e4"))
        for move_id,status,candidate in ((3,"candidate",30),(4,"rejected",40),(5,"error",None),(6,"error",None),(8,"analyzed_no_hit",None)):
            c.execute("INSERT INTO analysis_coverage(move_id,analysis_type,coverage_status,candidate_id,analyzer_version) VALUES(?,'missed_fork',?,?,'2')",(move_id,status,candidate))
        c.commit()
        self.definition = replace(ANALYZERS["missed_fork"],
                                  screener=lambda row: row["move_id"] != 1,
                                  scout=lambda row,evidence: ScoutResult(row["move_id"]==7,"test_scout_reason"))
        self.rows = c.execute("SELECT * FROM moves WHERE move_id IN (1,2,3,4,5,7,8,10)").fetchall()
        self.evidence = type("Evidence",(),{"positions":{},"stats":Counter()})()

    def plan(self,rows=None):
        return plan_negatives(self.connection,[self.definition],self.rows if rows is None else rows,self.evidence,coverage_decision)

    def test_writes_only_completed_negatives_and_preserves_everything_else(self):
        c = self.connection
        original = protected_snapshot(c)
        existing = coverage_rows(c)
        plans, report = self.plan()
        self.assertEqual(report["errors"],[])
        self.assertEqual(report["analyzers"]["missed_fork"]["pending_heavy"],1)
        self.assertEqual({p["move_id"] for p in plans},{1,2,5})
        writes = apply_negatives(c,plans,[1],{"missed_fork"})
        self.assertEqual(writes,Counter(screened_out=1,scouted_out=2,inserted=2,updated=1))
        self.assertEqual(protected_snapshot(c),original)
        final = coverage_rows(c)
        for key in ((3,"missed_fork"),(4,"missed_fork"),(6,"missed_fork"),(8,"missed_fork")):
            self.assertEqual(final[key],existing[key])
        for plan in plans:
            saved = final[(plan["move_id"],"missed_fork")]
            self.assertEqual(saved["analyzer_version"],"0")
            self.assertIsNone(saved["candidate_id"])
            self.assertFalse(json.loads(saved["details_json"])["heavy_analysis_performed"])
        self.assertEqual(final[(1,"missed_fork")]["scout_version"],"0")
        self.assertEqual(final[(1,"missed_fork")]["scout_config"],"")
        self.assertEqual(final[(2,"missed_fork")]["scout_config"],self.definition.scout_config())

    def test_rerun_skips_negatives_without_timestamp_or_sequence_churn(self):
        plans,_ = self.plan()
        apply_negatives(self.connection,plans,[1],{"missed_fork"})
        before = coverage_rows(self.connection)
        sequence = [tuple(r) for r in self.connection.execute("SELECT * FROM sqlite_sequence")]
        rerun, report = self.plan()
        self.assertEqual(rerun,[])
        self.assertEqual(report["analyzers"]["missed_fork"]["examined"],1)
        self.assertEqual(report["analyzers"]["missed_fork"]["pending_heavy"],1)
        # A repeated direct call is also a no-op, even with changed detail formatting.
        writes = apply_negatives(self.connection,plans,[1],{"missed_fork"})
        self.assertEqual(writes,Counter(unchanged=3))
        self.assertEqual(coverage_rows(self.connection),before)
        self.assertEqual([tuple(r) for r in self.connection.execute("SELECT * FROM sqlite_sequence")],sequence)

    def test_guard_handles_candidate_created_after_plan_and_missing_coverage(self):
        plans,_ = self.plan()
        self.connection.execute("INSERT INTO tactic_candidates VALUES(20,2,'missed_fork')")
        self.connection.commit()
        forged = dict(plans[0],move_id=10)
        writes = apply_negatives(self.connection,[plans[1],forged],[1],{"missed_fork"})
        self.assertEqual(writes,Counter(protected=2))
        self.assertNotIn((2,"missed_fork"),coverage_rows(self.connection))
        for move_id in (3,4,8):
            writes = apply_negatives(self.connection,[dict(plans[0],move_id=move_id)],[1],{"missed_fork"})
            self.assertEqual(writes,Counter(protected=1))

    def test_scope_and_status_violations_rollback_all_writes(self):
        plans,_ = self.plan()
        before = coverage_rows(self.connection)
        for change in ({"move_id":6},{"move_id":11},{"move_id":12},{"analysis_type":"missed_mate"},
                       {"coverage_status":"analyzed_no_hit"},{"analyzer_version":"2"}):
            with self.assertRaises(ValueError):
                apply_negatives(self.connection,[plans[0],dict(plans[1],**change)],[1],{"missed_fork"})
            self.assertEqual(coverage_rows(self.connection),before)

    def test_invalid_position_and_scout_failure_are_not_negatives(self):
        bad_row = dict(self.rows[0],fen_before="bad fen")
        plans, report = self.plan([bad_row])
        self.assertEqual(plans,[])
        self.assertEqual(len(report["errors"]),1)
        definition = replace(self.definition,scout=lambda row,e: (_ for _ in ()).throw(ValueError("test failure")))
        plans, report = plan_negatives(self.connection,[definition],[self.rows[1]],self.evidence,coverage_decision)
        self.assertEqual(plans,[])
        self.assertEqual(len(report["errors"]),1)
        self.assertEqual(coverage_decision(self.definition,coverage_rows(self.connection)[(5,"missed_fork")]),"retry")

    def test_unsafe_static_rejection_cannot_be_written(self):
        unsafe = replace(self.definition,has_safe_screener=False)
        plans, report = plan_negatives(self.connection,[unsafe],[self.rows[0]],self.evidence,coverage_decision)
        self.assertEqual(plans,[])
        self.assertEqual(len(report["errors"]),1)

    def test_stale_negative_updates_in_place(self):
        plans,_ = self.plan()
        apply_negatives(self.connection,[plans[0]],[1],{"missed_fork"})
        before = coverage_rows(self.connection)[(1,"missed_fork")]
        changed = replace(self.definition,screener_version="next")
        new,_ = plan_negatives(self.connection,[changed],[self.rows[0]],self.evidence,coverage_decision)
        writes = apply_negatives(self.connection,new,[1],{"missed_fork"})
        after = coverage_rows(self.connection)[(1,"missed_fork")]
        self.assertEqual(writes["updated"],1)
        self.assertEqual(after["coverage_id"],before["coverage_id"])
        self.assertEqual(after["screener_version"],"next")

    def test_sql_authorizer_blocks_candidate_training_and_delete_operations(self):
        c = self.connection
        c.set_authorizer(write_authorizer(coverage=True))
        try:
            for sql in ("DELETE FROM tactic_candidates", "UPDATE training_attempts SET candidate_id=999",
                        "DELETE FROM analysis_coverage", "INSERT INTO tactic_candidates VALUES(99,1,'missed_fork')"):
                with self.assertRaises(sqlite3.DatabaseError):
                    c.execute(sql)
        finally:
            c.set_authorizer(None)

    def test_dry_run_cache_miss_writes_only_to_scratch(self):
        result = {"cache_id":1,"score_pov":"white","cache_hit":False}
        def analyze(scratch,*args):
            self.assertIsNot(scratch,self.connection)
            scratch.execute("INSERT INTO engine_position_cache VALUES(1)")
            return dict(result)
        with closing(sqlite3.connect(":memory:")) as scratch, patch("analysis_engine.get_cached_position",return_value=None), patch("analysis_engine.get_or_analyze",side_effect=analyze):
            evidence = DryRunEvidence(self.connection,None,scratch)
            self.assertIsNone(evidence.position("test")["cache_id"])
            self.assertEqual(scratch.execute("SELECT COUNT(*) FROM engine_position_cache").fetchone()[0],1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM engine_position_cache").fetchone()[0],0)

    def test_dry_run_leaves_database_unchanged_and_starts_no_engine_for_static_work(self):
        before = coverage_rows(self.connection)
        self.connection.execute("PRAGMA query_only=ON")
        with tempfile.TemporaryDirectory() as folder, patch("negative_coverage.LazyScoutEngine.analyse",side_effect=AssertionError("engine forbidden")), redirect_stdout(io.StringIO()):
            report = run_negative_scope(self.connection,[self.definition],[self.rows[0]],[1],Path(folder)/"test.db",coverage_decision)
            self.assertEqual(list(Path(folder).iterdir()),[])
        self.assertEqual(report["writes"],{})
        self.assertEqual(coverage_rows(self.connection),before)

    def test_cli_cannot_accidentally_write_default_500_games(self):
        with patch("sys.argv",["crawler","--write-negatives"]), redirect_stdout(io.StringIO()), patch("sys.stderr",io.StringIO()):
            with self.assertRaises(SystemExit):
                parse_args()
        with patch("sys.argv",["crawler","--write-negatives","--last-games","10"]):
            self.assertTrue(parse_args().write_negatives)

    def test_expansion_requires_saved_validation_scope_and_rejects_filters(self):
        with patch("sys.argv",["crawler","--write-negatives","--validation-scope-500"]):
            self.assertTrue(parse_args().validation_scope_500)
        for options in (["--last-games","500"], ["--all-games"],
                        ["--validation-scope-500","--source","chesscom"],
                        ["--validation-scope-500","--analysis","missed_fork"]):
            with patch("sys.argv",["crawler","--write-negatives",*options]), patch("sys.stderr",io.StringIO()):
                with self.assertRaises(SystemExit):
                    parse_args()

    def test_validation_scope_uses_saved_ids_not_recent_imports(self):
        with closing(sqlite3.connect(":memory:")) as c:
            c.execute("CREATE TABLE games(game_id INTEGER PRIMARY KEY,source TEXT)")
            c.executemany("INSERT INTO games VALUES(?,'chesscom')",[(i,) for i in range(1,502)])
            args = type("Args",(),{"validation_scope_500":True})()
            with patch("analysis_scope.validation_scope_ids",return_value=list(range(1,501))):
                self.assertEqual(get_selected_game_ids(c,args),list(range(1,501)))
                c.execute("UPDATE games SET source='dev' WHERE game_id=1")
                with self.assertRaises(ValueError):
                    get_selected_game_ids(c,args)

    def test_validation_report_must_have_500_distinct_positive_integer_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"reports").mkdir()
            path = root/"reports"/"scout_preview_500.json"
            ids = list(range(1,501))
            path.write_text(json.dumps({"games":500,"game_ids":ids}))
            self.assertEqual(validation_scope_ids(root),ids)
            for invalid in (ids[:-1], [1]*500, [True]+ids[1:]):
                path.write_text(json.dumps({"games":500,"game_ids":invalid}))
                with self.assertRaises(ValueError):
                    validation_scope_ids(root)


if __name__ == "__main__":
    unittest.main()
