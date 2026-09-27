"""Exact owner author/save/review flow, with no self-import and no live user writes."""
from tests.opening_ui_wait import wait_for_opening
from contextlib import closing
from dataclasses import asdict
import json,sqlite3,tkinter as tk
from pathlib import Path
from unittest.mock import patch
import chess
import chess.engine
from opening_book_models import BookDetails,MoveDetails
from opening_book_repository import OpeningBookRepository
from opening_book_service import OpeningBookService
from opening_book_session import OpeningBookSession
from opening_library_service import OpeningLibraryService
from opening_library_repository import OpeningLibraryRepository
from opening_library_reference import OpeningReferenceService
from opening_library_package import inspect_package,semantic_identity
from opening_library_backup import backup_managed_books
from merlin_ui.game_review_view import GameReviewView
from tests.test_game_analysis import TemporaryAnalysis
from tests.opening_intelligence_fixtures import pgn
from tests.opening_book_fixtures import add_line


class LiveOpeningTests(TemporaryAnalysis):
    def setUp(self):
        super().setUp()
        guard=patch.object(chess.engine.SimpleEngine,'popen_uci',side_effect=AssertionError('No engine'))
        guard.start();self.addCleanup(guard.stop)
        errors=patch('merlin_ui.opening_book_studio.messagebox.showerror',side_effect=lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError(str(args))))
        errors.start();self.addCleanup(errors.stop)
        self.library=OpeningLibraryService()
        self.import_fixture(pgn('e4 e6 d4 d5 e5 c5','advance'))
        self.import_fixture(pgn('e4 e6 d4 d5 exd5 exd5','exchange'))
        self.import_fixture(pgn('b3 e5 Bb2 Nc6','unrelated'))
        self.reference=OpeningReferenceService(self.path,self.library)

    def authored(self,name='My Openings',status='active'):
        library=self.library.create_library(name)
        repo=OpeningBookRepository.open(library.path)
        try:
            service=OpeningBookService(repo);bid=service.create_book(BookDetails('The French',status=status))
            add_line(OpeningBookSession(service,bid),'e4 e6 d4 d5 e5')
        finally:repo.close()
        return self.library.get_library(library.library_id)

    def test_exact_owner_workflow_no_import_live_saved_branch(self):
        for method in ('import_library','import_book'):
            guard=patch.object(OpeningLibraryService,method,side_effect=AssertionError('Internal authoring must never import'))
            guard.start();self.addCleanup(guard.stop)
        before=self.digest();root=tk.Tk();root.withdraw();view=GameReviewView(root,database_path=self.path)
        try:
            view.open_game_position(1,None);wait_for_opening(view);view.open_opening_book_studio();studio=view.opening_book_studio
            self.assertEqual(len(self.library.list_libraries()),0)
            studio.new_book();studio.draft_title.set('The French')
            for san in 'e4 e6 d4 d5 e5'.split():
                studio.stage(san)
                if san=='e5':studio.fields['variation_name'].insert('1.0','Advance Variation')
                studio.save_editor()
            item=self.library.list_books()[0];identity=(item.library_id,item.snapshot.book.book_id)
            self.assertEqual(item.path,studio.repository.path)
            picker=view.opening_reference;picker.refresh(force=True);wait_for_opening(view)
            self.assertFalse(hasattr(picker,'library_picker'))
            self.assertIn('The French',str(picker.picker.cget('values')))
            picker.picker.current(1);picker.select();wait_for_opening(view);view.open_opening_facts();view._set_step(5)
            self.assertIn('Advance Variation',view.opening_panel.summary.cget('text'))
            view.open_game_position(2,None);wait_for_opening(view);picker.refresh(force=True);wait_for_opening(view)
            picker.picker.current(1);picker.select();wait_for_opening(view);view._set_step(5)
            old_revision=view.opening_panel.assessment.provenance.book_revision
            parent=studio.session.history[:4]
            node=next(k for k,path in studio.paths.items() if path==parent and k.startswith('m'))
            studio.activate_node(node);studio.stage('exd5')
            studio.fields['variation_name'].insert('1.0','Exchange Variation');studio.save_editor()
            root.update_idletasks();wait_for_opening(view)
            self.assertIn('Exchange Variation',view.opening_panel.summary.cget('text'))
            new=self.library.list_books()[0]
            self.assertEqual((new.library_id,new.snapshot.book.book_id),identity)
            self.assertGreater(view.opening_panel.assessment.provenance.book_revision,old_revision)
            self.assertEqual(len(self.library.list_books()),1)
            self.assertEqual(len(list(self.library.repository.root.glob('*.cwbook'))),1)
            self.assertEqual(before,self.digest())
            view.open_opening_library()
            self.assertTrue(view.opening_library_manager.tree.exists('library:'+item.library_id))
            if getattr(self,'artifact_directory',None):
                from PIL import ImageGrab
                target=Path(self.artifact_directory);target.mkdir(exist_ok=True)
                root.deiconify();studio.root.withdraw();root.update()
                ImageGrab.grab(window=view.opening_library_window.winfo_id()).save(target/'library_hierarchy.png')
                view.opening_library_window.withdraw();root.update()
                ImageGrab.grab(window=root.winfo_id()).save(target/'review_selectors.png')
                self.library.export_library(item.library_id,target/'My Openings.cwbook')
                (target/'owner_acceptance.json').write_text(json.dumps(dict(library_id=item.library_id,book_id=item.snapshot.book.book_id,
                    path=str(item.path),import_calls=0,managed_files=1,revision_before=old_revision,
                    revision_after=new.snapshot.book.revision,game_database_unchanged=True),indent=2))
        finally:view.close()

    def test_multiple_books_no_registration_primary_and_selected_studio_book(self):
        library=self.authored();first=library.books[0]
        repo=OpeningBookRepository.open(library.path)
        try:
            service=OpeningBookService(repo);bid=service.create_book(BookDetails('Jobava',status='active'))
            add_line(OpeningBookSession(service,bid),'d4 d5 Nc3 Nf6 Bf4')
        finally:repo.close()
        books=self.library.get_library(library.library_id).books;self.assertEqual(len(books),2)
        second=next(b for b in books if b.snapshot.book.book_id==bid)
        self.library.set_primary(second.installation_id)
        self.assertFalse(self.library.get(first.installation_id).primary)
        self.assertTrue(self.library.get(second.installation_id).primary)
        self.assertEqual(self.reference.choose(1).selected_id,first.installation_id)
        root=tk.Tk();root.withdraw();view=GameReviewView(root,database_path=self.path)
        try:
            view.open_installed_book(second)
            self.assertEqual(view.opening_book_studio.session.book_id,bid)
            self.assertEqual(view.opening_book_studio.repository.path,library.path)
        finally:view.close()

    def test_draft_active_archived_enabled_and_explicit_nonmatch(self):
        library=self.authored(status='draft');book=library.books[0]
        self.assertIsNone(self.reference.choose(1).selected_id)
        self.reference.select(1,book.installation_id);self.assertEqual(self.reference.choose(1).selected_id,book.installation_id)
        self.reference.clear_selection(1);self.library.set_status(book.installation_id,'active')
        self.assertEqual(self.reference.choose(1).selected_id,book.installation_id)
        self.library.set_enabled(book.installation_id,False);self.assertIsNone(self.reference.choose(1).selected_id)
        self.library.set_primary(book.installation_id);self.assertIsNone(self.reference.choose(1).selected_id)
        self.library.set_enabled(book.installation_id,True);self.library.set_status(book.installation_id,'archived')
        self.assertIsNone(self.reference.choose(1).selected_id)
        self.reference.select(3,book.installation_id)
        self.assertIn('no meaningful match',self.reference.choose(3).reason)

    def test_library_none_book_none_and_session_override(self):
        first=self.authored();second=self.authored('Alternative')
        root=tk.Tk();root.withdraw();view=GameReviewView(root,database_path=self.path)
        try:
            view.open_game_position(3,None);wait_for_opening(view);picker=view.opening_reference
            self.assertEqual(len(picker.choices),2)
            self.assertFalse(hasattr(picker,"library_picker"))
            self.assertIsNone(picker.selected_id)
            picker.picker.current(1);picker.select();selected=picker.selected_id
            picker.refresh(force=True);wait_for_opening(view);self.assertEqual(picker.selected_id,selected)
            picker.picker.current(0);picker.select();self.assertIsNone(picker.selected_id)
            self.assertIsNotNone(picker.selected_library_id)
            view.open_game_position(1,None);wait_for_opening(view)
            self.assertIsNone(picker.selected_id)
            self.assertEqual(len(picker.choices),2)
        finally:view.close()

    def test_whole_library_export_import_self_duplicate_and_partial_export(self):
        library=self.authored()
        repo=OpeningBookRepository.open(library.path)
        try:OpeningBookService(repo).create_book(BookDetails('Second book',status='draft'))
        finally:repo.close()
        library=self.library.get_library(library.library_id)
        external=self.path.parent/'external_test.cwbook';self.library.export_library(library.library_id,external)
        before=external.read_bytes();preview=inspect_package(external)
        self.assertEqual(len(preview.books),2)
        self.assertEqual(self.library.import_library(external,preview).library_id,library.library_id)
        single=self.path.parent/'one.cwbook';self.library.export_book(library.books[0].installation_id,single)
        self.assertEqual(self.library.import_library(single,inspect_package(single)).library_id,library.library_id)
        fresh=OpeningLibraryService(OpeningLibraryRepository(self.path.parent/'fresh'))
        imported=fresh.import_library(external,preview)
        self.assertNotEqual(imported.library_id,library.library_id)
        self.assertEqual([asdict(b.snapshot) for b in imported.books],[asdict(b.snapshot) for b in library.books])
        self.assertEqual(external.read_bytes(),before)
        fresh.set_status(imported.books[0].installation_id,'archived')
        self.assertEqual(external.read_bytes(),before)
        self.assertEqual(self.library.get_library(library.library_id).books[0].snapshot.book.status,'active')

    def test_external_readonly_adoption_and_independent_original(self):
        library=self.authored();external=self.path.parent/'Old owner library.cwbook'
        self.library.export_library(library.library_id,external);before=external.read_bytes()
        # A distinct profile has no knowledge of the original managed source.
        isolated=OpeningLibraryService(OpeningLibraryRepository(self.path.parent/'adoption'))
        root=tk.Tk();root.withdraw()
        from merlin_ui.opening_book_studio import OpeningBookStudio
        studio=OpeningBookStudio(root,game_database_path=self.path);studio.library_service=isolated
        try:
            with patch('merlin_ui.opening_book_studio.filedialog.askopenfilename',return_value=str(external)):
                studio.open_library()
            self.assertTrue(studio.external_readonly)
            self.assertIn('External Preview',studio.library_context.cget('text'))
            with self.assertRaises(sqlite3.OperationalError):studio.repository.update_book(studio.session.book_id,BookDetails('Must not save'))
            with patch('merlin_ui.opening_studio_workflow.choose_books',return_value=(1,)):studio.import_books(external)
            self.assertFalse(studio.external_readonly);self.assertEqual(len(isolated.list_libraries()),1)
            self.assertNotEqual(studio.repository.path,external)
            self.assertEqual(external.read_bytes(),before)
        finally:studio.close()

    def test_legacy_v1_catalog_read_preserves_id_no_schema_migration(self):
        library=self.authored();external=self.path.parent/'legacy_source.cwbook'
        self.library.export_library(library.library_id,external)
        old=OpeningLibraryService(OpeningLibraryRepository(self.path.parent/'v1'))
        result=old.import_book(external,inspect_package(external),library.books[0].snapshot.book.book_id)
        before=old.repository.catalog.read_bytes();item=old.get(result.installation_id)
        self.assertEqual(item.installation_id,item.library_id)
        self.assertEqual(before,old.repository.catalog.read_bytes())
        with closing(sqlite3.connect(old.repository.catalog)) as db:
            schema=db.execute('SELECT sql FROM sqlite_master ORDER BY name').fetchall()
        old.set_primary(item.installation_id);old.set_enabled(item.installation_id,False)
        with closing(sqlite3.connect(old.repository.catalog)) as db:
            self.assertEqual(schema,db.execute('SELECT sql FROM sqlite_master ORDER BY name').fetchall())
        self.assertTrue(old.get(item.installation_id).primary);self.assertFalse(old.get(item.installation_id).enabled)

    def test_multi_book_archive_preserves_other_book_and_backup(self):
        library=self.authored();repo=OpeningBookRepository.open(library.path)
        try:OpeningBookService(repo).create_book(BookDetails('Other',status='active'))
        finally:repo.close()
        library=self.library.get_library(library.library_id);first,other=library.books
        self.library.set_primary(first.installation_id)
        preview=self.library.preview_removal(first.installation_id)
        self.library.remove(preview,clear_primary=True)
        self.assertEqual(self.library.get(other.installation_id).snapshot,other.snapshot)
        self.assertEqual(self.library.get(first.installation_id).snapshot.book.status,'archived')
        backup=self.path.parent/'backup';backup_managed_books(backup,root=self.library.repository.root)
        restored=OpeningLibraryService(OpeningLibraryRepository(backup/'managed_opening_books'))
        self.assertEqual(restored.get(other.installation_id).snapshot,other.snapshot)

    def test_whole_library_preview_renders_and_confirms_without_execution(self):
        library=self.authored();path=self.path.parent/'preview.cwbook'
        self.library.export_library(library.library_id,path)
        root=tk.Tk();root.withdraw()
        from tkinter import ttk
        from merlin_ui.opening_library_manager import choose_import
        def accept():
            def walk(widget):
                for child in widget.winfo_children():
                    if isinstance(child,ttk.Button) and child.cget('text')=='Import library':child.invoke();return True
                    if walk(child):return True
                return False
            walk(root)
        root.after(100,accept)
        try:self.assertEqual(choose_import(root,inspect_package(path),whole_library=True),library.books[0].snapshot.book.book_id)
        finally:root.destroy()

    def test_empty_library_external_adoption_and_duplicate(self):
        library=self.library.create_library('Empty owner library')
        path=self.path.parent/'empty.cwbook';self.library.export_library(library.library_id,path)
        preview=self.library.preview_import(path)
        self.assertEqual(preview.books,())
        self.assertEqual(self.library.import_library(path,preview).library_id,library.library_id)
        other=OpeningLibraryService(OpeningLibraryRepository(self.path.parent/'empty-profile'))
        adopted=other.import_library(path,preview,owner_adoption=True)
        self.assertEqual(adopted.books,())

    def test_partial_overlap_requires_explicit_separate_library_choice(self):
        library=self.authored();external=self.path.parent/'expanded.cwbook'
        self.library.export_library(library.library_id,external)
        repo=OpeningBookRepository.open(external)
        try:OpeningBookService(repo).create_book(BookDetails('New book',status='active'))
        finally:repo.close()
        preview=self.library.preview_import(external)
        self.assertTrue(self.library.partial_overlap(preview))
        before=self.library.repository.catalog.read_bytes()
        with self.assertRaises(ValueError):self.library.import_library(external,preview)
        self.assertEqual(before,self.library.repository.catalog.read_bytes())
        self.assertEqual(len(self.library.list_libraries()),1)
        copied=self.library.import_library(external,preview,allow_partial_overlap=True)
        self.assertNotEqual(copied.library_id,library.library_id)
