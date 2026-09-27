"""Line display, isolated playback, and semantic overlay contracts."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import chess
from feedback import FeedbackContext
from line_playback import LinePlaybackState, format_proof_line_rows
from stored_line import StoredLine
from tactic_board_annotations import tactical_target_squares
import test_game_review_tactics as review_fixtures


class LineFormatTests(unittest.TestCase):
    def test_white_odd_even_and_real_move_numbers(self):
        board=chess.Board(); board.fullmove_number=12
        for text, count in (("e4 e5 Nf3",2),("e4 e5 Nf3 Nc6",2)):
            rows=format_proof_line_rows(StoredLine.from_san(board.fen(),text))
            self.assertEqual(len(rows),count)
            self.assertEqual((rows[0].move_number,rows[0].white,rows[0].black),(12,"e4","e5"))
            self.assertEqual(rows[1].move_number,13)
            self.assertEqual(rows[1].white_ply,3)
            self.assertEqual(rows[1].black,"Nc6" if len(text.split())==4 else "")

    def test_black_start_uses_empty_white_cell(self):
        board=chess.Board(); board.push_san("e4"); board.fullmove_number=9
        rows=format_proof_line_rows(StoredLine.from_san(board.fen(),"d5 exd5 Qxd5"))
        self.assertEqual([(r.move_number,r.white,r.black) for r in rows],[(9,"","d5"),(10,"exd5","Qxd5")])
        self.assertIsNone(rows[0].white_ply); self.assertEqual(rows[0].black_ply,1)

    def test_original_san_spelling_preserved(self):
        board=chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 25")
        line=StoredLine.from_san(board.fen(),"0-0 0-0-0")
        self.assertEqual(line.moves,("O-O","O-O-O"))
        rows=format_proof_line_rows(line)
        self.assertEqual((rows[0].white,rows[0].black),("0-0","0-0-0"))

    def test_capture_check_mate_and_promotion_san_preserved(self):
        for fen,text in ((chess.STARTING_FEN,"e4 e5 Bc4 Nc6 Qh5 Nf6 Qxf7#"),
                         ("7k/P7/8/8/8/8/8/K7 w - - 0 40","a8=Q+")):
            line=StoredLine.from_san(fen,text)
            rows=format_proof_line_rows(line)
            self.assertEqual([san for row in rows for san in (row.white,row.black) if san],text.split())

    def test_player_bounds_and_immutability(self):
        line=StoredLine.from_san(chess.STARTING_FEN,"d4 d5 c4")
        state=LinePlaybackState(line); board=chess.Board()
        self.assertEqual(state.step(-1),state); self.assertEqual(state.fen,board.fen())
        for ply,san in enumerate(line.moves,1):
            board.push_san(san); state=state.step(1)
            self.assertEqual(state.fen,board.fen()); self.assertEqual(state.ply,ply)
        self.assertEqual(state.step(1),state)
        for ply in (2,1,0):
            state=state.step(-1); self.assertEqual(state.fen,line.positions[ply])
        self.assertEqual(line.raw_text,"d4 d5 c4")

    def test_bad_empty_or_null_line_cannot_play(self):
        for raw in ("", "e4 invalid", "--"):
            line=StoredLine.from_san(chess.STARTING_FEN,raw)
            with self.assertRaises(ValueError): LinePlaybackState(line)
            with self.assertRaises(ValueError): format_proof_line_rows(line)

    def test_helpers_import_without_ui_database_or_engine(self):
        code="""
import builtins
original=builtins.__import__
def guard(name,*args,**kwargs):
    if name.startswith(('tkinter','sqlite3','chess.engine','analysis_','analyze_')): raise AssertionError(name)
    return original(name,*args,**kwargs)
