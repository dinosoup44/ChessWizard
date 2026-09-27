"""Destructive operations run only against disposable databases and managed themes."""
from contextlib import closing
from dataclasses import replace
import io
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import chess.pgn

from database_bootstrap import ensure_database
from data_management_repository import DataManagementRepository, validate_integrity
from data_activity import exclusive_data_activity, DataBusyError
from game_import_repository import GameImportRepository
from game_import_service import GameImportService
from ignored_imports import migrate_ignored_imports
from tests.test_game_import import pgn, HTTPFixture
from application_settings import ApplicationSettingsRepository
from theme_core import ThemeRepository
from theme_core.active import ActiveThemeService
from theme_core.editor import ThemeDraft
from theme_core.management import ThemeManagementService
import import_chesscom


class DataFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.path = self.folder / "test.db"
        ensure_database(self.path)
        self.repo = DataManagementRepository(self.path)
        with closing(sqlite3.connect(self.path)) as db:
            importer = GameImportRepository(db)
            for n in range(1, 4):
                raw = pgn(identity=str(n))
                importer.import_game(import_chesscom, "Example_User", chess.pgn.read_game(io.StringIO(raw)), raw)
            for gid in (1, 2):
                mid = db.execute("SELECT min(move_id) FROM moves WHERE game_id=?", (gid,)).fetchone()[0]
                cid = db.execute("INSERT INTO tactic_candidates(move_id,tactic_type) VALUES (?,'missed_fork')", (mid,)).lastrowid
                ep = db.execute("INSERT INTO tactic_episodes(game_id,tactic_type,primary_candidate_id,detector_version) VALUES (?,'missed_fork',?,3)", (gid,cid)).lastrowid
                db.execute("INSERT INTO tactic_episode_members(episode_id,candidate_id,sequence_order) VALUES (?,?,0)", (ep,cid))
                db.execute("INSERT INTO training_attempts(candidate_id,episode_id,tactic_type,result) VALUES (?,?,'missed_fork','solved')", (cid,ep))
                db.execute("INSERT INTO analysis_coverage(move_id,analysis_type,coverage_status,candidate_id) VALUES (?,'missed_fork','candidate',?)", (mid,cid))
                db.execute("INSERT INTO engine_analysis(move_id) VALUES (?)", (mid,))
                oid, rev = f"o{gid}",f"r{gid}"
                db.execute("""INSERT INTO tactic_occurrences VALUES (?,1,?,'test',?,?,'missed','white','fork',
                    'd2d4','instance',1,'fen','e2e4',CURRENT_TIMESTAMP)""", (oid, str(gid),gid,mid))
                db.execute("""INSERT INTO tactic_occurrence_evidence VALUES (?,?,'Fork','3','current','source',
                    'white','verified','approved','verified','unknown','{}',1,CURRENT_TIMESTAMP)""", (rev,oid))
                db.execute("INSERT INTO tactic_occurrence_lines VALUES (?,?,?,'main','proof','main','[]','source','complete')", (f"l{gid}",oid,rev))
                db.execute("INSERT INTO tactic_occurrence_legacy_candidates VALUES (?,?)", (cid,oid))
                db.execute("INSERT INTO tactic_occurrence_review_links VALUES (?,?,?)", (f"candidate:{cid}",oid,rev))
                db.execute("INSERT INTO analysis_runs(user_id,tool_name,last_game_id) VALUES (1,'old',?)", (gid,))
            db.execute("INSERT INTO engine_candidate_line_cache(fen,engine_identity,schema_version,payload_json) VALUES ('shared','engine',1,'{}')")
            db.execute("""INSERT INTO engine_position_cache(fen,engine_name,engine_version,analysis_profile,
                limit_type,limit_value,side_to_move,score_type) VALUES ('shared','engine','1','profile','depth',1,'white','cp')""")
            db.commit()
        profile = patch.dict(os.environ, CHESSWIZARD_DATA_DIR=str(self.folder))
        profile.start(); self.addCleanup(profile.stop)

    def rows(self, table):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(f"SELECT * FROM {table}").fetchall()

    def clean(self):
        with closing(sqlite3.connect(self.path)) as db:
            validate_integrity(db)
            self.assertEqual(db.execute("PRAGMA quick_check").fetchall(), [("ok",)])



