"""UI-only contracts using disposable data, settings and engine guards."""
from contextlib import closing
from dataclasses import replace
import gc
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import tkinter as tk
from tkinter import font
import unittest
from unittest.mock import patch
import chess
from application_settings import ApplicationSettings, ApplicationSettingsRepository
from game_context import actual_move_rows, training_game_context
from merlin_ui.application import ChessWizardApplication
from merlin_ui.information_panel import BACKGROUND
from tests.test_game_review_tactics import fixture_db, add
from game_review_sets import ALL_GAMES


class PolishTests(unittest.TestCase):
    def setUp(self):
        gc.collect()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"review.db"
        with closing(fixture_db()) as source, closing(sqlite3.connect(self.path)) as target:
            add(source,"missed_fork",ply=3)
            add(source,"missed_fork",game=2)
            source.backup(target)
        self.before = self.path.read_bytes()
        for guard in (patch.dict(os.environ,CHESSWIZARD_DATA_DIR=self.temp.name),
                      patch("theme_core.active._default_service",None),
                      patch("merlin_ui.game_review_view.load_review_sets",return_value=(ALL_GAMES,)),
                      patch("chess.engine.SimpleEngine.popen_uci",side_effect=AssertionError("UI cannot analyze"))):
            guard.start();self.addCleanup(guard.stop)
        self.root = tk.Tk()
        self.errors = []
        self.root.report_callback_exception=lambda *e:self.errors.append(str(e[1]))
        self.app = ChessWizardApplication(self.root,self.path)
        self.root.update()
        self.addCleanup(self.close)

    def close(self):
        self.app.close()
        self.app = None
        gc.collect()
        self.assertFalse(self.errors)
        self.assertEqual(self.path.read_bytes(),self.before)

    def menu(self,name):
        menu=self.root.nametowidget(self.root.cget("menu"))
        return self.root.nametowidget(menu.entrycget(name,"menu"))

    def pump(self,predicate):
        end=time.monotonic()+8
        while not predicate() and time.monotonic()<end:
            self.root.update();time.sleep(.01)
        self.assertTrue(predicate())

    def test_menus_and_removed_bottom_actions(self):
        menu=self.root.nametowidget(self.root.cget("menu"))
        self.assertEqual([menu.entrycget(i,"label") for i in range(3)],["File","View","Tools"])
        self.assertFalse(hasattr(self.app.review,"import_button"))
        self.assertFalse(hasattr(self.app.review,"analyze_button"))
        review = self.app.review
        self.assertEqual(review.shell.left_controls.winfo_children(), [review.game_mode])
        self.assertEqual([review.workspace_tabs.tab(tab,'text') for tab in review.workspace_tabs.tabs()], ['Game Review','Opening Review'])
        self.assertEqual(review.eval_timeline.master,review.game_mode)
        self.assertEqual(review.position_info.frame.master,review.game_mode)
        self.assertEqual(self.app.review.eval_timeline.winfo_manager(),"pack")
        self.menu("File").invoke("Import Games...")
        self.assertTrue(self.app.review.import_window.winfo_exists())
        self.assertEqual(self.app.review.import_dialog.output.cget("bg"),BACKGROUND)
        self.menu("Tools").invoke("Analyze Games...")
        self.assertFalse(hasattr(self.app.review.analysis_dialog,"review_button"))
        self.pump(lambda:not self.app.review.analysis_dialog.loading)
        self.menu("View").invoke("Appearance...")
        self.assertTrue(self.app.review.shell._theme_window.winfo_exists())
        self.menu("Tools").invoke("Admin Console...")
        self.pump(lambda:not self.app.review.shell._admin_console.busy)
        admin=self.app.review.shell._admin_console
        labels=[b.cget("text") for b in admin.buttons]
        self.assertIn("Refresh Status",labels)
        self.assertNotIn("Refresh",labels)
        self.assertNotIn("Appearance...",labels)
        check=next(b for b in admin.buttons if b.cget("text")=="Check Stockfish")
        diagnostic_page=admin.notebook.tabs()[5]
        self.assertTrue(str(check).startswith(diagnostic_page))
        admin.preset.set("deep");admin.preset_picker.event_generate("<<ComboboxSelected>>")
        self.assertIn("Preset: Deep",admin.pages["Analysis"].get("1.0","end"))
        self.assertEqual(admin.pages["Analysis"].cget("bg"),BACKGROUND)

    def test_tools_contract_training_and_separate_qa(self):
        view = self.app.review
        tools = self.menu("Tools")
        self.assertEqual([tools.entrycget(i, "label") for i in range(tools.index("end")+1)],
            ["Opening Library...", "Opening Studio...", "Game Explorer...", "Analyze Games...", "Training...", "Human Review / QA...", "Plugins...", "Admin Console..."])
        self.assertIsNone(view.human_review_panel)
        self.assertIsNone(view.review_set_picker)
        tools.invoke("Training...")
        first = self.app.training
        tools.invoke("Training...")
        self.assertIs(self.app.training, first)
        self.assertEqual(first.database_path, view.database_path)
        tools.invoke("Human Review / QA...")
        window = view.qa_window
        tools.invoke("Human Review / QA...")
        self.assertIs(view.qa_window, window)
        self.assertIs(view.human_review_panel.winfo_toplevel(), window)
        self.assertEqual(str(view.review_set_picker.cget("state")), "disabled")
        self.assertEqual(str(view.human_review_panel.save_button.cget("state")), "disabled")
        self.assertFalse(hasattr(view, "training_button"))
        view.close_human_review()
        self.assertIsNone(view.human_review_panel)

    def test_standalone_review_has_same_training_owner(self):
        from merlin_ui.game_review_view import GameReviewView
        window = tk.Toplevel(self.root)
        standalone = GameReviewView(window, self.path)
        try:
            menu = window.nametowidget(window.cget("menu"))
            tools = window.nametowidget(menu.entrycget("Tools", "menu"))
            tools.invoke("Training...")
            training = standalone.training
            tools.invoke("Training...")
            self.assertIs(standalone.training, training)
            training_menu = training.root.nametowidget(training.root.cget("menu"))
            training_tools = training.root.nametowidget(training_menu.entrycget("Tools", "menu"))
            training_tools.invoke("Training...")
            self.assertIs(standalone.training, training)
        finally:
            standalone.close()

    def test_actual_history_highlight_and_proof_restore(self):
        view = self.app.review
        view.open_game_position(1, 101)
        table = view.actual_moves
        self.root.update()
        self.assertTrue(table.winfo_ismapped())
        self.assertFalse(hasattr(view, "notebook"))
        self.assertFalse(table.tag_ranges("current"))
        for step in (1, 2):
            view.next_move()
            self.assertEqual(table.tag_ranges("current"), table.tag_ranges(f"step_{step}"))
        view.previous_move()
        self.assertEqual(table.tag_ranges("current"), table.tag_ranges("step_1"))
        view.go_to_start()
        self.assertFalse(table.tag_ranges("current"))
        view.tactics_panel.listbox.selection_set(0)
        view.tactics_panel._select()
        fen = view.board_widget.board.fen()
        self.assertEqual(table.tag_ranges("current"), table.tag_ranges("step_2"))
        history = table.get("1.0", "end")
        self.assertNotIn("Before move", view.position_label.cget("text"))
        self.assertNotIn("plies", view.position_label.cget("text"))
        self.assertNotIn("Move 2", view.position_info.get("1.0", "end"))
        view.tactics_panel.line_button.invoke()
        view.next_move()
        self.assertIn("Merlin Line", view.position_label.cget("text"))
        self.assertFalse(table.tag_ranges("current"))
        self.assertEqual(history, table.get("1.0", "end"))
        view.tactics_panel.line_button.invoke()
        self.assertEqual(view.board_widget.board.fen(), fen)
        self.assertEqual(table.tag_ranges("current"), table.tag_ranges("step_2"))

    def test_review_layout_keeps_history_and_navigation_visible(self):
        observations = []
        initial = float(self.root.tk.call("tk", "scaling"))
        from merlin_ui.game_review_view import GameReviewView
        try:
            for percent in (100, 125, 150):
                self.root.tk.call("tk", "scaling", percent/100*96/72)
                window = tk.Toplevel(self.root)
                view = GameReviewView(window, self.path)
                try:
                    for geometry in ("900x650", "1120x760"):
                        window.geometry(geometry)
                        view.open_game_position(1, 103)
                        view.tactics_panel.listbox.selection_set(0)
                        view.tactics_panel._select()
                        self.root.update()
                        self.assertFalse(view.position_info.frame.winfo_manager())
                        for widget in (view.actual_moves, view.position_strip, view.position_toggle, view.board_identity, view.navigation):
                            self.assertTrue(widget.winfo_ismapped())
                            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),
                                                 window.winfo_rooty()+window.winfo_height())
                        viewport = view.tactics_viewport.canvas
                        self.assertGreaterEqual(viewport.winfo_rooty(),
                            view.actual_moves.winfo_rooty()+view.actual_moves.winfo_height())
                        self.assertGreater(viewport.winfo_height(), 60)
                        viewport.yview_moveto(1)
                        self.root.update()
                        button = view.tactics_panel.line_button
                        self.assertGreaterEqual(button.winfo_rooty(), viewport.winfo_rooty())
                        self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),
                                             viewport.winfo_rooty()+viewport.winfo_height())
                        observations.append(dict(scaling=percent, geometry=geometry,
                            history_visible=True, details_scrollable=True, show_line_reachable=True,
                            viewport_height=viewport.winfo_height()))
                finally:
                    view.close()
        finally:
            self.root.tk.call("tk", "scaling", initial)
        target = os.environ.get("CHESSWIZARD_REVIEW_LAYOUT_REPORT")
        if target:
            Path(target).write_text(json.dumps(observations, indent=2), encoding="utf-8")

    def test_winner_names_and_raw_results(self):
        view=self.app.review
        for result,white,black in (("1-0","bold","normal"),("0-1","normal","bold"),("1/2-1/2","normal","normal")):
            view.current_game["result"]=result
            view.refresh_header()
            self.assertEqual(font.Font(font=view.white_label.cget("font")).actual("weight"),white)
            self.assertEqual(font.Font(font=view.black_label.cget("font")).actual("weight"),black)
            self.assertIn(result,view.subtitle_label.cget("text"))
            self.assertNotIn("Your color",view.subtitle_label.cget("text"))
            self.assertEqual(view.white_label.cget("text"),"White")
            self.assertEqual(view.black_label.cget("text"),"Black")

    def test_last_move_toggle_preserves_tactical_layers_and_settings(self):
        view=self.app.review
        view.open_game_position(1,103)
        board=view.board_widget
        board.set_tactical_targets((chess.E5,));board.set_arrows([{"from":chess.G1,"to":chess.F3}])
        board.selected_square=chess.G1
        targets,arrows=board.tactical_targets,list(board.arrows)
        self.menu("View").invoke("Show Last Move")
        self.assertIsNone(board.last_move)
        self.assertEqual(board.selected_square,chess.G1)
        self.assertEqual((board.tactical_targets,board.arrows),(targets,arrows))
        self.assertFalse(ApplicationSettingsRepository().load().show_last_move)
        self.menu("View").invoke("Show Last Move")
        self.assertEqual(board.last_move,chess.Move.from_uci("e7e5"))
        self.assertTrue(ApplicationSettingsRepository().load().show_last_move)

    def test_actual_cells_and_navigation_position_panel(self):
        view=self.app.review;view.open_game_position(1,101)
        table=view.actual_moves
        self.root.update()
        self.assertIn("Move\tWhite\tBlack",table.get("1.0","end"))
        self.assertIn("1\te4\te5",table.get("1.0","end"))
        for step in (1,2,3,4):
            index=table.tag_ranges("step_"+str(step))[0]
            x,y,w,h=table.bbox(index)
            table.event_generate("<Motion>",x=x+2,y=y+h//2)
            table.event_generate("<Button-1>",x=x+2,y=y+h//2)
            self.root.update()
            self.assertEqual(view.current_step,step)
            self.assertEqual(view.board_widget.board.fen(),view.moves[step-1]["fen_after"])
            self.assertEqual(view.board_widget.orientation,chess.BLACK)
        view.previous_move();self.assertEqual(table.tag_ranges("current"),table.tag_ranges("step_3"))
        self.assertIn("Actual last move: Nf3",view.position_info.get("1.0","end"))
        view.next_move();self.assertEqual(table.tag_ranges("current"),table.tag_ranges("step_4"))
        rows=actual_move_rows(view.moves[1:])
        self.assertEqual((rows[0].white,rows[0].black,rows[0].black_step),("","e5",1))
        view.tactics_panel.listbox.selection_set(0)
        view.tactics_panel.listbox.event_generate("<<ListboxSelect>>");self.root.update()
        self.assertIn("Moment:",view.position_info.get("1.0","end"))
        view.tactics_panel.line_button.invoke();view.next_move()
        self.assertEqual(view.navigation_mode,"merlin_line")
        self.assertIn("ACTUAL GAME MOVES",table.get("1.0","end"))
        self.assertIn("MERLIN PROOF",view.position_info.get("1.0","end"))
        view._set_step(1)
        self.assertNotIn("Moment:",view.position_info.get("1.0","end"))

    def test_training_context_reveal_and_source_game(self):
        viewer=self.app.open_training()
        viewer.show_candidate(0);self.root.update()
        self.assertEqual(viewer.current_candidate["move_id"],103)
        training_menu=viewer.root.nametowidget(viewer.root.cget("menu"))
        training_view=viewer.root.nametowidget(training_menu.entrycget("View","menu"))
        training_view.invoke("Show Legal Moves")
        self.assertFalse(viewer.show_legal_var.get())
        before=viewer.board_widget.board.fen()
        self.assertFalse(viewer.show_last_move_var.get());self.assertFalse(viewer.show_game_line)
        self.assertFalse(viewer.show_solution_var.get())
        self.assertNotIn("MERLIN SOLUTION",viewer.info_text.get("1.0","end"))
        viewer.last_move_button.invoke()
        self.assertEqual(viewer.board_widget.last_move,chess.Move.from_uci("e7e5"))
        self.assertEqual(viewer.last_move_button.cget("text"),"Hide Last Move")
        self.assertEqual(viewer.board_widget.board.fen(),before)
        viewer.game_line_button.invoke()
        self.assertIn("ACTUAL GAME HISTORY",viewer.info_text.get("1.0","end"))
        self.assertIn("Nf3",viewer.info_text.get("1.0","end"))
        self.assertFalse(viewer.show_solution_var.get())
        viewer.reveal_button.invoke()
        self.assertIn("MERLIN SOLUTION / PROOF",viewer.info_text.get("1.0","end"))
        viewer.game_line_button.invoke();viewer.last_move_button.invoke()
        self.assertNotIn("ACTUAL GAME HISTORY",viewer.info_text.get("1.0","end"))
        self.assertTrue(viewer.show_solution_var.get())
        viewer.review_button.invoke()
        self.assertEqual(self.app.review.current_game["game_id"],1)
        self.assertEqual(self.app.review.current_step,2)
        viewer.next_candidate();viewer.previous_candidate()
        self.assertEqual(viewer.current_candidate["move_id"],103)
        self.assertFalse(viewer.show_last_move_var.get());self.assertFalse(viewer.show_game_line)
        self.assertFalse(viewer.shell.left_controls.winfo_children())

    def test_empty_filter_clears_position_and_training_details(self):
        view=self.app.review
        view.open_game_position(1,103)
        view.tactics_panel.listbox.selection_set(0)
        view.tactics_panel.listbox.event_generate("<<ListboxSelect>>")
        view.filter_var.set("Mate");view.load_games()
        self.assertNotIn("Moment:",view.position_info.get("1.0","end"))
        viewer=self.app.open_training()
        viewer.reveal_button.invoke()
        viewer.filter_var.set("Missed Mate");viewer.change_filter()
        self.assertIsNone(viewer.current_candidate)
        self.assertNotIn("MERLIN SOLUTION",viewer.info_text.get("1.0","end"))
        self.assertEqual(str(viewer.review_button.cget("state")),"disabled")

    def test_missing_san_uses_stored_uci(self):
        view=self.app.review;view.open_game_position(1,101)
        view.moves[0]["san_played"]=None
        view.next_move()
        self.assertIn("Actual last move: e2e4",view.position_info.get("1.0","end"))
        self.assertIn("e2e4",view.actual_moves.get("1.0","end"))

    def test_layout_at_three_font_scalings(self):
        observations=[]
        initial=float(self.root.tk.call("tk","scaling"))
        for percent in (100,125,150):
            self.root.tk.call("tk","scaling",percent/100*96/72)
            viewer=self.app.open_training()
            for geometry in ("900x650","1120x760"):
                viewer.root.geometry(geometry);self.root.update()
                controls=[viewer.last_move_button,viewer.game_line_button,viewer.hint_button,
                          viewer.reveal_button,viewer.practice_button,viewer.review_button,
                          viewer.navigation.step_back_button,viewer.navigation.step_forward_button]
                for button in controls:
                    self.assertTrue(button.winfo_ismapped())
                    self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),viewer.root.winfo_rooty()+viewer.root.winfo_height())
                    self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),viewer.root.winfo_rootx()+viewer.root.winfo_width())
                    self.assertGreaterEqual(button.winfo_width(),button.winfo_reqwidth())
                board=viewer.board_widget
                self.assertGreater(board.board_pixels,160)
                self.assertEqual(board.square_size*8,board.board_pixels)
                observations.append(dict(scaling=percent,geometry=geometry,board_pixels=board.board_pixels,controls_visible=True))
            viewer.close();self.app.training=None;gc.collect()
        self.root.tk.call("tk","scaling",initial)
        target=os.environ.get("CHESSWIZARD_LAYOUT_REPORT")
        if target:Path(target).write_text(json.dumps(observations,indent=2),encoding="utf-8")


class SettingsTests(unittest.TestCase):
    def test_ui_setting_has_no_analysis_identity_effect(self):
        definition=next(d for d in ApplicationSettings().schema() if d.setting_id=="show_last_move")
        self.assertFalse(definition.affects_raw_cache_identity)
        self.assertFalse(definition.affects_result_currentness)
        with tempfile.TemporaryDirectory() as folder:
            repo=ApplicationSettingsRepository(Path(folder)/"settings.json")
            repo.save(replace(repo.load(),show_last_move=False))
            self.assertFalse(repo.load().show_last_move)
            self.assertEqual(repo.load().active_theme_id,"default")
