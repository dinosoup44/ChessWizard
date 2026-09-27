"""Navigation/progress regressions using only temporary games and authored openings."""
from tests.opening_ui_wait import wait_for_opening
from dataclasses import replace
from pathlib import Path
import ast
import threading
from unittest.mock import patch
import chess
from tests import test_opening_workspace as fixtures
from tests.test_game_analysis import TemporaryAnalysis
from opening_analysis_service import OpeningAnalysisService
from opening_review_navigation import deviation_occurrences


class OpeningReviewPolishTests(fixtures.OpeningWorkspaceFixture):
    def select_tab(self, tree):
        self.space.tabs.select(tree.master)
        self.root.update()

    def test_game_selection_preserves_projection_until_moment_click(self):
        before=self.digest();book=self.repo.path.read_bytes();self.analyze()
        self.panel.select_moment(6);self.panel.show_line();self.view.next_move()
        state=self.view.opening_exploration;fen=self.view.board_widget.board.fen()
        timeline=self.view.evaluation_values;banner=self.view.board_identity['text']
        with patch.object(self.view,'open_game_position',wraps=self.view.open_game_position) as navigate:
            self.space.games_grid.selection_set('5');self.root.update()
            navigate.assert_not_called()
        self.assertEqual(self.view.current_game['game_id'],1)
        self.assertEqual(self.panel.assessment.game_id,5)
        self.assertEqual(self.view.opening_exploration,state)
        self.assertEqual(self.view.board_widget.board.fen(),fen)
        self.assertEqual(self.view.evaluation_values,timeline)
        self.assertEqual(self.view.board_identity['text'],banner)
        self.assertFalse(self.panel.studio_button.instate(['disabled']))
        self.panel.select_moment(4);self.root.update()
        self.assertEqual(self.view.current_game['game_id'],5)
        self.assertIsNone(self.view.opening_exploration)
        self.assertEqual(self.view.board_widget.board.fen(),self.view.moves[3]['fen_before'])
        self.assertEqual(self.view.game_quality.moves[0].move.game_id,5)
        self.assertEqual(self.digest(),before);self.assertEqual(self.repo.path.read_bytes(),book)

    def test_move_buttons_work_in_actual_history_and_authored_line(self):
        self.analyze()
        self.assertFalse(self.panel.forward.instate(['disabled']))
        self.panel.forward.invoke();self.root.update()
        self.assertEqual(self.view.current_step,1)
        self.assertEqual(self.view.board_widget.board.fen(),self.view.moves[0]['fen_after'])
        self.panel.back.invoke();self.assertEqual(self.view.current_step,0)
        self.panel.select_moment(6);self.panel.show_line()
        self.panel.forward.invoke();state=self.view.opening_exploration
        self.assertEqual(state.ply,1);self.assertEqual(self.view.current_step,5)
        self.panel.back.invoke();self.assertEqual(self.view.opening_exploration.ply,0)
        self.view.return_to_game();self.assertEqual(self.view.current_step,5)
        self.panel.forward.invoke();self.assertEqual(self.view.current_step,6)
        self.assertTrue(self.panel.forward.instate(['disabled']))

    def test_sorting_and_game_selection_do_not_navigate(self):
        self.analyze();self.select_tab(self.space.games_grid)
        self.space.sort_games('game');self.space.games_grid.detach('2')
        self.space.games_grid.selection_set('3');self.root.update()
        self.space.sort_games('game')
        self.assertEqual(self.space.games_grid.selection(),('3',))
        self.assertEqual(self.view.current_game['game_id'],1)
        self.assertEqual(self.panel.assessment.game_id,3)
        self.assertFalse(hasattr(self.space,'previous_button'))
        self.assertFalse(hasattr(self.space,'next_button'))
        self.assertFalse(hasattr(self.space,'navigate'))
        self.assertFalse(hasattr(self.space.affected,'open_button'))
        self.assertFalse(self.space.deviations.bind('<Double-1>'))

    def test_deviation_summary_game_and_moment_boundaries(self):
        self.analyze();self.select_tab(self.space.deviations)
        key=next(k for k in self.space.deviations.get_children() if {r.key for r in self.space.group_rows[k]}=={'2:5','3:5'})
        self.space.deviations.selection_set(key);self.root.update()
        self.assertEqual(self.view.current_game['game_id'],1)
        self.assertEqual(set(self.space.affected.tree.get_children()),{'2','3'})
        self.assertEqual(self.space.deviations.set(key,'party'),'Opponent')
        self.assertIn('h3',self.space.deviations.set(key,'move'))
        self.assertTrue(self.space.deviations.set(key,'opening'))
        self.space.affected.tree.selection_set('2');self.root.update()
        self.assertEqual(self.view.current_game['game_id'],1)
        self.assertEqual([m.book.game_id for m in self.panel.moments],[2])
        self.assertIn('Selected game: 2',self.space.selected_game_label['text'])
        self.panel.events.selection_set(self.panel.moments[0].key);self.root.update()
        self.assertEqual((self.view.current_game['game_id'],self.view.current_step),(2,4))
        self.assertEqual(self.view.opening_anchor_ply,5)
        self.assertEqual(self.view.board_widget.board.fen(),self.view.moves[4]['fen_before'])
        self.assertTrue(self.view.actual_moves.tag_ranges('current'))
        self.space.affected.tree.selection_set('3');self.root.update()
        self.assertEqual(self.view.current_game['game_id'],2)
        self.assertEqual([m.book.game_id for m in self.panel.moments],[3])
        self.panel.events.selection_set(self.panel.moments[0].key);self.root.update()
        self.assertEqual((self.view.current_game['game_id'],self.view.current_step),(3,4))
        self.assertIn('Game 3',self.view.board_identity['text'])

    def test_gap_navigation_and_studio_destination(self):
        before=self.repo.path.read_bytes();self.analyze();self.select_tab(self.space.gaps)
        self.space.gaps.selection_set(self.space.gaps.get_children()[0]);self.root.update()
        self.assertIn('Coverage gap',self.space.affected.caption['text'])
        self.space.affected.tree.selection_set('3');self.root.update()
        self.assertEqual(self.view.current_game['game_id'],1)
        self.assertFalse(self.panel.studio_button.instate(['disabled']))
        wait_for_opening(self.view);self.view.open_opening_context()
        self.assertEqual(self.view.opening_book_studio.session.board.fen(),self.view.board_widget.board.fen())
        self.assertIsNone(self.view.opening_book_studio.staged_review.handoff)
        self.assertEqual(len(self.panel.moments),1)
        self.assertEqual(self.panel.moments[0].tags,('Opponent left opening','Opening gap'))
        self.panel.select_moment(5)
        wait_for_opening(self.view);self.view.next_move();self.view.open_opening_context()
        h=self.view.opening_book_studio.staged_review.handoff
        self.assertEqual(h.candidate_moves,('h2h3',))
        self.assertEqual(h.source_ply,5)
        self.view.opening_book_studio.staged_review.cancel()
        self.assertEqual(self.repo.path.read_bytes(),before)

    def test_variation_summary_only_filters_and_game_only_selects(self):
        self.analyze();self.select_tab(self.space.variations)
        keys=self.space.variations.get_children();self.assertGreater(len(keys),1)
        for key in keys:
            self.space.variations.selection_set(key);self.root.update()
            self.assertEqual(self.view.current_game['game_id'],1)
            self.assertEqual(set(self.space.affected.rows),{str(r.game.context.game_id) for r in self.space.group_rows[key]})
            gid=self.space.affected.tree.get_children()[0]
            self.space.affected.tree.selection_set(gid);self.root.update()
            self.assertEqual(self.panel.assessment.game_id,int(gid))
            self.assertEqual(self.view.current_game['game_id'],1)

    def test_relevant_line_removed_and_explicit_authored_line_still_works(self):
        self.analyze();self.panel.select_moment(6)
        self.assertFalse(hasattr(self.panel,'tabs'))
        self.assertFalse(hasattr(self.panel,'branch'))
        row=self.panel.assessment.moves[5]
        self.panel.show_line()
        self.assertEqual(self.view.opening_exploration.ply,0)
        self.view.next_move()
        self.assertEqual(self.view.board_widget.board.fen(),self.view.opening_exploration.line[0].fen_after)
        self.view.return_to_game();self.assertEqual(self.view.board_widget.board.fen(),self.view.moves[5]['fen_before'])
        self.panel.select_moment(5)
        row=self.panel.assessment.moves[4]
        self.assertGreater(len(row.available_moves),1)
        self.panel.select_actual(2);self.assertIsNone(self.view.opening_exploration)
        self.assertEqual(self.view.board_widget.board.fen(),self.view.moves[1]['fen_after'])

    def test_progress_refresh_no_engine_no_writes_and_result_parity(self):
        before=self.digest();book=self.repo.path.read_bytes();events=[]
        service=OpeningAnalysisService(self.path)
        result=service.analyze_lookup(self.panel.lookup,progress=events.append)
        plain=service.analyze_lookup(self.panel.lookup)
        self.assertEqual(result,plain)
        self.assertEqual((events[0].completed,events[-1].completed),(0,7))
        self.assertIn('deviations',events[-1].phase)
        started=threading.Event();release=threading.Event();original=OpeningAnalysisService.analyze_lookup
        def delayed(service,*args,**kwargs):
            started.set();release.wait(5);return original(service,*args,**kwargs)
        with patch.object(OpeningAnalysisService,'analyze_lookup',delayed):
            self.view.workspace_tabs.select(self.space);self.view._workspace_mode_changed()
            self.assertTrue(started.wait(2))
            self.assertIn('Analyzing The French',self.space.status['text'])
            self.view.next_move();self.assertEqual(self.view.current_step,1)
            release.set();self.pump(lambda:self.space.result is not None)
        identity=self.space.result.result_identity
        self.picker._refresh_all();wait_for_opening(self.view);self.pump(lambda:not self.space.busy)
        self.assertEqual(self.space.result.result_identity,identity)
        self.assertEqual(self.digest(),before);self.assertEqual(self.repo.path.read_bytes(),book)

    def test_occurrence_contract_keeps_multiple_visits_and_core_is_portable(self):
        result=self.analyze();game=next(g for g in result.games if g.context.game_id==2);first=game.deviations[0]
        repeated=replace(first,book=replace(first.book,ply=9,move_id=9999))
        altered=replace(result,games=(replace(game,deviations=(first,repeated)),))
        rows=deviation_occurrences(altered,first.book.position,first.book.played_uci,first.party)
        self.assertEqual([r.key for r in rows],['2:5','2:9'])
        for name in ('opening_review_navigation','opening_review_line'):
            tree=ast.parse(Path(name+'.py').read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom):self.assertFalse((node.module or '').startswith(('tkinter','merlin_ui','chess.engine')))

    def test_opening_side_is_visible_and_updates_in_studio(self):
        self.view.open_opening_book_studio();studio=self.view.opening_book_studio;studio.load_book(self.item)
        self.assertEqual(studio.side_label['text'],'Opening Side: Black')
        with patch('merlin_ui.opening_studio_workflow.edit_fields',return_value=dict(name='The French',description='',version='1',status='draft',repertoire_side='both')):
            studio.edit_book()
        self.assertEqual(studio.side_label['text'],'Opening Side: Both / Reference')

    def test_normal_move_return_and_authored_followup_cell_preserve_exact_cursor(self):
        self.analyze();self.view._set_step(6)
        actual=self.view.board_widget.board.fen()
        move=self.panel.assessment.moves[5].available_moves[0]
        self.panel.explore(6,move.move_id)
        self.assertEqual(self.view.current_step,6)
        state=self.view.opening_exploration
        self.assertGreater(len(state.line),1)
        self.panel.select_line(2)
        self.assertEqual(self.view.board_widget.board.fen(),state.line[1].fen_after)
        self.view.return_to_game()
        self.assertEqual(self.view.board_widget.board.fen(),actual)
        self.assertEqual(self.view.current_step,6)

    def test_committed_edit_reports_refresh_and_discards_stale_progress(self):
        self.analyze();original=OpeningAnalysisService.analyze_lookup
        release=threading.Event();started=threading.Event()
        def delayed(service,*args,**kwargs):
            started.set();release.wait(5);return original(service,*args,**kwargs)
        self.author.set_repertoire_side(self.bid,'both')
        with patch.object(OpeningAnalysisService,'analyze_lookup',delayed):
            self.picker.library_changed();wait_for_opening(self.view)
            self.assertTrue(started.wait(2))
            self.assertIn('Opening changed',self.space.status['text'])
            self.assertIn('refreshing review',self.space.status['text'])
            self.picker.picker.current(0);self.picker.select();release.set()
            self.pump(lambda:not self.space.busy)
        self.assertIsNone(self.space.item)
        self.assertIsNone(self.space.result)

    def test_window_and_panes_settle_without_triggering_loop_guard(self):
        self.analyze();self.root.deiconify()
        for scale in (1,1.25,1.5):
            self.root.tk.call('tk','scaling',scale*96/72)
            for geometry in ('1120x760','1200x900','1000x800'):
                self.root.geometry(geometry)
                for tree in (self.space.games_grid,self.space.deviations,self.space.gaps,self.space.variations):
                    self.select_tab(tree)
                    self.pump(lambda:tree.winfo_height()>40)
                    if tree is not self.space.games_grid:
                        tree.selection_set(tree.get_children()[0]);self.root.update()
                        self.pump(lambda:self.space.affected.tree.winfo_height()>40)
                        self.assertGreater(self.space.affected.tree.winfo_height(),40)
                    self.assertGreater(tree.winfo_height(),40,(scale,geometry,str(tree),self.root.geometry(),self.space.winfo_ismapped(),self.space.splitter.winfo_height(),self.space.splitter.minimum_heights,self.space.upper.winfo_reqheight(),self.space.upper.winfo_height()))
                    settled=(self.root.winfo_height(),self.space.splitter.sash_coord(0))
                    for _ in range(5):
                        self.root.update()
                        self.assertEqual((self.root.winfo_height(),self.space.splitter.sash_coord(0)),settled)
                    self.assertFalse(self.space._automatic_size_guard.blocked)
                    self.assertFalse(self.view._automatic_size_guard.blocked)
