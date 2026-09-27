from collections import Counter
from dataclasses import replace
import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import chess
from analyze_forks_v3 import analyze_existing_candidate,evaluation_acceptance,PIECE_VALUES,interpret_proof
from board_analysis import attacked_pieces,material_balance,capture_square
from tactical_target_proof import trace_target_settlement
from tactical_proof import BoundedProof,ProofStep,ProofWindow
from candidate_verification import existing_candidates,verify_candidates
from candidate_verification_registry import CANDIDATE_VERIFIERS
from candidate_reconciliation_repository import reconcile_candidate
from analysis_results import HeavyResult
from tactical_opportunities import TacticalOpportunity,TacticalOutcome,TacticalMotif
from feedback import FeedbackContextBuilder,FeedbackGenerator
from test_heavy_services import move_row,candidate_payload
import test_heavy_services as fixtures
from tests.support.fork_positions import candidate, proof_for


class ForkV3Tests(unittest.TestCase):
    def test_fixed_stored_move_not_engine_number_one(self):
        row=candidate();after=chess.Board(row["fen_before"]);after.push_uci(row["solution_move_uci"])
        proof=proof_for(after,"Kf7 Nxa8")
        def evaluate(fen,profile):
            return dict(score_pov="white",score_type="cp",score_cp=-200 if fen==row["fen_after"] else 400,
                        mate=None,best_move_uci="e1d1",principal_variation="Kd1",cache_id=1)
        with patch("analyze_forks_v3.verify_bounded_line",return_value=proof):
            result=analyze_existing_candidate(row,evaluate)
        self.assertEqual(result.state,"candidate")
        self.assertEqual(result.candidate["solution_move_uci"],"d5c7")
        self.assertEqual(result.opportunity.primary_outcome.kind,"win_rook")
        self.assertEqual(result.details["realizable_targets"][0]["square"],"a8")
        feedback=FeedbackGenerator().generate(FeedbackContextBuilder().build({**row,**result.candidate},result.opportunity))
        self.assertIn("wins the rook",feedback.explanation)
        self.assertNotIn("winning both",feedback.explanation)

    def test_evaluation_alternative_rules_and_bad_counterplay(self):
        self.assertEqual(evaluation_acceptance(1000,400,600,500),"preserves_winning_position")
        self.assertEqual(evaluation_acceptance(0,-400,0,0),"meaningful_improvement")
        self.assertEqual(evaluation_acceptance(100,50,80,60),"preserves_acceptable_position")
        self.assertIsNone(evaluation_acceptance(500,0,-200,-200))
        self.assertIsNone(evaluation_acceptance(700,0,100,100))

    def test_scope_guards_no_discovery_and_rejected_protection(self):
        for change in ({"candidate_id":None},{"candidate_status":"rejected"},{"detector_version":999}):
            evaluator=Mock()
            with self.assertRaises(ValueError): analyze_existing_candidate({**candidate(),**change},evaluator)
            evaluator.assert_not_called()
        evaluator=Mock();r=candidate(chess.STARTING_FEN,"e2e4","d2d4")
        self.assertEqual(analyze_existing_candidate(r,evaluator).details["reason"],"stored_move_no_longer_has_fork_geometry")
        evaluator.assert_not_called()

    def test_unsettled_and_mate_proofs_are_ambiguous_not_rejections(self):
        row=candidate();after=chess.Board(row["fen_before"]);after.push_uci(row["solution_move_uci"])
        raw=dict(score_pov="white",score_type="cp",score_cp=400,mate=None,cache_id=None)
        for state in ("unsettled","mate","missing_continuation"):
            with patch("analyze_forks_v3.verify_bounded_line",return_value=proof_for(after,"Kf7",state)):
                result=analyze_existing_candidate(row,lambda *args:raw)
                self.assertEqual(result.state,"error")
                self.assertEqual(result.details["classification"],"ambiguous")


    def test_opponent_can_countercheck_instead_of_saving_target(self):
        after=chess.Board("r6k/8/8/8/8/1Q6/8/4K3 b - - 0 1")
        targets=attacked_pieces(after,chess.B3,target_color=chess.BLACK)
        proof=proof_for(after,"Ra1+ Kf2")
        result=trace_target_settlement(after,chess.B3,targets,proof,PIECE_VALUES)
        self.assertTrue(result.events[0]["gives_check"])
        self.assertTrue(result.events[1]["answers_check"])

    def test_both_target_identities_follow_movement(self):
        after=chess.Board("r5k1/8/2n5/1Q6/8/8/8/4K3 b - - 0 1")
        targets=attacked_pieces(after,chess.B5,target_color=chess.BLACK)
        # Explicit target set exercises accounting; geometry policy is separate.
        from board_analysis import PieceRef
        targets=(PieceRef(chess.A8,chess.ROOK,chess.BLACK),PieceRef(chess.C6,chess.KNIGHT,chess.BLACK))
        proof=proof_for(after,"Kh7 Qxc6 Kh8 Qxa8+")
        result=trace_target_settlement(after,chess.B5,targets,proof,PIECE_VALUES)
        self.assertEqual(set(result.captured_targets),{chess.C6,chess.A8})

    def test_target_countercaptures_are_not_credited_twice(self):
        from board_analysis import PieceRef
        after=chess.Board("r6k/8/8/8/8/1Q6/8/R3K3 b - - 0 1")
        targets=(PieceRef(chess.A8,chess.ROOK,chess.BLACK),)
        proof=proof_for(after,"Rxa1+ Qd1 Rxd1+ Kxd1")
        trace=trace_target_settlement(after,chess.B3,targets,proof,PIECE_VALUES)
        self.assertLessEqual(trace.attributable_cp,0)
        # Direct target capture after its own counter-capture: queen b3 can
        # recapture on a2, but cannot count that rook twice.
        after=chess.Board("r6k/8/8/8/8/1Q6/R7/4K3 b - - 0 1")
        proof=proof_for(after,"Rxa2 Qxa2")
        trace=trace_target_settlement(after,chess.B3,targets,proof,PIECE_VALUES)
        self.assertEqual(trace.attributable_cp,0)


    def test_candidate_registry_leaves_discovery_versions_unchanged(self):
        from analysis_registry import ANALYZERS
        self.assertEqual(ANALYZERS['missed_fork'].analyzer_version,'2')
        self.assertEqual(CANDIDATE_VERIFIERS['missed_fork'].analyzer_version,'3')
        self.assertEqual(ANALYZERS['missed_fork'].scout_config(),CANDIDATE_VERIFIERS['missed_fork'].scout_config())


    def test_selection_is_anchored_on_candidates_not_all_moves(self):
        connection=Mock();cursor=Mock();cursor.description=[];cursor.__iter__=Mock(return_value=iter([]))
        connection.execute.return_value=cursor
        self.assertEqual(existing_candidates(connection,'missed_fork'),[])
        sql,params=connection.execute.call_args.args
        self.assertIn('FROM tactic_candidates c JOIN moves',sql)
        self.assertIn('WHERE c.tactic_type=?',sql)
        self.assertEqual(params,('missed_fork',))


