from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import chess
from analysis_registry import ANALYZERS
from analysis_crawler import coverage_decision
from analysis_results import HeavyResult
from analyze_xrays import analyze_single_move
from board_analysis import new_slider_move_lines, direct_slider_lines
from heavy_adapters import dispatch_heavy
from heavy_repository import save_heavy_result
from tactical_material import MaterialPolicy
from tactical_opportunities import opportunity_to_dict, opportunity_from_dict
from tactical_opportunity_repository import read_candidate_opportunity
from xray_adapter import xray_adapter
from xray_geometry import xray_moves, xray_screener
from xray_scout import scout_xray, xray_scout_config
from tactical_fixtures import move_context, scripted_evidence
import test_heavy_services as fixtures

GOLD = json.loads((Path(__file__).parent / "fixtures/xray_v1_gold.json").read_text())

def case_named(name):
    return next(c for c in GOLD["cases"] if c["case_id"] == name)

def calculate(case):
    row = move_context(case["fen"], case["played_uci"])
    evaluate = (lambda f,p:{"score_type":"mate", "score_pov":"white", "mate":case["mate_score"]}) if case.get("mate_score") else scripted_evidence(row, case["prefix"])[0]
    return row, analyze_single_move(row, evaluate)

class XrayTests(unittest.TestCase):
    def test_gold_contracts_and_immutable_context(self):
        for case in GOLD["cases"]:
            with self.subTest(case=case["case_id"]):
                board = chess.Board(case["fen"]); snapshot = board.fen(), list(board.move_stack)
                self.assertTrue(board.is_valid())
                if case.get("geometry_only"):
                    self.assertEqual(any(c.move_uci == case["tactic_uci"] for c in xray_moves(board)), case["expected_created"])
                else:
                    row, result = calculate(case)
                    self.assertEqual(result.state, case["expected"], result.details)
                    if result.opportunity:
                        self.assertTrue(xray_screener(row))
                        self.assertEqual(result.opportunity.motifs[0].attribution, "supported")
                        self.assertGreaterEqual(result.opportunity.metadata["related_retained_material_cp"], 100)
                        self.assertTrue(result.opportunity.proof.settled_position_reached)
                self.assertEqual((board.fen(), board.move_stack), snapshot)

    def test_first_two_contacts_only(self):
        board = chess.Board(case_named("three_contacts_not_skipped")["fen"])
        board.push_uci("b1a1")
        line = next(l for l in direct_slider_lines(board, chess.A1) if l.step == (0,1))
        self.assertEqual((line.front.square,line.rear.square), (chess.A2,chess.A3))

    def test_played_existing_castling_and_promotion_edges(self):
        board = chess.Board(case_named("rook_exchanged_blocker_rear_queen")["fen"])
        self.assertNotIn("b1a1", {c.move_uci for c in xray_moves(board,"b1a1")})
        board.push_uci("b1a1"); board.turn = chess.WHITE
        self.assertNotIn("a1a2", {c.move_uci for c in xray_moves(board)})
        castle = chess.Board("4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1")
        self.assertFalse({c.move_uci for c in new_slider_move_lines(castle)} & {"e1g1","e1c1"})
        promotion = chess.Board("8/P6k/8/n7/8/q7/6PP/7K w - - 0 1")
        choices = {c.move_uci for c in xray_moves(promotion)}
        self.assertIn("a7a8r", choices); self.assertIn("a7a8q", choices)
        self.assertNotIn("a7a8n", choices)

    def test_immediate_delayed_and_both_colors(self):
        for name,timing,color in (("rook_exchanged_blocker_rear_queen","immediate","white"),
                                 ("removed_blocker_rear_rook","delayed","white"),
                                 ("black_exchanged_blocker","immediate","black")):
            _,result = calculate(case_named(name))
            self.assertEqual(result.opportunity.payoff_timing,timing)
            self.assertEqual(result.opportunity.proof.score_pov,color)

    def test_multiple_motifs_do_not_claim_pin_causality(self):
        _,result = calculate(case_named("removed_blocker_rear_rook"))
        motifs = {m.kind:m.attribution for m in result.opportunity.motifs}
        self.assertEqual(motifs,{"xray":"supported","removal_of_defender":"supported","pin":"context_only"})

    def test_exchange_losses_and_unrelated_gains(self):
        _,result = calculate(case_named("attacker_exchange_retained"))
        self.assertEqual(result.opportunity.metadata["related_retained_material_cp"],300)
        self.assertEqual(result.opportunity.proof.retained_material_gain_cp,300)
        self.assertTrue(result.opportunity.metadata["attacker_exchanged"])
        self.assertEqual(result.opportunity.presentation.level,"secondary_motif")
        for name in ("rear_recaptured","unrelated_gain","quiet_blocker_displacement","enemy_quiet_displacement","rear_escapes"):
            self.assertIsNone(calculate(case_named(name))[1].opportunity)

    def test_quick_deep_final_gates_and_missing_evidence(self):
        case = case_named("rook_exchanged_blocker_rear_queen")
        row = move_context(case["fen"],case["played_uci"])
        for stage,expected in (("quick","insufficient_quick_gain"),("deep","insufficient_deep_gain"),("final","continuation_not_sustained")):
            evaluate,fens = scripted_evidence(row,case["prefix"])
            def altered(fen,profile):
                raw = evaluate(fen,profile)
                if stage == "quick" and profile == "tactic_quick_v1": raw["score_cp"] = 0
                if stage == "deep" and profile == "tactic_verify_v1": raw["score_cp"] = 0
                if stage == "final" and fen in fens[5:]: raw["score_cp"] = -200
                return raw
            result = analyze_single_move(row,altered)
            self.assertEqual(result.state,"analyzed_no_hit")
            self.assertIn(expected,{r["reason"] for r in result.details["rejections"]})
        with self.assertRaises(ValueError):
            analyze_single_move(row,lambda f,p:{"score_type":"cp","score_cp":None,"score_pov":"white"})

    def test_mate_at_baseline_alternative_and_continuation_defers(self):
        case = case_named("rook_exchanged_blocker_rear_queen"); row = move_context(case["fen"],case["played_uci"])
        for start in (0,1,3):
            evaluate,fens = scripted_evidence(row,case["prefix"])
            def mate(fen,profile):
                return {"score_type":"mate","mate":3,"score_pov":"white"} if fen in fens[start:] else evaluate(fen,profile)
            result = analyze_single_move(row,mate)
            self.assertEqual(result.state,"analyzed_no_hit")
            self.assertEqual(result.details["ownership"],"mate_review")

    def test_scout_configuration_versions_and_boundary(self):
        for loss,expected in ((79,False),(80,True)):
            evidence=Mock(); evidence.for_player.side_effect=[{"score_type":"cp","score_cp":100},{"score_type":"cp","score_cp":100-loss}]
            self.assertEqual(scout_xray({},evidence).send_to_heavy,expected)
        evidence=Mock(); evidence.for_player.side_effect=[{"score_type":"mate","mate":-2},{"score_type":"cp","score_cp":0}]
        self.assertTrue(scout_xray({},evidence).send_to_heavy)
        config=json.loads(xray_scout_config()); self.assertEqual(config["thresholds"]["min_loss_cp"],80)
        self.assertEqual(config["profile"]["limit_value"],10000)
        d=ANALYZERS["missed_xray"]
        self.assertEqual((d.screener_version,d.scout_version,d.analyzer_version),("1","1","1"))

    def test_adapter_and_retryable_error(self):
        case=case_named("rook_exchanged_blocker_rear_queen"); row=move_context(case["fen"],case["played_uci"]); snapshot=dict(row)
        positions=Mock(); positions.position.side_effect=scripted_evidence(row,case["prefix"])[0]
        self.assertEqual(xray_adapter(row,positions).state,"candidate")
        self.assertEqual(row,snapshot)
        bad={**row,"color":"unknown"}; self.assertTrue(xray_screener(bad))
        result=dispatch_heavy(ANALYZERS["missed_xray"],Mock(),Mock(),bad,{},position_service=positions)
        self.assertEqual(result.state,"error")
        self.assertEqual({c.args[1] for c in positions.position.call_args_list},{"tactic_quick_v1","tactic_verify_v1"})

