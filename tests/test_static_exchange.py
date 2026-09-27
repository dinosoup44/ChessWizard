"""Shared SEE V1 contracts; supplied legal lines are the independent material oracle."""
from dataclasses import FrozenInstanceError, asdict, replace
import ast
import subprocess
import sys
import json
from pathlib import Path
import unittest
import chess
from analysis_settings import MaterialValues
from board_analysis import capture_square
from position_range_evidence import LegalReplay
from board_analysis.static_exchange import (
    StaticExchangePolicy as ExchangePolicy, evaluate_static_exchange as see_exchange,
    ExchangeCompleteness, ExchangeUncertainty, ExchangeVerdict,
)

CASES = json.loads((Path(__file__).parent / "fixtures/see_synthetic.json").read_text())
BY_NAME = {c["name"]: c for c in CASES}


def result(name, **kwargs):
    c = BY_NAME[name]
    return see_exchange(c["fen"], c["move"], **kwargs)


class StaticExchangeTests(unittest.TestCase):
    def test_hand_authored_reference_lines_and_estimates(self):
        for c in CASES:
            with self.subTest(case=c["name"]):
                r = see_exchange(c["fen"], c["move"])
                replay = LegalReplay(c["fen"], c["reference_line"])
                victim = capture_square(chess.Board(c["fen"]), chess.Move.from_uci(c["move"]))
                e = replay.evidence(track_squares=(victim,))
                d = e.material_transition.delta
                self.assertEqual(d.for_color(r.initiating_side)-d.for_color(not r.initiating_side), c["expected_reference_cp"])
                self.assertEqual(r.estimated_net_cp, c["expected_see_cp"])
                self.assertFalse(e.get_piece_fate(replay.identity_at_start(victim)).alive)
                self.assertIsNotNone(e.attacker_survival)
                replay.relevant_recaptures(ply=1, track_squares=(victim,))
                replay.position_evidence(ply=1, squares=(r.target_square,))

    def test_every_chain_step_is_legal_and_ledger_matches_toolkit(self):
        for c in CASES:
            with self.subTest(case=c["name"]):
                r = see_exchange(c["fen"], c["move"])
                line = [s.move_uci for s in r.exchange_sequence]
                for count, step in enumerate(r.exchange_sequence, 1):
                    replay = LegalReplay(c["fen"], line[:count])
                    d = replay.evidence().material_transition.delta
                    self.assertEqual(step.cumulative_net_cp, d.for_color(r.initiating_side)-d.for_color(not r.initiating_side))
                self.assertEqual(r.provisional_net_cp, r.exchange_sequence[r.selected_prefix_plies-1].cumulative_net_cp)

    def test_determinism_source_unchanged_and_immutable(self):
        for c in CASES:
            board = chess.Board(c["fen"])
            before = (board.fen(), list(board.move_stack))
            r = see_exchange(board, c["move"])
            self.assertEqual(r, see_exchange(board, c["move"]))
            self.assertEqual(before, (board.fen(), list(board.move_stack)))
            with self.assertRaises(FrozenInstanceError):
                r.estimated_net_cp = 10000

    def test_pinned_and_king_recapturers_excluded(self):
        for name in ("absolute pinned pawn", "absolute pinned knight", "illegal king recapture"):
            r = result(name)
            self.assertEqual(len(r.exchange_sequence), 1)
            self.assertTrue(any("excluded" in n for n in r.pin_xray_notes))
        self.assertEqual(len(result("legal king recapture").exchange_sequence), 2)
        self.assertEqual(len(result("relative pin permits capture").exchange_sequence), 2)

    def test_xray_recomputed_after_occupancy_change(self):
        for name in ("rook xray revealed", "bishop discovery", "en passant occupancy xray"):
            r = result(name)
            self.assertTrue(any("newly available" in n for n in r.pin_xray_notes))
            self.assertEqual(len(r.exchange_sequence), 3)

    def test_lva_ties_and_optional_stop(self):
        self.assertEqual(result("same-value defenders").exchange_sequence[1].move_uci, "d6e5")
        r = result("pawn minor rook chain")
        self.assertEqual(len(r.exchange_sequence), 5)
        self.assertEqual(r.selected_prefix_plies, 1)
        self.assertEqual(r.exchange_sequence[-1].cumulative_net_cp, 500)
        self.assertEqual(result("different-cost recapturers").exchange_sequence[1].move_uci, "f6e5")

    def test_promotions_and_configured_values(self):
        self.assertTrue(result("promotion capture").promotion_notes)
        self.assertEqual(result("recapture promotion").exchange_sequence[-1].move_uci, "b2a1q")
        self.assertEqual(result("minor survives", material=MaterialValues(pawn=120)).estimated_net_cp, 120)
        self.assertEqual(result("rook for minor", material=MaterialValues(rook=550)).estimated_net_cp, -250)

    def test_check_terminal_and_cap_are_incomplete(self):
        for name in ("check needs off-square evasion", "capture checkmate"):
            self.assertIsNone(result(name).estimated_net_cp)
        r = result("pawn trade", policy=ExchangePolicy(max_plies=1))
        self.assertIsNone(r.estimated_net_cp)
        self.assertIn("exchange_cap_reached", r.legality_notes)
        with self.assertRaises(ValueError):
            ExchangePolicy(max_plies=0)

    def test_limitations_never_authorize_rejection(self):
        for c in CASES:
            r = see_exchange(c["fen"], c["move"])
            self.assertFalse(r.safe_for_hard_rejection)
            self.assertIn("single_square_only", r.limitations)
        r = result("favorable local capture loses mate")
        c = BY_NAME["favorable local capture loses mate"]
        self.assertGreater(r.estimated_net_cp, 0)
        self.assertTrue(LegalReplay(c["fen"], c["reference_line"]).board_at().is_checkmate())
        self.assertLess(result("compensation away from target").estimated_net_cp, 0)
        c = BY_NAME["intermezzo before recapture"]
        self.assertTrue(LegalReplay(c["fen"], c["reference_line"]).board_at(2).is_check())

    def test_illegal_ep_exposing_king_and_non_capture_rejected(self):
        with self.assertRaises(ValueError):
            see_exchange("7k/8/8/r4pPK/8/8/8/8 w - f6 0 1", "g5f6")
        with self.assertRaises(ValueError):
            see_exchange(chess.Board(), "e2e4")
        with self.assertRaises(ValueError):
            see_exchange("8/8/8/8/8/8/8/8 w - - 0 1", "a1a2")


    def test_zero_and_unknown_have_distinct_typed_semantics(self):
        neutral = result("pawn trade")
        unknown = result("check needs off-square evasion")
        self.assertEqual(neutral.estimated_net_cp, 0)
        self.assertIs(neutral.verdict, ExchangeVerdict.NEUTRAL)
        self.assertIs(neutral.completeness, ExchangeCompleteness.COMPLETE_LVA_CHAIN_ONLY)
        self.assertEqual(neutral.uncertainty_reasons, ())
        self.assertIsNone(unknown.estimated_net_cp)
        self.assertIs(unknown.verdict, ExchangeVerdict.UNKNOWN)
        self.assertIn(ExchangeUncertainty.OFF_SQUARE_CHECK_EVASION_REQUIRED, unknown.uncertainty_reasons)
        self.assertIn(ExchangeUncertainty.TERMINAL_MATERIAL_NOT_GAME_OUTCOME, result("capture checkmate").uncertainty_reasons)
        capped = result("pawn trade", policy=ExchangePolicy(max_plies=1))
        self.assertIn(ExchangeUncertainty.EXCHANGE_BOUND_EXHAUSTED, capped.uncertainty_reasons)
        with self.assertRaises(ValueError):
            replace(unknown, estimated_net_cp=0)
        with self.assertRaises(ValueError):
            replace(neutral, estimated_net_cp=None)

    def test_terminal_source_does_not_become_numeric_after_clock_reset(self):
        c = BY_NAME["pawn trade"]
        board = chess.Board(c["fen"])
        board.halfmove_clock = 150
        self.assertTrue(board.is_seventyfive_moves())
        r = see_exchange(board, c["move"])
        self.assertIsNone(r.estimated_net_cp)
        self.assertIn(ExchangeUncertainty.TERMINAL_MATERIAL_NOT_GAME_OUTCOME, r.uncertainty_reasons)
        self.assertEqual(board.halfmove_clock, 150)

    def test_advisory_flags_cannot_be_constructor_or_policy_options(self):
        r = result("minor survives")
        self.assertIs(r.authoritative_for_tactic_truth, False)
        self.assertIs(r.safe_for_hard_rejection, False)
        for flag in ("authoritative_for_tactic_truth", "safe_for_hard_rejection"):
            with self.assertRaises((TypeError, ValueError)):
                replace(r, **{flag: True})
            with self.assertRaises(TypeError):
                ExchangePolicy(**{flag: True})
        with self.assertRaises(FrozenInstanceError):
            r.authoritative_for_tactic_truth = True

    def test_source_history_is_preserved_and_invalid_types_are_explicit(self):
        c = BY_NAME["pawn trade"]
        board = chess.Board(c["fen"])
        board.push_uci(c["move"])
        before = (board.fen(), list(board.move_stack))
        see_exchange(board, "f6e5")
        self.assertEqual(before, (board.fen(), board.move_stack))
        with self.assertRaises(TypeError):
            see_exchange(None, "a1a2")
        with self.assertRaises(TypeError):
            see_exchange(c["fen"], c["move"], policy={"max_plies": 32})
        with self.assertRaises(ValueError):
            see_exchange(chess.Board(c["fen"], chess960=True), c["move"])

    def test_existing_production_modules_do_not_consume_see(self):
        root = Path(__file__).resolve().parents[1]
        for path in root.glob("*.py"):
            if path.name == "see_exchange_prototype.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                names = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                         [n.name for n in node.names] if isinstance(node, ast.Import) else [])
                self.assertFalse(any("static_exchange" in n or n == "see_exchange_prototype" for n in names), path.name)
        exports = (root / "board_analysis/__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("static_exchange", exports)

    def test_cold_import_and_call_rejects_forbidden_dependencies(self):
        root = str(Path(__file__).resolve().parents[1])
        c = BY_NAME["pawn trade"]
        code = """
import builtins, sys
sys.path.insert(0, sys.argv[1])
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.startswith(('sqlite3', 'tkinter', 'subprocess', 'chess.engine', 'analyze_', 'engine_', 'tactic_', 'major_material_blunder')):
        raise AssertionError('Forbidden core dependency: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from board_analysis.static_exchange import evaluate_static_exchange
r = evaluate_static_exchange(sys.argv[2], sys.argv[3])
assert r.estimated_net_cp == 0 and not r.authoritative_for_tactic_truth
"""
        run = subprocess.run([sys.executable, "-I", "-B", "-c", code, root, c["fen"], c["move"]],
                             capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == "__main__":
    unittest.main()
