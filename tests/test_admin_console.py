"""Read-only Admin contracts with temporary databases, preferences and export destinations."""
from contextlib import closing
from dataclasses import asdict, replace
import hashlib
import gc
import json
from pathlib import Path
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch
from admin_database import database_status, TABLES
from admin_engine import engine_status, test_engine as probe_engine
from admin_service import AdminService
from admin_capabilities import capability_status, profile_status
from application_settings import ApplicationSettingsRepository
from theme_core import ThemeRepository
from theme_core.active import ActiveThemeService
from theme_core.editor import ThemeDraft
from merlin_ui.admin_console import AdminConsole, SECTIONS
from merlin_ui.view_shell import MerlinViewShell

PROJECT=Path(__file__).resolve().parents[1]


def fixture(path):
    with closing(sqlite3.connect(path)) as c:
        c.executescript("""
            CREATE TABLE games(game_id INTEGER PRIMARY KEY,user_color TEXT,white_username TEXT);
            CREATE TABLE moves(move_id INTEGER PRIMARY KEY,game_id INTEGER,fen_before TEXT);
            CREATE TABLE tactic_candidates(candidate_id INTEGER PRIMARY KEY,tactic_type TEXT,detector_version TEXT,notes TEXT);
            CREATE TABLE tactic_occurrences(occurrence_id TEXT PRIMARY KEY,game_id INTEGER,occurrence_kind TEXT,actor_color TEXT);
            CREATE TABLE tactic_occurrence_evidence(revision_id TEXT PRIMARY KEY,occurrence_id TEXT REFERENCES tactic_occurrences,payload_json TEXT);
            CREATE TABLE tactic_occurrence_lines(line_id TEXT PRIMARY KEY,occurrence_id TEXT REFERENCES tactic_occurrences);
            CREATE TABLE tactic_occurrence_legacy_candidates(candidate_id INTEGER PRIMARY KEY REFERENCES tactic_candidates,occurrence_id TEXT REFERENCES tactic_occurrences);
            CREATE TABLE tactic_occurrence_review_links(review_identity TEXT PRIMARY KEY,occurrence_id TEXT REFERENCES tactic_occurrences);
            CREATE TABLE training_attempts(attempt_id INTEGER PRIMARY KEY,candidate_id INTEGER REFERENCES tactic_candidates);
            CREATE TABLE analysis_coverage(analysis_type TEXT,coverage_status TEXT,analyzer_version TEXT);
            CREATE TABLE engine_position_cache(cache_id INTEGER PRIMARY KEY,payload_json TEXT);
            CREATE TABLE engine_candidate_line_cache(line_set_id INTEGER PRIMARY KEY,payload_json TEXT);
            INSERT INTO games VALUES(1,'white','PRIVATE_USER_SECRET'),(2,NULL,'PRIVATE_USER_SECRET');
            INSERT INTO moves VALUES(1,1,'PRIVATE_FEN_SECRET');
            INSERT INTO tactic_candidates VALUES(1,'missed_fork','3.1','PRIVATE_CANDIDATE_SECRET');
            INSERT INTO tactic_occurrences VALUES('PRIVATE_ID_1',1,'played','white'),
                ('PRIVATE_ID_2',1,'played','black'),('PRIVATE_ID_3',1,'missed','white'),
                ('PRIVATE_ID_4',1,'missed','black'),('PRIVATE_ID_5',2,'missed','white');
            INSERT INTO tactic_occurrence_legacy_candidates VALUES(1,'PRIVATE_ID_1');
            INSERT INTO tactic_occurrence_evidence VALUES('private_revision','PRIVATE_ID_1','PRIVATE_EVIDENCE_SECRET');
            INSERT INTO training_attempts VALUES(1,1);
            INSERT INTO analysis_coverage VALUES('missed_fork','candidate','2'),('missed_pin','error','2');
            INSERT INTO engine_position_cache VALUES(1,'PRIVATE_CACHE_SECRET');
            INSERT INTO engine_candidate_line_cache VALUES(1,'PRIVATE_LINE_SECRET');
        """)
        c.commit()


