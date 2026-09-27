"""Single-screen authoring acceptance and managed-identity safety, on temp data only."""
from contextlib import closing
import gc
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
import chess
from opening_book_models import BookDetails, MoveDetails, SourceDetails
from opening_book_repository import OpeningBookRepository
from opening_book_service import OpeningBookService
from opening_book_session import OpeningBookSession
from opening_book_transfer import append_books
from opening_book_polyglot import export_entries
from opening_library_service import OpeningLibraryService
from opening_library_package import semantic_identity
from opening_studio_service import OpeningStudioService
from merlin_ui.opening_book_studio import OpeningBookStudio
from tests.opening_book_fixtures import add_line

UI='merlin_ui.opening_studio_workflow.'


class WorkspaceFixture(unittest.TestCase):
    def setUp(self):
        gc.collect()
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        for guard in (patch.dict(os.environ,CHESSWIZARD_DATA_DIR=str(self.folder/'profile')),
                      patch('theme_core.active._default_service',None),
                      patch('chess.engine.SimpleEngine.popen_uci',side_effect=AssertionError('No engine'))):
            guard.start();self.addCleanup(guard.stop)
        self.workspace=OpeningStudioService();self.library=self.workspace.library

    def authored_file(self,name='external.cwbook',titles=('The French','London')):
        path=self.folder/name;repo=OpeningBookRepository.create(path)
        try:
            service=OpeningBookService(repo)
            for title in titles:
                bid=service.create_book(BookDetails(title,status='active',metadata_json='{"author":"Tester","license":"CC0"}'))
                session=OpeningBookSession(service,bid)
                add_line(session,'e4 e6 d4 d5 e5')
                add_line(session,'d4 Nf6 Nf3 d5')
                add_line(session,'Nf3 Nf6 d4 d5')
                snap=session.snapshot;move=snap.moves[0]
                service.edit_move(bid,move.move_id,MoveDetails(80,True,True,'note','teaching',variation_name='French'))
                repo.set_position_note(bid,move.from_position_id,'Position note','{"keep":true}')
                repo.save_source(bid,move.from_position_id,move.move_id,SourceDetails(title='Source'))
        finally:repo.close()
        return path


