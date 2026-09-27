"""Owner-review presentation contracts and isolated partial-cache completion."""
from contextlib import closing
import tkinter as tk
import unittest
from unittest.mock import patch
import chess
from application_settings import ApplicationSettings, ApplicationSettingsRepository
from candidate_lines import LineScore
from candidate_line_repository import CandidateLineRepository
from evaluation_repository import EvaluationRepository
from game_analysis_models import AnalysisScopeKind, GameAnalysisScope
from game_analysis_service import GameAnalysisService
from merlin_ui.evaluation_widgets import EvaluationBar, EvaluationTimeline
from merlin_ui.game_review_view import GameReviewView
from position_evaluation import GamePosition, PositionEvaluation, EvaluationSettings
from tests.test_game_analysis import TemporaryAnalysis
from tests.test_game_import import pgn
from tests.test_position_evaluation import RecordedGenerator

LONG_MOVES = ("1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 "
              "6. Re1 b5 7. Bb3 d6 8. c3 O-O 9. h3 Nb8 10. d4 Nbd7 "
              "11. c4 c6 12. Nc3 Qc7 13. Be3 Bb7 14. Rc1 Rfe8 "
              "15. cxb5 axb5 16. Nxb5 Qb8 17. Nc3 1-0")


def values(scores):
    board = chess.Board()
    result = []
    for step, score in enumerate(scores):
        # Alternating legal knight moves give realistic FEN full-move/turn labels.
        if step:
            board.push_uci(("g1f3", "g8f6", "f3g1", "f6g8")[(step - 1) % 4])
        point = GamePosition(1, step or None, step, board.fen(), "Start" if not step else str(step))
        result.append(PositionEvaluation(point, score, complete=score is not None))
    return tuple(result)


class TimelineDrawingTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.root.geometry("580x280")
        self.timeline = EvaluationTimeline(self.root, lambda step: None)
        self.timeline.pack(fill="x")
        self.root.update()

    def text(self, tag):
        return [self.timeline.itemcget(i, "text") for i in self.timeline.find_withtag(tag)]

    def test_empty_state_has_no_plot_or_selection_artifacts(self):
        self.timeline.show(values([None] * 34), 7)
        self.assertEqual(self.text("empty_state"), ["No evaluation data for this game.",
            "Run Analyze Games to create the evaluation timeline."])
        self.assertEqual(self.text("coverage"), ["Evaluation · 0/34 positions"])
        self.assertTrue(all(self.timeline.type(i) == "text" for i in self.timeline.find_all()))

    def test_partial_has_only_known_bars_and_unknown_selection_is_not_zero(self):
        self.timeline.show(values([LineScore(score_cp=100)] * 5 + [None] * 29), 12)
        self.assertIn("Partial analysis · 5/34 positions", self.text("coverage")[0])
        self.assertEqual(len(self.timeline.find_withtag("evaluation_bar")), 5)
        self.assertFalse(self.timeline.find_withtag("bar_12"))
        self.assertFalse(self.timeline.find_withtag("selected_bar"))
        self.assertTrue(self.timeline.find_withtag("selected_unknown"))
        self.assertIn("Not analyzed", self.text("selected_label")[0])
        self.assertLess(len(self.timeline.find_withtag("move_label")), 8)
        self.assertIn("5", self.text("move_label"))

    def test_signed_bars_zero_clamp_mate_and_truthful_numeric_labels(self):
        scores = [LineScore(score_cp=n) for n in (400, -400, 0, 800, 2400)]
        scores += [LineScore(mate_score=3), LineScore(mate_score=-4)]
        self.timeline.show(values(scores), 4)
        center = self.timeline.coords("zero_axis")[1]
        bars = [self.timeline.coords(f"bar_{i}") for i in range(7)]
        self.assertLess(bars[0][1], center); self.assertEqual(bars[0][3], center)
        self.assertEqual(bars[1][1], center); self.assertGreater(bars[1][3], center)
        self.assertEqual(bars[2][3] - bars[2][1], 2)
        self.assertEqual(bars[3][1::2], bars[4][1::2])
        self.assertEqual(bars[4][1::2], bars[5][1::2])
        self.assertGreater(bars[6][3], center)
        self.assertFalse(self.timeline.find_withtag("mate_marker"))
        self.assertIn("+24.00", self.text("selected_label")[0])
        self.assertTrue(self.timeline.find_withtag("selected_bar"))
        self.timeline.show(values(scores), 6, proof_mode=True)
        self.assertIn("Actual game anchor", self.text("selected_label")[0])
        self.assertIn("-M4", self.text("selected_label")[0])

    def test_flat_endpoints_for_consecutive_clamped_and_mate_bars(self):
        scores = [LineScore(score_cp=n) for n in (100, -100, 800, 1200, 2400, -800, -2400)]
        scores += [LineScore(mate_score=3), LineScore(mate_score=2), LineScore(mate_score=-4)]
        points = values(scores)
        original_height = self.timeline.cget("height")
        top = 2 * self.timeline.line_height + 8
        bottom = 5 * self.timeline.line_height + 8
        center = (top + bottom) / 2
        for selected in (2, 6, 7, 9):
            self.timeline.show(points, selected)
            self.assertEqual(self.timeline.cget("height"), original_height)
            self.assertEqual(self.timeline.values, points)
            self.assertEqual(len(self.timeline.find_withtag("evaluation_bar")), len(scores))
            for step, point in enumerate(points):
                bar = self.timeline.find_withtag(f"bar_{step}")[0]
                self.assertEqual(self.timeline.type(bar), "rectangle")
                left, low, right, high = self.timeline.coords(bar)
                endpoint = bottom - (bottom - top) * point.white_fraction(800)
                self.assertEqual((low, high), (min(endpoint, center), max(endpoint, center)))
                self.assertEqual(self.timeline.itemcget(bar, "outline"), "")
                # No text, polygons or lines may cap the rectangular endpoint.
                items = self.timeline.find_overlapping(left, endpoint - 1, right, endpoint + 1)
                self.assertTrue(all(self.timeline.type(item) == "rectangle" for item in items))
            for step in (2, 3, 4, 7, 8):
                self.assertEqual(self.timeline.coords(f"bar_{step}")[1], top)
            for step in (5, 6, 9):
                self.assertEqual(self.timeline.coords(f"bar_{step}")[3], bottom)
            highlight = self.timeline.find_withtag("selected_bar")
            self.assertEqual(len(highlight), 1)
            self.assertEqual(self.timeline.type(highlight[0]), "rectangle")
            left, low, right, high = self.timeline.coords(f"bar_{selected}")
            self.assertEqual(self.timeline.coords(highlight[0]), [left - 2, low - 2, right + 2, high + 2])
            self.assertIn(points[selected].label(), self.text("selected_label")[0])

    def test_eval_label_is_independent_and_does_not_overlap_black_label(self):
        bar = EvaluationBar(self.root, height=260)
        bar.pack(side="left"); self.root.update()
        for score in (None, LineScore(score_cp=69), LineScore(score_cp=-69),
                      LineScore(score_cp=0), LineScore(mate_score=3), LineScore(mate_score=-4)):
            value = values([score])[0]; bar.show(value)
            self.assertEqual(bar.itemcget("black_label", "text"), "Black")
            self.assertEqual(bar.itemcget("white_label", "text"), "White")
            self.assertEqual(bar.itemcget("evaluation_label", "text"), value.label() if score else "Not analyzed")
            self.assertLess(bar.bbox("evaluation_label")[3], bar.bbox("black_label")[1])