class AdminFixture(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name);self.db=self.path/"test.db";fixture(self.db)
        self.themes=ActiveThemeService(ThemeRepository(self.path/"themes"),
                                      ApplicationSettingsRepository(self.path/"settings.json"))
        self.service=AdminService(PROJECT,self.db,self.themes)
        self.original=self.db.read_bytes()


class AdminReadTests(AdminFixture):
    def test_counts_relations_versions_and_physical_size(self):
        result=database_status(self.db)
        self.assertTrue(result.available)
        self.assertEqual(result.size_bytes,len(self.original))
        self.assertEqual(result.counts["games"],2)
        self.assertEqual(result.counts["tactic_occurrences"],5)
        self.assertEqual(result.occurrence["relations"],dict(
            missed_by_user=1,played_by_user=1,played_by_opponent=1,missed_by_opponent=1,unknown=1))
        self.assertEqual(result.occurrence["mapped_candidates"],1)
        self.assertEqual(result.occurrence["broken_links"],0)
        self.assertEqual(result.stored_versions[0]["detector_version"],"3.1")
        self.assertEqual(result.quick_check,"Not run")
        self.assertEqual(self.db.read_bytes(),self.original)

    def test_cache_content_bytes_available_without_dbstat(self):
        self.assertEqual(database_status(self.db).cache_payload_bytes,{})
        result=database_status(self.db,diagnostics=True)
        self.assertEqual(result.cache_payload_bytes["engine_position_cache"],len("PRIVATE_CACHE_SECRET"))
        self.assertEqual(result.cache_payload_bytes["engine_candidate_line_cache"],len("PRIVATE_LINE_SECRET"))
        self.assertEqual(self.db.read_bytes(),self.original)

    def test_optional_payload_timeout_preserves_completed_integrity(self):
        connection=sqlite3.connect(self.db.as_uri()+"?mode=ro",uri=True)
        connection.row_factory=sqlite3.Row
        proxy=Mock(wraps=connection)
        def execute(query,*args):
            if "sum(coalesce(length" in query:
                raise sqlite3.OperationalError("interrupted")
            return connection.execute(query,*args)
        proxy.execute.side_effect=execute
        with patch("admin_database.sqlite3.connect",return_value=proxy):
            result=database_status(self.db,diagnostics=True)
        self.assertEqual(result.quick_check,"ok")
        self.assertEqual(result.foreign_key_violations,0)
        self.assertEqual(result.cache_payload_bytes,{})
        self.assertIn("Cache payload size: interrupted",result.errors)
        self.assertEqual(self.db.read_bytes(),self.original)

    def test_missing_database_is_not_created(self):
        path=self.path/"missing.db";result=database_status(path,diagnostics=True)
        self.assertFalse(path.exists())
        self.assertFalse(result.available)
        self.assertIsNone(result.counts["games"])
        self.assertTrue(result.errors)

    def test_missing_optional_tables_are_unavailable_not_zero(self):
        path=self.path/"small.db"
        with closing(sqlite3.connect(path)) as c:c.execute("CREATE TABLE games(game_id INTEGER)")
        result=database_status(path)
        self.assertEqual(result.counts["games"],0)
        self.assertIsNone(result.counts["tactic_occurrences"])
        self.assertEqual(result.occurrence["schema_state"],"absent")
        self.assertIsNone(capability_status(PROJECT,None)["registered_analyzers"][0]["candidate_rows"])

    def test_diagnostics_are_read_only_and_expose_foreign_key_failures(self):
        good=database_status(self.db,diagnostics=True)
        self.assertEqual((good.quick_check,good.foreign_key_violations),("ok",0))
        with closing(sqlite3.connect(self.db)) as c:
            c.execute("INSERT INTO training_attempts VALUES (99,999)");c.commit()
        before=self.db.read_bytes()
        bad=database_status(self.db,diagnostics=True)
        self.assertEqual(bad.foreign_key_violations,1)
        self.assertEqual(self.db.read_bytes(),before)

    def test_registries_and_toolkit_metadata_do_not_promote_maturity(self):
        data=capability_status(PROJECT,{"missed_fork":1})
        from analysis_registry import ANALYZERS
        self.assertEqual({x["key"] for x in data["registered_analyzers"]},set(ANALYZERS))
        fork=next(x for x in data["registered_analyzers"] if x["key"]=="missed_fork")
        self.assertEqual(fork["analyzer_version"],str(ANALYZERS["missed_fork"].analyzer_version))
        self.assertEqual(fork["maturity"],"Not declared in registry")
        see=next(x for x in data["other_capabilities"] if x["key"]=="see")
        self.assertEqual(see["kind"],"toolkit")
        self.assertIn("Validated",see["status"])
        self.assertIn("Advisory only",see["description"])
        self.assertFalse(see["contract"]["authoritative_for_tactic_truth"])
        self.assertFalse(see["contract"]["safe_for_hard_rejection"])
        blunder=next(x for x in data["other_capabilities"] if x["key"]=="major_material_blunder")
        self.assertIn("ROBUST",blunder["status"])
        self.assertIn("Report-only",blunder["activation"])

    def test_profiles_are_real_read_only_and_no_global_selection_is_invented(self):
        from analysis_settings import BUILTIN_PROFILES
        data=profile_status()
        self.assertEqual(set(data["presets"]),set(BUILTIN_PROFILES))
        self.assertEqual(data["presets"]["normal"],asdict(BUILTIN_PROFILES["normal"]))
        self.assertIn("No global active",data["selection"])
        self.assertIn("Read-only",data["editing"])

    def test_snapshot_and_export_exclude_raw_private_data(self):
        with patch("subprocess.run",side_effect=AssertionError("No subprocess in ordinary Admin")):
            snapshot=self.service.snapshot(diagnostics=True)
            path=self.service.export(snapshot,self.path/"report.json")
        payload=path.read_text(encoding="utf-8")
        for marker in ("PRIVATE_USER_SECRET","PRIVATE_FEN_SECRET","PRIVATE_CANDIDATE_SECRET",
                       "PRIVATE_ID_","private_revision","PRIVATE_CACHE_SECRET","PRIVATE_LINE_SECRET","PRIVATE_EVIDENCE_SECRET"):
            self.assertNotIn(marker,payload)
        self.assertNotIn("source_namespace",payload)
        self.assertNotIn("backup_path",payload)
        self.assertEqual(json.loads(payload)["database"]["quick_check"],"ok")
        self.assertEqual(self.db.read_bytes(),self.original)
        self.assertFalse(self.themes.settings.path.exists())

    def test_export_cannot_overwrite_existing_file_or_other_extension(self):
        snapshot=self.service.snapshot()
        existing=self.path/"existing.json";existing.write_text("original")
        with self.assertRaises(FileExistsError):self.service.export(snapshot,existing)
        self.assertEqual(existing.read_text(),"original")
        with self.assertRaises(ValueError):self.service.export(snapshot,self.path/"anything.db")
        self.assertFalse((self.path/"anything.db").exists())

    def test_bad_theme_settings_and_manifest_do_not_crash_diagnostics(self):
        self.themes.settings.path.write_text("{malformed")
        service=AdminService(self.path,self.db,self.themes)
        (self.path/"occurrence_storage_lineage.json").write_text("{bad")
        snapshot=service.snapshot(diagnostics=True)
        self.assertTrue(snapshot.application["settings_error"])
        self.assertTrue(snapshot.application["theme_error"])
        self.assertIn("manifest_error",snapshot.database.occurrence)
        self.assertEqual(snapshot.database.quick_check,"ok")
        self.assertEqual(snapshot.build["release_version"],__import__("chesswizard_version").DISPLAY_VERSION)
        (self.path/"occurrence_storage_lineage.json").write_text("[]")
        self.assertIn("manifest_error",service.snapshot().database.occurrence)


