"""Conservative context contracts; no analyzer reclassification or live data writes."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
import chess

from critical_moment_context import (ContextPolicy,ContextType,ImportanceBand,EvaluationEvidence,
                                    MomentEvidence,interpret_context,evaluation_swing)
from critical_moment_evidence import observe_material_loss
from critical_moment_repository import ContextEvaluationReader
from review_reason_labels import review_reason_label
from game_review_sets import load_review_sets, ReviewSet, ReviewSetEntry
from human_analyzer_reviews import audit_cases_for_game


class CriticalContextTests(unittest.TestCase):
    def base(self,**kwargs):
        return replace(MomentEvidence("fixture",2,"verified",("fixture:stored-proof",),tactic_verified=True),**kwargs)

    def test_real_neutral_early_tactic_requires_complete_proof_and_no_larger_outcome(self):
        e=self.base(retained_payoff_cp=0,proof_complete=True,larger_outcome_proven=False)
        self.assertEqual(interpret_context(e).primary_context,ContextType.LOW_GEOMETRY)
        self.assertEqual(interpret_context(e).importance_band,ImportanceBand.LOW)
        for change in ({"proof_complete":False},{"larger_outcome_proven":None},{"larger_outcome_proven":True},{"tactic_verified":None},{"fullmove_number":20}):
            self.assertNotEqual(interpret_context(replace(e,**change)).importance_band,ImportanceBand.LOW)

    def test_verified_gain_normal_high_and_unfavorable_final_evaluation(self):
        for gain,band in ((300,ImportanceBand.NORMAL),(500,ImportanceBand.HIGH)):
            e=self.base(retained_payoff_cp=gain,proof_complete=True,final_eval_range_cp=(-350,-250))
            before=asdict(e);context=interpret_context(e)
            self.assertEqual(context.primary_context,ContextType.TACTICAL)
            self.assertEqual(context.importance_band,band)
            self.assertEqual(context.final_position_label,"unfavorable")
            self.assertEqual(asdict(e),before)
            self.assertNotIn("winning",context.explanation_key)

    def test_major_queen_loss_uses_toolkit_legal_capture_fate_and_no_recapture(self):
        fen="7k/8/8/8/8/8/3q4/K2R4 w - - 0 10"
        observation=observe_material_loss(fen,("d1d2","h8h7","d2d3"))
        self.assertTrue(observation.supported)
        self.assertEqual(observation.loss_cp,900)
        e=self.base(observed_loss_cp=observation.loss_cp,observed_victim_type="queen",loss_supported=True,facts=observation.facts)
        context=interpret_context(e)
        self.assertEqual(context.primary_context,ContextType.MATERIAL_BLUNDER)
        self.assertEqual(context.importance_band,ImportanceBand.CRITICAL)
        self.assertIn(ContextType.TACTICAL,context.supporting_contexts)

    def test_available_recapture_or_incomplete_window_blocks_material_blunder(self):
        fen="7k/8/8/8/8/3r4/3q4/K2R4 w - - 0 10"
        self.assertFalse(observe_material_loss(fen,("d1d2","d3d2","a1b1")).supported)
        self.assertFalse(observe_material_loss("7k/8/8/8/8/8/3q4/K2R4 w - - 0 10",("d1d2",)).supported)

    def test_defense_and_forced_simplification_need_explicit_complete_proof(self):
        e=self.base(defensive_proof="mate_prevented",proof_complete=True,forced_simplification_proven=True)
        context=interpret_context(e)
        self.assertEqual(context.primary_context,ContextType.DEFENSIVE)
        self.assertEqual(context.importance_band,ImportanceBand.CRITICAL)
        self.assertIn(ContextType.SIMPLIFICATION,context.supporting_contexts)
        self.assertEqual(interpret_context(replace(e,proof_complete=False)).primary_context,ContextType.TACTICAL)
        self.assertEqual(interpret_context(replace(e,defensive_proof=None)).primary_context,ContextType.SIMPLIFICATION)

    def test_drawish_requires_all_near_equal_low_material_facts(self):
        e=self.base(final_eval_range_cp=(-50,80),total_material_cp=2000,rook_pawn_only=True)
        self.assertIn(ContextType.DRAWISH,interpret_context(e).supporting_contexts)
        for change in ({"final_eval_range_cp":None},{"final_eval_range_cp":(-222,-78)},{"total_material_cp":5000},{"rook_pawn_only":False}):
            self.assertNotIn(ContextType.DRAWISH,interpret_context(replace(e,**change)).supporting_contexts)

    def test_mate_terminal_ownership_and_draw_are_not_material_wins(self):
        e=self.base(terminal_state="checkmate",terminal_proven=True)
        self.assertEqual(interpret_context(e).importance_band,ImportanceBand.CRITICAL)
        self.assertEqual(interpret_context(replace(e,terminal_state="stalemate")).importance_band,ImportanceBand.NORMAL)
        self.assertNotEqual(interpret_context(replace(e,terminal_proven=False)).importance_band,ImportanceBand.CRITICAL)

    def test_missing_or_incompatible_evals_stay_unknown(self):
        before=EvaluationEvidence("before","request-a","cache:1",500)
        after=EvaluationEvidence("after","request-a","cache:2",-100)
        swing=evaluation_swing(before,after)
        self.assertEqual(swing.player_pov_delta,-600)
        self.assertTrue(swing.winning_to_nonwinning);self.assertTrue(swing.crossed_equal)
        self.assertIsNone(evaluation_swing(before,None).player_pov_delta)
        self.assertIsNone(evaluation_swing(before,replace(after,request_identity="other")).player_pov_delta)
        mate=replace(after,player_cp=None,mate_for_player=False)
        self.assertTrue(evaluation_swing(before,mate).mate_appeared)
        self.assertTrue(evaluation_swing(mate,before).mate_disappeared)
        self.assertIsNone(evaluation_swing(before,mate).player_pov_delta)

    def test_empty_or_ambiguous_score_cannot_fake_mate_disappearance(self):
        with self.assertRaises(ValueError): EvaluationEvidence("fen","request","cache")
        with self.assertRaises(ValueError): EvaluationEvidence("fen","request","cache",100,True)
        with self.assertRaises(ValueError): EvaluationEvidence("fen","request","cache",True)

    def test_typed_experimental_settings_and_result_identity(self):
        e=self.base(proof_complete=True,retained_payoff_cp=500)
        self.assertNotEqual(interpret_context(e).policy_identity,interpret_context(e,ContextPolicy(high_payoff_cp=600)).policy_identity)
        self.assertEqual(interpret_context(e,ContextPolicy(high_payoff_cp=600)).importance_band,ImportanceBand.NORMAL)
        with self.assertRaises(ValueError):ContextPolicy(early_fullmove=-1)
        self.assertTrue(all(not f.affects_raw_cache_identity for f in ContextPolicy().schema()))

    def test_core_imports_without_ui_engine_database_or_analyzers(self):
        code="""
