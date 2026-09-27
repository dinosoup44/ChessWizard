"""Isolated Opening Review V2 acceptance; engine startup is forbidden."""
from tests.opening_ui_wait import wait_for_opening
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import ast
import threading
import time
import tkinter as tk
from unittest.mock import patch
import chess
import chess.engine
from analysis_control import AnalysisCancelled
from candidate_line_repository import CandidateLineRepository
from move_quality_repository import MoveQualityRepository
from opening_analysis_service import OpeningAnalysisService
from opening_book_models import BookDetails, MoveDetails, position_identity
from opening_book_repository import OpeningBookRepository
from opening_book_service import OpeningBookService
from opening_book_session import OpeningBookSession
from opening_library_service import OpeningLibraryService
from opening_library_listing import managed_book_choices
from opening_studio_handoff import make_studio_handoff, handoff_line_plan
from opening_workspace import book_suggestion, opening_game_sort, opening_moments
from merlin_ui.game_review_view import GameReviewView
from tests.test_game_analysis import TemporaryAnalysis
from tests.opening_intelligence_fixtures import french_book, pgn
from tests.opening_book_fixtures import add_line
from tests.test_opening_accuracy import evidence


class OpeningWorkspaceFixture(TemporaryAnalysis):
    def setUp(self):
        super().setUp()
        guard=patch.object(chess.engine.SimpleEngine,'popen_uci',side_effect=AssertionError('No engine'))
        guard.start();self.addCleanup(guard.stop)
        errors=patch('merlin_ui.opening_book_studio.messagebox.showerror',side_effect=lambda *a,**k: (_ for _ in ()).throw(AssertionError(str(a))))
        errors.start();self.addCleanup(errors.stop)
        self.library=OpeningLibraryService();self.lib=self.library.create_library('Fixture Openings')
        self.repo=OpeningBookRepository.open(self.lib.path);self.addCleanup(self.repo.close)
        self.author=OpeningBookService(self.repo);self.bid=french_book(self.author)
        self.author.set_repertoire_side(self.bid,'black')
        session=OpeningBookSession(self.author,self.bid)
        add_line(session,'e4 e6 d4 d5 e5 c5 c3 Nc6 Nf3')
        self.author.edit_move(self.bid,session.history[5],MoveDetails(preferred=True))
        for index,line in enumerate(('e4 e6 d4 d5 e5 a6','e4 e6 d4 d5 h3 c5','e4 e6 d4 d5 h3 Nf6',
                'e4 e6 d4 d5 exd5 exd5','d4 e6 e4 d5 e5 c5 c3 Nc6 Nf3','e4 c5 Nf3 Nc6','e4 e6 d4 d5 e5 c5'),1):
            self.import_fixture(pgn(line,'workspace-'+str(index)))
        with closing(self.connect()) as db:
            db.execute("UPDATE games SET user_color='black'")
            db.execute("UPDATE games SET user_color='white' WHERE game_id=7")
            for gid in (1,2):
                for move in MoveQualityRepository(db).moves(gid):
                    if gid==1 and move.step==6:continue
                    root,played=evidence(move,12 if gid==1 else 0)
                    CandidateLineRepository(db).put(root)
                    if played:CandidateLineRepository(db).put(played)
            db.commit()
        self.item=self.library.get_library(self.lib.library_id).books[0]
        self.root=tk.Tk();self.root.withdraw()
        self.view=GameReviewView(self.root,database_path=self.path)
        self.addCleanup(self.close_view)
        self.view.open_game_position(1,None);wait_for_opening(self.view)
        self.picker=self.view.opening_reference;self.panel=self.view.opening_panel;self.space=self.view.opening_workspace
        self.picker.service.select(1,self.item.installation_id);self.picker.refresh(force=True);wait_for_opening(self.view)

    def close_view(self):
        self.space.cancel.set()
        if self.space.worker:self.space.worker.join(5)
        self.view.close()

    def pump(self, predicate):
        deadline=time.monotonic()+8
        while not predicate() and time.monotonic()<deadline:
            self.root.update();time.sleep(.005)
        self.assertTrue(predicate(),self.space.status.cget('text'))

    def analyze(self):
        self.view.workspace_tabs.select(self.space);self.view._workspace_mode_changed()
        self.pump(lambda:self.space.result is not None or (not self.space.busy and self.space.result_key is not None))
        self.assertIsNotNone(self.space.result,self.space.status.cget('text'))
        return self.space.result


