from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import sqlite3
from contextlib import closing

import chess
from analysis_crawler import ANALYZERS, coverage_decision
from analysis_planner import plan_negatives, preview_heavy_refresh
from analysis_engine import DryRunPositionAnalysisService
from analysis_results import HeavyResult
from analyze_pins_v2 import analyze_single_move
import analyze_pins as v1
import analyze_pins_v2 as v2
from pin_attribution import attribute_pin
from pin_opportunities import material_outcome
from pin_geometry import pinning_moves, PIECE_VALUES
from tactical_proof import ProofWindow, verify_bounded_line
from tactical_opportunities import Attribution, PayoffTiming, PresentationLevel
from test_heavy_services import move_row
import test_heavy_services as fixtures
from test_pins import ABSOLUTE_FEN, RELATIVE_FEN


def scripted(row, prefix, cp=300):
    """Legal deterministic fixture PV, padded with quiet moves; zero engines."""
    board = chess.Board(row["fen_before"])
    color = board.turn
    fens, sans, ucis = [board.fen()], [], []
    for san in prefix.split():
        move = board.parse_san(san)
        sans.append(board.san(move)); ucis.append(move.uci())
        board.push(move); fens.append(board.fen())
    seen = {" ".join(f.split()[:4]) for f in fens}
    while len(sans) < 20:
        legal = sorted(board.legal_moves, key=lambda m:(board.piece_type_at(m.from_square) != chess.PAWN, m.uci()))
        for move in legal:
            if board.is_capture(move) or board.gives_check(move) or move.promotion:
                continue
            test = board.copy(stack=False); test.push(move)
            key = " ".join(test.fen().split()[:4])
            if key not in seen:
                break
        else:
            raise AssertionError("Fixture lacks quiet continuation")
        sans.append(board.san(move)); ucis.append(move.uci())
        board.push(move); fens.append(board.fen()); seen.add(key)
    index = {fen:i for i,fen in enumerate(fens)}
    def evaluate(fen, profile):
        score = 0 if fen == row["fen_after"] else cp if fen in index else -1000
        i = index.get(fen, len(sans))
        return {"score_type":"cp", "score_cp":score if color else -score, "mate":None,
                "score_pov":"white", "principal_variation":" ".join(sans[i:]),
                "best_move_uci":ucis[i] if i < len(ucis) else None, "cache_id":None}
    return evaluate, fens


