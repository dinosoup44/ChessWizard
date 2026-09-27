"""Played facts remain independent of admission, counterfactual proof and importance."""
from dataclasses import asdict, FrozenInstanceError
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import chess
from played_fork_assessment import assess_played_fork, PlayedForkAssessment
from played_fork_proof import payoff_evidence_from_saved
from played_fork_descriptions import describe_played_fork
from tactic_occurrences import TacticColor, TacticOccurrenceRelation


FEN = 'r3k3/8/8/3N4/8/8/8/4K3 w - - 0 1'
ACTUAL = ('d5c7', 'e8f7', 'c7a8')


def _saved(status: str = 'ambiguous') -> dict:
    return {'details': {'classification': status, 'root_move_passes_gate': True,
        'root_admission': {'root': {'fen': FEN}, 'required_move': ACTUAL[0]},
        'branches': [{'proof_line': 'Nc7+ Kd7 Nxa8', 'proof_state': 'stable',
                      'classification': 'verified', 'retained_related_cp': 500,
                      'material_gain_cp': 500}]}}


def _assessment(actual: tuple[str, ...] | None = ACTUAL, *,
                proof: dict | None = None,
                perspective: TacticColor = TacticColor.WHITE) -> PlayedForkAssessment:
    return assess_played_fork(occurrence_identity='synthetic-knight-fork',
        decision_fen=FEN, actual_move=ACTUAL[0], actor_color=TacticColor.WHITE,
        perspective_color=perspective, actual_line=actual,
        proof=payoff_evidence_from_saved(proof, decision_fen=FEN,
            actual_move=ACTUAL[0], source_identity='synthetic-supplied-proof'))


