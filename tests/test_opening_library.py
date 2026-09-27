"""Isolated package trust, installed identity, defaults and UI reference contracts."""
from tests.opening_ui_wait import wait_for_opening
from contextlib import closing
from dataclasses import asdict,replace
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import chess
import chess.engine
from opening_book_models import BookDetails, MoveDetails, SourceDetails
from opening_book_repository import OpeningBookRepository
from opening_book_service import OpeningBookService
from opening_book_session import OpeningBookSession
from opening_book_polyglot import export_polyglot
from opening_library_package import inspect_package,semantic_identity,write_package
from opening_library_repository import OpeningLibraryRepository
from opening_library_service import OpeningLibraryService
from opening_library_reference import OpeningReferenceService
from opening_library_backup import backup_managed_books
from tests.opening_book_fixtures import add_line
from tests.opening_intelligence_fixtures import french_book,pgn,FRENCH_CASES
from tests.test_game_analysis import TemporaryAnalysis


class LibraryManagementTests(TemporaryAnalysis):
    def setUp(self):
        super().setUp()
        self.source=self.path.parent/'source.cwbook'
        self.repo=OpeningBookRepository.create(self.source);self.addCleanup(self.repo.close)
        self.author=OpeningBookService(self.repo);self.bid=french_book(self.author)
        self.repo.update_book(self.bid,BookDetails('The French',version='1.0',status='active',metadata_json=json.dumps(dict(author='Fixture author',license='CC0',source='https://example.invalid/reference'))))
        snap=self.repo.snapshot(self.bid);move=snap.moves[0]
        self.repo.set_position_note(self.bid,move.from_position_id,'Position note')
        self.repo.save_source(self.bid,move.from_position_id,move.move_id,SourceDetails(title='Authored source',private_note='Shared with book'))
        self.library=OpeningLibraryService(OpeningLibraryRepository(self.path.parent/'opening_books'))
        self.import_fixture(pgn(FRENCH_CASES['advance'],'french'))
        self.import_fixture(pgn('d4 d5 c4 e6 Nc3','general'))
        self.import_fixture(pgn('b3 e5 Bb2 Nc6','neither'))
        self.reference=OpeningReferenceService(self.path,self.library)

    def install(self):
        return self.library.import_book(self.source,self.library.preview_import(self.source),self.bid).installation_id

    def general(self, french=False):
        bid=self.author.create_book(BookDetails('General Openings',status='active'))
        session=OpeningBookSession(self.author,bid);add_line(session,'d4 d5 c4 e6 Nc3')
        if french:add_line(session,'e4 e6 d4 d5 e5 c5')
        return self.library.import_book(self.source,self.library.preview_import(self.source),bid).installation_id

    def test_lazy_catalog_and_import_source_independence(self):
        self.assertEqual(self.library.list_books(),());self.assertFalse(self.library.repository.root.exists())
        before=self.source.read_bytes();identifier=self.install();item=self.library.get(identifier)
        self.assertEqual(before,self.source.read_bytes());self.assertTrue(item.enabled);self.assertFalse(item.primary)
        self.assertEqual(len(item.snapshot.moves),len(self.repo.snapshot(self.bid).moves))
        self.repo.close();self.repo.close=lambda:None;self.source.unlink()
        self.assertIsNotNone(self.library.get(identifier).snapshot)

    def test_exact_and_semantic_duplicates_no_churn(self):
        identifier=self.install();catalog=self.library.repository.catalog.read_bytes()
        duplicate=self.library.import_book(self.source,self.library.preview_import(self.source),self.bid)
        self.assertEqual(duplicate.installation_id,identifier);self.assertTrue(duplicate.already_installed)
        self.assertEqual(catalog,self.library.repository.catalog.read_bytes())
        self.repo.connection.execute('UPDATE books SET revision=revision+1,updated_at=? WHERE book_id=?',('changed',self.bid));self.repo.connection.commit()
        self.assertEqual(self.install(),identifier)

    def test_versions_names_ids_and_stale_preview(self):
        first=self.install();old=self.library.preview_import(self.source)
        self.repo.update_book(self.bid,BookDetails('The French',version='1.1',status='active'))
        with self.assertRaises(ValueError):self.library.import_book(self.source,old,self.bid)
        second=self.install();self.assertNotEqual(first,second)
        third=self.library.clone_book(first,'The French').installation_id
        self.assertEqual(len(self.library.list_books()),3)
        self.assertEqual(self.library.get(first).snapshot.book.version,'1.0')
        self.assertEqual(self.library.get(second).snapshot.book.version,'1.1')
        self.assertNotEqual(third,second)

    def test_selected_only_export_roundtrip_and_polyglot(self):
        self.general();identifier=self.install();snapshot=self.library.get(identifier).snapshot
        exported=self.path.parent/'shared.cwbook';self.library.export_book(identifier,exported)
        preview=inspect_package(exported);self.assertEqual(len(preview.books),1)
        self.assertEqual(asdict(snapshot),asdict(preview.books[0]))
        fresh=OpeningLibraryService(OpeningLibraryRepository(self.path.parent/'fresh'))
        imported=fresh.import_book(exported,preview,self.bid)
        second=self.path.parent/'reshared.cwbook';fresh.export_book(imported.installation_id,second)
        self.assertEqual(semantic_identity(inspect_package(second).books[0]),semantic_identity(snapshot))
        original_bin=self.path.parent/'original.bin';shared_bin=self.path.parent/'shared.bin'
        export_polyglot(snapshot,original_bin);export_polyglot(preview.books[0],shared_bin)
        self.assertEqual(original_bin.read_bytes(),shared_bin.read_bytes())
        with self.assertRaises(FileExistsError):self.library.export_book(identifier,exported)

    def test_clone_new_identity_metadata_independence_and_provenance(self):
        identifier=self.install();original=self.library.get(identifier)
        clone=self.library.clone_book(identifier,'My French').installation_id
        copied=self.library.get(clone);metadata=json.loads(copied.snapshot.book.metadata_json)
        self.assertEqual(metadata['cloned_from']['installation_id'],identifier)
        self.assertIn('book_uuid',metadata);self.assertEqual(copied.snapshot.moves,original.snapshot.moves)
        self.library.update_metadata(clone,author='Me',license='Unspecified',description='Independent')
        self.assertEqual(self.library.get(identifier).snapshot,original.snapshot)
        output=self.path.parent/'clone.bin';export_polyglot(copied.snapshot,output);self.assertGreater(output.stat().st_size,0)

    def test_independent_enabled_primary_and_remove_confirmation(self):
        identifier=self.install();self.library.set_primary(identifier);self.library.set_enabled(identifier,False)
        item=self.library.get(identifier);self.assertTrue(item.primary);self.assertFalse(item.enabled)
        self.assertIsNone(self.reference.choose(1).selected_id)
        preview=self.library.preview_removal(identifier,selected_id=identifier)
        self.assertTrue(preview.selected_in_review)
        with self.assertRaises(ValueError):self.library.remove(preview)
        archived=self.library.remove(preview,clear_primary=True)
        self.assertTrue(archived.is_file());self.assertEqual(self.library.list_books(),())
        self.assertEqual(len(inspect_package(archived).books),1)

    def test_removal_stale_preview_and_rollback(self):
        identifier=self.install();preview=self.library.preview_removal(identifier)
        self.library.set_enabled(identifier,False)
        with self.assertRaises(ValueError):self.library.remove(preview)
        preview=self.library.preview_removal(identifier)
        with patch.object(Path,'rename',side_effect=OSError('in use')):
            with self.assertRaises(OSError):self.library.remove(preview)
        self.assertIsNotNone(self.library.get(identifier).snapshot)

    def test_default_primary_irrelevant_multiple_and_neither(self):
        french=self.install();general=self.general()
        self.library.set_primary(french)
        self.assertEqual(self.reference.choose(1).selected_id,french)
        self.assertEqual(self.reference.choose(2).selected_id,general)
        self.assertIsNone(self.reference.choose(3).selected_id)
        self.library.set_primary(general)
        self.assertEqual(self.reference.choose(1).selected_id,french)
        self.general(french=True);self.library.set_primary(None)
        self.assertEqual(self.reference.choose(1).selected_id,french)
        self.assertEqual(len(self.reference.choose(1).relevant),2)
        self.library.clone_book(french,'Equally matching French')
        self.assertIsNone(self.reference.choose(1).selected_id)
        self.library.set_primary(french);self.assertEqual(self.reference.choose(1).selected_id,french)

    def test_explicit_none_disabled_versions_removed_and_root_not_matching(self):
        first=self.install();self.library.set_enabled(first,False)
        self.assertIsNone(self.reference.choose(1).selected_id)
        self.reference.select(1,first);self.assertEqual(self.reference.choose(1).selected_id,first)
        self.reference.select(1,None);self.assertIsNone(self.reference.choose(1).selected_id)
        self.reference.clear_selection(1);self.library.set_enabled(first,True)
        self.assertEqual(self.reference.choose(1).selected_id,first)
        self.assertFalse(self.reference.find_relevant_books(3).relevant)
        self.repo.update_book(self.bid,BookDetails('The French',version='1.1',status='active'));second=self.install()
        self.reference.select(1,second);self.assertEqual(self.reference.choose(1).selected_id,second)
        matches=self.reference.find_relevant_books(1).relevant
        self.assertEqual({m.version for m in matches},{'1.0','1.1'})
        self.library.remove(self.library.preview_removal(second));self.assertIsNone(self.reference.choose(1).selected_id)

    def mutate_package(self,sql):
        path=self.path.parent/'bad.cwbook';shutil.copyfile(self.source,path)
        with closing(sqlite3.connect(path)) as db:db.executescript(sql)
        return path

    def test_malformed_unsupported_extra_schema_and_executable_payloads(self):
        for sql in ('PRAGMA user_version=99;', 'CREATE TABLE extra(payload BLOB);',
                    'CREATE TRIGGER evil AFTER INSERT ON books BEGIN SELECT load_extension("evil"); END;',
                    "UPDATE books SET metadata_json=x'4d5a9000';", "UPDATE books SET metadata_json='not json';",
                    "UPDATE book_moves SET san='nonsense' WHERE move_id=1;",
                    "UPDATE book_moves SET to_position_id=99999 WHERE move_id=1;"):
            with self.subTest(sql=sql):
                path=self.mutate_package(sql)
                with self.assertRaises(ValueError):inspect_package(path)
        path=self.path.parent/'not.cwbook';path.write_bytes(b'MZ executable')
        with self.assertRaises(ValueError):inspect_package(path)

    def test_stripped_foreign_key_schema_cannot_hide_orphan_rows(self):
        path=self.mutate_package("""PRAGMA writable_schema=ON;
            UPDATE sqlite_master SET sql=replace(sql,' REFERENCES books ON DELETE CASCADE','')
            WHERE name='book_positions';
            PRAGMA writable_schema=OFF;""")
        with self.assertRaisesRegex(ValueError,'reference constraints'):inspect_package(path)

    def test_path_traversal_limits_and_passive_references(self):
        with self.assertRaises(ValueError):inspect_package(self.path.parent/'..'/self.path.parent.name/'source.cwbook')
        with self.assertRaises(ValueError):self.library.repository.path('../../evil')
        path=self.mutate_package("UPDATE books SET description='../../evil.py https://example.invalid';")
        with patch('webbrowser.open',side_effect=AssertionError('No URLs')),patch('subprocess.Popen',side_effect=AssertionError('No execution')):
            preview=inspect_package(path);self.library.import_book(path,preview,self.bid)
        with patch('opening_library_package.MAX_PACKAGE_BYTES',1):
            with self.assertRaises(ValueError):inspect_package(self.source)
        path=self.mutate_package("UPDATE books SET description='"+'a'*65537+"';")
        with self.assertRaises(ValueError):inspect_package(path)
        with patch('opening_library_package.reject_links',side_effect=ValueError('reparse')):
            with self.assertRaises(ValueError):inspect_package(self.source)

    def test_v1_import_no_source_migration(self):
        self.repo.connection.execute('ALTER TABLE book_moves DROP COLUMN variation_name')
        self.repo.connection.execute('ALTER TABLE book_moves DROP COLUMN variation_description')
        self.repo.connection.execute('PRAGMA user_version=1');self.repo.connection.commit()
        before=self.source.read_bytes();identifier=self.install()
        self.assertEqual(before,self.source.read_bytes())
        self.assertEqual(inspect_package(self.library.get(identifier).path).schema_version,2)

    def test_backup_protects_active_and_removed(self):
        identifier=self.install();second=self.library.clone_book(identifier,'Archived').installation_id
        self.library.remove(self.library.preview_removal(second))
        target=self.path.parent/'backup';count,size=backup_managed_books(target,root=self.library.repository.root)
        self.assertEqual(count,3);self.assertGreater(size,0)
        restored=OpeningLibraryService(OpeningLibraryRepository(target/'managed_opening_books'))
        self.assertEqual(restored.get(identifier).snapshot,self.library.get(identifier).snapshot)
        self.assertTrue((target/'managed_opening_books'/'removed'/(second+'.cwbook')).exists())

    def test_no_engine_no_game_writes_and_portable_core(self):
        before=self.digest();identifier=self.install();self.library.set_primary(identifier)
        with patch.object(chess.engine.SimpleEngine,'popen_uci',side_effect=AssertionError('No engine')):
            result=self.reference.find_relevant_books(1)
        self.assertEqual(result.relevant[0].installation_id,identifier);self.assertEqual(before,self.digest())
        import ast
        for path in Path('.').glob('opening_library_*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node,ast.ImportFrom):self.assertFalse((node.module or '').startswith(('tkinter','merlin_ui','chess.engine')))

    def test_game_review_picker_facts_none_primary_and_switching(self):
        import tkinter as tk
        from merlin_ui.game_review_view import GameReviewView
        identifier=self.install();self.library.set_primary(identifier);before=self.digest()
        root=tk.Tk();root.withdraw();view=GameReviewView(root,database_path=self.path)
        try:
            view.open_game_position(1,None);view.open_opening_facts();view._set_step(5)
            self.assertIsNone(view.opening_reference.selected_id)
            view.opening_reference.service.select(1,identifier)
            view.opening_reference.refresh(force=True);wait_for_opening(view)
            self.assertEqual(view.opening_reference.selected_id,identifier)
            self.assertEqual(view.opening_panel.assessment.provenance.library_identity,identifier)
            self.assertEqual(view.opening_panel.assessment.provenance,
                             self.reference.find_relevant_books(1).relevant[0].assessment.provenance)
            self.assertIn('Advance Variation',view.opening_panel.summary.cget('text'))
            # Legacy single-book catalogs use a bare library identity, not library:book.
            view.open_opening_context()
            self.assertEqual(view.opening_book_studio.session.book_id,view.opening_panel.lookup.snapshot.book.book_id)
            self.assertEqual(view.opening_book_studio.session.position_id,
                             view.opening_panel.assessment.moves[4].after_position_id)
            picker=view.opening_reference;picker.picker.current(0);picker.select()
            self.assertIsNone(view.opening_panel.assessment)
            self.assertIn('Choose an Opening',view.opening_panel.summary.cget('text'))
            picker.defaults();self.assertIsNone(picker.selected_id)
            view.open_game_position(3,None);self.assertIsNone(picker.selected_id)
            self.assertNotIn('Advance Variation',view.opening_panel.summary.cget('text'))
            view.open_game_position(1,None);view.open_opening_library()
            self.assertTrue(view.opening_library_manager.tree.exists(identifier))
            view.current_game=None;view.opening_reference.refresh()
            self.assertIsNone(view.opening_reference.selected_id)
            self.assertIsNone(view.opening_panel.assessment)
            self.assertEqual(before,self.digest())
        finally:view.close()
