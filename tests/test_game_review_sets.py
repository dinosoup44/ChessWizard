"""Audit fixtures narrow games without changing stored tactical presentation."""
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from game_review_sets import ALL_GAMES, BUILTIN_REVIEW_SETS, ReviewSet, ReviewSetEntry, load_review_sets
import test_game_review_tactics as fixtures


def entry(game_id, reason="genuine disagreement", move_id=None):
    return ReviewSetEntry(game_id, "test_reason", reason, "test_artifact.json", str(move_id), move_id)


class ReviewSetDataTests(unittest.TestCase):


    def test_filter_order_labels_empty_and_immutable_metadata(self):
        review = ReviewSet("test", "Test", "", (entry(1), entry(1,"unsettled evidence"), entry(3)))
        games = [{"game_id": gid, "white_username":"W", "black_username":"B"} for gid in (3,2,1)]
        self.assertEqual([g["game_id"] for g in review.filter_games(games)], [3,1])
        self.assertEqual(ALL_GAMES.filter_games(games), games)
        self.assertEqual(ALL_GAMES.game_label(games[0]), "3 · W vs B")
        self.assertEqual(review.game_label(games[2]), "Game 1 — genuine disagreement (+1 reasons)")
        self.assertEqual(ReviewSet("empty","Empty","").filter_games(games), [])
        with self.assertRaises(FrozenInstanceError):
            review.entries[0].reason_label = "changed"


class ReviewSetWidgetTests(unittest.TestCase):
    select_game = fixtures.GameReviewWidgetTests.select_game

    def setUp(self):
        fixtures.GameReviewWidgetTests.setUp(self)
        self.view.review_sets = (ALL_GAMES, ReviewSet("questionable","Human Review — Questionable","",
                                    (entry(1,move_id=103),entry(1,"unsettled evidence",103),entry(3,move_id=301))),
                                ReviewSet("empty","Empty review set","", (entry(999),)))
        self.view.open_human_review()
        self.view.review_set_picker.configure(values=[s.label for s in self.view.review_sets])

    def choose_set(self, label):
        self.root.deiconify(); self.root.update()
        self.view.review_set_var.set(label)
        self.view.review_set_picker.event_generate("<<ComboboxSelected>>")
        self.root.update()

    def test_selector_deduplicates_games_loads_normal_moments_and_restores_all(self):
        v = self.view
        self.assertEqual([g["game_id"] for g in v.games],[3,2,1])
        original = tuple(v.game_picker["values"])
        self.select_game(1)
        before = tuple(v.moments)
        self.choose_set("Human Review — Questionable")
        self.assertEqual([g["game_id"] for g in v.games],[3,1])
        self.assertEqual(v.current_game["game_id"],1)
        self.assertEqual(tuple(v.moments),before)
        self.assertIn("(+1 reasons)",v.game_picker["values"][1])
        self.choose_set("All Games")
        self.assertEqual(tuple(v.game_picker["values"]),original)
        self.assertEqual(v.current_game["game_id"],1)

    def test_tactic_filter_intersects_without_reset_or_fallback(self):
        v = self.view
        v.filter_var.set("Mate"); v.load_games()
        self.choose_set("Human Review — Questionable")
        self.assertEqual(v.filter_var.get(),"Mate")
        self.assertEqual(v.games,[])
        v.filter_var.set("Fork"); v.load_games()
        self.assertEqual([g["game_id"] for g in v.games],[1])
        self.assertEqual(v.review_set_var.get(),"Human Review — Questionable")
        self.choose_set("All Games")
        self.assertEqual(v.filter_var.get(),"Fork")
        self.assertEqual([g["game_id"] for g in v.games],[1])

    def test_empty_set_clears_board_details_playback_and_shows_message(self):
        v = self.view; self.select_game(1)
        panel = v.tactics_panel
        panel.listbox.selection_set(0); panel._select(); panel.line_button.invoke(); v.next_move()
        with patch.object(v.shell,"set_status") as status:
            self.choose_set("Empty review set")
            self.assertIn("No games are available in this review set",status.call_args.args[0])
        self.assertIsNone(v.current_game); self.assertIsNone(panel.selected)
        self.assertEqual(v.moves,[]); self.assertEqual(v.moments,[])
        self.assertEqual(v.navigation_mode,"game")
        self.assertEqual(v.game_picker.get(),"")
        self.assertEqual(str(v.navigation.step_forward_button["state"]),"disabled")
        self.assertEqual(v.board_widget.arrows,[])
        self.assertEqual(v.board_widget.tactical_targets,())

    def test_review_game_show_play_hide_and_no_database_writes(self):
        v = self.view; self.choose_set("Human Review — Questionable"); self.select_game(1)
        panel = v.tactics_panel
        panel.listbox.selection_set(0); panel._select(); self.root.update()
        root_fen = v.board_widget.board.fen(); actual = v.current_step
        last_move = v.board_widget.last_move; targets = v.board_widget.tactical_targets
        arrows = list(v.board_widget.arrows)
        panel.line_button.invoke(); v.navigation.step_forward_button.invoke(); self.root.update()
        self.assertEqual(v.navigation_mode,"merlin_line")
        self.assertEqual(v.board_widget.board.fen(),panel.selected.stored_line.positions[1])
        v.navigation.step_back_button.invoke(); self.root.update()
        self.assertEqual(v.board_widget.board.fen(),root_fen)
        self.assertEqual(v.board_widget.arrows,arrows)
        self.assertEqual(v.board_widget.tactical_targets,targets)
        panel.line_button.invoke(); self.root.update()
        self.assertEqual(v.navigation_mode,"game"); self.assertEqual(v.current_step,actual)
        self.assertEqual(v.board_widget.last_move,last_move)
        self.assertEqual(v.connection.total_changes,0)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.before)

    def test_audit_only_move_does_not_create_a_tactical_moment(self):
        self.choose_set("Human Review — Questionable"); self.select_game(3)
        self.assertEqual(self.view.moments,[])
        self.view.next_move()
        self.assertEqual(self.view.current_step,1)
        self.assertEqual(self.view.connection.total_changes,0)