class ReviewSplitterTests(TemporaryAnalysis):
    def view(self, scale=1):
        root = tk.Tk(); self.addCleanup(root.destroy)
        root.tk.call("tk", "scaling", scale * 96 / 72)
        view = GameReviewView(root, self.path); self.addCleanup(view.connection.close)
        root.update()
        return root, view

    def test_default_resize_scales_and_minimum_sizes_without_preference_writes(self):
        self.import_fixture(pgn(moves=LONG_MOVES))
        before = self.digest()
        for scale in (1, 1.25, 1.5):
            root, view = self.view(scale)
            for geometry in ("1120x760", "900x650", "1120x950"):
                root.geometry(geometry); root.update()
                split = view.review_splitter
                usable = split.winfo_height() - split.sash_size
                y = split.sash_coord(0)[1]
                self.assertGreaterEqual(y, split.minimum_heights[0] - 2)
                self.assertGreaterEqual(usable - y, split.minimum_heights[1] - 2)
                self.assertAlmostEqual(y, max(split.minimum_heights[0], min(usable - split.minimum_heights[1], usable * .4)), delta=2)
                self.assertGreater(view.actual_moves.winfo_height(), 95)
                # A click without movement must not persist the minimum-clamped ratio.
                split.event_generate("<ButtonPress-1>", x=20, y=y + 2)
                split.event_generate("<ButtonRelease-1>", x=20, y=y + 2)
                root.update()
                self.assertLessEqual(view.eval_timeline.winfo_y() + view.eval_timeline.winfo_height(), view.shell.left_controls.winfo_height())
            self.assertFalse(view.settings.path.exists())
            root.withdraw()
        self.assertEqual(before, self.digest())

    def test_drag_persists_only_on_release_and_restores_other_preferences(self):
        self.import_fixture()
        repo = ApplicationSettingsRepository()
        repo.save(ApplicationSettings(show_last_move=False))
        root, view = self.view()
        split = view.review_splitter
        original = repo.path.read_bytes()
        x, y = split.sash_coord(0)
        split.event_generate("<ButtonPress-1>", x=20, y=y + 2)
        split.event_generate("<B1-Motion>", x=20, y=y + 60)
        root.update()
        self.assertEqual(repo.path.read_bytes(), original)
        self.assertGreater(split.sash_coord(0)[1], y)
        split.event_generate("<ButtonRelease-1>", x=20, y=y + 60)
        root.update()
        saved = repo.load()
        self.assertGreater(saved.review_moves_fraction, .4)
        self.assertFalse(saved.show_last_move)
        after = repo.path.read_bytes()
        root.geometry("1120x900"); root.update()
        self.assertEqual(repo.path.read_bytes(), after)
        _, other = self.view()
        self.assertEqual(other.review_splitter.fraction, saved.review_moves_fraction)

    def test_scrolling_actual_click_and_navigation_after_drag(self):
        self.import_fixture(pgn(moves=LONG_MOVES))
        before = self.digest()
        with patch("chess.engine.SimpleEngine.popen_uci", side_effect=AssertionError("UI started engine")):
            root, view = self.view()
            split = view.review_splitter
            y = split.sash_coord(0)[1]
            split.event_generate("<ButtonPress-1>", x=20, y=y + 2)
            split.event_generate("<B1-Motion>", x=20, y=y + 35)
            split.event_generate("<ButtonRelease-1>", x=20, y=y + 35)
            root.update()
            moves = view.actual_moves
            moves.yview_moveto(0); root.update()
            first = moves.yview()
            moves.event_generate("<MouseWheel>", delta=-120); root.update()
            self.assertGreater(moves.yview()[0], first[0])
            moves.yview_moveto(0); root.update()
            index = moves.tag_ranges("step_5")[0]
            x, y, _, _ = moves.bbox(index)
            moves.event_generate("<Motion>", x=x + 2, y=y + 2)
            moves.event_generate("<Button-1>", x=x + 2, y=y + 2); root.update()
            self.assertEqual(view.current_step, 5)
            self.assertEqual(view.eval_timeline.selected_step, 5)
            self.assertEqual(view.board_widget.board.fen(), view.evaluation_values[5].position.fen)
            view.previous_move(); self.assertEqual(view.eval_timeline.selected_step, 4)
            view.next_move(); self.assertEqual(view.eval_timeline.selected_step, 5)
            view.go_to_start(); self.assertEqual(view.eval_timeline.selected_step, 0)
        self.assertEqual(before, self.digest())

    def test_setting_validation_and_identity_flags(self):
        with self.assertRaises(ValueError): ApplicationSettings(review_moves_fraction=0)
        with self.assertRaises(ValueError): ApplicationSettings(review_moves_fraction=float("nan"))
        definition = next(s for s in ApplicationSettings().schema() if s.setting_id == "review_moves_fraction")
        self.assertFalse(definition.affects_cache_identity)
        self.assertFalse(definition.affects_analysis_currentness)