class XrayRepositoryTests(unittest.TestCase):
    setUp=fixtures.RepositoryTests.setUp

    def test_owner_appearing_after_preflight_is_rechecked_in_transaction(self):
        from solution_ownership import SolutionOwnershipService, find_solution_owner
        row,result=calculate(case_named("rook_exchanged_blocker_rear_queen"))
        solution=result.candidate["solution_move_uci"]
        owners=SolutionOwnershipService(self.c)
        self.assertIsNone(owners.owner(1,"missed_xray",solution))
        self.c.execute("INSERT INTO tactic_candidates(candidate_id,move_id,tactic_type,solution_move_uci,detector_version) VALUES(42,1,'missed_pin',?,2)",(solution,))
        self.c.execute("INSERT INTO training_attempts VALUES(1,42)"); self.c.commit()
        def transactional_lookup(connection,*args):
            self.assertTrue(connection.in_transaction)
            return find_solution_owner(connection,*args)
        with patch("heavy_repository.find_solution_owner",side_effect=transactional_lookup) as lookup:
            saved=save_heavy_result(self.c,ANALYZERS["missed_xray"],row,result,{(1,"missed_xray")},coverage_decision)
        lookup.assert_called_once()
        self.assertEqual(saved["state"],"analyzed_no_hit")
        self.assertEqual(self.c.execute("SELECT candidate_id FROM tactic_candidates").fetchall()[0][0],42)
        self.assertEqual(self.c.execute("SELECT candidate_id FROM training_attempts").fetchall()[0][0],42)

    def test_roundtrip_identity_training_and_idempotency(self):
        row,result=calculate(case_named("rook_exchanged_blocker_rear_queen")); d=ANALYZERS["missed_xray"]
        doc=opportunity_to_dict(result.opportunity)
        self.assertEqual(opportunity_to_dict(opportunity_from_dict(doc)),doc)
        self.c.execute("INSERT INTO tactic_candidates(candidate_id,move_id,tactic_type,detector_version) VALUES(42,1,'missed_xray',0)")
        self.c.execute("INSERT INTO training_attempts VALUES(1,42)"); self.c.commit()
        saved=save_heavy_result(self.c,d,row,result,{(1,"missed_xray")},coverage_decision)
        self.assertEqual(saved["candidate_id"],42)
        self.assertEqual(self.c.execute("SELECT candidate_id FROM training_attempts").fetchone()[0],42)
        self.c.execute("ALTER TABLE moves ADD COLUMN uci_played TEXT")
        self.c.execute("UPDATE moves SET uci_played=? WHERE move_id=1",(row["uci_played"],)); self.c.commit()
        self.assertEqual(read_candidate_opportunity(self.c,42).opportunity,result.opportunity)
        before=self.c.total_changes
        self.assertEqual(save_heavy_result(self.c,d,row,result,{(1,"missed_xray")},coverage_decision)["action"],"unchanged")
        self.assertEqual(self.c.total_changes,before)

    def test_other_motif_owner_preserved_without_duplicate(self):
        row,result=calculate(case_named("rook_exchanged_blocker_rear_queen")); d=ANALYZERS["missed_xray"]
        self.c.execute("INSERT INTO tactic_candidates(candidate_id,move_id,tactic_type,solution_move_uci,detector_version) VALUES(42,1,'missed_pin',?,2)",(result.candidate["solution_move_uci"],))
        self.c.execute("INSERT INTO training_attempts VALUES(1,42)"); self.c.commit()
        old=tuple(self.c.execute("SELECT * FROM tactic_candidates").fetchone())
        saved=save_heavy_result(self.c,d,row,result,{(1,"missed_xray")},coverage_decision)
        self.assertEqual(saved["state"],"analyzed_no_hit")
        self.assertEqual(tuple(self.c.execute("SELECT * FROM tactic_candidates").fetchone()),old)
        self.assertEqual(self.c.execute("SELECT count(*) FROM tactic_candidates").fetchone()[0],1)
        self.assertIn("existing_opportunity_owned",self.c.execute("SELECT details_json FROM analysis_coverage").fetchone()[0])
        self.assertFalse(self.c.execute("PRAGMA foreign_key_check").fetchall())

    def test_protected_rejection_scope_and_retryable_error(self):
        row,result=calculate(case_named("rook_exchanged_blocker_rear_queen")); d=ANALYZERS["missed_xray"]
        with self.assertRaises(ValueError): save_heavy_result(self.c,d,row,result,set(),coverage_decision)
        save_heavy_result(self.c,d,row,HeavyResult("error",details={"message":"fixture"}),{(1,"missed_xray")},coverage_decision)
        self.assertNotEqual(coverage_decision(d,dict(self.c.execute("SELECT * FROM analysis_coverage").fetchone())),"current")
        save_heavy_result(self.c,d,row,result,{(1,"missed_xray")},coverage_decision)
        self.c.execute("UPDATE analysis_coverage SET coverage_status='rejected',analyzer_version='0'"); self.c.commit()
        before=self.c.total_changes
        self.assertEqual(save_heavy_result(self.c,d,row,HeavyResult("analyzed_no_hit"),{(1,"missed_xray")},coverage_decision)["action"],"protected")
        self.assertEqual(self.c.total_changes,before)