class EngineDiagnosticTests(AdminFixture):
    def test_missing_engine_does_not_start_process(self):
        runner=Mock()
        result=probe_engine(self.path,runner=runner)
        self.assertFalse(result.found);runner.assert_not_called()

    def test_uci_only_request_reports_version_and_never_touches_db(self):
        from engine_cache import STOCKFISH_PATH
        executable=self.path/STOCKFISH_PATH;executable.parent.mkdir(parents=True);executable.write_bytes(b"fixture")
        runner=Mock(return_value=subprocess.CompletedProcess([],0,"id name Stockfish 18\nuciok\nreadyok\n",""))
        result=probe_engine(self.path,runner=runner)
        self.assertEqual(result.diagnostic,"Passed")
        self.assertEqual(result.reported_name,"Stockfish 18")
        self.assertEqual(runner.call_args.kwargs["input"],"uci\nisready\nquit\n")
        self.assertLessEqual(runner.call_args.kwargs["timeout"],5)
        self.assertNotIn("go",runner.call_args.kwargs["input"])
        self.assertEqual(self.db.read_bytes(),self.original)

    def test_timeout_and_bad_response_report_failure(self):
        from engine_cache import STOCKFISH_PATH
        executable=self.path/STOCKFISH_PATH;executable.parent.mkdir(parents=True);executable.write_bytes(b"fixture")
        result=probe_engine(self.path,runner=Mock(side_effect=subprocess.TimeoutExpired("engine",5)))
        self.assertEqual(result.diagnostic,"Failed")
        result=probe_engine(self.path,runner=Mock(return_value=subprocess.CompletedProcess([],0,"private raw output","")))
        self.assertEqual(result.diagnostic,"Failed")
        self.assertNotIn("private raw output",result.error)