class PartialCacheCompletionTests(TemporaryAnalysis):
    def test_five_of_34_fills_only_29_and_completed_rerun_is_byte_identical(self):
        self.import_fixture(pgn(moves=LONG_MOVES))
        generator = RecordedGenerator()
        with closing(self.connect()) as db:
            repo = EvaluationRepository(db)
            positions = repo.positions(1)
            self.assertEqual(len(positions), 34)
            cache = CandidateLineRepository(db)
            for position in positions[:5]:
                cache.put(generator.generate(position.fen, EvaluationSettings().generator))
            db.commit()
            initial = [tuple(r) for r in db.execute("select * from engine_candidate_line_cache order by line_set_id")]
            self.assertEqual(repo.readiness(1), (34, 29))
        scope = GameAnalysisScope(AnalysisScopeKind.SELECTED, (1,))
        service = GameAnalysisService(self.path, definitions=(), quality_settings=None)
        with patch("evaluation_service.CandidateLineGenerator", return_value=generator):
            first = service.run(scope)
        self.assertEqual((first.evaluation_cache_hits, first.evaluation_searches, first.evaluation_inserts, first.errors), (5, 29, 29, 0))
        with closing(self.connect()) as db:
            self.assertEqual(EvaluationRepository(db).readiness(1), (34, 0))
            rows = [tuple(r) for r in db.execute("select * from engine_candidate_line_cache order by line_set_id")]
            self.assertEqual(rows[:5], initial)
            self.assertEqual(len(rows), 34)
        before = self.digest()
        with patch("chess.engine.SimpleEngine.popen_uci", side_effect=AssertionError("Completed rerun")):
            second = service.run(scope)
        self.assertEqual((second.engine_searches, second.database_changes), (0, 0))
        self.assertEqual(before, self.digest())
        self.assertEqual(self.count("analysis_coverage"), 0)
        self.assertEqual(self.count("tactic_candidates"), 0)
        self.assert_integrity()
