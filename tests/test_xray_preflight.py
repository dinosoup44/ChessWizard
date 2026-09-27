"""Existing-evidence contracts use synthetic cache data; never launch an engine."""
from dataclasses import replace
import sqlite3
import unittest
from unittest.mock import patch
import chess
import engine_cache
from analysis_preflight import PreflightContext, apply_existing_preflight
from analysis_registry import ANALYZERS
from existing_position_evidence import ExistingPositionEvidence
from solution_ownership import SolutionOwnershipService
from xray_geometry import xray_moves
from xray_preflight import preflight_existing_evidence
from tactical_fixtures import move_context, scripted_evidence
from test_xrays import GOLD, case_named


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE engine_position_cache (
              cache_id INTEGER PRIMARY KEY, fen TEXT, engine_name TEXT, engine_version TEXT,
              analysis_profile TEXT, analysis_version INTEGER, limit_type TEXT, limit_value INTEGER,
              side_to_move TEXT, score_type TEXT, score_cp INTEGER, mate INTEGER,
              best_move_uci TEXT, best_move_san TEXT, principal_variation TEXT,
              depth INTEGER, seldepth INTEGER, nodes INTEGER, time_ms REAL, analyzed_at TEXT, score_pov TEXT);
            CREATE TABLE tactic_candidates (candidate_id INTEGER PRIMARY KEY, move_id INTEGER,
              tactic_type TEXT, solution_move_uci TEXT, UNIQUE(move_id,tactic_type));
        """)
        case = case_named("queen_exchanged_blocker")
        self.row = move_context(case["fen"],case["played_uci"])
        self.context = PreflightContext("missed_xray","1",ExistingPositionEvidence(self.db),SolutionOwnershipService(self.db))
        self.choices = tuple(xray_moves(chess.Board(self.row["fen_before"]),self.row["uci_played"]))
        self.assertGreater(len(self.choices),1)
        for target in ("engine_cache.get_or_analyze", "chess.engine.SimpleEngine.popen_uci"):
            blocker = patch(target,side_effect=AssertionError("Preflight must never request an engine"))
            blocker.start(); self.addCleanup(blocker.stop)

    def cache(self, fen, cp=0, **overrides):
        row = dict(fen=fen,engine_name=engine_cache.ENGINE_NAME,engine_version=engine_cache.ENGINE_VERSION,
                   analysis_profile="tactic_quick_v1",**engine_cache.get_profile("tactic_quick_v1"),
                   side_to_move="white" if chess.Board(fen).turn else "black",score_type="cp",score_cp=cp,
                   mate=None,score_pov="white")
        row.update(overrides)
        self.db.execute("DELETE FROM engine_position_cache WHERE fen=?",(fen,))
        self.db.execute(f"INSERT INTO engine_position_cache ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",tuple(row.values()))

    def all_fail(self):
        self.cache(self.row["fen_before"],300)
        self.cache(self.row["fen_after"],0)
        for choice in self.choices:
            self.cache(choice.fen_after,-1000)

    def run_preflight(self, row=None, context=None):
        before = self.db.total_changes,tuple(self.db.iterdump())
        self.db.execute("PRAGMA query_only=ON")
        try:
            result = preflight_existing_evidence(row or self.row,context or self.context)
        finally:
            self.db.execute("PRAGMA query_only=OFF")
        self.assertEqual(before,(self.db.total_changes,tuple(self.db.iterdump())))
        return result

    def own(self, choices):
        for i,choice in enumerate(choices):
            self.db.execute("INSERT INTO tactic_candidates(move_id,tactic_type,solution_move_uci) VALUES (1,?,?)",
                            (f"other_specialist_{i}",choice.move_uci))

    def test_all_cached_fail_and_one_passes(self):
        self.all_fail()
        result = self.run_preflight()
        self.assertEqual(result.disposition,"cached_quick_rejected")
        self.assertTrue(all(e["cache_id"] for e in result.provenance["evidence"]))
        self.cache(self.choices[0].fen_after,300)
        self.assertEqual(self.run_preflight().disposition,"heavy_required")

    def test_quick_gate_boundary_and_policy_reconsideration(self):
        self.all_fail()
        self.cache(self.choices[0].fen_after,120)
        self.assertEqual(self.run_preflight().disposition,"heavy_required")
        from xray_preflight import POLICY
        with patch("xray_preflight.POLICY",replace(POLICY,quick_gain_cp=121)):
            self.assertEqual(self.run_preflight().disposition,"cached_quick_rejected")
        self.assertEqual(self.run_preflight().disposition,"heavy_required")

    def test_missing_stale_wrong_profile_and_incompatible_evidence_keep_work(self):
        cases = [None,{"analysis_version":0},{"analysis_profile":"tactic_scout_v1"},
                 {"limit_value":9},{"engine_version":"old"},{"score_pov":"black"},
                 {"score_cp":None},{"side_to_move":"invalid"}]
        for override in cases:
            with self.subTest(override=override):
                self.all_fail()
                fen = self.choices[0].fen_after
                if override is None:
                    self.db.execute("DELETE FROM engine_position_cache WHERE fen=?",(fen,))
                else:
                    self.cache(fen,-1000,**override)
                result = self.run_preflight()
                self.assertEqual(result.disposition,"heavy_required")
                self.assertTrue(result.provenance["missing_or_incompatible_evidence"])

    def test_missing_baseline_and_changed_configuration_keep_work(self):
        self.all_fail()
        for key in ("fen_before","fen_after"):
            self.all_fail()
            self.db.execute("DELETE FROM engine_position_cache WHERE fen=?",(self.row[key],))
            self.assertEqual(self.run_preflight().disposition,"heavy_required")
        self.all_fail()
        with patch.dict("existing_position_evidence.SCOUT_ENGINE_OPTIONS",{"Threads":2}):
            self.assertEqual(self.run_preflight().disposition,"heavy_required")
        with patch.dict(engine_cache.PROFILES["tactic_quick_v1"],{"analysis_version":2}):
            self.assertEqual(self.run_preflight().disposition,"heavy_required")
        self.assertEqual(self.run_preflight(context=replace(self.context,analyzer_version="2")).disposition,"heavy_required")

    def test_mate_baseline_only_not_alternative_or_scout(self):
        self.all_fail()
        self.cache(self.choices[0].fen_after,score_type="mate",score_cp=None,mate=3)
        self.assertEqual(self.run_preflight().disposition,"heavy_required")
        self.cache(self.row["fen_before"],score_type="mate",score_cp=None,mate=-3)
        self.assertEqual(self.run_preflight().disposition,"mate_deferred")
        self.cache(self.row["fen_before"],analysis_profile="tactic_scout_v1",score_type="mate",score_cp=None,mate=3)
        self.assertEqual(self.run_preflight().disposition,"heavy_required")

    def test_played_checkmate_only_stalemate_and_draw_survive(self):
        fen = "7k/5Q2/6K1/8/8/8/8/8 w - - 0 1"
        row = move_context(fen,"f7g7")
        self.assertTrue(chess.Board(row["fen_after"]).is_checkmate())
        with patch.object(self.context.positions,"position",side_effect=AssertionError("No evidence needed")):
            self.assertEqual(self.run_preflight(row).disposition,"played_checkmate")
        row = move_context(fen,"f7e6")
        self.assertTrue(chess.Board(row["fen_after"]).is_stalemate())
        self.assertEqual(self.run_preflight(row).disposition,"heavy_required")
        row = move_context("7k/8/6K1/8/8/8/8/8 w - - 0 1","g6f6")
        self.assertTrue(chess.Board(row["fen_after"]).is_insufficient_material())
        self.assertEqual(self.run_preflight(row).disposition,"heavy_required")

    def test_all_owned_some_owned_and_ownership_reconsideration(self):
        self.own(self.choices[:1])
        self.assertEqual(self.run_preflight().disposition,"heavy_required")
        self.db.execute("DELETE FROM tactic_candidates")
        self.own(self.choices)
        result = self.run_preflight()
        self.assertEqual(result.disposition,"already_owned")
        self.assertTrue(all(c["owner"]["candidate_id"] for c in result.provenance["alternatives"]))
        self.db.execute("DELETE FROM tactic_candidates WHERE solution_move_uci=?",(self.choices[0].move_uci,))
        self.assertEqual(self.run_preflight().disposition,"heavy_required")

    def test_mixed_quick_failure_and_ownership_is_not_an_approved_removal(self):
        self.all_fail()
        self.db.execute("DELETE FROM engine_position_cache WHERE fen=?",(self.choices[0].fen_after,))
        self.own(self.choices[:1])
        self.assertEqual(self.run_preflight().disposition,"heavy_required")

    def test_canonical_self_owner_is_excluded(self):
        self.db.execute("INSERT INTO tactic_candidates VALUES (10,1,'missed_xray',?)",(self.choices[0].move_uci,))
        self.assertIsNone(self.context.ownership.owner(1,"missed_xray",self.choices[0].move_uci))

    def test_all_eight_positive_gold_cases_survive(self):
        cases = [c for c in GOLD["cases"] if c.get("expected")=="candidate"]
        self.assertEqual(len(cases),8)
        for case in cases:
            with self.subTest(case=case["case_id"]):
                self.db.execute("DELETE FROM engine_position_cache")
                row = move_context(case["fen"],case["played_uci"])
                evaluate,_ = scripted_evidence(row,case["prefix"])
                fens = [row["fen_before"],row["fen_after"]] + [c.fen_after for c in xray_moves(chess.Board(row["fen_before"]),row["uci_played"])]
                for fen in fens:
                    self.cache(fen,evaluate(fen,"tactic_quick_v1")["score_cp"])
                self.assertEqual(self.run_preflight(row).disposition,"heavy_required")

    def test_registry_opt_in_and_generic_plan_no_writes(self):
        self.assertEqual([n for n,d in ANALYZERS.items() if d.preflight_existing_evidence],["missed_xray"])
        pending = [{"move_id":1,"analysis_type":"missed_xray"},{"move_id":1,"analysis_type":"missed_pin"}]
        plan = {"pending_heavy_checks":pending,"errors":[]}
        self.assertIs(apply_existing_preflight(None,[ANALYZERS["missed_pin"]],[],plan),plan)
        self.all_fail()
        before = self.db.total_changes,tuple(self.db.iterdump())
        self.db.execute("PRAGMA query_only=ON")
        result = apply_existing_preflight(self.db,list(ANALYZERS.values()),[self.row],plan)
        self.assertEqual(result["pending_heavy_checks"],pending[1:])
        self.assertEqual(result["pending_before_preflight"],pending)
        self.assertEqual(result["existing_evidence_preflight"]["engine_searches"],0)
        self.assertEqual(before,(self.db.total_changes,tuple(self.db.iterdump())))

    def test_preflight_failure_keeps_pending(self):
        def broken(row,context):
            raise ValueError("Unavailable evidence")
        definition = replace(ANALYZERS["missed_xray"],preflight_existing_evidence=broken)
        plan = {"pending_heavy_checks":[{"move_id":1,"analysis_type":"missed_xray"}]}
        result = apply_existing_preflight(self.db,[definition],[self.row],plan)
        self.assertEqual(result["pending_heavy_checks"],plan["pending_heavy_checks"])
        self.assertEqual(result["existing_evidence_preflight"]["analyzers"]["missed_xray"]["errors"],1)
