"""Performance boundaries and selection races over temporary owner-independent data."""
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import ast
import shutil
import threading
import tkinter as tk
from unittest.mock import patch
from opening_library_metadata import managed_book_headers
from opening_library_listing import managed_book_choices
from opening_book_reader import read_books
from opening_book_repository import OpeningBookRepository
from opening_book_navigation import branch_paths
from opening_library_service import OpeningLibraryService
from opening_library_reference import OpeningReferenceService
from opening_analysis_service import OpeningAnalysisService
from merlin_ui.game_review_view import GameReviewView
from merlin_ui.opening_book_studio import OpeningBookStudio
from tests.opening_ui_wait import wait_for_opening
from tests.test_opening_workspace import OpeningWorkspaceFixture


class OpeningPerformanceTests(OpeningWorkspaceFixture):
    def test_initial_review_and_dropdown_never_load_graphs_or_match_games(self):
        window=tk.Toplevel(self.root);window.withdraw()
        with ExitStack() as stack:
            for owner,name in ((OpeningLibraryService,'get'),(OpeningLibraryService,'list_libraries'),
                               (OpeningReferenceService,'choose'),(OpeningAnalysisService,'analyze_lookup'),
                               (OpeningBookRepository,'snapshot'),(OpeningBookRepository,'library_snapshot')):
                stack.enter_context(patch.object(owner,name,side_effect=AssertionError('No graph or analysis for selection UI')))
            view=GameReviewView(window,database_path=self.path)
            try:
                view.open_game_position(1,None)
                view.open_opening_facts();self.root.update()
                picker=view.opening_reference
                for _ in range(3):picker.tk.call(picker.picker.cget('postcommand'))
                self.assertEqual(picker.picker.get(),'Select an Opening')
                self.assertIsNone(picker.selected_id);self.assertIsNone(picker.worker)
                self.assertIsNone(view.opening_workspace.item)
                self.assertFalse(view.opening_workspace.busy)
            finally:view.close()

    def test_metadata_queries_only_books_not_graph_tables(self):
        import opening_book_reader
        original=opening_book_reader._connect
        queries=[]
        def connect(path):
            db=original(path);db.set_trace_callback(queries.append);return db
        with patch.object(opening_book_reader,'_connect',connect):
            choices=managed_book_choices(self.library)
        self.assertTrue(choices)
        self.assertTrue(all(c.content_identity is None for c in choices))
        self.assertFalse(any(any(t in q.lower() for t in ('book_moves','positions','source_references')) for q in queries),queries)

    def test_rapid_selection_coalesces_and_stale_result_cannot_publish(self):
        other=self.library.clone_book(self.item.installation_id,'Second').installation_id
        picker=self.picker;picker.defaults();picker.refresh(force=True)
        started=threading.Event();release=threading.Event();threads=[];calls=[]
        original=picker.service.library.get
        def delayed(reference):
            threads.append(threading.get_ident());calls.append(reference)
            if reference==self.item.installation_id:
                started.set();release.wait(5)
            return original(reference)
        errors=[];self.root.report_callback_exception=lambda *a:errors.append(a)
        try:
            with patch.object(picker.service.library,'get',side_effect=delayed),patch.object(self.space,'set_book',wraps=self.space.set_book) as publish:
                picker.service.select(1,self.item.installation_id);picker.refresh(force=True)
                self.assertTrue(started.wait(2))
                ticker=[];self.root.after(0,lambda:ticker.append(True));self.root.update()
                self.assertTrue(ticker)
                picker.service.select(1,other);picker.refresh(force=True)
                self.assertIn('Loading Second',picker.status['text'])
                self.assertIsNone(picker.loaded_item)
                release.set();wait_for_opening(self.view)
                published=[c.args[0].installation_id for c in publish.call_args_list if c.args[0] is not None]
                self.assertEqual(published,[other])
                self.assertEqual(picker.loaded_item.installation_id,other)
                self.assertEqual(calls,[self.item.installation_id,other])
                self.assertTrue(all(t!=threading.get_ident() for t in threads))
                self.assertEqual(errors,[])
        finally:
            release.set()
            if picker.worker:picker.worker.join(5)

    def test_none_cancels_pending_load_and_clears_details(self):
        picker=self.picker;release=threading.Event();started=threading.Event()
        original=picker.service.library.get
        def delayed(reference):
            started.set();release.wait(5);return original(reference)
        try:
            with patch.object(picker.service.library,'get',side_effect=delayed):
                picker.refresh(force=True);self.assertTrue(started.wait(2))
                picker.picker.current(0);picker.select()
                release.set();wait_for_opening(self.view)
                self.assertIsNone(picker.loaded_item);self.assertIsNone(self.space.item)
                self.assertIsNone(self.panel.assessment)
                self.assertEqual(self.space.games_grid.get_children(),())
        finally:release.set()

    def test_studio_reuses_tree_and_paths_then_invalidates_after_edit(self):
        self.view.open_opening_book_studio();studio=self.view.opening_book_studio
        nodes=[k for k in studio.branch_nodes if k.startswith('b')]
        for key in nodes:studio.activate_node(key)
        before=studio.session.snapshot
        with patch('opening_book_navigation.branch_paths',wraps=branch_paths) as paths, \
             patch.object(studio.library_service,'list_libraries',side_effect=AssertionError('No full library read')), \
             patch.object(studio.tree,'insert',side_effect=AssertionError('Do not rebuild loaded tree')), \
             patch.object(studio.tree,'delete',side_effect=AssertionError('Do not rebuild loaded tree')), \
             patch.object(studio,'notify_library_changed',side_effect=AssertionError('Navigation is not an edit')):
            for _ in range(3):
                for key in nodes:studio.activate_node(key)
            self.assertEqual(paths.call_count,0)
        studio.repository.set_position_note(studio.session.book_id,studio.session.position_id,'Changed')
        studio.session.refresh()
        with patch('opening_book_navigation.branch_paths',wraps=branch_paths) as paths:
            studio.navigation.sync();studio.render()
            self.assertGreater(paths.call_count,0)
        self.assertIsNot(studio.session.snapshot,before)
        self.assertGreater(studio.session.snapshot.book.revision,before.book.revision)
        self.assertIs(studio._tree_snapshot,studio.session.snapshot)

    def test_wal_revision_change_invalidates_selected_review(self):
        self.repo.connection.execute('PRAGMA journal_mode=WAL')
        before=self.picker.summary_session.lookup.provenance.book_revision
        self.repo.set_position_note(self.bid,self.repo.snapshot(self.bid).book.root_position_id,'New root note')
        self.picker.refresh();wait_for_opening(self.view)
        self.assertGreater(self.picker.summary_session.lookup.provenance.book_revision,before)
        self.assertEqual(self.panel.lookup.snapshot.position(self.panel.lookup.snapshot.book.root_position_id).position_note,'New root note')

    def test_selected_graph_only_and_semantic_identity_unchanged(self):
        expected=self.library.get_library(self.lib.library_id).books[0]
        with patch.object(OpeningBookRepository,'library_snapshot',side_effect=AssertionError('No full-library snapshot')):
            actual=self.library.get(self.item.installation_id)
        self.assertEqual(actual,expected)

    def test_metadata_core_has_no_ui_or_engine_imports(self):
        for name in ('opening_library_metadata.py','opening_library_listing.py'):
            tree=ast.parse(Path(name).read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom):
                    self.assertFalse((node.module or '').startswith(('tkinter','merlin_ui','chess.engine')))
