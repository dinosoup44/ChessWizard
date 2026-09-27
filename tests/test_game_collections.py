"""Collections against disposable databases only; all engine access is prohibited."""
from contextlib import closing
from dataclasses import asdict, replace
import ast
import hashlib
import json
from pathlib import Path
import sqlite3
import tkinter as tk
import time
import unittest
from unittest.mock import patch

from database_bootstrap import ensure_database
from data_activity import exclusive_data_activity, DataBusyError
from data_management_repository import DataManagementRepository
from game_collection_models import CollectionDetails
from game_collection_schema import migrate_game_collections, validate_schema, SCHEMA_OBJECTS
from game_collection_service import GameCollectionService
from game_search_models import GameSearchCriteria as Criteria, sorted_games
from game_search_repository import metadata_query
from game_search_service import GameSearchService
from merlin_ui.game_collections import CollectionManager
from merlin_ui.game_explorer import GameExplorerWindow
from tests.test_game_search import SearchFixture
from tests.test_game_import import pgn


def drop_collections(db):
    db.execute('DROP TABLE game_collection_members')
    db.execute('DROP TABLE game_collections')
    db.commit()


def unrelated_snapshot(db):
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
              if r[0] not in ('game_collections', 'game_collection_members', 'sqlite_sequence')]
    return {name: tuple(tuple(r) for r in db.execute('SELECT * FROM "'+name+'" ORDER BY rowid')) for name in tables}


class CollectionFixture(SearchFixture):
    def setUp(self):
        super().setUp()
        for number in range(6, 11):
            self.import_fixture(pgn(identity=str(number), day=f'2026.09.{number:02}'))
        self.collections = GameCollectionService(self.path)
        self.study = self.collections.create(CollectionDetails('Study', 'Review these games'))
        self.favorites = self.collections.create(CollectionDetails('Favorites', 'Favorite games'))
        self.empty = self.collections.create(CollectionDetails('Empty', 'Ready for later'))
        self.collections.add_games(self.study, (1, 2, 3, 4))
        self.collections.add_games(self.favorites, (1, 5, 6))