import builtins
original=builtins.__import__
def guard(name,*args,**kwargs):
 if name.startswith(('tkinter','sqlite3','chess.engine','analyze_','analysis_backbone','fork_','pin_')): raise AssertionError(name)
 return original(name,*args,**kwargs)
builtins.__import__=guard
import critical_moment_context,critical_moment_evidence
"""
        run=subprocess.run([sys.executable,"-B","-c",code],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)


class ReviewLabelTests(unittest.TestCase):
    def test_codes_remain_stable_and_unknown_code_has_safe_wording(self):
        known=review_reason_label("terminal_mate")
        self.assertEqual(known.reason_code,"terminal_mate")
        self.assertEqual(known.reason_label,"Mate may be the main story here")
        unknown=review_reason_label("future_internal_code")
        self.assertEqual(unknown.reason_code,"future_internal_code")
        self.assertEqual(unknown.reason_label,"This audit case needs review")

    def test_packaged_human_labels_and_logger_preserve_codes_and_identity(self):
        wording=review_reason_label('selective_12_new_deferral')
        entry=ReviewSetEntry(21,wording.reason_code,wording.reason_label,
            'synthetic-review.json','synthetic:21:201',201,move_number=3,color='white',
            proposed_move='Nc7+',tactic_type='missed_fork',reason_explanation=wording.explanation)
        sets={'questionable':ReviewSet('questionable','Questionable','Synthetic review',(entry,))}
        self.assertEqual(entry.reason_code,"selective_12_new_deferral")
        self.assertIn("mate or draw",entry.reason_label)
        self.assertTrue(entry.reason_explanation)
        case=audit_cases_for_game(sets["questionable"],21)[0]
        self.assertEqual(case.review_reason_codes,("selective_12_new_deferral",))
        self.assertEqual(case.identity,replace(case,review_reason=("old wording",),review_reason_codes=()).identity)
        self.assertIn(entry.reason_label,sets["questionable"].game_label({"game_id":21}))


class EvaluationCacheTests(unittest.TestCase):
    def test_exact_profile_budget_pov_and_zero_writes(self):
        c=sqlite3.connect(":memory:");self.addCleanup(c.close)
        c.execute("CREATE TABLE engine_position_cache(cache_id,fen,engine_name,engine_version,analysis_profile,analysis_version,limit_type,limit_value,score_type,score_cp,mate,score_pov)")
        def add(cid,fen,score,pov,depth=18):
            c.execute("INSERT INTO engine_position_cache VALUES(?,?, 'Stockfish','18','tactic_verify_v1',1,'depth',?,'cp',?,NULL,?)",(cid,fen,depth,score,pov))
        add(1,"before",300,"white");add(2,"after",100,"black")
        before=c.total_changes
        reader=ContextEvaluationReader(c)
        a,b=reader.pair("before","after",chess.BLACK)
        self.assertEqual((a.player_cp,b.player_cp),(-300,100))
        self.assertEqual(evaluation_swing(a,b).player_pov_delta,400)
        self.assertEqual(c.total_changes,before)
        self.assertEqual(reader.pair("missing","after",chess.WHITE),(None,None))
        c.execute("DELETE FROM engine_position_cache WHERE cache_id=2")
        add(2,"after",100,"white",22)
        self.assertEqual(reader.pair("before","after",chess.WHITE),(None,None))