class WorkspaceTests(WorkspaceFixture):
    def test_read_only_startup_and_one_durable_authoring_home(self):
        self.assertEqual(self.workspace.books(),())
        self.assertIsNone(self.workspace.home())
        self.assertFalse(self.library.repository.root.exists())
        draft=self.workspace.draft()
        try:
            first=self.workspace.commit_draft(draft.snapshot(1),'French')
            second=self.workspace.commit_draft(draft.snapshot(1),'London')
        finally:draft.close()
        self.assertEqual(first.path,second.path)
        self.assertNotEqual(first.installation_id,second.installation_id)
        self.assertEqual(OpeningStudioService().home().library_id,first.library_id)

    def test_selective_import_remaps_graph_and_preserves_sources_and_source_bytes(self):
        source=self.authored_file();before=source.read_bytes();preview=self.library.preview_import(source)
        draft=self.workspace.draft()
        try:existing=self.workspace.commit_draft(draft.snapshot(1),'Existing')
        finally:draft.close()
        original=existing.snapshot
        imported,=self.workspace.import_selected(source,preview,(preview.books[1].book.book_id,))
        self.assertEqual(imported.path,existing.path)
        self.assertEqual(semantic_identity(imported.snapshot),semantic_identity(preview.books[1]))
        self.assertEqual(export_entries(imported.snapshot),export_entries(preview.books[1]))
        self.assertEqual(self.library.get(existing.installation_id).snapshot,original)
        self.assertEqual(source.read_bytes(),before)
        self.assertEqual(len(self.workspace.books()),2)
        with closing(sqlite3.connect(imported.path)) as db:
            self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_duplicate_reuses_exact_book_without_writes_and_name_conflict_keeps_both(self):
        source=self.authored_file(titles=('French',));preview=self.library.preview_import(source)
        first,=self.workspace.import_selected(source,preview,(1,))
        before=first.path.read_bytes();catalog=self.library.repository.catalog.read_bytes()
        second,=self.workspace.import_selected(source,preview,(1,))
        self.assertEqual(first.installation_id,second.installation_id)
        self.assertEqual(first.path.read_bytes(),before);self.assertEqual(self.library.repository.catalog.read_bytes(),catalog)
        self.assertEqual(self.workspace.preview(preview)[0].duplicate_id,first.installation_id)
        other=self.authored_file('other.cwbook',('French',))
        repo=OpeningBookRepository.open(other)
        try:repo.set_position_note(1,repo.snapshot(1).book.root_position_id,'Different material')
        finally:repo.close()
        new_preview=self.library.preview_import(other);entry=self.workspace.preview(new_preview)[0]
        self.assertTrue(entry.name_conflict);self.assertIsNone(entry.duplicate_id)
        self.workspace.import_selected(other,new_preview,(1,))
        self.assertEqual(len(self.workspace.books()),2)
        self.assertEqual(len(set(self.workspace.labels(self.workspace.books()))),2)

    def test_changed_import_source_is_rejected_before_storage_creation(self):
        source=self.authored_file();preview=self.library.preview_import(source)
        repo=OpeningBookRepository.open(source)
        try:repo.update_book(1,BookDetails('Changed'))
        finally:repo.close()
        with self.assertRaisesRegex(ValueError,'source changed'):self.workspace.import_selected(source,preview,(1,))
        self.assertFalse(self.library.repository.root.exists())

    def test_append_failure_rolls_back_all_selected_books(self):
        source=self.authored_file();preview=self.library.preview_import(source)
        destination=self.authored_file('destination.cwbook',('Preserve',));before=destination.read_bytes()
        repo=OpeningBookRepository.open(destination)
        try:
            calls=[]
            def authorize(action,a,b,c,d):
                if action==sqlite3.SQLITE_INSERT and a=='source_references':
                    calls.append(a)
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            repo.connection.set_authorizer(authorize)
            with self.assertRaises(sqlite3.DatabaseError):append_books(repo,preview.books)
            repo.connection.set_authorizer(None)
            self.assertEqual(len(repo.books()),1)
        finally:repo.close()
        self.assertTrue(calls);self.assertEqual(destination.read_bytes(),before)

    def test_legacy_books_stay_put_and_deletion_reserves_ids_and_clears_reference(self):
        source=self.authored_file(titles=('Legacy','Other'))
        lib=self.library.import_library(source,self.library.preview_import(source))
        first,other=lib.books;before=lib.path.read_bytes()
        self.library.set_primary(first.installation_id)
        self.library.delete_book(self.library.preview_removal(first.installation_id))
        self.assertEqual(lib.path.read_bytes(),before)
        with self.assertRaises(ValueError):self.library.get(first.installation_id)
        self.assertEqual(self.library.get(other.installation_id).snapshot,other.snapshot)
        self.assertFalse(any(b.primary for b in self.workspace.books()))
        self.assertEqual([b.installation_id for b in self.workspace.books()],[other.installation_id])
        draft=self.workspace.draft()
        try:new=self.workspace.commit_draft(draft.snapshot(1),'New')
        finally:draft.close()
        self.assertNotEqual(new.installation_id,first.installation_id)
        self.assertEqual(lib.path.read_bytes(),before)

    def test_delete_stale_preview_rejected_and_deleted_last_home_id_never_reused(self):
        draft=self.workspace.draft()
        try:first=self.workspace.commit_draft(draft.snapshot(1),'First')
        finally:draft.close()
        preview=self.library.preview_removal(first.installation_id)
        self.library.set_status(first.installation_id,'draft')
        with self.assertRaisesRegex(ValueError,'changed'):self.library.delete_book(preview)
        self.library.delete_book(self.library.preview_removal(first.installation_id))
        draft=self.workspace.draft()
        try:new=self.workspace.commit_draft(draft.snapshot(1),'Second')
        finally:draft.close()
        self.assertEqual(first.path,new.path);self.assertGreater(new.snapshot.book.book_id,first.snapshot.book.book_id)