class PinV2Tests(unittest.TestCase):
    def test_unchanged_thresholds_and_separate_heavy_version(self):
        for name in ("QUICK_MIN_GAIN_CP", "QUICK_MAX_DROP_CP", "VERIFY_MIN_GAIN_CP", "VERIFY_MAX_DROP_CP", "MIN_RETAINED_MATERIAL_CP", "MIN_FINAL_EVAL_CP"):
            self.assertEqual(getattr(v1, name), getattr(v2, name))
        definition = ANALYZERS["missed_pin"]
        self.assertEqual((definition.screener_version, definition.scout_version, definition.analyzer_version), ("1", "1", "2"))
        self.assertEqual(v1.ANALYZER_VERSION, "1")

    def test_absolute_immediate_and_delayed_candidates_with_structured_proof(self):
        row = move_row(ABSOLUTE_FEN, "h1h2")
        for prefix, timing in (("Bb2 a6 Bxc3+ Kc5", PayoffTiming.IMMEDIATE),
                               ("Bb2 a6 Kh2 a5 Bxc3+ Kc5", PayoffTiming.DELAYED)):
            evaluate, _ = scripted(row, prefix)
            original = dict(row)
            result = analyze_single_move(row, evaluate)
            self.assertEqual(result.state, "candidate", result.details)
            self.assertEqual(row, original)
            self.assertEqual(result.opportunity.payoff_timing, timing)
            self.assertEqual(result.opportunity.proof.window_user_moves, 4)
            self.assertTrue(result.opportunity.proof.settled_position_reached)
            self.assertEqual(result.opportunity.primary_outcome.kind, "win_piece")
            self.assertEqual(result.opportunity.motifs[0].attribution, Attribution.SUPPORTED)

    def test_same_immediate_pin_for_black(self):
        board = chess.Board(ABSOLUTE_FEN).mirror()
        row = move_row(board.fen(), "h8h7")
        evaluate, _ = scripted(row, "Bb7 a3 Bxc6+ Kc4")
        result = analyze_single_move(row, evaluate)
        self.assertEqual(result.state, "candidate", result.details)
        self.assertEqual(result.opportunity.proof.score_pov, "black")

    def test_relative_target_exposure_supported(self):
        row = move_row(RELATIVE_FEN, "h1h2")
        evaluate, _ = scripted(row, "Bb2 Nb5 Bxd4 a6")
        result = analyze_single_move(row, evaluate)
        self.assertEqual(result.state, "candidate", result.details)
        self.assertEqual(result.opportunity.primary_outcome.kind, "win_queen")

    def test_pinner_advances_on_original_ray_then_takes_rear_target(self):
        row = move_row(RELATIVE_FEN, "h1h2")
        evaluate, _ = scripted(row, "Bb2 a6 Bxc3 a5 Bxd4")
        result = analyze_single_move(row, evaluate)
        self.assertEqual(result.state, "candidate", result.details)
        self.assertEqual(result.opportunity.metadata["related_retained_material_cp"], 1200)
        self.assertEqual(result.opportunity.primary_outcome.kind, "win_queen")


    def test_recapture_rejects_snapshot_gain(self):
        row = move_row(ABSOLUTE_FEN.replace("3P4", "8"), "h1h2")
        evaluate, _ = scripted(row, "Bb2 a6 Bxc3+ Kxc3")
        result = analyze_single_move(row, evaluate)
        self.assertEqual(result.state, "analyzed_no_hit")
        self.assertIn("material_not_retained", {r["reason"] for r in result.details["rejections"]})

    def test_score_floor_still_rejects_material_gain(self):
        row = move_row(ABSOLUTE_FEN, "h1h2")
        evaluate, fens = scripted(row, "Bb2 a6 Bxc3+ Kc5")
        def losing(fen, profile):
            raw = evaluate(fen, profile)
            if fen in fens[5:]:
                raw["score_cp"] = -200
            return raw
        result = analyze_single_move(row, losing)
        self.assertEqual(result.state, "analyzed_no_hit")
        self.assertIn("continuation_not_sustained", {r["reason"] for r in result.details["rejections"]})

    def test_missing_illegal_and_mate_evidence(self):
        row = move_row(ABSOLUTE_FEN, "h1h2")
        evaluate, fens = scripted(row, "Bb2 a6 Bxc3+ Kc5")
        for pv, raises in (("", False), ("Qa9", True)):
            def broken(fen, profile):
                raw = evaluate(fen, profile)
                if fen == fens[1]: raw["principal_variation"] = pv
                return raw
            if raises:
                with self.assertRaises(ValueError): analyze_single_move(row, broken)
            else:
                self.assertEqual(analyze_single_move(row, broken).state, "analyzed_no_hit")
        for mate in (2, -2):
            result = analyze_single_move(row, lambda fen, profile:{"score_pov":"white", "score_type":"mate", "mate":mate})
            self.assertEqual(result.state, "analyzed_no_hit")
            self.assertEqual(result.details["reason"], "mate_score_deferred")
        with self.assertRaises(ValueError):
            analyze_single_move(row, lambda fen, profile:{"score_pov":"white", "score_type":"cp", "score_cp":None})

    def test_four_move_bound_does_not_accept_late_payoff(self):
        row = move_row(ABSOLUTE_FEN, "h1h2")
        evaluate, fens = scripted(row, "Bb2 a6 Kh2 a5 Kh3 a4 Kh4 a3 Kh5 a2 Bxc3+ Kc5")
        result = analyze_single_move(row, evaluate)
        self.assertEqual(result.state, "analyzed_no_hit", result.details)


