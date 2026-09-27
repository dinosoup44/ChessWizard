import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from analysis_crawler import ANALYZERS, coverage_decision, get_coverage, preview_analyzer
from analysis_scout import fork_scout_config, mate_scout_config
from engine_cache import PROFILES
from migrate_analysis_coverage import create_analysis_coverage_table
from migrate_analysis_scout_stage import add_scout_stage, rebuild_version_index
from migrate_analysis_scout_rejection import migrate, OLD_COLUMNS, rebuild_coverage


def row_for(definition, status, **overrides):
    return dict(analysis_type=definition.analysis_type, coverage_status=status,
                screener_version=definition.screener_version,
                scout_version=definition.scout_version, scout_config=definition.scout_config(),
                analyzer_version=definition.analyzer_version) | overrides


class CurrentnessTests(unittest.TestCase):
    def test_all_statuses_for_both_analyzers(self):
        for definition in ANALYZERS.values():
            for status in ("screened_out", "scouted_out", "analyzed_no_hit", "candidate", "rejected", "error"):
                with self.subTest(analysis=definition.analysis_type, status=status):
                    expected = "retry" if status == "error" else "current"
                    if status == "screened_out" and not definition.has_safe_screener:
                        expected = "needs_screen"
                    self.assertEqual(coverage_decision(definition,row_for(definition,status)),expected)
            self.assertEqual(coverage_decision(definition,None),"needs_screen")
            self.assertEqual(coverage_decision(definition,row_for(definition,"future_status")),"needs_screen")

    def test_static_depends_only_on_safe_screener(self):
        definition = ANALYZERS["missed_fork"]
        row = row_for(definition,"screened_out",scout_version="obsolete",scout_config="",analyzer_version="obsolete")
        self.assertEqual(coverage_decision(definition,row),"current")
        row["screener_version"] = "obsolete"
        self.assertEqual(coverage_decision(definition,row),"needs_screen")

    def test_mate_scout_negative_is_current_without_safe_static_screen(self):
        definition = ANALYZERS["missed_mate"]
        self.assertFalse(definition.has_safe_screener)
        row = row_for(definition,"scouted_out",analyzer_version="obsolete")
        self.assertEqual(coverage_decision(definition,row),"current")

    def test_scout_negative_staleness_and_stage_routing(self):
        for definition in ANALYZERS.values():
            for field, value, expected in (
                ("screener_version","obsolete","needs_screen"),
                ("scout_version","0","needs_scout"),
                ("scout_version","obsolete","needs_scout"),
                ("scout_config","","needs_scout"),
                ("scout_config","obsolete","needs_scout"),
                ("analyzer_version","obsolete","current"),
            ):
                with self.subTest(analysis=definition.analysis_type, field=field, value=value):
                    self.assertEqual(coverage_decision(definition,row_for(definition,"scouted_out",**{field:value})),expected)

    def test_heavy_candidates_and_rejections_ignore_all_upstream_changes(self):
        for definition in ANALYZERS.values():
            for status in ("candidate", "rejected"):
                row = row_for(definition,status,screener_version="0",scout_version="0",scout_config="")
                self.assertEqual(coverage_decision(definition,row),"current")
                updated_scout = replace(definition,scout_version="999",scout_config=lambda: "different")
                self.assertEqual(coverage_decision(updated_scout,row),"current")
                row["analyzer_version"] = "obsolete"
                self.assertEqual(coverage_decision(definition,row),"needs_reanalysis")

    def test_no_hit_conservatively_requires_all_dependencies(self):
        definition = ANALYZERS["missed_fork"]
        for field, value, expected in (
            ("screener_version","obsolete","needs_screen"),
            ("scout_version","obsolete","needs_scout"),
            ("scout_config","","needs_scout"),
            ("analyzer_version","obsolete","needs_reanalysis"),
        ):
            self.assertEqual(coverage_decision(definition,row_for(definition,"analyzed_no_hit",**{field:value})),expected)

    def test_error_always_retries_and_types_do_not_cross_invalidate(self):
        fork, mate = ANALYZERS["missed_fork"], ANALYZERS["missed_mate"]
        self.assertEqual(coverage_decision(fork,row_for(fork,"error",scout_config="",screener_version="0")),"retry")
        self.assertEqual(coverage_decision(fork,row_for(mate,"scouted_out")),"needs_screen")
        row = row_for(mate,"scouted_out")
        with patch("analysis_scout.FORK_MIN_LOSS_CP",999):
            self.assertEqual(coverage_decision(mate,row),"current")

    def test_configuration_identity_tracks_profile_limits_engine_and_thresholds(self):
        fork_before, mate_before = fork_scout_config(), mate_scout_config()
        self.assertEqual(fork_before,fork_scout_config())
        self.assertEqual(json.loads(fork_before)["profile"]["limit_value"],10000)
        with patch.dict(PROFILES["tactic_scout_v1"],limit_value=20000):
            self.assertNotEqual(fork_before,fork_scout_config())
            self.assertNotEqual(mate_before,mate_scout_config())
        with patch("analysis_scout.ENGINE_VERSION","future"):
            self.assertNotEqual(mate_before,mate_scout_config())
        with patch("analysis_scout.MATE_LIMIT",4):
            self.assertNotEqual(mate_before,mate_scout_config())
            self.assertEqual(fork_before,fork_scout_config())
        with patch("analysis_scout.FORK_MIN_LOSS_CP",100):
            self.assertNotEqual(fork_before,fork_scout_config())


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test.db"
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript("""
                CREATE TABLE moves(move_id INTEGER PRIMARY KEY);
                INSERT INTO moves VALUES(1),(2),(3),(4),(5),(6);
                CREATE TABLE tactic_candidates(candidate_id INTEGER PRIMARY KEY, candidate_status TEXT);
                INSERT INTO tactic_candidates VALUES(42,'candidate'),(43,'rejected');
                CREATE TABLE training_attempts(attempt_id INTEGER PRIMARY KEY, candidate_id INTEGER REFERENCES tactic_candidates(candidate_id));
                INSERT INTO training_attempts VALUES(1,42),(2,43);
            """)
            create_analysis_coverage_table(connection)
            add_scout_stage(connection)
            rebuild_version_index(connection)
            for i,status in enumerate(("candidate","rejected","screened_out","analyzed_no_hit","error"),1):
                candidate = 41+i if i < 3 else None
                connection.execute(
                    "INSERT INTO analysis_coverage(coverage_id,move_id,analysis_type,analyzer_version,coverage_status,candidate_id,details_json,checked_at,updated_at) "
                    "VALUES(?,?,'missed_fork','2',?,?,?, '2026-01-01','2026-01-02')",
                    (i,i,status,candidate,'{"preserve":true}'),
                )
            # Cover AUTOINCREMENT preservation even after a previous high ID was deleted.
            connection.execute("UPDATE sqlite_sequence SET seq=1000 WHERE name='analysis_coverage'")
            connection.executescript("""
                CREATE TABLE coverage_reference(id INTEGER PRIMARY KEY, coverage_id INTEGER REFERENCES analysis_coverage(coverage_id) ON DELETE CASCADE);
                INSERT INTO coverage_reference VALUES(1,1);
                CREATE TABLE audit_log(coverage_id INTEGER);
                CREATE TRIGGER coverage_audit AFTER INSERT ON analysis_coverage
                BEGIN INSERT INTO audit_log VALUES(new.coverage_id); END;
            """)
            connection.commit()

    def test_backup_preservation_indexes_foreign_keys_sequence_and_rerun(self):
        with redirect_stdout(io.StringIO()):
            backup = migrate(self.path)
        with closing(sqlite3.connect(backup)) as before, closing(sqlite3.connect(self.path)) as current:
            for table in ("moves","tactic_candidates","training_attempts","coverage_reference","audit_log","analysis_coverage"):
                columns = ",".join(OLD_COLUMNS) if table == "analysis_coverage" else "*"
                self.assertEqual(current.execute(f"SELECT {columns} FROM {table}").fetchall(),before.execute(f"SELECT {columns} FROM {table}").fetchall())
            self.assertNotIn("scout_config",[r[1] for r in before.execute("PRAGMA table_info(analysis_coverage)")])
            self.assertEqual(current.execute("SELECT DISTINCT scout_config FROM analysis_coverage").fetchall(),[("",)])
            for pragma in ("index_list", "foreign_key_list"):
                # SQLite may enumerate recreated indexes in a different order.
                current_items = {r[1:] for r in current.execute(f"PRAGMA {pragma}(analysis_coverage)")}
                before_items = {r[1:] for r in before.execute(f"PRAGMA {pragma}(analysis_coverage)")}
                self.assertEqual(current_items,before_items)
            self.assertEqual(
                current.execute("SELECT name,sql FROM sqlite_master WHERE tbl_name='analysis_coverage' AND type IN ('index','trigger') ORDER BY name").fetchall(),
                before.execute("SELECT name,sql FROM sqlite_master WHERE tbl_name='analysis_coverage' AND type IN ('index','trigger') ORDER BY name").fetchall(),
            )
            self.assertEqual(current.execute("SELECT seq FROM sqlite_sequence WHERE name='analysis_coverage'").fetchone(),(1000,))
            original = current.execute("SELECT * FROM analysis_coverage").fetchall()
        with redirect_stdout(io.StringIO()):
            migrate(self.path)
        with closing(sqlite3.connect(self.path)) as current:
            self.assertEqual(current.execute("SELECT * FROM analysis_coverage").fetchall(),original)
            self.assertEqual(current.execute("PRAGMA foreign_key_check").fetchall(),[])

    def test_new_status_requires_evidence_and_preserves_constraints_and_triggers(self):
        with redirect_stdout(io.StringIO()):
            migrate(self.path)
        with closing(sqlite3.connect(self.path)) as c:
            c.execute("PRAGMA foreign_keys=ON")
            for version,config in (("0",""),("1",""),("0","config")):
                with self.assertRaises(sqlite3.IntegrityError):
                    c.execute("INSERT INTO analysis_coverage(move_id,analysis_type,coverage_status,scout_version,scout_config) VALUES(6,'missed_mate','scouted_out',?,?)",(version,config))
            definition = ANALYZERS["missed_mate"]
            c.execute("INSERT INTO analysis_coverage(move_id,analysis_type,coverage_status,scout_version,scout_config) VALUES(6,'missed_mate','scouted_out',?,?)",(definition.scout_version,definition.scout_config()))
            self.assertEqual(c.execute("SELECT * FROM audit_log").fetchall(),[(1001,)])
            c.row_factory = sqlite3.Row
            row = get_coverage(c,6,"missed_mate")
            self.assertEqual(coverage_decision(definition,row),"current")
            for sql in (
                "INSERT INTO analysis_coverage(move_id,analysis_type,coverage_status) VALUES(6,'missed_mate','error')",
                "INSERT INTO analysis_coverage(move_id,analysis_type,coverage_status) VALUES(999,'missed_mate','error')",
                "INSERT INTO analysis_coverage(move_id,analysis_type,coverage_status) VALUES(6,'other','bad_status')",
            ):
                with self.assertRaises(sqlite3.IntegrityError):
                    c.execute(sql)

    def test_failure_after_rebuild_rolls_back_entire_migration(self):
        def fail_after_rebuild(connection):
            rebuild_coverage(connection)
            raise RuntimeError("simulated failure before commit")
        with patch("migrate_analysis_scout_rejection.rebuild_coverage",side_effect=fail_after_rebuild), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,"simulated failure"):
                migrate(self.path)
        with closing(sqlite3.connect(self.path)) as c:
            self.assertNotIn("scout_config",[r[1] for r in c.execute("PRAGMA table_info(analysis_coverage)")])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM analysis_coverage").fetchone()[0],5)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM coverage_reference").fetchone()[0],1)
            self.assertEqual(c.execute("PRAGMA quick_check").fetchone(),("ok",))

    def test_static_preview_reports_stale_scout_separately_without_rescreening(self):
        with redirect_stdout(io.StringIO()):
            migrate(self.path)
        with closing(sqlite3.connect(self.path)) as c:
            definition = ANALYZERS["missed_mate"]
            c.execute("INSERT INTO analysis_coverage(move_id,analysis_type,coverage_status,scout_version,scout_config) VALUES(6,'missed_mate','scouted_out','1','old-config')")
            c.row_factory = sqlite3.Row
            with patch("analysis_crawler.screen_move",side_effect=AssertionError("should reuse static pass")), redirect_stdout(io.StringIO()):
                report = preview_analyzer(c,definition,[{"move_id":6}],0)
            self.assertEqual(report["needs_scout"],1)
            self.assertEqual(report["needs_screen"],0)


if __name__ == "__main__":
    unittest.main()
