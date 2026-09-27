"""First-run contracts use isolated profiles; no production data or engine searches."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from application_paths import resolve_database_path, resolve_review_path
from application_settings import application_data_directory, ApplicationSettingsRepository
from database_bootstrap import BootstrapError, ensure_database
from database_schema import REQUIRED_COLUMNS, SCHEMA_STATEMENTS
from chesswizard_version import DISPLAY_VERSION, PRODUCT_NAME, VERSION
from game_review_sets import ALL_GAMES, load_review_sets
from human_analyzer_review_repository import HumanReviewRepository
from theme_core import ThemeRepository
from theme_core.active import ActiveThemeService


class IsolatedProfile(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profile = self.root / 'profile'
        self.db = self.profile / 'merlin.db'
        override = patch.dict(os.environ, CHESSWIZARD_DATA_DIR=str(self.profile))
        override.start(); self.addCleanup(override.stop)
        engine = patch('chess.engine.SimpleEngine.popen_uci', side_effect=AssertionError('No engine during startup'))
        engine.start(); self.addCleanup(engine.stop)


class BootstrapTests(IsolatedProfile):
    def test_current_schema_occurrence_and_zero_personal_rows(self):
        result = ensure_database(self.db)
        self.assertTrue(result.created)
        with closing(sqlite3.connect(self.db)) as c:
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertLessEqual(set(REQUIRED_COLUMNS), tables)
            self.assertIn('tactic_occurrence_evidence', tables)
            for table in tables - {'application_metadata'}:
                self.assertEqual(c.execute('SELECT count(*) FROM "'+table+'"').fetchone()[0], 0, table)
            self.assertEqual(c.execute('SELECT count(*) FROM application_metadata').fetchone()[0], 5)
            self.assertEqual(c.execute('PRAGMA quick_check').fetchall(), [('ok',)])
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])
            actual = dict(c.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' AND name!='application_metadata'"))
        with closing(sqlite3.connect(':memory:')) as expected:
            for sql in SCHEMA_STATEMENTS: expected.execute(sql)
            self.assertEqual(actual, dict(expected.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")))

    def test_idempotent_existing_bytes_and_mtime(self):
        ensure_database(self.db)
        with closing(sqlite3.connect(self.db)) as c:
            c.execute("INSERT INTO application_metadata VALUES ('test_sentinel','keep')"); c.commit()
        before = self.db.read_bytes(), self.db.stat().st_mtime_ns
        self.assertFalse(ensure_database(self.db).created)
        self.assertEqual(before, (self.db.read_bytes(), self.db.stat().st_mtime_ns))

    def test_existing_current_schema_without_new_metadata_is_not_migrated(self):
        self.profile.mkdir()
        with closing(sqlite3.connect(self.db)) as c:
            for sql in SCHEMA_STATEMENTS: c.execute(sql)
            c.commit()
        original = self.db.read_bytes()
        self.assertFalse(ensure_database(self.db).created)
        self.assertEqual(original, self.db.read_bytes())

    def test_failed_schema_transaction_leaves_no_published_database(self):
        with patch('database_bootstrap.SCHEMA_STATEMENTS', ('CREATE TABLE temporary_fact(x)', 'INVALID SQL')):
            with self.assertRaises(BootstrapError): ensure_database(self.db)
        self.assertFalse(self.db.exists())
        self.assertEqual(list(self.profile.iterdir()), [])

    def test_existing_bad_file_is_preserved(self):
        self.profile.mkdir(); self.db.write_bytes(b'not a database')
        with self.assertRaises(BootstrapError): ensure_database(self.db)
        self.assertEqual(self.db.read_bytes(), b'not a database')

    def test_existing_old_schema_is_preserved(self):
        self.profile.mkdir()
        with closing(sqlite3.connect(self.db)) as c: c.execute('CREATE TABLE games(game_id)')
        before = self.db.read_bytes()
        with self.assertRaisesRegex(BootstrapError, 'missing tables'): ensure_database(self.db)
        self.assertEqual(before, self.db.read_bytes())

    def test_publish_race_preserves_winning_database(self):
        from database_bootstrap import _publish_new
        winner = self.root/'winner.db'; ensure_database(winner)
        expected = winner.read_bytes()
        def competing_publish(temporary, destination):
            destination.write_bytes(expected)
            return _publish_new(temporary, destination)
        with patch('database_bootstrap._publish_new', side_effect=competing_publish):
            self.assertFalse(ensure_database(self.db).created)
        self.assertEqual(expected, self.db.read_bytes())
        self.assertEqual(list(self.profile.iterdir()), [self.db])

    def test_new_installation_namespace_is_not_shared(self):
        ensure_database(self.db); other = self.root/'other.db'; ensure_database(other)
        def namespace(path):
            with closing(sqlite3.connect(path)) as c:
                return c.execute("SELECT value FROM application_metadata WHERE key='source_namespace'").fetchone()[0]
        self.assertNotEqual(namespace(self.db), namespace(other))

    def test_unsupported_bootstrap_version_is_not_repaired(self):
        ensure_database(self.db)
        with closing(sqlite3.connect(self.db)) as c:
            c.execute("UPDATE application_metadata SET value='99' WHERE key='bootstrap_version'"); c.commit()
        before = self.db.read_bytes()
        with self.assertRaisesRegex(BootstrapError, 'Unsupported'): ensure_database(self.db)
        self.assertEqual(before, self.db.read_bytes())


class UserPathTests(IsolatedProfile):
    def test_explicit_profile_never_falls_back_to_source_database(self):
        source = self.root/'source'; source.mkdir(); (source/'merlin.db').write_bytes(b'private')
        self.assertEqual(resolve_database_path(root=source), self.db)
        self.assertEqual(resolve_database_path(self.root/'explicit.db'), self.root/'explicit.db')

    def test_existing_user_database_precedes_development_database(self):
        self.profile.mkdir(); self.db.touch()
        source = self.root/'source'; source.mkdir(); (source/'merlin.db').touch()
        with patch.dict(os.environ, CHESSWIZARD_DATA_DIR=''), patch('application_paths.application_data_directory', return_value=self.profile):
            self.assertEqual(resolve_database_path(root=source), self.db)

    def test_development_fallback_is_source_only_and_cwd_independent(self):
        source = self.root/'source'; source.mkdir(); legacy = source/'merlin.db'; legacy.touch()
        with patch.dict(os.environ, CHESSWIZARD_DATA_DIR=''), patch('application_paths.application_data_directory', return_value=self.profile):
            self.assertEqual(resolve_database_path(root=source, frozen=False), legacy)
            self.assertEqual(resolve_database_path(root=source, frozen=True), self.db)

    def test_relative_profile_override_is_rejected(self):
        with patch.dict(os.environ, CHESSWIZARD_DATA_DIR='relative'):
            with self.assertRaises(ValueError): application_data_directory()

    def test_missing_reviews_are_user_local_and_not_created_on_load(self):
        repository = HumanReviewRepository()
        self.assertEqual(repository.path, self.profile/'reviews/human_analyzer_review.jsonl')
        self.assertEqual(repository.load(), ())
        self.assertFalse(self.profile.exists())

    def test_existing_development_review_path_preserved(self):
        (self.root/'merlin.db').touch(); reviews = self.root/'reviews/human_analyzer_review.jsonl'
        reviews.parent.mkdir(); reviews.write_text('')
        with patch.dict(os.environ, CHESSWIZARD_DATA_DIR=''), patch('application_paths.application_root', return_value=self.root):
            self.assertEqual(resolve_review_path(self.root/'merlin.db'), reviews)


class OptionalReviewAndVersionTests(IsolatedProfile):
    def test_missing_catalog_keeps_normal_all_games(self):
        self.assertEqual(load_review_sets(self.root/'absent.json'), (ALL_GAMES,))

    def test_existing_development_catalog_still_loads(self):
        path=self.root/'synthetic-catalog.json'
        path.write_text(json.dumps({'schema_version':1,'sets':[
            {'id':f'synthetic-{i}','label':f'Synthetic {i}','description':'Test catalog','entries':[]}
            for i in range(5)]}))
        self.assertEqual(len(load_review_sets(path)), 6)

    def test_malformed_present_catalog_is_not_silently_hidden(self):
        path = self.root/'bad.json'; path.write_text('{')
        with self.assertRaises(ValueError): load_review_sets(path)

    def test_admin_snapshot_and_export_use_central_version(self):
        from admin_service import AdminService
        ensure_database(self.db)
        themes = ActiveThemeService(ThemeRepository(self.profile/'themes'), ApplicationSettingsRepository(self.profile/'settings.json'))
        service = AdminService(database_path=self.db, theme_service=themes)
        snapshot = service.snapshot(diagnostics=True)
        self.assertEqual(snapshot.build['release_version'], DISPLAY_VERSION)
        self.assertEqual(snapshot.build['version'], VERSION)
        self.assertEqual(snapshot.build['product_name'], PRODUCT_NAME)
        self.assertIn('initialized', snapshot.database.occurrence['activation'])
        target = service.export(snapshot, self.root/'diagnostic.json')
        self.assertEqual(json.loads(target.read_text())['build']['release_version'], DISPLAY_VERSION)

    def test_single_runtime_version_literal(self):
        project = Path(__file__).resolve().parents[1]
        runtime = list(project.glob('*.py')) + list((project/'merlin_ui').glob('*.py'))
        matches = [p.name for p in runtime if VERSION in p.read_text(encoding='utf-8-sig')]
        self.assertEqual(matches, ['chesswizard_version.py'])

    def test_ui_startup_failure_shows_error_and_does_not_continue(self):
        from merlin_ui.startup import prepare_database
        window = Mock()
        with patch('merlin_ui.startup.ensure_database', side_effect=BootstrapError('test failure')), patch('merlin_ui.startup.messagebox.showerror') as show, self.assertLogs('merlin_ui.startup', level='ERROR'):
            self.assertIsNone(prepare_database(window, self.db))
        show.assert_called_once(); window.destroy.assert_called_once()
        self.assertIn('test failure', show.call_args.args[1])

    def test_tactics_line_and_training_link_work_without_review_metadata(self):
        from tests.test_game_review_tactics import fixture_db, add
        from merlin_ui.game_review_view import GameReviewView
        self.profile.mkdir()
        with closing(fixture_db()) as source, closing(sqlite3.connect(self.db)) as target:
            candidate = add(source, 'missed_fork'); source.backup(target)
        before = self.db.read_bytes()
        train = Mock(); root = tk.Tk()
        themes = ActiveThemeService(ThemeRepository(self.profile/'themes'), ApplicationSettingsRepository(self.profile/'settings.json'))
        try:
            with patch('theme_core.active.get_active_theme_service', return_value=themes), patch('game_review_sets.BUILTIN_REVIEW_SETS', self.root/'missing.json'):
                view = GameReviewView(root, self.db, on_train_candidate=train)
                view.show_game(next(i for i,g in enumerate(view.games) if g['game_id']==1)); root.update()
                view.tactics_panel.listbox.selection_set(0); view.tactics_panel.listbox.event_generate('<<ListboxSelect>>'); root.update()
                self.assertEqual(view.tactics_panel.selected.candidate_id, candidate)
                self.assertIsNone(view.human_review_panel)
                self.assertIsNone(view.review_set_picker)
                self.assertEqual(view.board_widget.board.fen(), view.tactics_panel.selected.fen_before)
                view.tactics_panel.line_button.invoke(); root.update(); self.assertIsNotNone(view.line_playback)
                view.tactics_panel.line_button.invoke(); root.update(); self.assertIsNone(view.line_playback)
                view.tactics_panel.train_button.invoke(); train.assert_called_once_with(candidate)
        finally:
            view.close()
        self.assertEqual(before, self.db.read_bytes())
        self.assertFalse((self.profile/'reviews').exists())
