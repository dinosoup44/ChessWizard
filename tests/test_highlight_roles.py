"""End-to-end highlight roles from recorded targets through the shared canvas."""
from dataclasses import replace
import hashlib
import json
import unittest
import chess
from feedback import FeedbackContext
from tactic_board_annotations import tactical_target_squares, stationary_target_squares
from stored_line import StoredLine
import test_game_review_tactics as fixtures


class HighlightRoleTests(unittest.TestCase):
    setUp = fixtures.GameReviewWidgetTests.setUp
    select_game = fixtures.GameReviewWidgetTests.select_game

    def select_recorded_targets(self):
        self.select_game(1)
        panel=self.view.tactics_panel
        panel.listbox.selection_set(0); panel._select()
        moment=panel.selected
        context=FeedbackContext(fen_before=moment.fen_before,legacy_metadata_json=json.dumps({
            "targets":[{"square":"e5"},{"square":"d7"}]}))
        panel.selected=replace(moment,target_squares=tactical_target_squares(context))
        self.view.refresh_board()
        self.view.board_widget._layout(640,640)
        self.view.board_widget.redraw()
        return self.view, panel, self.view.board_widget

    def items_at(self, board, role, square):
        x,y=board.square_to_xy(square)
        return [item for item in board.find_withtag(role) if board.coords(item)[:2]==[x,y]]

    def test_distinct_squares_simultaneous_and_survive_redraw(self):
        view,panel,board=self.select_recorded_targets()
        # The previous e7-e5 move and the separate recorded d7 target coexist.
        for unused in range(3):
            board.redraw()
            last=self.items_at(board,'last_move',chess.E7)
            target=self.items_at(board,'tactical_target',chess.D7)
            self.assertEqual(len(last),1); self.assertEqual(len(target),1)
            self.assertEqual(board.itemcget(last[0],'outline'),board.board_style['last_move'])
            self.assertEqual(board.itemcget(target[0],'fill'),board.board_style['tactical_target'])
            self.assertNotEqual(board.itemcget(last[0],'outline'),board.itemcget(target[0],'fill'))
            self.assertTrue(board.find_withtag('merlin_recommendation'))

    def test_target_supersedes_yellow_last_move_border_on_same_square(self):
        view,panel,board=self.select_recorded_targets()
        self.assertEqual(self.items_at(board,'last_move',chess.E5),[])
        target=self.items_at(board,'tactical_target',chess.E5)[0]
        self.assertEqual(board.itemcget(target,'outline'),board.board_style['tactical_target'])
        self.assertTrue(self.items_at(board,'last_move',chess.E7))

    def test_selection_outline_above_target_and_last_move(self):
        view,panel,board=self.select_recorded_targets()
        for square,role in ((chess.D7,'tactical_target'),(chess.E7,'last_move')):
            board.selected_square=square; board.redraw()
            selected=self.items_at(board,'selected_square',square)[0]
            lower=self.items_at(board,role,square)[0]
            self.assertGreater(selected,lower)
            self.assertEqual(board.itemcget(selected,'outline'),board.board_style['selected_square'])
            self.assertEqual(board.itemcget(selected,'fill'),'')

    def test_show_step_back_hide_preserves_stationary_roles(self):
        view,panel,board=self.select_recorded_targets(); base=board.board.fen(); step=view.current_step
        panel.line_button.invoke()
        self.assertEqual(board.tactical_targets,(chess.E5,chess.D7))
        self.assertTrue(board.arrows)
        view.next_move()  # d4: neither recorded target moved.
        self.assertEqual(board.tactical_targets,(chess.E5,chess.D7))
        self.assertEqual(board.last_move,chess.Move.from_uci('d2d4'))
        self.assertEqual(board.arrows,[])
        view.next_move()  # d5: the d7 participant moved, so its old marker must clear.
        self.assertEqual(board.tactical_targets,(chess.E5,))
        view.previous_move()
        self.assertEqual(board.tactical_targets,(chess.E5,chess.D7))
        panel.line_button.invoke()
        self.assertEqual(board.board.fen(),base); self.assertEqual(view.current_step,step)
        self.assertEqual(board.tactical_targets,(chess.E5,chess.D7))
        self.assertEqual(board.last_move,chess.Move.from_uci('e7e5'))
        self.assertTrue(board.arrows)
        self.assertEqual(view.connection.total_changes,0)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.before)

    def test_style_overrides_keep_distinct_roles(self):
        view,panel,board=self.select_recorded_targets()
        board.board_style.update(last_move='#ddcc55',tactical_target='#ee8877',selected_square='#66aadd')
        board.redraw()
        self.assertEqual(board.itemcget(self.items_at(board,'last_move',chess.E7)[0],'outline'),'#ddcc55')
        self.assertEqual(board.itemcget(self.items_at(board,'tactical_target',chess.D7)[0],'outline'),'#ee8877')


class TargetPrefixTests(unittest.TestCase):
    def test_capture_and_en_passant_remove_only_affected_targets(self):
        for setup, capture in (("e4 d5", "exd5"), ("e4 a6 e5 d5", "exd6")):
            board=chess.Board()
            for san in setup.split(): board.push_san(san)
            line=StoredLine.from_san(board.fen(),capture)
            self.assertTrue(line.positions)
            self.assertEqual(stationary_target_squares((chess.D5,chess.E8),line.positions),(chess.E8,))

    def test_target_return_does_not_restore_old_marker_but_backward_prefix_does(self):
        line=StoredLine.from_san(chess.STARTING_FEN,"e4 Nf6 d3 Ng8")
        self.assertEqual(stationary_target_squares((chess.G8,),line.positions[:2]),(chess.G8,))
        self.assertEqual(stationary_target_squares((chess.G8,),line.positions),())
        self.assertEqual(stationary_target_squares((chess.G8,),line.positions[:2]),(chess.G8,))