class DataTests(DataFixture):
    def test_exact_preview_zero_writes_and_single_delete_preserves_shared_and_outside(self):
        original = self.path.read_bytes()
        plan = self.repo.plan_game_deletion((1,))
        self.assertEqual(original, self.path.read_bytes())
        counts = dict(plan.counts)
        for table in ("games","tactic_candidates","tactic_occurrences","training_attempts",
                      "tactic_occurrence_evidence","tactic_occurrence_lines","tactic_occurrence_review_links"):
            self.assertEqual(counts[table], 1, table)
        self.assertEqual(counts["moves"], 4)
        cache = self.rows("engine_candidate_line_cache"), self.rows("engine_position_cache")
        candidate2 = self.rows("tactic_candidates")[1]
        self.repo.execute_game_deletion(plan)
        self.assertEqual(self.rows("tactic_candidates"), [candidate2])
        self.assertEqual(cache, (self.rows("engine_candidate_line_cache"),self.rows("engine_position_cache")))
        self.assertEqual(len(self.rows("games")), 2)
        self.clean()

    def test_multiple_including_unanalyzed_and_delete_all(self):
        self.repo.execute_game_deletion(self.repo.plan_game_deletion((1,3)))
        self.assertEqual([r[0] for r in self.rows("games")], [2])
        self.repo.execute_game_deletion(self.repo.plan_game_deletion((2,)))
        self.assertFalse(self.rows("games"))
        self.clean()

    def test_stale_plan_rejected_without_deleting(self):
        plan = self.repo.plan_game_deletion((1,))
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE tactic_candidates SET notes='changed' WHERE candidate_id=1");db.commit()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "changed since"):
            self.repo.execute_game_deletion(plan)
        self.assertEqual(before, self.path.read_bytes())

    def test_ignore_and_delete_rollback_together(self):
        plan = self.repo.plan_game_deletion((1,))
        before = self.path.read_bytes()
        calls = 0
        def fail_after_delete(db):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("injected integrity failure")
            validate_integrity(db)
        with patch("data_management_repository.validate_integrity", side_effect=fail_after_delete):
            with self.assertRaises(ValueError):
                self.repo.execute_game_deletion(plan, ignore_future_imports=True)
        self.assertEqual(before, self.path.read_bytes())
        self.assertFalse(self.repo.ignored())

    def test_ignore_import_skip_idempotent_and_allow_again(self):
        self.repo.execute_game_deletion(self.repo.plan_game_deletion((1,)), ignore_future_imports=True)
        self.assertEqual(self.repo.ignored()[0][:2], ("chesscom","1"))
        service = GameImportService(self.path)
        fixture = HTTPFixture(pgn(identity="1"))
        with patch("game_import_http.urlopen", fixture):
            for _ in range(2):
                result = service.run("chesscom", "Example_User")
                self.assertEqual((result.added,result.existing,result.ignored,result.errors),(0,0,1,0))
                self.assertIn("Ignored by user: 1", result.summary())
        self.repo.allow_import_again((("chesscom","1"),))
        self.assertEqual(len(self.rows("games")),2)
        with patch("game_import_http.urlopen", fixture):
            self.assertEqual(service.run("chesscom","Example_User").added,1)
        self.assertGreater(max(r[0] for r in self.rows("games")),3)
        self.clean()

    def test_ignore_identity_includes_source(self):
        from ignored_imports import is_ignored
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("INSERT INTO ignored_import_games(source,source_game_id) VALUES ('chesscom','same')");db.commit()
            self.assertTrue(is_ignored(db,"chesscom","same"))
            self.assertFalse(is_ignored(db,"lichess","same"))

    def test_reset_preserves_metadata_settings_ignores_and_schema(self):
        settings = self.folder/"settings.json";settings.write_text('{"sentinel":1}')
        reviews = self.folder/"reviews.jsonl";reviews.write_text("historical sentinel")
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("INSERT INTO ignored_import_games(source,source_game_id) VALUES ('lichess','blocked')")
            db.commit()
            schema = db.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
        metadata = self.rows("application_metadata")
        self.repo.execute_game_deletion(self.repo.plan_reset())
        self.assertEqual(self.rows("application_metadata"), metadata)
        self.assertEqual(settings.read_text(),'{"sentinel":1}')
        self.assertEqual(reviews.read_text(),"historical sentinel")
        self.assertEqual(len(self.repo.ignored()),1)
        for table in ("games","moves","tactic_candidates","tactic_occurrences","training_attempts","analysis_coverage",
                      "chess_accounts","analysis_runs","engine_analysis","engine_position_cache","engine_candidate_line_cache"):
            self.assertFalse(self.rows(table),table)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(schema,db.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall())
        before = self.path.read_bytes()
        self.repo.execute_game_deletion(self.repo.plan_reset())
        self.assertEqual(before,self.path.read_bytes())
        self.repo.execute_game_deletion(self.repo.plan_reset(clear_ignored=True))
        self.assertFalse(self.repo.ignored())
        self.clean()

    def test_reset_includes_legacy_negative_development_game(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("INSERT INTO games(game_id,user_id,source,source_game_id) VALUES (-1,1,'dev','legacy')")
            db.commit()
        plan = self.repo.plan_reset()
        self.assertIn(-1,plan.game_ids)
        self.repo.execute_game_deletion(plan)
        self.assertFalse(self.rows("games"))
        self.clean()

    def test_training_lifetime_blocks_deletion_and_stale_candidate_cannot_start(self):
        from training_session import begin_training_session, RemovedTrainingCandidate
        plan = self.repo.plan_game_deletion((1,))
        with closing(sqlite3.connect(self.path)) as db:
            session = begin_training_session(db,self.path,1,"missed_fork",1)
            try:
                with self.assertRaises(DataBusyError):
                    self.repo.execute_game_deletion(plan)
            finally:session.close()
            plan = self.repo.plan_game_deletion((1,))
            self.repo.execute_game_deletion(plan)
            with self.assertRaises(RemovedTrainingCandidate):
                begin_training_session(db,self.path,1,"missed_fork",1)
        self.clean()

    def test_new_schema_ownership_must_be_reviewed(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TABLE future_feature(game_id)");db.commit()
        with self.assertRaisesRegex(ValueError,"Unreviewed"):
            self.repo.plan_reset()

    def test_reset_rollback(self):
        plan = self.repo.plan_reset(clear_ignored=True)
        before = self.path.read_bytes()
        with patch("data_management_repository.validate_integrity", side_effect=[None, ValueError("injected")]):
            with self.assertRaises(ValueError):
                self.repo.execute_game_deletion(plan)
        self.assertEqual(before,self.path.read_bytes())

    def test_busy_operation_blocks_delete_import_and_analysis(self):
        from game_analysis_service import GameAnalysisService
        plan = self.repo.plan_game_deletion((1,))
        with exclusive_data_activity(self.path):
            with self.assertRaises(DataBusyError):self.repo.execute_game_deletion(plan)
            self.assertEqual(GameImportService(self.path).run("chesscom","Example_User").errors,1)
            self.assertEqual(GameAnalysisService(self.path).run().errors,1)

    def test_occurrence_without_fk_is_still_validated(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE tactic_occurrences SET game_id=999");db.commit()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,"ownership"):
            self.repo.plan_game_deletion((1,))
        self.assertEqual(before,self.path.read_bytes())

    def test_migration_is_explicit_additive_and_idempotent(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("DROP TABLE ignored_import_games");db.commit()
        before = self.path.read_bytes()
        self.assertFalse(self.repo.ignore_available())
        self.repo.plan_game_deletion((1,))
        self.assertEqual(before,self.path.read_bytes())
        with closing(sqlite3.connect(self.path)) as db:
            tables = {r[0]:db.execute(f"SELECT * FROM {r[0]}").fetchall()
                      for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            migrate_ignored_imports(db)
            for name, rows in tables.items():self.assertEqual(rows,db.execute(f"SELECT * FROM {name}").fetchall())
            migrated = self.path.read_bytes()
            migrate_ignored_imports(db)
            self.assertEqual(migrated,self.path.read_bytes())


class ThemeDeleteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.active = ActiveThemeService(ThemeRepository(self.folder/"themes"),
                                        ApplicationSettingsRepository(self.folder/"settings.json"))
        self.service = ThemeManagementService(self.active)
        self.theme = self.active.repository.save(name="Sample",colors=ThemeDraft().colors,pieces={},decorations={})

    def test_inactive_and_active_delete(self):
        plan = self.service.plan(self.theme.theme.theme_id)
        self.assertFalse(plan.active)
        self.service.delete(plan)
        self.assertFalse(self.active.repository.list_themes())
        theme = self.active.repository.save(name="Active",colors=ThemeDraft().colors,pieces={},decorations={})
        self.active.activate(theme.theme.theme_id)
        events=[];self.active.subscribe(events.append)
        self.service.delete(self.service.plan(theme.theme.theme_id))
        self.assertEqual(self.active.settings.load().active_theme_id,"default")
        self.assertEqual(events[-1].loaded.theme.theme_id,"default")

    def test_fallback_paths_and_hardlinks_protected(self):
        for unsafe in ("default","..","../themes",str(self.folder),""):
            with self.assertRaises((ValueError,OSError)):self.service.plan(unsafe)
        folder=self.active.repository._folder(self.theme.theme.theme_id)
        outside=self.folder/"shared.json"
        os.link(folder/"theme.json",outside)
        with self.assertRaisesRegex(ValueError,"Shared"):
            self.service.plan(self.theme.theme.theme_id)
        self.assertTrue(outside.exists())

    def test_symlink_rejected(self):
        folder=self.active.repository._folder(self.theme.theme.theme_id)
        target=self.folder/"target";target.mkdir()
        try: (folder/"escape").symlink_to(target,target_is_directory=True)
        except OSError:self.skipTest("Symlink creation unavailable without Windows privilege")
        with self.assertRaises(ValueError):self.service.plan(self.theme.theme.theme_id)

    def test_asset_counts_complete_removal_and_reparse_guard(self):
        from PIL import Image
        from theme_core.assets import decode_png
        image=io.BytesIO();Image.new("RGBA",(4,4),(0,0,0,0)).save(image,format="PNG")
        theme=self.active.repository.save(name="Assets",colors=ThemeDraft().colors,
            pieces={"white_king":decode_png(image.getvalue())},decorations={})
        plan=self.service.plan(theme.theme.theme_id)
        self.assertEqual(plan.asset_count,1)
        with patch.object(Path,"is_symlink",return_value=True):
            with self.assertRaises(ValueError):self.service.delete(plan)
        folder=self.active.repository._folder(plan.theme_id)
        self.service.delete(plan)
        self.assertFalse(folder.exists())

    def test_partial_failure_restores_package_and_valid_fallback(self):
        self.active.activate(self.theme.theme.theme_id)
        plan=self.service.plan(self.theme.theme.theme_id)
        def partial_failure(folder):
            (folder/"theme.json").unlink()
            raise OSError("locked")
        with patch("theme_core.management.shutil.rmtree",side_effect=partial_failure):
            with self.assertRaises(OSError):self.service.delete(plan)
        self.assertEqual(self.active.settings.load().active_theme_id,"default")
        self.active.repository.load(plan.theme_id)


class DataUITests(DataFixture):
    def setUp(self):
        super().setUp()
        from merlin_ui.game_review_view import GameReviewView
        from game_review_sets import ALL_GAMES
        theme=patch("theme_core.active._default_service",None);theme.start();self.addCleanup(theme.stop)
        self.root=tk.Tk();self.root.withdraw()
        self.view=GameReviewView(self.root,self.path,review_sets=(ALL_GAMES,))
        self.addCleanup(self.view.close)

    def pump(self, dialog):
        end=time.monotonic()+10
        while dialog.busy and time.monotonic()<end:
            self.root.update();time.sleep(.01)
        self.root.update()
        self.assertFalse(dialog.busy)

    def test_menu_preview_cancel_and_displayed_game_delete_refresh(self):
        menu=self.root.nametowidget(self.root.cget("menu"))
        file=self.root.nametowidget(menu.entrycget("File","menu"))
        file.invoke("Manage Data...");self.root.update()
        dialog=self.view.management_dialog
        self.assertEqual(len(dialog.games.get_children()),3)
        before=self.path.read_bytes()
        dialog.games.selection_set("1")
        with patch("merlin_ui.manage_data_dialog.messagebox.askyesno",return_value=False) as confirm:
            dialog.delete_games(False);self.pump(dialog)
            self.assertIn("4",confirm.call_args.args[1])
        self.assertEqual(before,self.path.read_bytes())
        self.view.open_game_position(1,1)
        training=self.view.open_training()
        with patch("merlin_ui.manage_data_dialog.messagebox.askyesno",return_value=True):
            dialog.delete_games(False);self.pump(dialog)
        self.assertNotEqual(self.view.current_game["game_id"],1)
        self.assertTrue(all(c["game_id"]!=1 for c in training.candidates))
        self.clean()

    def test_reset_confirmation_defaults_and_empty_views(self):
        from merlin_ui.admin_console import AdminConsole
        from admin_service import AdminService
        admin=AdminConsole(tk.Toplevel(self.root),AdminService(database_path=self.path))
        admin.open_reset();dialog=admin.reset_dialog
        self.assertFalse(dialog.clear_ignored.get())
        before=self.path.read_bytes()
        with patch("merlin_ui.manage_data_dialog.messagebox.askyesno",return_value=False):
            dialog.preview();self.pump(dialog)
        self.assertEqual(before,self.path.read_bytes())
        with patch("merlin_ui.manage_data_dialog.messagebox.askyesno",return_value=True):
            dialog.preview();self.pump(dialog)
        self.assertFalse(self.view.games)
        self.assertFalse(self.rows("games"))
        self.clean()
