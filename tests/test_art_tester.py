"""Production board reuse and real Tk interaction regressions with temporary assets."""
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest.mock import patch
import chess
from PIL import Image
from merlin_ui.art_tester import ArtTester
from merlin_ui.chess_board import ChessBoard
from merlin_ui.view_shell import MerlinViewShell
from theme_core import PIECE_ROLES, DECORATION_SLOTS
from theme_core.board_geometry import BoardGeometry


class BoardGeometryTests(unittest.TestCase):
    def test_centers_roundtrip_both_orientations_and_sizes(self):
        for width,height in ((800,600),(600,900),(1001,731),(320,320)):
            for themed in (False,True):
                g=BoardGeometry.fit(width,height,framed=themed)
                for orientation in (True,False):
                    for square in chess.SQUARES:
                        x,y=g.square_xy(square,orientation)
                        self.assertEqual(g.square_at(x+g.square_size/2,y+g.square_size/2,orientation),square)
                self.assertIsNone(g.square_at(g.x-1,g.y))
                self.assertIsNone(g.square_at(g.x+g.size,g.y))
        self.assertIsNone(BoardGeometry.fit(0,0).square_at(0,0))

    def test_fixed_slot_bounds_and_legacy_geometry(self):
        old=BoardGeometry.fit(800,600)
        self.assertEqual((old.x,old.y,old.size),(100,0,600))
        g=BoardGeometry.fit(800,600,framed=True)
        for role,(x,y,w,h) in g.decoration_boxes().items():
            if role!='center_emblem':
                self.assertTrue(x+w<=g.x or x>=g.x+g.size or y+h<=g.y or y>=g.y+g.size)
        self.assertEqual(set(g.decoration_boxes()),set(DECORATION_SLOTS))


class ArtTesterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name);self.png=self.path/'piece.png'
        Image.new('RGBA',(30,50),(40,130,220,180)).save(self.png)
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        self.view=ArtTester(self.root,self.path/'themes')

    def test_same_production_board_as_review_and_training_shell(self):
        other=tk.Toplevel(self.root);other.withdraw()
        shell=MerlinViewShell(other)
        self.assertIs(type(self.view.board_widget),ChessBoard)
        self.assertIs(type(shell.board_widget),type(self.view.board_widget))
        other.destroy()

    def test_starting_roles_empty_and_flip(self):
        w=self.view.board_widget
        self.assertEqual(len(w.board.piece_map()),32)
        for role in PIECE_ROLES:self.assertTrue(self.view.assign_file(role,self.png))
        w._layout(640,640);w.redraw()
        images=w.find_withtag('piece');self.assertEqual(len(images),32)
        roles={tag for item in images for tag in w.gettags(item)}-{'piece'}
        self.assertEqual(roles,set(PIECE_ROLES))
        for flipped in (True,False):
            self.view.flipped.set(flipped);self.view.show_position()
            self.assertEqual(w.orientation,not flipped)
        self.view.sample.set('Empty board');self.view.show_position()
        self.assertEqual(w.board.piece_map(),{});self.assertEqual(w.find_withtag('piece'),())

    def test_decorations_never_change_geometry_or_hit_testing(self):
        w=self.view.board_widget;w._layout(800,600)
        before=w.geometry_model
        for slot in DECORATION_SLOTS:self.view.draft.assign(slot,self.png)
        self.view.refresh_preview();w._layout(800,600);w.redraw()
        self.assertEqual(w.geometry_model,before)
        self.assertEqual(len(w.find_withtag('decoration')),9)
        self.assertEqual(w.xy_to_square(*w.square_center(chess.A1)),chess.A1)
        w.set_theme();self.assertEqual(w.board_style,w._default_board_style)

    def test_save_reload_remove_and_draft_status(self):
        v=self.view
        with patch('sqlite3.connect',side_effect=AssertionError('No database allowed')):
            self.assertTrue(v.assign_file('white_king',self.png))
            v.name.set('Preview test');self.assertTrue(v.save_theme())
            self.assertIn('draft',v.status.get())
            v.select_theme();self.assertIn('white_king',v.draft.pieces)
            v.clear_asset('white_king')
            self.assertNotIn('white_king',v.draft.pieces)
            self.assertEqual(v.asset_rows['white_king']['thumbnail'].cget('image'),'')
            self.assertIn('0/12',v.completeness.get())

    def test_invalid_colors_block_save_and_bad_png_keeps_previous_asset(self):
        v=self.view;v.assign_file('white_king',self.png)
        bad=self.path/'bad.exe';bad.write_bytes(b'bad')
        self.assertFalse(v.assign_file('white_king',bad));self.assertIn('white_king',v.draft.pieces)
        v.name.set('Bad colors');v.color_vars['light_square'].set('bad')
        self.assertFalse(v.save_theme());self.assertFalse(v.repository.root.exists())

    def test_samples_overlays_resize_and_coordinates(self):
        v=self.view;v.overlays.set(True)
        for unused in range(10):
            v.step_sample(1);v.flipped.set(not v.flipped.get());v.show_position()
            self.assertEqual(v.board_widget.selected_square,chess.D4)
            self.assertEqual(len(v.board_widget.arrows),1)
            for size in ((320,500),(700,700),(950,500)):
                v.board_widget._layout(*size);v.board_widget.redraw()
        v.coordinates.set(False);v.overlays.set(False);v.show_position()
        self.assertFalse(v.board_widget.show_coordinates)
        self.assertEqual(v.board_widget.arrows,[]);self.assertIsNone(v.board_widget.selected_square)
