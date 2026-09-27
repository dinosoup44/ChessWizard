"""Actual and alternate discovery reuse Fork proof without changing tactic truth."""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from analysis_settings import load_profile
from analyze_forks_v31 import analyze_position, evaluate_fork_move
from analyze_forks_v3_multiline import analyze_existing_candidate
from candidate_line_proof import IncompleteLineEvidence
from fork_occurrence_adapter import evaluate_recorded_fork
from tactic_occurrences import TacticColor, TacticOccurrenceRelation
from tactical_opportunities import TacticalMotif
from test_fork_multiline import FixtureService, selected_two_ply_proof
from test_forks_v3 import candidate


def played_row():
    row = candidate(played='d5c7')
    row.pop('candidate_id')
    return row


class PlayedForkTests(unittest.TestCase):
    def run_played(self, row=None, actual=('d5c7', 'e8f7', 'c7a8')):
        row = row or played_row()
        with patch('analyze_forks_v3_multiline.verify_bounded_line', side_effect=selected_two_ply_proof):
            return evaluate_recorded_fork(row, FixtureService(row), perspective_color=TacticColor.WHITE,
                                         actual_game_line=actual, source_identity='fixture:played:1')

    def test_actual_root_enters_same_proof_and_has_supported_targets(self):
        row = played_row(); before = deepcopy(row)
        with patch('sqlite3.connect', side_effect=AssertionError('No DB')), \
             patch('subprocess.Popen', side_effect=AssertionError('No engine')):
            result = self.run_played(row)
        self.assertEqual(result.classification, 'verified')
        self.assertEqual(result.occurrence.relation, TacticOccurrenceRelation.PLAYED_BY_PERSPECTIVE)
        self.assertTrue(result.occurrence.actual_move_matches_tactical_move)
        self.assertIsNone(result.occurrence.candidate_id)
        self.assertEqual(result.proof.details['realizable_targets'][0]['square'], 'a8')
        self.assertEqual({t['piece'] for t in result.proof.details['geometric_targets']}, {'king', 'rook'})
        self.assertGreaterEqual(result.proof.details['realized_payoff']['move_sequence_retained_cp'], 100)
        self.assertEqual(row, before)

    def test_missed_guard_stays_intact_and_normal_result_stays_counterfactual(self):
        row = played_row(); service = FixtureService(row)
        with self.assertRaisesRegex(ValueError, 'unplayed'):
            analyze_position(row, row['uci_played'], service)
        self.assertFalse(service.calls)
        row = candidate(); before = deepcopy(row)
        with patch('analyze_forks_v3_multiline.verify_bounded_line', side_effect=selected_two_ply_proof):
            result = analyze_existing_candidate(row, FixtureService(row))
        self.assertEqual(result.state, 'candidate')
        self.assertNotEqual(result.opportunity.proof.played_move_uci, result.opportunity.proof.tactical_move_uci)
        self.assertEqual(row, before)
        self.assertEqual(row['candidate_id'], 42)
        self.assertEqual(row['candidate_status'], 'candidate')

    def test_actual_continuation_is_not_replaced_by_counterfactual_proof(self):
        result = self.run_played(actual=('d5c7', 'e8d8', 'c7a8'))
        self.assertEqual(result.occurrence.actual_game_line, ('d5c7', 'e8d8', 'c7a8'))
        self.assertNotEqual(result.occurrence.actual_game_line, result.occurrence.counterfactual_line)
        self.assertEqual(result.occurrence.counterfactual_line[0], 'd5c7')

    def test_missing_cache_is_unresolved_not_rejected_or_verified(self):
        class Missing:
            def candidate_lines(self, *args, **kwargs):
                raise IncompleteLineEvidence('exact_cache_missing')
        result = evaluate_recorded_fork(played_row(), Missing(), perspective_color=TacticColor.WHITE,
                                       actual_game_line=('d5c7',), source_identity='fixture:gap')
        self.assertEqual(result.classification, 'unresolved')
        self.assertIsNone(result.occurrence)

    def test_perspective_identity_and_actual_evidence_required(self):
        for row, perspective, line in ((played_row(), TacticColor.BLACK, ('d5c7',)),
                                       (candidate(played='d5c7'), TacticColor.WHITE, ('d5c7',)),
                                       (played_row(), TacticColor.WHITE, ('e1f1',))):
            with self.assertRaises(ValueError):
                evaluate_recorded_fork(row, FixtureService(row), perspective_color=perspective,
                                       actual_game_line=line, source_identity='fixture:bad')

    def test_context_only_proof_not_promoted_to_played_fork(self):
        proof = self.run_played().proof
        context = replace(proof, opportunity=replace(proof.opportunity,
            motifs=(TacticalMotif('fork', False, 'context_only'),)))
        with patch('fork_occurrence_adapter.evaluate_fork_move', return_value=context):
            result = self.run_played()
        self.assertEqual(result.classification, 'rejected')
        self.assertEqual(result.reason, 'fork_is_context_only')
        self.assertIs(result.proof, context)
        self.assertIsNone(result.occurrence)

    def test_shared_quality_gate_still_rejects_poor_actual_root(self):
        row = played_row()
        result = evaluate_recorded_fork(row, FixtureService(row, [('Kf1',800),('Nc7+',0)]),
            perspective_color=TacticColor.WHITE, actual_game_line=('d5c7',), source_identity='fixture:gate')
        self.assertEqual(result.classification, 'rejected')
        self.assertEqual(result.reason, 'stored_move_failed_shared_quality_gate')