class StudioWorkflowTests(WorkspaceFixture):
    def setUp(self):
        super().setUp()
        self.root=tk.Tk();self.root.withdraw();self.studio=OpeningBookStudio(self.root)
        self.addCleanup(self.close_studio)
        guard=patch('merlin_ui.opening_book_studio.messagebox.showerror',side_effect=AssertionError('Unexpected UI error'))
        guard.start();self.addCleanup(guard.stop)

    def close_studio(self):
        self.studio.drafting=False;self.studio.dirty=False
        if self.studio.session:self.studio.session.discard()
        self.studio.close()

    def create(self,title,line=''):
        s=self.studio;s.new_book();s.draft_title.set(title)
        if line:
            for move in line.split():s.stage(move);s.save_editor()
        else:s.save_editor()
        return s.selected_reference()

    def select(self,title):
        s=self.studio;index=next(i for i,b in enumerate(s.book_items) if b.book.name==title)
        s.book_picker.current(index);s.select_book()

    def test_exact_four_book_owner_workflow_and_game_review_visibility(self):
        s=self.studio
        first=self.create('The French','e4 e6');self.create('Pirc Defense','e4 d6');self.create('London','d4 d5')
        self.select('The French');s.activate_node(next(k for k,p in s.paths.items() if p and k.startswith('m')))
        s.edit_move();s.fields['move_note'].insert('1.0','Owner note');s.save_editor()
        self.select('London');s.book_start();s.stage('Nf3');s.fields['variation_name'].insert('1.0','Alternative');s.save_editor()
        s.new_book();self.assertTrue(s.drafting);self.assertEqual(s.draft_title.get(),'')
        self.assertEqual(s.session.board.fen(),chess.STARTING_FEN);self.assertEqual(s.session.history,())
        self.assertEqual(s.tree.get_children(),())
        self.assertEqual(len(self.workspace.books()),3)
        s.draft_title.set("King's Gambit")
        for move in ('e4','e5','f4'):s.stage(move);s.save_editor()
        new_id=s.selected_reference();self.assertEqual(len(s.book_items),4)
        self.select('The French');self.assertEqual(s.selected_reference(),first)
        self.assertIn('Owner note',[m.move_note for m in s.session.snapshot.moves])
        self.select("King's Gambit");self.assertEqual(s.selected_reference(),new_id)
        self.assertEqual([m.san for m in s.session.snapshot.moves],['e4','e5','f4'])
        # Game Review consumes this same managed listing, without a publish/import step.
        from database_bootstrap import ensure_database
        from merlin_ui.game_review_view import GameReviewView
        db=self.folder/'test-games.db';ensure_database(db);before=db.read_bytes()
        review_root=tk.Toplevel(self.root);review=GameReviewView(review_root,database_path=db)
        try:
            self.assertIn(new_id,{b.installation_id for b in review.opening_reference.service.library.list_books()})
            review.open_installed_book(self.library.get(new_id))
            self.assertEqual(review.opening_book_studio.selected_reference(),new_id)
        finally:review.close()
        self.assertEqual(db.read_bytes(),before)

    def test_first_preview_no_storage_and_cancel_new_book(self):
        s=self.studio;s.new_book();s.draft_title.set('Unsaved');s.notation.insert(0,'e4');s.stage_text()
        self.assertEqual(s.session.pending,'e2e4');self.assertFalse(self.library.repository.root.exists())
        with patch(UI+'choose_action',return_value='cancel'):self.assertFalse(s.guard())
        self.assertTrue(s.drafting)
        with patch(UI+'choose_action',return_value='discard'):self.assertTrue(s.guard())
        self.assertFalse(s.drafting);self.assertIsNone(s.session);self.assertFalse(self.library.repository.root.exists())

    def test_switch_save_discard_cancel_and_validation_failure(self):
        first=self.create('First','e4');self.create('Second','d4');s=self.studio
        self.select('First');s.stage('d4')
        with patch(UI+'choose_action',return_value='cancel'):self.select('Second')
        self.assertEqual(s.selected_reference(),first);self.assertEqual(s.session.pending,'d2d4')
        with patch(UI+'choose_action',return_value='save'):self.select('Second')
        self.assertEqual(s.session.snapshot.book.name,'Second')
        self.select('First');self.assertEqual({m.san for m in s.session.snapshot.moves},{'e4','d4'})
        s.stage('Nf3')
        with patch(UI+'choose_action',return_value='discard'):self.select('Second')
        self.select('First');self.assertNotIn('Nf3',[m.san for m in s.session.snapshot.moves])
        s.new_book();s.stage('e4')
        with patch(UI+'choose_action',return_value='save'),patch('merlin_ui.opening_book_studio.messagebox.showerror') as error:
            self.select('Second')
        self.assertTrue(error.called);self.assertTrue(s.drafting);self.assertEqual(s.session.pending,'e2e4')

    def test_import_selected_shows_in_dropdown_and_export_leaves_canonical_unchanged(self):
        s=self.studio;source=self.authored_file();before=source.read_bytes()
        with patch(UI+'choose_books',return_value=(2,)):s.import_books(source)
        self.assertFalse(s.external_readonly);self.assertFalse(s.drafting)
        self.assertEqual(s.book_picker.cget('values'),('London',))
        canonical=s.repository.path;identity=s.selected_reference();payload=canonical.read_bytes()
        exported=self.folder/'share.cwbook'
        with patch(UI+'filedialog.asksaveasfilename',return_value=str(exported)):s.export_book()
        self.assertEqual(s.repository.path,canonical);self.assertEqual(s.selected_reference(),identity)
        self.assertEqual(payload,canonical.read_bytes());self.assertEqual(before,source.read_bytes())
        self.assertEqual(semantic_identity(self.library.preview_import(exported).books[0]),semantic_identity(s.session.snapshot))
        with patch(UI+'choose_books',return_value=(2,)):s.import_books(source)
        self.assertEqual(len(s.book_items),1);self.assertEqual(s.selected_reference(),identity)

    def test_line_override_clear_and_alternative_keep_graph_and_polyglot(self):
        self.create('Lines','e4 e5 Nf3');s=self.studio
        before=s.session.snapshot;polyglot=export_entries(before);ids=[m.move_id for m in before.moves]
        with patch(UI+'simpledialog.askstring',return_value='My line'):s.rename_line()
        self.assertEqual(s.navigation.active.label,'My line')
        self.assertEqual(export_entries(s.session.snapshot),polyglot)
        with patch(UI+'simpledialog.askstring',return_value=''):s.rename_line()
        self.assertEqual(s.navigation.active.label,'Opening trunk')
        self.assertEqual([m.move_id for m in s.session.snapshot.moves],ids)
        self.assertEqual(export_entries(s.session.snapshot),polyglot)
        s.add_alternative();self.assertEqual(s.session.board.turn,chess.WHITE)
        self.assertEqual(len(s.session.history),2)
        self.assertIn('White to move',s.shell.status_var.get())
        s.stage('Bc4');s.save_editor()
        self.assertEqual({m.san for m in s.session.snapshot.moves},{'e4','e5','Nf3','Bc4'})
        fallback=s.navigation.active.label;self.assertTrue(fallback.startswith('Line from'))
        polyglot=export_entries(s.session.snapshot)
        with patch(UI+'simpledialog.askstring',return_value='Bishop alternative'):s.rename_line()
        self.assertEqual(s.navigation.active.label,'Bishop alternative')
        with patch(UI+'simpledialog.askstring',return_value=''):s.rename_line()
        self.assertEqual(s.navigation.active.label,fallback)
        self.assertEqual(export_entries(s.session.snapshot),polyglot)

    def test_pirc_branch_point_and_custom_header_survive_book_reload(self):
        reference=self.create('Pirc','e4 d6 d4 Nf6 Nc3 g6 f4 Bg7')
        s=self.studio;polyglot=export_entries(s.session.snapshot)
        s.add_alternative()
        self.assertIn('Branch point after 4.f4',s.shell.status_var.get())
        self.assertIn('Black to move',s.shell.status_var.get())
        self.assertEqual(export_entries(s.session.snapshot),polyglot)
        s.stage('c5');s.save_editor()
        anchor=s.navigation.active.anchor
        with patch(UI+'simpledialog.askstring',return_value='Austrian alternative'):s.rename_line()
        polyglot=export_entries(s.session.snapshot)
        s.load_book(self.library.get(reference))
        branch=next(b for b in s.navigation.branches() if b.anchor==anchor)
        self.assertEqual(branch.label,'Austrian alternative')
        s.navigation.activate(branch)
        with patch(UI+'simpledialog.askstring',return_value=''):s.rename_line()
        self.assertTrue(s.navigation.active.label.startswith('Line from'))
        self.assertEqual(export_entries(s.session.snapshot),polyglot)
        self.root.update_idletasks()

    def test_delete_cancel_export_first_and_confirm_with_live_choices(self):
        first=self.create('First','e4');self.create('Keep','d4');s=self.studio;self.select('First')
        before=s.repository.path.read_bytes();catalog=self.library.repository.catalog.read_bytes()
        with patch(UI+'choose_action',return_value='cancel'):s.delete_book()
        self.assertEqual(catalog,self.library.repository.catalog.read_bytes())
        with patch(UI+'choose_action',return_value='export'),patch(UI+'filedialog.asksaveasfilename',return_value=str(self.folder/'first.cwbook')):s.delete_book()
        self.assertIn(first,{b.installation_id for b in self.workspace.books()})
        with patch(UI+'choose_action',return_value='delete'):s.delete_book()
        self.assertEqual(s.book_picker.cget('values'),('Keep',))
        self.assertEqual(s.repository.path.read_bytes(),before)
        self.assertNotIn(first,{b.installation_id for b in self.workspace.books()})

    def test_rename_book_keeps_id_sources_and_existing_notes(self):
        source=self.authored_file(titles=('Old',));s=self.studio
        with patch(UI+'choose_books',return_value=(1,)):s.import_books(source)
        identity=s.selected_reference();before=s.session.snapshot
        with patch(UI+'edit_fields',return_value=dict(name='Renamed',description='Updated',version='1',status='active',author='Owner',license='CC0')):s.edit_book()
        self.assertEqual(s.selected_reference(),identity);self.assertEqual(s.session.snapshot.moves,before.moves)
        self.assertEqual(s.session.snapshot.positions,before.positions);self.assertEqual(s.session.snapshot.sources,before.sources)
        self.assertEqual(s.book_picker.cget('values'),('Renamed',))