class CollectionTests(CollectionFixture):
    def test_fixture_counts_overlap_empty_and_newest_first(self):
        self.assertEqual(self.count('games'), 10)
        self.assertEqual({c.name: c.member_count for c in self.collections.list_collections()},
                         {'Study': 4, 'Favorites': 3, 'Empty': 0})
        self.assertEqual([m.game_id for m in self.collections.members(self.study)], [3, 2, 1, 4])
        self.assertIn(1, [m.game_id for m in self.collections.members(self.favorites)])
        self.assertEqual(self.collections.members(self.empty), ())

    def test_create_rename_description_stable_id_and_unique_name(self):
        self.collections.edit(self.study, CollectionDetails('Study later', 'Review move 18'))
        c = next(c for c in self.collections.list_collections() if c.collection_id == self.study)
        self.assertEqual((c.name, c.description, c.member_count), ('Study later', 'Review move 18', 4))
        with self.assertRaises(ValueError):self.collections.create(CollectionDetails('STUDY LATER'))
        with self.assertRaises(ValueError):self.collections.edit(self.empty, CollectionDetails('Favorites'))
        self.assertEqual(len(self.collections.members(self.study)), 4)
        for name in ('', '   ', 'x'*121, '\x00'):
            with self.assertRaises(ValueError):CollectionDetails(name)
        with self.assertRaises(ValueError):CollectionDetails('Valid', 'x'*4001)

    def test_idempotent_add_remove_and_edit_have_no_timestamp_or_byte_churn(self):
        before = self.digest()
        self.assertEqual(self.collections.add_games(self.study, (1, 1, 2)), 0)
        self.assertEqual(self.collections.remove_games(self.study, (10,)), 0)
        self.assertEqual(self.collections.edit(self.study, CollectionDetails('Study', 'Review these games')), 0)
        self.assertEqual(self.digest(), before)
        self.assertEqual(self.collections.add_games(self.study, (7, 7, 8)), 2)
        self.assertEqual(self.collections.remove_games(self.study, (7, 8)), 2)
        self.assertEqual(len(self.collections.members(self.study)), 4)

    def test_delete_collection_never_changes_games_or_other_metadata(self):
        with closing(self.connect()) as db:before = unrelated_snapshot(db)
        self.collections.delete(self.study)
        self.assertEqual(len(self.collections.members(self.favorites)), 3)
        new_id = self.collections.create(CollectionDetails('Replacement'))
        self.assertGreater(new_id, self.empty)
        with closing(self.connect()) as db:self.assertEqual(before, unrelated_snapshot(db))
        self.assert_integrity()

    def test_batch_failure_rolls_back_all_and_ids_are_strict(self):
        before = self.digest()
        with self.assertRaises(ValueError):self.collections.add_games(self.study, (7, 9999))
        self.assertEqual(self.digest(), before)
        for ids in ((True,), ('1',), (0,)):
            with self.assertRaises(ValueError):self.collections.add_games(self.study, ids)
        with self.assertRaises(ValueError):self.collections.add_games(9999, (1,))
        self.assertEqual(self.digest(), before)
        with exclusive_data_activity(self.path), self.assertRaises(DataBusyError):
            self.collections.add_games(self.study, (7,))

    def test_collection_crud_membership_read_paths_do_not_touch_chess_tables(self):
        with closing(self.connect()) as db:before = unrelated_snapshot(db)
        cid = self.collections.create(CollectionDetails('Independent', 'Original description'))
        self.collections.add_games(cid, (2, 3, 8))
        self.collections.edit(cid, CollectionDetails('Renamed', 'Updated description'))
        self.collections.remove_games(cid, (3,))
        self.collections.members(cid);self.collections.list_collections()
        self.collections.delete(cid)
        with closing(self.connect()) as db:self.assertEqual(before, unrelated_snapshot(db))

    def test_delete_ignore_and_reset_block_saved_games_until_all_memberships_removed(self):
        repository = DataManagementRepository(self.path)
        before = self.digest()
        for ids in ((1,), (1, 10)):
            with self.assertRaisesRegex(ValueError, 'Study'):
                repository.plan_game_deletion(ids)
        with self.assertRaisesRegex(ValueError, 'Favorites'):
            repository.plan_reset(clear_ignored=True)
        self.assertEqual(self.digest(), before)
        self.collections.remove_games(self.study, (1,))
        with self.assertRaisesRegex(ValueError, 'Favorites'):
            repository.plan_game_deletion((1,))
        self.collections.remove_games(self.favorites, (1,))
        repository.execute_game_deletion(repository.plan_game_deletion((1,)), ignore_future_imports=True)
        self.assertEqual(len(repository.ignored()), 1)
        self.assertIn(self.empty, [c.collection_id for c in self.collections.list_collections()])
        self.assert_integrity()

    def test_membership_added_after_preview_blocks_delete_and_ignore_without_any_writes(self):
        repo = DataManagementRepository(self.path)
        plan = repo.plan_game_deletion((10,))
        self.collections.add_games(self.study, (10,))
        before = self.digest()
        for ignored in (False, True):
            with self.assertRaisesRegex(ValueError, 'Deletion blocked'):
                repo.execute_game_deletion(plan, ignore_future_imports=ignored)
        self.assertEqual(self.digest(), before)
        self.assertEqual(repo.ignored(), ())

    def test_membership_added_after_reset_preview_blocks_reset(self):
        for cid in (self.study, self.favorites):
            self.collections.remove_games(cid, tuple(m.game_id for m in self.collections.members(cid)))
        repo = DataManagementRepository(self.path)
        plan = repo.plan_reset()
        self.collections.add_games(self.empty, (10,))
        before = self.digest()
        with self.assertRaisesRegex(ValueError, 'Deletion blocked'):repo.execute_game_deletion(plan)
        self.assertEqual(self.digest(), before)

    def test_deletion_failure_rolls_back_memberships(self):
        repo = DataManagementRepository(self.path)
        plan = repo.plan_game_deletion((10,))
        before = self.digest()
        from data_management_repository import validate_integrity
        calls = 0
        def fail(db):
            nonlocal calls
            calls += 1
            if calls == 2:raise ValueError('injected rollback')
            validate_integrity(db)
        with patch('data_management_repository.validate_integrity', side_effect=fail):
            with self.assertRaises(ValueError):repo.execute_game_deletion(plan)
        self.assertEqual(self.digest(), before)

    def test_game_fk_restrict_orphan_constraint_and_empty_collection_reset(self):
        with closing(self.connect()) as db:
            db.execute('PRAGMA foreign_keys=ON')
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('INSERT INTO game_collection_members(collection_id,game_id) VALUES (?,9999)', (self.study,))
            db.rollback()
            db.execute("INSERT INTO games(game_id,user_id,source,source_game_id) VALUES(11,1,'chesscom','eleven')")
            db.execute('INSERT INTO game_collection_members(collection_id,game_id) VALUES (?,11)', (self.study,))
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM games WHERE game_id=11')
            db.commit()
        for cid in (self.study, self.favorites):
            self.collections.remove_games(cid, tuple(m.game_id for m in self.collections.members(cid)))
        repo = DataManagementRepository(self.path)
        repo.execute_game_deletion(repo.plan_reset())
        self.assertEqual([c.member_count for c in self.collections.list_collections()], [0, 0, 0])
        self.assertEqual(self.count('games'), 0)
        self.assert_integrity()

    def test_search_combinations_sorting_counts_and_no_writes(self):
        self.candidate(1);self.candidate(2, 'pin', ply=2)
        self.quality(1)
        before = self.digest()
        self.assertEqual(self.ids(collection_id=self.study), [3, 2, 1, 4])
        self.assertEqual(self.ids(collection_id=self.study, opponent='other'), [2])
        self.assertEqual(self.ids(collection_id=self.study, color='black', result='win'), [2])
        self.assertEqual(self.ids(collection_id=self.study, result='loss'), [3])
        self.assertEqual(self.ids(collection_id=self.study, motifs=('fork',)), [1])
        self.assertEqual(self.ids(collection_id=self.study, min_accuracy=99, max_accuracy=100), [3, 2, 1])
        self.assertEqual(self.ids(collection_id=self.empty), [])
        self.assertEqual(self.ids(collection_id=self.study, opponent='absent'), [])
        self.assertEqual(self.ids(uncollected=True), [10, 9, 8, 7])
        result = self.service.search(Criteria(collection_id=self.study))
        self.assertEqual(result.total_games, 10)
        self.assertIn('4 games found', result.summary)
        self.assertEqual([r.game_id for r in sorted_games(result.games, 'game_id')], [1, 2, 3, 4])
        self.assertEqual(self.service.search(Criteria(collection_id=self.empty)).summary, 'No games in this collection.')
        self.assertEqual(self.digest(), before)
        original = Criteria(collection_id=self.study, color='black')
        self.assertEqual(Criteria(**json.loads(json.dumps(asdict(original)))), original)
        for args in ({'collection_id':True}, {'collection_id':-1}, {'collection_id':1,'uncollected':True}):
            with self.assertRaises(ValueError):Criteria(**args)

    def test_indexed_membership_lookup_and_core_portability(self):
        with closing(self.connect()) as db:
            sql, params = metadata_query(Criteria(collection_id=self.study))
            plan = str([tuple(r) for r in db.execute('EXPLAIN QUERY PLAN '+sql, params)])
            self.assertIn('sqlite_autoindex_game_collection_members_1', plan)
            sql, params = metadata_query(Criteria(uncollected=True))
            plan = str([tuple(r) for r in db.execute('EXPLAIN QUERY PLAN '+sql, params)])
            self.assertIn('idx_game_collection_members_game', plan)
        for path in Path('.').glob('game_collection_*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or '').startswith(('tkinter','merlin_ui','chess.engine')))
                if isinstance(node, ast.Import):
                    self.assertFalse(any(n.name.startswith(('tkinter','merlin_ui','chess.engine')) for n in node.names))


class MigrationTests(CollectionFixture):
    def test_fresh_bootstrap_and_idempotent_migration(self):
        before = self.digest()
        with closing(sqlite3.connect(self.path)) as db:
            validate_schema(db);migrate_game_collections(db);migrate_game_collections(db)
        self.assertEqual(self.digest(), before)
        self.assert_integrity()

    def test_existing_schema_migration_preserves_all_old_rows_and_objects(self):
        with closing(sqlite3.connect(self.path)) as db:
            drop_collections(db)
            before = unrelated_snapshot(db)
            objects = dict(db.execute("SELECT name,sql FROM sqlite_master"))
            migrate_game_collections(db)
            self.assertEqual(unrelated_snapshot(db), before)
            after = dict(db.execute("SELECT name,sql FROM sqlite_master"))
            self.assertEqual({k:v for k,v in after.items() if k in objects}, objects)
            self.assertTrue(set(SCHEMA_OBJECTS) <= set(after))
        once = self.digest()
        with closing(sqlite3.connect(self.path)) as db:migrate_game_collections(db)
        self.assertEqual(self.digest(), once)
        self.assert_integrity()

    def test_unmigrated_reads_bootstrap_and_delete_do_not_migrate(self):
        with closing(sqlite3.connect(self.path)) as db:drop_collections(db)
        before = self.digest()
        ensure_database(self.path)
        self.assertFalse(self.collections.available())
        self.assertEqual(self.collections.list_collections(), ())
        self.assertEqual(len(self.service.search().games), 10)
        with self.assertRaisesRegex(ValueError, 'migration'):self.service.search(Criteria(collection_id=1))
        with self.assertRaisesRegex(ValueError, 'migration'):self.collections.create(CollectionDetails('No migration'))
        self.assertEqual(self.digest(), before)
        repo = DataManagementRepository(self.path)
        plan = repo.plan_game_deletion((1,))
        self.assertNotIn('game_collection_members', dict(plan.counts))
        repo.execute_game_deletion(plan)
        self.assertFalse(self.collections.available())

    def test_partial_incompatible_and_dirty_schema_migrations_fail_without_changes(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DROP INDEX idx_game_collection_members_game');db.commit()
            before = self.digest()
            with self.assertRaises(ValueError):migrate_game_collections(db)
            self.assertEqual(self.digest(), before)
            drop_collections(db)
            db.execute('PRAGMA foreign_keys=OFF')
            db.execute("INSERT INTO moves(game_id,ply_number,move_number,color,is_user_move,fen_before,fen_after,san_played,uci_played) VALUES(9999,1,1,'white',1,'x','x','e4','e2e4')");db.commit()
            before = self.digest()
            with self.assertRaisesRegex(ValueError, 'integrity'):migrate_game_collections(db)
            self.assertFalse(self.collections.available())
            self.assertEqual(self.digest(), before)


class CollectionUITests(CollectionFixture):
    def wait_search(self, window, root):
        deadline = time.monotonic()+8
        while window.busy and time.monotonic()<deadline:
            root.update();time.sleep(.01)
        self.assertFalse(window.busy)
        root.update()

    def test_explorer_filter_multiselect_add_remove_and_exact_handoff(self):
        root = tk.Tk();root.withdraw();opened=[]
        window = GameExplorerWindow(root,self.path,on_open_game=opened.append)
        self.addCleanup(lambda: window.close() if not window.closed else None)
        self.wait_search(window,root)
        window.collection_picker.current(window.collection_ids.index(self.study))
        window.collection_changed();self.wait_search(window,root)
        self.assertEqual(set(window.tree.get_children()), {'1','2','3','4'})
        window.tree.selection_set(('1','2'));window.selection_changed()
        window.open_selected();self.assertEqual(opened, [])
        with patch('merlin_ui.game_collections.CollectionPicker') as picker:
            picker.return_value.result = self.empty
            window.add_selected()
        self.wait_search(window,root)
        self.assertEqual({m.game_id for m in self.collections.members(self.empty)}, {1,2})
        window.tree.selection_set(('1','2'));window.remove_selected();self.wait_search(window,root)
        self.assertEqual(set(window.tree.get_children()), {'3','4'})
        window.tree.selection_set('3');window.open_selected();self.assertEqual(opened, [3])
        self.collections.edit(self.study, CollectionDetails('Renamed Study'))
        window.collection_changed();self.wait_search(window,root)
        self.assertEqual(window.selected_collection(), self.study)
        self.assertIn('Renamed Study', window.collection_filter.get())
        window.reset();self.wait_search(window,root)
        self.assertEqual(len(window.tree.get_children()),10)
        self.assertEqual(self.count('games'),10)

    def test_manager_crud_inspection_remove_and_delete_confirmation(self):
        root=tk.Tk();root.withdraw();self.addCleanup(root.destroy);opened=[]
        manager=CollectionManager(root,self.path,on_open_game=opened.append)
        manager.refresh(self.study);root.update()
        self.assertEqual(len(manager.members.get_children()),4)
        manager.members.selection_set('2');manager.open_selected();self.assertEqual(opened,[2])
        manager.members.selection_set(('1','2'));manager.remove();root.update()
        self.assertEqual(len(manager.members.get_children()),2)
        with patch('merlin_ui.game_collections.CollectionEditor') as editor:
            editor.return_value.result=CollectionDetails('UI Study','Description from editor')
            manager.edit()
        root.update();self.assertEqual(manager.description.get(),'Description from editor')
        with patch('merlin_ui.game_collections.messagebox.askyesno',return_value=False):manager.delete()
        self.assertIn(self.study,manager.collections)
        with patch('merlin_ui.game_collections.messagebox.askyesno',return_value=True):manager.delete()
        self.assertNotIn(self.study,manager.collections)
        manager.refresh(self.empty);root.update()
        self.assertEqual(manager.status.get(),'No games in this collection.')
        self.assertEqual(self.count('games'),10)

    def test_old_database_disables_writes_and_explains_migration(self):
        with closing(sqlite3.connect(self.path)) as db:drop_collections(db)
        before=self.digest();root=tk.Tk();root.withdraw();self.addCleanup(root.destroy)
        manager=CollectionManager(root,self.path,on_open_game=lambda gid:None)
        self.assertEqual(str(manager.new_button.cget('state')),'disabled')
        self.assertIn('migration',manager.status.get())
        self.assertEqual(self.digest(),before)