class OpeningWorkspaceTests(OpeningWorkspaceFixture):
    def test_flat_choices_duplicate_labels_status_side_and_no_paths(self):
        other=self.library.create_library('Other Collection')
        with closing(OpeningBookRepository.open(other.path)) as repo:
            service=OpeningBookService(repo)
            service.create_book(BookDetails('The French',status='archived',metadata_json='{"repertoire_side":"white"}'))
            service.create_book(BookDetails('Unique',status='draft'))
        choices=managed_book_choices(self.library)
        self.assertEqual(len(choices),3)
        self.assertEqual(len({c.label for c in choices}),3)
        self.assertEqual(next(c.label for c in choices if c.name=='Unique'),'Unique')
        self.assertEqual({c.status for c in choices},{'draft','archived'})
        self.assertEqual({c.repertoire_side for c in choices},{'black','white',None})
        self.assertTrue(all('.cwbook' not in c.label for c in choices))
        self.picker.refresh(force=True);wait_for_opening(self.view)
        self.assertFalse(hasattr(self.picker,'library_picker'))
        self.assertEqual(len(self.picker.picker['values']),4)

    def test_background_grid_matching_metrics_sort_same_board_and_none_persistence(self):
        before=self.digest();book=self.repo.path.read_bytes()
        result=self.analyze()
        self.assertEqual(set(result.matching_set.game_ids),{1,2,3,4,5})
        self.assertEqual(set(self.space.games_grid.get_children()),{'1','2','3','4','5'})
        self.assertIn('partial',self.space.metrics.cget('text'))
        self.assertIn(f'{result.adherence.in_book_moves} / {result.adherence.opportunities}',self.space.metrics.cget('text'))
        self.assertIn(' / ',self.space.metrics.cget('text'))
        self.assertTrue(self.space.variations.get_children());self.assertTrue(self.space.deviations.get_children())
        board=self.view.board_widget
        for column in ('date','accuracy','adherence','variation','result','game'):
            self.space.sort_games(column)
            self.assertEqual(self.view.current_game['game_id'],1)
        for descending in (False,True):
            ordered=opening_game_sort(result.games,'accuracy',descending)
            scores=[g.accuracy.user.quality.accuracy for g in ordered]
            known=[x for x in scores if x is not None]
            self.assertEqual(known,sorted(known,reverse=descending))
            self.assertTrue(all(x is None for x in scores[len(known):]))
        self.space.games_grid.selection_set('2');self.space._choose_game()
        self.assertEqual(self.view.current_game['game_id'],1)
        self.assertEqual(self.panel.assessment.game_id,2)
        self.panel.select_moment(5);wait_for_opening(self.view)
        self.assertEqual(self.view.current_game['game_id'],2);self.assertIs(self.view.board_widget,board)
        self.assertEqual(self.view.workspace_tabs.select(),str(self.space))
        self.view.workspace_tabs.select(self.view.game_review_mode);self.root.update()
        self.assertEqual(self.view.current_game['game_id'],2)
        self.assertEqual(self.picker.selected_id,self.item.installation_id)
        self.picker.picker.current(0);self.picker.select()
        self.assertIsNone(self.space.selected_game)
        self.assertNotIn('Selected game:',self.space.selected_game_label['text'])
        for gid in (1,6,7):
            self.view.open_game_position(gid,None);wait_for_opening(self.view);self.assertIsNone(self.picker.selected_id)
        self.assertEqual(self.space.games_grid.get_children(),())
        self.assertEqual(self.digest(),before);self.assertEqual(self.repo.path.read_bytes(),book)

    def test_moments_decision_arrow_line_steps_and_actual_escape(self):
        self.analyze();self.panel.select_moment(6)
        self.assertEqual(self.view.current_step,5)
        self.assertEqual(self.view.board_widget.board.fen(),self.view.moves[5]['fen_before'])
        self.assertEqual(book_suggestion(self.panel.assessment,6),'c7c5')
        self.assertEqual(self.view.board_widget.arrows,[{'from':chess.C7,'to':chess.C5}])
        self.assertTrue(self.view.actual_moves.tag_ranges('current'))
        self.assertTrue(any(m.kind=='User deviation' for m in self.panel.moments))
        self.panel.show_line();self.assertIn('OPENING LINE',self.panel.indicator['text'])
        self.view.next_move();self.assertEqual(self.view.opening_exploration.ply,1)
        self.view.previous_move();self.assertEqual(self.view.opening_exploration.ply,0)
        self.view.return_to_game();self.assertEqual(self.view.board_widget.board.fen(),self.view.moves[5]['fen_before'])
        self.panel.show_line();self.view.actual_moves.on_jump(4)
        self.assertIsNone(self.view.opening_exploration);self.assertIsNone(self.view.opening_anchor_ply)
        self.assertEqual(self.view.board_widget.board.fen(),self.view.moves[3]['fen_after'])
        self.view.open_game_position(2,None);wait_for_opening(self.view);self.panel.select_moment(5)
        self.assertEqual(self.view.board_widget.arrows,[])
        self.assertTrue(any({'Opponent left opening','Opening gap'} <= set(m.tags) for m in self.panel.moments))
        self.view.open_game_position(4,None);wait_for_opening(self.view);self.panel.select_moment(6)
        self.assertEqual(self.view.board_widget.arrows,[])
        self.view.open_game_position(5,None);wait_for_opening(self.view)
        self.assertTrue(any(m.kind=='Re-entry into opening' for m in self.panel.moments))

    def test_exact_handoff_cancel_confirm_and_refresh(self):
        result=self.analyze();before=self.digest();snapshot=self.repo.snapshot(self.bid)
        self.view._set_step(4);self.view.open_opening_context();studio=self.view.opening_book_studio
        self.assertEqual(studio.session.board.fen(),self.view.moves[3]['fen_after'])
        self.assertIsNone(studio.staged_review.handoff)
        self.assertEqual(studio.tabs.select(),str(studio.browser_frame))
        self.view.show_opening_moment(6);self.view.next_move();self.view.open_opening_context()
        handoff=studio.staged_review.handoff
        self.assertEqual(handoff.candidate_moves,('a7a6',))
        self.assertEqual(studio.session.board.fen(),self.view.moves[5]['fen_before'])
        self.assertEqual(self.repo.snapshot(self.bid),snapshot)
        with patch('merlin_ui.opening_studio_handoff.confirm_book_line',return_value=None):studio.staged_review.confirm()
        self.assertEqual(self.repo.snapshot(self.bid),snapshot)
        with patch('merlin_ui.opening_studio_handoff.confirm_book_line',return_value='Played a6'):studio.staged_review.confirm()
        self.assertIsNone(studio.staged_review.handoff)
        updated=self.repo.snapshot(self.bid)
        self.assertTrue(set(snapshot.moves).issubset(set(updated.moves)))
        self.assertEqual(len(updated.moves),len(snapshot.moves)+1)
        self.pump(lambda:self.space.result is not None and self.space.result.result_identity!=result.result_identity)
        self.assertEqual(self.picker.selected_id,self.item.installation_id)
        self.assertIsNone(next(g for g in self.space.result.games if g.context.game_id==1).first_user_deviation)
        self.assertEqual(self.digest(),before)
        with self.assertRaises(ValueError):handoff_line_plan(updated,self.lib.library_id,handoff)

    def test_gap_drilldown_stages_without_writes_and_reentry_exact_route(self):
        self.analyze();before=self.repo.path.read_bytes()
        self.space.tabs.select(self.space.gaps.master);self.root.update()
        key=next(k for k in self.space.gaps.get_children() if any(r.game.context.game_id==2 for r in self.space.group_rows[k]))
        self.space.gaps.selection_set(key);self.root.update()
        self.space.affected.tree.selection_set('2');self.root.update()
        self.assertEqual(self.view.current_game['game_id'],1)
        self.panel.select_moment(5);wait_for_opening(self.view)
        self.assertEqual(self.view.current_game['game_id'],2);self.assertEqual(self.view.current_step,4)
        self.view.next_move();self.view.open_opening_context();staged=self.view.opening_book_studio.staged_review
        self.assertEqual(staged.handoff.candidate_moves,('h2h3',));staged.cancel()
        self.assertEqual(before,self.repo.path.read_bytes())
        self.space.browsing=False
        self.view.open_game_position(5,None);wait_for_opening(self.view);self.view._set_step(3)
        h=make_studio_handoff(self.panel.lookup,self.panel.assessment,self.view.moves,3)
        self.assertEqual(h.candidate_moves,())
        self.assertEqual(h.anchor.position,position_identity(self.view.moves[2]['fen_after']))
        self.view.open_opening_context()
        self.assertEqual(position_identity(self.view.opening_book_studio.session.board),h.requested_position)
        self.assertEqual(before,self.repo.path.read_bytes())

    def test_unspecified_side_empty_set_and_cancellation(self):
        self.repo.update_book(self.bid,BookDetails('French without inferred intent'))
        self.picker.refresh(force=True);wait_for_opening(self.view);self.view.workspace_tabs.select(self.space);self.view._workspace_mode_changed()
        self.assertFalse(self.space.busy);self.assertIn('Opening Side',self.space.status['text'])
        self.author.set_repertoire_side(self.bid,'white');self.picker.library_changed();wait_for_opening(self.view)
        self.pump(lambda:self.space.result is not None)
        self.assertEqual(self.space.result.matching_set.game_ids,(7,))
        event=threading.Event();event.set()
        with self.assertRaises(AnalysisCancelled):
            OpeningAnalysisService(self.path,self.library).analyze_lookup(self.panel.lookup,cancel=event)

    def test_stale_background_result_never_replaces_manual_none(self):
        started=threading.Event();release=threading.Event()
        original=OpeningAnalysisService.analyze_lookup
        def delayed(service,*args,**kwargs):
            started.set();release.wait(5);return original(service,*args,**kwargs)
        with patch.object(OpeningAnalysisService,'analyze_lookup',delayed):
            self.view.workspace_tabs.select(self.space);self.view._workspace_mode_changed()
            self.assertTrue(started.wait(2))
            self.picker.picker.current(0);self.picker.select();release.set()
            self.pump(lambda:not self.space.busy)
        self.assertIsNone(self.space.result);self.assertIsNone(self.picker.selected_id)
        self.assertEqual(self.space.games_grid.get_children(),())

    def test_shared_projections_and_handoff_import_without_ui_or_engine(self):
        for module in ('opening_library_listing','opening_workspace','opening_studio_handoff'):
            tree=ast.parse(Path(module+'.py').read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom):
                    self.assertFalse((node.module or '').startswith(('tkinter','merlin_ui','chess.engine')))

    def test_opening_layout_at_common_scales(self):
        initial=float(self.root.tk.call('tk','scaling'))
        try:
            for percent in (100,125,150):
                self.root.tk.call('tk','scaling',percent/100*96/72)
                window=tk.Toplevel(self.root);window.geometry('1200x850')
                view=GameReviewView(window,self.path)
                try:
                    view.open_game_position(1,None);wait_for_opening(view)
                    picker=view.opening_reference
                    picker.service.select(1,self.item.installation_id);picker.refresh(force=True);wait_for_opening(view)
                    view.workspace_tabs.select(view.opening_workspace)
                    self.root.update()
                    workspace=view.opening_workspace
                    self.assertLessEqual(window.winfo_height(),900)
                    for widget in (picker.picker,workspace.games_grid,workspace.detail.events,
                                   workspace.detail.show_button,workspace.detail.studio_button):
                        self.assertTrue(widget.winfo_ismapped())
                        self.assertGreater(widget.winfo_height(),10)
                        self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),window.winfo_rooty()+window.winfo_height())
                        self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),window.winfo_rootx()+window.winfo_width())
                    self.assertGreater(workspace.games_grid.winfo_height(),60)
                    self.assertGreater(workspace.detail.events.winfo_height(),45)
                    self.assertGreater(workspace.splitter.sash_coord(0)[1],0)
                    if getattr(self,'artifact_directory',None):
                        from PIL import ImageGrab
                        self.root.update()
                        ImageGrab.grab(window=window.winfo_id()).save(Path(self.artifact_directory)/f'workspace_{percent}.png')
                finally:
                    view.opening_workspace.cancel.set()
                    if view.opening_workspace.worker:view.opening_workspace.worker.join(5)
                    view.close()
        finally:self.root.tk.call('tk','scaling',initial)

    def test_book_change_clears_arrow_and_explored_handoff_preserves_route(self):
        self.analyze();self.panel.select_moment(6)
        self.assertTrue(self.view.board_widget.arrows)
        self.picker.picker.current(0);self.picker.select()
        self.assertEqual(self.view.board_widget.arrows,[])
        self.picker.service.select(1,self.item.installation_id);self.picker.refresh(force=True);wait_for_opening(self.view)
        self.panel.select_moment(6);self.panel.show_line();self.view.next_move()
        state=self.view.opening_exploration
        handoff=make_studio_handoff(self.panel.lookup,self.panel.assessment,self.view.moves,
            self.view.current_step,explored_fen=state.fen,explored_moves=(state.line[0].move_id,))
        self.assertEqual(handoff.anchor.path[-1],state.line[0].move_id)
        self.assertEqual(handoff.requested_position,position_identity(state.fen))
        self.view.open_opening_context()
        self.assertEqual(tuple(self.view.opening_book_studio.session.history),handoff.anchor.path)
        self.assertIsNone(self.view.opening_book_studio.staged_review.handoff)

    def test_explicit_side_details_preserves_book_metadata(self):
        self.view.open_opening_book_studio();studio=self.view.opening_book_studio
        studio.load_book(self.item)
        def edit(parent,title,fields,**kwargs):
            self.assertEqual(kwargs['choices']['repertoire_side'],('unspecified','white','black','both'))
            return {**fields,'repertoire_side':'both'}
        before=self.repo.snapshot(self.bid)
        with patch('merlin_ui.opening_studio_workflow.edit_fields',edit):studio.edit_book()
        updated=self.repo.snapshot(self.bid)
        self.assertEqual(updated.book.repertoire_side,'both')
        self.assertEqual(updated.moves,before.moves)
        self.assertEqual(updated.book.book_id,before.book.book_id)