class PlayedForkAssessmentTests(unittest.TestCase):


    def test_geometry_recorded_result_and_proof_are_independent(self):
        result = _assessment(proof=_saved())
        self.assertEqual(result.geometry.status, 'confirmed_fork')
        self.assertEqual(result.proof.status, 'ambiguous')
        self.assertIsNone(result.proof.retained_payoff_cp)
        self.assertEqual(result.recorded.net_cp, 500)
        self.assertEqual(result.recorded.line_san, ('Nc7+', 'Kf7', 'Nxa8'))
        self.assertNotEqual(result.recorded.actual_line, result.proof.branches[0].line_uci)
        self.assertIsNone(result.occurrence.counterfactual_line)
        capture = result.recorded.target_captures[0]
        self.assertTrue(capture.by_forking_piece)
        self.assertEqual(capture.plies_after_root, 2)
        self.assertEqual(capture.capture.victim.initial_square, chess.A8)
        wording = describe_played_fork(result)
        self.assertIn('captured the rook', wording.summary)
        self.assertIn('ambiguous', wording.proof_context)
        self.assertNotIn('forced', wording.summary)

    def test_missing_and_root_only_history_remain_unresolved(self):
        for actual in (None, ACTUAL[:1]):
            result = _assessment(actual)
            self.assertEqual(result.recorded.status, 'unresolved')
            self.assertIsNone(result.recorded.recorded_target_capture)
            self.assertEqual(result.review_readiness, 'ready_for_geometry_review')
            self.assertEqual(result.proof.status, 'unavailable')
        self.assertIsNone(_assessment(None).recorded.net_cp)

    def test_gate_rejection_and_material_loss_do_not_erase_geometry(self):
        fen = '1rr1k3/8/8/3Q4/8/8/8/4K3 w - - 0 1'
        line = ('d5c6', 'e8f8', 'c6c8', 'b8c8')
        proof = _saved('rejected')
        proof['details'].update(root_move_passes_gate=False,
            root_admission={'root': {'fen': fen}, 'required_move': line[0]}, branches=[])
        result = assess_played_fork(occurrence_identity='synthetic-losing-fork',
            decision_fen=fen, actual_move=line[0], actor_color=TacticColor.WHITE,
            perspective_color=TacticColor.WHITE, actual_line=line,
            proof=payoff_evidence_from_saved(proof, decision_fen=fen,
                actual_move=line[0], source_identity='synthetic-rejected-proof'))
        self.assertEqual(result.geometry.status, 'confirmed_fork')
        self.assertEqual(result.proof.admission_status, 'rejected')
        self.assertTrue(result.recorded.recorded_target_capture)
        self.assertEqual(result.recorded.status, 'material_loss')
        self.assertEqual(result.recorded.net_cp, -400)
        self.assertEqual(result.recorded.gained_cp - result.recorded.lost_cp, -400)
        self.assertIn('did not pass', describe_played_fork(result).admission_context)

    def test_other_piece_capture_keeps_original_target_identity(self):
        result = assess_played_fork(occurrence_identity='synthetic-other-capturer',
            decision_fen='r3k3/1B6/8/3N4/8/8/8/4K3 w - - 0 1',
            actual_move='d5c7', actor_color=TacticColor.WHITE,
            perspective_color=TacticColor.WHITE,
            actual_line=('d5c7', 'e8f7', 'b7a8'))
        capture = result.recorded.target_captures[0]
        self.assertFalse(capture.by_forking_piece)
        self.assertEqual(capture.capture.victim.initial_square, chess.A8)
        self.assertIn('another piece', describe_played_fork(result).recorded_context)
        self.assertNotIn('captured', describe_played_fork(result).summary)

    def test_saved_classifications_are_not_reinterpreted(self):
        for status in ('verified', 'verified_payoff_changed', 'rejected', 'ambiguous',
                       'deferred', 'unavailable', 'error'):
            raw = _saved(status)
            before = deepcopy(raw)
            result = _assessment(proof=raw)
            self.assertEqual(result.proof.status, status)
            self.assertEqual(raw, before)
            self.assertEqual(result.proof.retained_payoff_cp,
                500 if status.startswith('verified') else None)

    def test_invalid_identity_and_illegal_lines_fail(self):
        raw = _saved()
        raw['details']['root_admission']['required_move'] = 'e1f1'
        with self.assertRaises(ValueError): _assessment(proof=raw)
        for line in (('e1f1',), ('d5c7', 'e8e1')):
            with self.assertRaises(ValueError): _assessment(line)
        with self.assertRaises(ValueError):
            assess_played_fork(occurrence_identity='wrong-side', decision_fen=FEN,
                actual_move=ACTUAL[0], actor_color=TacticColor.BLACK,
                perspective_color=TacticColor.WHITE)

    def test_opponent_perspective_and_no_fork(self):
        result = _assessment(perspective=TacticColor.BLACK)
        self.assertEqual(result.occurrence.relation, TacticOccurrenceRelation.PLAYED_BY_OPPONENT)
        self.assertTrue(describe_played_fork(result).summary.startswith('Your opponent'))
        start = assess_played_fork(occurrence_identity='synthetic-start',
            decision_fen=chess.STARTING_FEN, actual_move='e2e4',
            actor_color=TacticColor.WHITE, perspective_color=TacticColor.WHITE)
        self.assertIsNone(start.occurrence)
        self.assertEqual(start.geometry.status, 'not_fork')

    def test_immutable_deterministic_models_without_engine_or_database(self):
        with patch('subprocess.Popen', side_effect=AssertionError('No engine')), \
             patch('sqlite3.connect', side_effect=AssertionError('No DB')):
            result = _assessment(proof=_saved())
            self.assertEqual(result, _assessment(proof=_saved()))
            self.assertEqual(describe_played_fork(result), describe_played_fork(result))
            json.dumps(asdict(result))
            with self.assertRaises(FrozenInstanceError): result.proof.status = 'verified'
            with self.assertRaises(FrozenInstanceError): result.recorded.net_cp = 0

    def test_fresh_import_without_engine_database_ui_or_analyzer(self):
        code="""
import builtins
original=builtins.__import__
def guard(name,*args,**kwargs):
    if name.startswith(('tkinter','merlin_ui','analyze_','chess.engine','sqlite3','analysis_engine','candidate_line_engine')):
        raise AssertionError(name)
    return original(name,*args,**kwargs)
builtins.__import__=guard
import played_fork_assessment, played_fork_proof, played_fork_descriptions
"""
        result=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
