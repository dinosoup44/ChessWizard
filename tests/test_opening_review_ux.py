"""Opening exploration preserves real-game anchors and read-only book knowledge."""
from tests.opening_ui_wait import wait_for_opening
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import ast
import tkinter as tk
from unittest.mock import patch
import chess.engine
from opening_book_models import MoveDetails
from opening_book_repository import OpeningBookRepository
from opening_book_service import OpeningBookService
from opening_book_session import OpeningBookSession
from opening_library_service import OpeningLibraryService
from opening_exploration import explore_book_move, relevant_actual_moves
from tests.test_game_analysis import TemporaryAnalysis
from tests.opening_intelligence_fixtures import french_book, pgn
from tests.opening_book_fixtures import add_line
from merlin_ui.game_review_view import GameReviewView


class OpeningReviewUXTests(TemporaryAnalysis):
    def setUp(self):
        super().setUp()
        guard = patch.object(chess.engine.SimpleEngine,'popen_uci',side_effect=AssertionError('No engine'))
        guard.start(); self.addCleanup(guard.stop)
        self.library = OpeningLibraryService()
        lib = self.library.create_library('My Openings')
        self.repo = OpeningBookRepository.open(lib.path); self.addCleanup(self.repo.close)
        self.author = OpeningBookService(self.repo)
        self.bid = french_book(self.author)
        session = OpeningBookSession(self.author,self.bid)
        add_line(session,'e4 e6 d4 d5 e5 c5 c3 Nc6 Nf3 Qb6 Be2')
        self.author.edit_move(self.bid,session.history[8],MoveDetails(weight=90,preferred=True))
        self.author.edit_move(self.bid,session.history[5],MoveDetails(weight=80,preferred=True))
        self.item = self.library.get_library(lib.library_id).books[0]
        for index,line in enumerate((
            'e4 e6 d4 d5 e5 c5 c3 Nc6 Bd3',
            'e4 e6 d4 d5 e5 a6',
            'e4 e6 d4 d5 exd5 exd5',
            'b3 e5 Bb2 Nc6',
            'd4 e6 e4 d5 e5 c5 c3 Nc6 Nf3',
        ),1): self.import_fixture(pgn(line,'opening-ux-'+str(index)))
        self.root = tk.Tk(); self.root.withdraw()
        self.view = GameReviewView(self.root,database_path=self.path)
        self.addCleanup(self.view.close)
        self.view.open_game_position(1,None);wait_for_opening(self.view)
        self.picker = self.view.opening_reference
        self.picker.service.select(1,self.item.installation_id); self.picker.refresh(force=True);wait_for_opening(self.view)
        self.panel = self.view.opening_panel

    def open(self, game_id):
        self.view.open_game_position(game_id,None);wait_for_opening(self.view)
        self.assertEqual(self.picker.selected_id,self.item.installation_id)

    def test_manual_book_library_and_none_persist_until_cleared(self):
        for gid in (2,4,1):
            self.open(gid)
            self.assertEqual(self.picker.selected_library_id,self.item.library_id)
            self.assertEqual(self.panel.assessment.game_id,gid)
        self.open(4)
        self.assertIn('does not meaningfully enter The French',self.panel.summary.cget('text'))
        self.assertEqual(self.panel.moments,())
        self.picker.service.select(4,None); self.picker.refresh(force=True);wait_for_opening(self.view)
        for gid in (1,2,4):
            self.view.open_game_position(gid,None);wait_for_opening(self.view)
            self.assertIsNone(self.picker.selected_id)
            self.assertEqual(self.picker.selected_library_id,self.item.library_id)
        self.library.set_status(self.item.installation_id,'active')
        self.picker.defaults(); self.view.open_game_position(1,None);wait_for_opening(self.view)
        self.assertIsNone(self.picker.selected_id)
        self.assertIsNone(self.picker.service.manual_selection)

    def test_user_deviation_italic_arrow_actual_anchor_and_exact_restoration(self):
        db_before = self.digest(); book_before = self.repo.path.read_bytes()
        self.panel.select_moment(9); self.panel.show_line()
        state = self.view.opening_exploration
        self.assertEqual((self.view.current_step,state.anchor_ply,state.line[0].san),(8,9,'Nf3'))
        self.assertEqual(self.view.navigation_mode,'opening_exploration')
        self.assertIn('Opening move: Nf3',self.panel.indicator.cget('text'))
        self.assertEqual(self.view.board_widget.board.fen(),state.fen)
        self.assertEqual(self.view.board_widget.board.piece_at(chess.G1).piece_type,chess.KNIGHT)
        self.assertEqual(self.view.board_widget.arrows,[{'from':chess.G1,'to':chess.F3}])
        self.assertTrue(self.view.actual_moves.tag_ranges('current'))
        event=next(m for m in self.panel.moments if m.book.ply==9)
        self.assertTrue(event.book.deviation)
        self.assertFalse(event.book.played_move_in_book)
        self.assertIn(event.key,self.panel.events.selection())
        self.assertTrue(self.panel.assessment.moves[7].played_move_in_book)
        self.assertFalse(self.view.eval_bar.winfo_manager())
        # The actual-history widget always invokes the canonical restoration path.
        self.view.actual_moves.on_jump(9)
        self.assertIsNone(self.view.opening_exploration)
        self.assertEqual(self.view.board_widget.board.fen(),self.view.moves[8]['fen_after'])
        self.assertEqual(self.view.board_widget.arrows,[])
        self.assertEqual(self.view.eval_bar.winfo_manager(),'grid')
        self.assertEqual(self.digest(),db_before); self.assertEqual(self.repo.path.read_bytes(),book_before)

    def test_opponent_deviation_and_active_nonpreferred_never_suggest(self):
        self.open(2); self.panel.select_actual(6)
        self.assertIsNone(self.view.opening_exploration)
        self.assertEqual(self.view.board_widget.arrows,[])
        self.assertIn('Deviation by: Opponent',self.panel.summary.cget('text'))
        self.assertFalse(self.panel.assessment.moves[5].played_move_in_book)
        row=self.panel.assessment.moves[5]
        self.assertIsNotNone(row.preferred_move)
        self.panel.explore(6,row.preferred_move.move_id)
        self.assertIsNotNone(self.view.opening_exploration)
        self.assertIsNone(self.view.opening_exploration.suggestion)
        self.assertEqual(self.view.board_widget.arrows,[])
        self.open(3); self.panel.select_actual(5)
        self.assertIsNone(self.view.opening_exploration)
        self.assertEqual(self.view.board_widget.arrows,[])
        self.assertTrue(self.panel.assessment.moves[4].played_move_in_book)
        with closing(self.connect()) as db:
            db.execute('UPDATE games SET user_color=NULL WHERE game_id=1'); db.commit()
        self.open(1); self.panel.select_actual(9)
        self.assertIsNone(self.view.opening_exploration)
        self.panel.explore(9,self.panel.assessment.moves[8].preferred_move.move_id)
        self.assertIsNone(self.view.opening_exploration.suggestion)
        self.assertEqual(self.view.board_widget.arrows,[])


    def test_continuation_bounds_anchor_and_return_game_mode(self):
        self.panel.select_moment(9); self.panel.show_line()
        initial=self.view.opening_exploration
        self.assertEqual([m.san for m in initial.line],['Nf3','Qb6','Be2'])
        self.panel.step(1)
        self.assertEqual(self.view.current_step,8)
        self.assertEqual(self.view.opening_exploration.ply,1)
        self.assertEqual(self.view.board_widget.arrows,[])
        self.panel.step(100)
        self.assertEqual(self.view.opening_exploration.ply,3)
        self.panel.step(1); self.assertEqual(self.view.opening_exploration.ply,3)
        self.panel.step(-100); self.assertEqual(self.view.opening_exploration.ply,0)
        self.panel.step(-1); self.assertEqual(self.view.opening_exploration.ply,0)
        self.assertEqual(self.view.board_widget.board.fen(),initial.decision_fen)
        self.view.workspace_tabs.select(self.view.game_review_mode); self.view._workspace_mode_changed()
        self.assertIsNone(self.view.opening_exploration)
        self.assertEqual(self.view.current_step,8)
        self.assertEqual(self.view.board_widget.board.fen(),self.view.moves[8]['fen_before'])
        self.assertEqual(self.view.eval_timeline.master,self.view.game_mode)
        self.panel.select_moment(9); self.panel.show_line(); self.view.return_to_game()
        self.assertIsNone(self.view.opening_exploration)
        self.assertEqual(self.view.current_step,8)

    def test_live_edit_invalidates_exploration_preserves_selection(self):
        self.panel.select_moment(9); self.panel.show_line()
        old=self.panel.assessment.provenance
        edge=next(m for m in self.repo.snapshot(self.bid).moves if m.variation_name=='Advance Variation')
        details=MoveDetails(**{name:getattr(edge,name) for name in MoveDetails.__dataclass_fields__})
        self.author.edit_move(self.bid,edge.move_id,replace(details,variation_name='Live Advance'))
        self.picker.library_changed();wait_for_opening(self.view)
        self.assertEqual(self.picker.selected_id,self.item.installation_id)
        self.assertIsNone(self.view.opening_exploration)
        self.assertEqual(self.view.current_step,8)
        self.assertNotEqual(self.panel.assessment.provenance,old)
        self.view._set_step(5)
        self.assertIn('Live Advance',self.panel.summary.cget('text'))

    def test_reentry_marks_only_result_not_unknown_intermediate_moves(self):
        self.open(5)
        rows=relevant_actual_moves(self.panel.assessment)
        self.assertEqual([row.played_move_in_book for row in rows[:3]],[False]*3)
        self.assertTrue(rows[2].reentry)
        self.assertTrue(any(m.book.ply==3 and 'Re-entry into opening' in m.tags for m in self.panel.moments))

    def test_core_rejects_wrong_anchor_and_has_no_ui_or_engine_imports(self):
        result=self.panel.assessment; lookup=self.panel.lookup
        move=result.moves[8].preferred_move
        with self.assertRaises(ValueError):
            explore_book_move(lookup,result,9,chess.STARTING_FEN,move.move_id)
        with self.assertRaises(ValueError):
            explore_book_move(lookup,result,0,self.view.moves[8]['fen_before'],move.move_id)
        for node in ast.walk(ast.parse(Path('opening_exploration.py').read_text())):
            if isinstance(node,ast.ImportFrom):
                self.assertFalse((node.module or '').startswith(('tkinter','merlin_ui','chess.engine')))
