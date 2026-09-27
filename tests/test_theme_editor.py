"""Appearance integration contracts; all settings, assets and databases are temporary."""
from dataclasses import replace
from contextlib import closing
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest.mock import patch
import zipfile
import chess
from application_settings import ApplicationSettings, ApplicationSettingsRepository
from theme_core import Theme, ThemeRepository, BoardColors, DECORATION_SLOTS
from theme_core.active import ActiveThemeService, DEFAULT_THEME
from theme_core.assets import decode_png
from theme_core.editor import ThemeDraft
from theme_core.packages import import_theme_package, MAX_ARCHIVE_ENTRIES
from tests.test_theme_core import png_bytes
from tests.test_game_review_tactics import fixture_db
from merlin_ui.theme_editor import ThemeEditor
from merlin_ui.view_shell import MerlinViewShell
from merlin_ui.game_review_view import GameReviewView
from merlin_ui.candidate_viewer import CandidateViewer


class ThemeFixture(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.repo = ThemeRepository(self.path / "themes")
        self.settings = ApplicationSettingsRepository(self.path / "settings.json")
        self.service = ActiveThemeService(self.repo, self.settings)

    def draft(self):
        return ThemeDraft(name="Artist example", colors=BoardColors(light_square="#aaccdd"),
                          pieces={"white_king":decode_png(png_bytes())})

    def package(self, entries, name="package.zip"):
        path = self.path / name
        with zipfile.ZipFile(path, "w") as archive:
            for filename, data in entries:
                archive.writestr(filename, data)
        return path

    def manifest(self):
        return Theme("artist-example", "Artist example",
                     pieces={"white_king":"pieces/white_king.png"}).to_data()


class ThemeIntegrationTests(ThemeFixture):
    def test_default_requires_no_files_and_setting_uses_shared_schema(self):
        self.assertEqual(self.service.current.loaded, DEFAULT_THEME)
        self.assertFalse(self.repo.root.exists())
        self.assertFalse(self.settings.path.exists())
        definition = ApplicationSettings().schema()[0]
        self.assertEqual(definition.setting_id, "active_theme_id")
        self.assertEqual(definition.level, "basic")
        self.assertFalse(definition.affects_raw_cache_identity)
        self.assertFalse(definition.affects_result_currentness)

    def test_active_persists_restart_and_reapply_is_no_write(self):
        saved = self.draft().save(self.repo)
        calls = []
        unsubscribe = self.service.subscribe(calls.append)
        self.service.activate(saved.theme.theme_id)
        stamp = self.settings.path.stat().st_mtime_ns
        self.service.activate(saved.theme.theme_id)
        self.assertEqual(self.settings.path.stat().st_mtime_ns, stamp)
        self.assertEqual(len(calls), 1)
        fresh = ActiveThemeService(self.repo, self.settings)
        self.assertEqual(fresh.current.loaded, saved)
        unsubscribe()
        self.service.activate("default")
        self.assertEqual(len(calls), 1)

    def test_deleted_corrupt_missing_and_malformed_theme_fallback(self):
        for issue in ("missing_png", "corrupt_png", "manifest", "version", "deleted"):
            with self.subTest(issue=issue):
                saved = self.draft().save(self.repo)
                self.service.activate(saved.theme.theme_id)
                folder = self.repo.root / saved.theme.theme_id
                if issue == "missing_png":
                    (folder / "pieces/white_king.png").unlink()
                elif issue == "corrupt_png":
                    (folder / "pieces/white_king.png").write_bytes(b"bad")
                elif issue in ("manifest", "deleted"):
                    (folder / "theme.json").unlink()
                else:
                    data = saved.theme.to_data();data["version"] = 2
                    (folder / "theme.json").write_text(json.dumps(data))
                resolved = self.service.refresh()
                self.assertEqual(resolved.loaded, DEFAULT_THEME)
                self.assertTrue(resolved.error)
                self.assertEqual(self.settings.load().active_theme_id, saved.theme.theme_id)

    def test_bad_settings_fall_back_and_explicit_default_repairs(self):
        self.settings.path.write_text("{bad")
        self.assertTrue(self.service.refresh().error)
        self.service.activate("default")
        self.assertEqual(self.settings.load(), ApplicationSettings())
        with self.assertRaises(ValueError):
            ApplicationSettings(active_theme_id="../bad")

    def test_failed_activation_preserves_current_preference(self):
        saved = self.draft().save(self.repo)
        self.service.activate(saved.theme.theme_id)
        old = self.settings.path.read_bytes()
        with self.assertRaises((ValueError, OSError)):
            self.service.activate("missing")
        self.assertEqual(self.settings.path.read_bytes(), old)

    def test_folder_and_zip_art_tester_format_roundtrip(self):
        source = ThemeRepository(self.path / "artist")
        saved = self.draft().save(source)
        folder = source.root / saved.theme.theme_id
        imported = import_theme_package(self.repo, folder)
        self.assertEqual(imported.pieces, saved.pieces)
        for wrapper in ("", saved.theme.theme_id + "/"):
            entries = [(wrapper + p.relative_to(folder).as_posix(), p.read_bytes())
                       for p in folder.rglob("*") if p.is_file()]
            imported = import_theme_package(self.repo, self.package(entries))
            self.assertEqual(imported.pieces, saved.pieces)
            self.assertEqual(imported.theme.colors, saved.theme.colors)
            self.assertEqual(self.repo.load(imported.theme.theme_id), imported)
            managed = self.repo.root / imported.theme.theme_id
            self.assertEqual({p.relative_to(managed).as_posix() for p in managed.rglob("*") if p.is_file()},
                             {"theme.json", "pieces/white_king.png"})
        self.assertFalse(self.settings.path.exists())

    def test_frozen_art_tester_example_with_all_21_assets(self):
        data=json.loads((Path(__file__).parent/"fixtures/art_tester_theme_v1.json").read_text())
        prefix=data["theme_id"]+"/"
        entries=[(prefix,b""),(prefix+"pieces/",b""),(prefix+"board/",b""),
                 (prefix+"theme.json",json.dumps(data))]
        entries.extend((prefix+name,png_bytes()) for name in (*data["pieces"].values(),*data["decorations"].values()))
        loaded=import_theme_package(self.repo,self.package(entries))
        self.assertEqual(len(loaded.pieces),12)
        self.assertEqual(len(loaded.decorations),9)
        self.assertTrue(loaded.theme.complete)
        self.assertEqual(len([p for p in (self.repo.root/loaded.theme.theme_id).rglob("*") if p.is_file()]),22)

    def test_broken_managed_root_does_not_block_default_or_fallback(self):
        with patch("theme_core.active.ThemeRepository",side_effect=ValueError("Linked root")):
            default=ActiveThemeService(settings=self.settings)
            self.assertEqual(default.current.loaded,DEFAULT_THEME)
            self.settings.save(ApplicationSettings(active_theme_id="missing"))
            self.assertEqual(default.refresh().loaded,DEFAULT_THEME)
            self.assertTrue(default.current.error)

    def test_corrupt_archive_and_folder_rejected_without_install(self):
        path=self.path/"broken.zip";path.write_bytes(b"not a zip")
        with self.assertRaises(ValueError):import_theme_package(self.repo,path)
        source=ThemeRepository(self.path/"source")
        saved=self.draft().save(source)
        (source.root/saved.theme.theme_id/"payload.py").write_text("do not execute")
        with self.assertRaises(ValueError):import_theme_package(self.repo,source.root/saved.theme.theme_id)
        self.assertFalse(self.repo.root.exists())

    def test_archive_rejects_unapproved_extensions_and_nested_archives(self):
        for extension in ("exe", "dll", "py", "pyw", "js", "bat", "cmd", "ps1", "com", "vbs",
                          "msi", "scr", "jar", "reg", "lnk", "zip", "svg", "jpg", "txt"):
            path = self.package([("theme.json", json.dumps(self.manifest())),
                                 ("pieces/white_king.png", png_bytes()), ("payload."+extension,b"data")])
            with self.subTest(extension=extension), self.assertRaises(ValueError):
                import_theme_package(self.repo, path)
        self.assertFalse(self.repo.root.exists())

    def test_archive_rejects_unsafe_paths(self):
        for name in ("../x.png", "/x.png", "C:/x.png", "pieces\\x.png", "./x.png", "a//b.png", "a/../../x.png"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                import_theme_package(self.repo,self.package([(name,png_bytes())]))
        self.assertFalse(self.repo.root.exists())

    def test_archive_symlink_and_special_entry_rejected(self):
        for mode in (stat.S_IFLNK,stat.S_IFIFO,stat.S_IFCHR):
            entry = zipfile.ZipInfo("pieces/white_king.png")
            entry.create_system = 3;entry.external_attr = (mode | 0o777) << 16
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                import_theme_package(self.repo,self.package([(entry,png_bytes())]))

    def test_archive_budgets_duplicates_and_unlisted_png_rejected(self):
        cases = [
            [(f"{i}.png", b"") for i in range(MAX_ARCHIVE_ENTRIES+1)],
            [("theme.json",json.dumps(self.manifest())), ("unlisted.png",png_bytes())],
            [("theme.json",json.dumps(self.manifest())),("pieces/white_king.png",png_bytes((2049,1)))],
            [("theme.json",json.dumps(self.manifest())),("pieces/white_king.png",b"x"*(8*1024*1024+1))],
            [("theme.json",'{"name":"a","name":"b"}')],
        ]
        for entries in cases:
            with self.subTest(entries=len(entries)), self.assertRaises(ValueError):
                import_theme_package(self.repo,self.package(entries))
        self.assertFalse(self.repo.root.exists())

    def test_incomplete_draft_uses_assigned_art_and_missing_roles_remain_empty(self):
        saved = self.draft().save(self.repo)
        resolved = self.service.activate(saved.theme.theme_id)
        self.assertFalse(resolved.loaded.theme.complete)
        self.assertEqual(len(resolved.loaded.pieces),1)
        self.assertEqual(len(resolved.loaded.theme.missing_roles),11)

    def test_settings_write_failure_preserves_previous_file(self):
        self.settings.save(ApplicationSettings())
        old = self.settings.path.read_bytes()
        with patch("application_settings.os.replace",side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.settings.save(ApplicationSettings(active_theme_id="other"))
        self.assertEqual(old,self.settings.path.read_bytes())
        self.assertEqual(list(self.path.glob(".settings-*")),[])

    def test_core_is_portable_and_has_no_engine_database_ui_imports(self):
        code = """
import builtins
old = builtins.__import__
def guarded(name,*args,**kwargs):
    if name.startswith(('tkinter','sqlite3','chess.engine','analyze_','analysis_engine','quality_gate','the_scale','board_analysis')):
        raise AssertionError(name)
    return old(name,*args,**kwargs)
builtins.__import__=guarded
import theme_core.active, theme_core.packages, application_settings
"""
        result = subprocess.run([sys.executable,"-B","-c",code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


class ThemeEditorWidgetTests(ThemeFixture):
    def setUp(self):
        super().setUp()
        self.root = tk.Tk();self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *args:self.errors.append(args)
        self.addCleanup(self.root.destroy)
        self.view = ThemeEditor(self.root,self.service)

    def test_editor_snapshot_preview_activate_and_restore_default(self):
        other = tk.Toplevel(self.root);other.withdraw()
        shell = MerlinViewShell(other,theme_service=self.service)
        v = self.view
        v.draft = self.draft();v.sync_editor();v.theme_choice.set("Editor preview")
        self.assertFalse(v.activate_selected())
        self.assertEqual(shell.board_widget.theme_images.loaded,DEFAULT_THEME)
        self.assertTrue(v.save_theme())
        self.assertEqual(shell.board_widget.theme_images.loaded,DEFAULT_THEME)
        self.assertTrue(v.activate_selected())
        active = shell.board_widget.theme_images.loaded
        self.assertEqual(active.theme.colors,v.board_widget.theme_images.loaded.theme.colors)
        self.assertEqual(active.pieces,v.board_widget.theme_images.loaded.pieces)
        shell.board_widget.set_last_move(chess.Move.from_uci("e2e4"))
        shell.board_widget.set_tactical_targets([chess.E4])
        shell.board_widget.selected_square=chess.D4
        state=(shell.board_widget.board.fen(),shell.board_widget.last_move,shell.board_widget.tactical_targets)
        self.service.activate("default")
        self.assertEqual(state,(shell.board_widget.board.fen(),shell.board_widget.last_move,shell.board_widget.tactical_targets))
        self.assertEqual(shell.board_widget.selected_square,chess.D4)
        other.destroy()
        self.assertEqual(len(self.service._listeners),1)
        self.assertEqual(self.errors,[])

    def test_real_review_and_training_share_service_without_data_writes(self):
        fixture = fixture_db()
        db = self.path/"chess.db"
        with closing(sqlite3.connect(db)) as copy:
            fixture.backup(copy)
        fixture.close()
        before = db.read_bytes()
        review_root=tk.Toplevel(self.root);review_root.withdraw()
        training_root=tk.Toplevel(self.root);training_root.withdraw()
        with patch("theme_core.active.get_active_theme_service",return_value=self.service), \
             patch("chess.engine.SimpleEngine.popen_uci",side_effect=AssertionError("No engine")):
            review=GameReviewView(review_root,database_path=db)
            training=CandidateViewer(training_root, database_path=db)
            saved=self.draft().save(self.repo)
            self.service.activate(saved.theme.theme_id)
            for view in (review,training):
                self.assertEqual(view.board_widget.theme_images.loaded,saved)
            review.close();training.connection.close();training_root.destroy()
        self.assertEqual(db.read_bytes(),before)
        self.assertEqual(self.errors,[])

    def test_focus_refresh_across_independent_services_and_bad_assets(self):
        second_service=ActiveThemeService(self.repo,self.settings)
        other=tk.Toplevel(self.root);other.withdraw()
        shell=MerlinViewShell(other,theme_service=second_service)
        saved=self.draft().save(self.repo)
        self.service.activate(saved.theme.theme_id)
        second_service.refresh()
        self.assertEqual(shell.board_widget.theme_images.loaded,saved)
        (self.repo.root/saved.theme.theme_id/"pieces/white_king.png").unlink()
        second_service.refresh()
        self.assertEqual(shell.board_widget.theme_images.loaded,DEFAULT_THEME)
        other.destroy()
        self.assertEqual(self.errors,[])

    def test_appearance_entry_reuses_one_window_and_disposes_subscriptions(self):
        other=tk.Toplevel(self.root);other.withdraw()
        shell=MerlinViewShell(other,theme_service=self.service)
        shell.open_theme_editor()
        first=shell._theme_window
        shell.open_theme_editor()
        self.assertIs(shell._theme_window,first)
        first.destroy()
        shell.open_theme_editor()
        self.assertIsNot(shell._theme_window,first)
        other.destroy()
        self.assertEqual(len(self.service._listeners),1)
        self.assertEqual(self.errors,[])

    def test_decorations_overlays_and_controls_fit_preview(self):
        v=self.view
        v.draft=self.draft()
        for role in DECORATION_SLOTS:v.draft.decorations[role]=decode_png(png_bytes())
        v.sync_editor();v.overlays.set(True);v.show_position()
        board=v.board_widget
        board._layout(700,700);board.redraw()
        self.assertEqual(len(board.find_withtag("decoration")),9)
        for square in chess.SQUARES:
            self.assertEqual(board.xy_to_square(*board.square_center(square)),square)
        self.assertEqual(board.last_move,chess.Move.from_uci("e2e4"))
        self.assertEqual(board.selected_square,chess.D4)
        self.assertEqual(len(board.arrows),1)
        self.assertEqual(self.errors,[])