class TargetedRepositoryTests(unittest.TestCase):
    def setUp(self):
        fixtures.RepositoryTests.setUp(self)
        self.c.execute('PRAGMA foreign_keys=ON')
        self.definition=CANDIDATE_VERIFIERS["missed_fork"]
        self.c.execute("INSERT INTO tactic_candidates(candidate_id,move_id,tactic_type,candidate_status,detector_version,solution_move_uci,solution_line,metadata_json) VALUES(42,1,'missed_fork','candidate',2,'d2d4','d4 d5','{\"unrelated\":true}')")
        self.c.execute("INSERT INTO training_attempts VALUES(1,42)");self.c.commit()
        self.expected={**move_row(),**dict(self.c.execute("SELECT * FROM tactic_candidates WHERE candidate_id=42").fetchone())}

    def test_enrich_and_rerun_keep_id_history_unrelated_metadata(self):
        op=TacticalOpportunity(TacticalOutcome("win_piece"),(TacticalMotif("fork",True,"supported","Fixture proof"),))
        result=HeavyResult("candidate",candidate_payload(3),{"reason":"verified"},op)
        self.assertEqual(reconcile_candidate(self.c,self.definition,self.expected,result,{42})["candidate_id"],42)
        current=dict(self.c.execute("SELECT * FROM tactic_candidates WHERE candidate_id=42").fetchone())
        self.assertTrue(json.loads(current["metadata_json"])["unrelated"])
        self.assertEqual(current["created_at"],"original")
        self.assertEqual(tuple(self.c.execute("SELECT * FROM training_attempts").fetchone()),(1,42))
        changes=self.c.total_changes
        self.assertEqual(reconcile_candidate(self.c,self.definition,self.expected,result,{42})["action"],"unchanged")
        self.assertEqual(changes,self.c.total_changes)

    def test_rejection_keeps_anchor_and_history_error_does_nothing(self):
        before=self.c.total_changes
        reconcile_candidate(self.c,self.definition,self.expected,HeavyResult("error"),{42})
        self.assertEqual(before,self.c.total_changes)
        reconcile_candidate(self.c,self.definition,self.expected,HeavyResult("analyzed_no_hit",details={"reason":"counterplay"}),{42})
        self.assertEqual(tuple(self.c.execute("SELECT candidate_id,candidate_status FROM tactic_candidates").fetchone()),(42,"rejected"))
        self.assertEqual(self.c.execute("SELECT candidate_id FROM training_attempts").fetchone()[0],42)

    def test_conflicts_scope_rejected_rows_and_no_inserts(self):
        with self.assertRaises(ValueError): reconcile_candidate(self.c,self.definition,self.expected,HeavyResult("analyzed_no_hit"),set())
        self.c.execute("UPDATE tactic_candidates SET candidate_status='rejected'");self.c.commit()
        with self.assertRaises(ValueError): reconcile_candidate(self.c,self.definition,self.expected,HeavyResult("analyzed_no_hit"),{42})
        self.assertEqual(self.c.execute("SELECT count(*) FROM tactic_candidates").fetchone()[0],1)

    def test_coverage_failure_rolls_back_entire_candidate_update(self):
        self.c.executescript("CREATE TRIGGER fail_coverage BEFORE INSERT ON analysis_coverage BEGIN SELECT RAISE(ABORT,'fixture'); END;")
        before=tuple(self.c.iterdump())
        with self.assertRaises(sqlite3.IntegrityError):
            reconcile_candidate(self.c,self.definition,self.expected,HeavyResult('analyzed_no_hit'),{42})
        self.assertEqual(before,tuple(self.c.iterdump()))
        self.assertEqual(self.c.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_changed_notes_and_newer_version_remain_protected(self):
        self.c.execute("UPDATE tactic_candidates SET notes='User review' WHERE candidate_id=42");self.c.commit()
        with self.assertRaises(ValueError):reconcile_candidate(self.c,self.definition,self.expected,HeavyResult('analyzed_no_hit'),{42})
        self.c.execute('UPDATE tactic_candidates SET detector_version=999 WHERE candidate_id=42');self.c.commit()
        with self.assertRaises(ValueError):reconcile_candidate(self.c,self.definition,self.expected,HeavyResult('analyzed_no_hit'),{42})