class PinV2RepositoryTests(unittest.TestCase):
    setUp = fixtures.RepositoryTests.setUp

    def test_v1_candidate_protected_and_v2_new_result_idempotent(self):
        definition = ANALYZERS["missed_pin"]
        row = move_row(ABSOLUTE_FEN, "h1h2")
        evaluate, _ = scripted(row, "Bb2 a6 Bxc3+ Kc5")
        result = analyze_single_move(row, evaluate)
        self.c.execute("INSERT INTO tactic_candidates(candidate_id,move_id,tactic_type,detector_version) VALUES(42,1,'missed_pin',1)")
        self.c.execute("INSERT INTO training_attempts VALUES(1,42)")
        self.c.execute("INSERT INTO analysis_coverage(move_id,analysis_type,coverage_status,analyzer_version,candidate_id) VALUES(1,'missed_pin','candidate','1',42)")
        self.c.commit()
        allowed = {(1, "missed_pin")}
        changes = self.c.total_changes
        saved = fixtures.save_heavy_result(self.c, definition, row, result, allowed, coverage_decision)
        self.assertEqual(saved["action"], "protected")
        self.assertEqual(self.c.total_changes, changes)
        saved = fixtures.save_heavy_result(self.c, definition, row, result, allowed, coverage_decision, reconcile_stale=True)
        self.assertEqual(saved["candidate_id"], 42)
        self.assertEqual(self.c.execute("SELECT candidate_id FROM training_attempts").fetchone()[0], 42)
        changes = self.c.total_changes
        self.assertEqual(fixtures.save_heavy_result(self.c, definition, row, result, allowed, coverage_decision)["action"], "unchanged")
        self.assertEqual(changes, self.c.total_changes)

    def test_planner_does_not_automatically_rerun_stale_v1(self):
        definition = ANALYZERS["missed_pin"]
        for status in ("candidate", "rejected", "analyzed_no_hit"):
            self.c.execute("DELETE FROM analysis_coverage")
            self.c.execute("INSERT INTO analysis_coverage(move_id,analysis_type,coverage_status,analyzer_version) VALUES(1,'missed_pin',?,'1')", (status,))
            self.c.commit()
            evidence = type("Evidence", (), {"stats":Counter()})()
            _, report = plan_negatives(self.c, [definition], [move_row()], evidence, coverage_decision)
            self.assertEqual(report["pending_heavy_checks"], [])
            self.assertEqual(report["analyzers"]["missed_pin"]["protected"], 1)

    def test_read_only_refresh_proposal_excludes_candidates_and_is_not_dispatch(self):
        definition = ANALYZERS["missed_pin"]
        self.c.execute("INSERT INTO analysis_coverage(move_id,analysis_type,coverage_status,screener_version,scout_version,scout_config,analyzer_version) VALUES(1,'missed_pin','analyzed_no_hit','1','1',?,'1')", (definition.scout_config(),))
        self.c.commit()
        evidence = type("Evidence", (), {"stats":Counter()})()
        changes = self.c.total_changes
        report = preview_heavy_refresh(self.c, [definition], [move_row()], evidence, coverage_decision)
        self.assertEqual(report["proposed_heavy_by_tactic"], {"missed_pin":1})
        self.assertEqual(report["pending_heavy_checks"], [])
        self.assertEqual(self.c.total_changes, changes)
        self.c.execute("INSERT INTO tactic_candidates(candidate_id,move_id,tactic_type) VALUES(42,1,'missed_pin')")
        self.c.commit()
        report = preview_heavy_refresh(self.c, [definition], [move_row()], evidence, coverage_decision)
        self.assertEqual(report["proposed_heavy_checks"], [])

    def test_dry_service_reuses_live_cache_and_keeps_scratch_ids_non_durable(self):
        live = Mock()
        live.execute.return_value.fetchone.return_value = ("CREATE TABLE engine_position_cache(id INTEGER)",)
        raw = {"cache_id":42, "cache_hit":True, "score_pov":"white", "score_type":"cp", "score_cp":200}
        with closing(sqlite3.connect(":memory:")) as scratch:
            stats = Counter()
            service = DryRunPositionAnalysisService(live, None, stats, scratch)
            with patch("analysis_engine.get_cached_position", return_value=raw), patch("analysis_engine.get_or_analyze") as search:
                self.assertEqual(service.position("fen", "tactic_verify_v1")["cache_id"], 42)
                search.assert_not_called()
            with patch("analysis_engine.get_cached_position", return_value=None), patch("analysis_engine.get_or_analyze", return_value={**raw,"cache_hit":False}):
                self.assertIsNone(service.position("other", "tactic_verify_v1")["cache_id"])
            self.assertEqual(stats["engine_searches"], 1)
            self.assertEqual(stats["live_hits"], 1)


if __name__ == "__main__":
    unittest.main()