class AdminWidgetTests(AdminFixture):
    def setUp(self):
        super().setUp()
        self.root=tk.Tk();self.root.withdraw()
        self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.addCleanup(self.close_ui)
        self.console=AdminConsole(self.root,self.service)
        self.wait()

    def close_ui(self):
        self.root.destroy()
        self.console = None
        gc.collect()

    def wait(self):
        deadline=time.monotonic()+6
        while self.console.busy and time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.assertFalse(self.console.busy,"Admin background request timed out")
        self.assertEqual(self.errors,[])

    def test_sections_read_only_profiles_and_diagnostics_render(self):
        self.assertEqual(set(self.console.pages),set(SECTIONS))
        for page in self.console.pages.values():
            self.assertEqual(page.cget("state"),"disabled")
        self.console.preset.set("deep");self.console.render_analysis()
        self.assertIn("Deep",self.console.pages["Analysis"].get("1.0","end"))
        self.console.load(True);self.wait()
        self.assertIn("quick_check: ok",self.console.pages["Diagnostics"].get("1.0","end"))
        self.assertIn("SEE Toolkit V1",self.console.pages["Analyzers"].get("1.0","end"))
        self.assertEqual(self.db.read_bytes(),self.original)

    def test_existing_theme_service_is_shared_and_disposed(self):
        saved=ThemeDraft(name="Admin theme").save(self.themes.repository)
        self.themes.activate(saved.theme.theme_id)
        self.assertIn("Admin theme",self.console.theme_label.get())
        self.assertNotIn("Appearance...",[b.cget("text") for b in self.console.buttons])
        self.root.destroy()
        self.assertEqual(len(self.themes._listeners),0)
        self.root=tk.Tk();self.root.withdraw()

    def test_export_uses_last_snapshot_and_no_automatic_file(self):
        self.assertFalse((self.path/"diagnostics.json").exists())
        with patch("merlin_ui.admin_console.filedialog.asksaveasfilename",return_value=str(self.path/"diagnostics.json")):
            self.console.export()
        self.assertTrue((self.path/"diagnostics.json").is_file())
        self.assertEqual(self.db.read_bytes(),self.original)

    def test_shared_shell_entry_reuses_one_console(self):
        other=tk.Toplevel(self.root);other.withdraw()
        shell=MerlinViewShell(other,theme_service=self.themes,admin_database_path=self.db)
        with patch("admin_service.AdminService",return_value=self.service) as factory:
            shell.open_admin_console()
            factory.assert_called_once_with(database_path=self.db,theme_service=self.themes)
            first=shell._admin_window
            shell.open_admin_console()
            self.assertIs(first,shell._admin_window)
        deadline=time.monotonic()+6
        while shell._admin_console.busy and time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.assertFalse(shell._admin_console.busy)
        other.destroy()
        self.assertEqual(self.errors,[])

    def test_busy_action_does_not_launch_another_job(self):
        self.console.busy=True
        with patch("threading.Thread") as thread:
            self.console.load(True)
            thread.assert_not_called()
        self.console.busy=False