builtins.__import__=guard
import line_playback, tactic_board_annotations
"""
        run=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)

    def test_stored_targets_only_and_invalid_targets_ignored(self):
        context=FeedbackContext(fen_before=chess.STARTING_FEN,legacy_metadata_json=json.dumps({
            "targets":[{"square":"e8"},{"square":"d8"},{"square":"e2"},{"square":"x9"},{"square":True}]}))
        self.assertEqual(tactical_target_squares(context),(chess.D8,chess.E8))
        self.assertEqual(tactical_target_squares(replace(context,legacy_metadata_json="bad")),())


class LinePlaybackWidgetTests(unittest.TestCase):
    setUp = review_fixtures.GameReviewWidgetTests.setUp
    select_game = review_fixtures.GameReviewWidgetTests.select_game

    def select_tactic(self):
        self.select_game(1)
        panel=self.view.tactics_panel
        panel.listbox.selection_set(0); panel._select(); self.root.update()
        return panel

    def test_shared_buttons_line_start_end_reset_and_hide_restore(self):
        panel=self.select_tactic(); v=self.view
        actual=v.current_step; history=[dict(row) for row in v.moves]; base=v.board_widget.board.fen()
        panel.line_button.invoke(); self.root.update()
        self.assertEqual(v.navigation_mode,"merlin_line")
        self.assertEqual(v.board_widget.board.fen(),base)
        self.assertTrue(v.board_widget.arrows)
        self.assertEqual(panel.proof_text.tag_ranges("current_ply"),())
        v.previous_move(); self.assertEqual(v.line_playback.ply,0)
        for ply in (1,2,3):
            v.navigation.step_forward_button.invoke(); self.root.update()
            self.assertEqual(v.board_widget.board.fen(),panel.selected.stored_line.positions[ply])
            self.assertEqual(v.current_step,actual)
            self.assertEqual(v.board_widget.arrows,[])
            marks=panel.proof_text.tag_ranges("current_ply")
            self.assertEqual(panel.proof_text.get(*marks),panel.selected.stored_line.raw_text.split()[ply-1])
        v.next_move(); self.assertEqual(v.line_playback.ply,3)
        v.previous_move(); self.assertEqual(v.line_playback.ply,2)
        v.go_to_start(); self.assertEqual(v.line_playback.ply,0); self.assertTrue(v.board_widget.arrows)
        v.next_move(); panel.line_button.invoke(); self.root.update()
        self.assertEqual(v.navigation_mode,"game"); self.assertIsNone(v.line_playback)
        self.assertEqual(v.current_step,actual); self.assertEqual(v.board_widget.board.fen(),base)
        self.assertFalse(panel.proof_frame.winfo_ismapped())
        self.assertEqual([dict(row) for row in v.moves],history)
        v.next_move(); self.assertEqual(v.current_step,actual+1)
        self.assertEqual(v.connection.total_changes,0)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.before)

    def test_illegal_proof_visible_but_game_mode_preserved(self):
        panel=self.select_tactic(); v=self.view; base=v.board_widget.board.fen()
        panel.selected=replace(panel.selected,stored_line=StoredLine.from_san(base,"d4 BAD"))
        panel.line_button.invoke(); self.root.update()
        self.assertIn("Playback unavailable",panel.proof_text.get("1.0","end"))
        self.assertEqual(v.navigation_mode,"game"); self.assertEqual(v.board_widget.board.fen(),base)
        self.assertEqual(v.connection.total_changes,0)

    def test_new_selection_game_and_filter_clear_projected_state(self):
        panel=self.select_tactic(); v=self.view
        panel.line_button.invoke(); v.next_move()
        panel._select(); self.assertEqual(v.navigation_mode,"game"); self.assertFalse(panel.show_line)
        self.assertEqual(v.board_widget.board.fen(),panel.selected.fen_before)
        panel.line_button.invoke(); v.next_move(); v.next_game()
        self.assertEqual(v.navigation_mode,"game"); self.assertIsNone(panel.selected)
        self.select_tactic(); panel.line_button.invoke(); v.next_move()
        v.filter_var.set("Skewer"); v.load_games()
        self.assertEqual(v.navigation_mode,"game"); self.assertEqual(v.moves,[])

    def test_semantic_overlap_order_and_no_extra_pieces(self):
        panel=self.select_tactic(); v=self.view; w=v.board_widget
        w._layout(640,640)
        panel.selected=replace(panel.selected,target_squares=(chess.E5,))
        v.refresh_board()
        self.assertEqual(w.tactical_targets,(chess.E5,))
        w.selected_square=chess.E5; w.redraw()
        last=w.find_withtag('last_move'); target=w.find_withtag('tactical_target'); selected=w.find_withtag('selected_square')
        self.assertTrue(last and target and selected)
        self.assertLess(max(last),min(target)); self.assertLess(max(target),min(selected))
        self.assertNotEqual(w.itemcget(last[0],'outline'),w.itemcget(target[0],'fill'))
        self.assertEqual(w.itemcget(selected[0],'fill'),'')
        self.assertTrue(w.find_withtag('merlin_recommendation'))
        expected=len(w.board.piece_map())
        # Contrast strokes are decorative, never additional chess pieces.
        self.assertEqual(len([i for i in w.find_all() if w.type(i)=='text'
            and w.itemcget(i,'font').startswith('{Segoe UI Symbol}') and 'piece_contrast_edge' not in w.gettags(i)]),expected)
        self.assertEqual(len(w.find_withtag('piece_contrast_edge')),4*expected)
        panel.line_button.invoke(); v.next_move(); self.assertEqual(w.tactical_targets,(chess.E5,))
        w.clear_overlays(); self.assertEqual(w.tactical_targets,())
