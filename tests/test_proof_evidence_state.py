"""Proof lifetime, terminal ownership, and factual replay contracts."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json, unittest
import chess
from analysis_settings import load_profile
from analyze_forks_v31 import review_counterplay, analyze_position
from analyze_forks_v3 import PIECE_VALUES
from proof_escalation import ProofEscalationResult, verification_profile
from proof_evidence_state import retained_branches, terminal_facts, proof_state
from proof_endpoint_facts import collect_endpoint_facts
from candidate_line_engine import CandidateLineGenerator
from candidate_line_service import CandidateLineService
from candidate_line_proof import ApprovedPositionEvidence, TerminalPositionEvidence, IncompleteLineEvidence
from candidate_line_request import request_identity
from fork_robustness import summarize_continuations
from test_fork_multiline import branch_fixture


class ProofEvidenceStateTests(unittest.TestCase):
    def context(self):
        after=chess.Board();after.push_san('e4')
        return SimpleNamespace(details={},after=after,row={'color':'white'},profile=load_profile('normal_escalation'))

    def review_failed(self, original_state, status='budget_exhausted', reason='branch_limit'):
        branches=[dict(branch_fixture(retained=100),proof_state=original_state),branch_fixture()]
        before=deepcopy(branches)
        context=self.context()
        escalation=Mock()
        escalation.escalate_selected.return_value=[(0,ProofEscalationResult(status,reason))]
        with patch('analyze_forks_v31._prefix',return_value=()):
            review_counterplay(context,branches,[],escalation)
        self.assertEqual(branches[0]['proof_state'],before[0]['proof_state'])
        self.assertEqual(branches[0]['state'],before[0]['state'])
        return branches,context.details

    def test_stable_proof_survives_denied_and_failed_rechecks(self):
        for status,reason,expected in [('budget_exhausted','branch_limit','branch_limit_denied'),
                ('budget_exhausted','verification_request_limit','request_limit_denied'),
                ('budget_exhausted','child_depth_limit','child_depth_denied'),
                ('incomplete','missing score','completed')]:
            with self.subTest(status=status,reason=reason):
                branches,details=self.review_failed('stable',status,reason)
                self.assertEqual(branches[0]['escalation_attempt_state'],expected)
                self.assertEqual(details['escalation_attempts'][0]['evidence_state'],None)
                self.assertEqual(summarize_continuations(branches).reason,'acceptable_continuations_disagree')

    def test_engine_error_preserves_proof_but_propagates_operational_failure(self):
        branches=[branch_fixture(retained=100),branch_fixture()];context=self.context()
        esc=Mock();esc.escalate_selected.return_value=[(0,ProofEscalationResult('error','engine unavailable'))]
        with patch('analyze_forks_v31._prefix',return_value=()), self.assertRaisesRegex(RuntimeError,'engine unavailable'):
            review_counterplay(context,branches,[],esc)
        self.assertEqual(branches[0]['proof_state'],'stable')
        self.assertEqual(context.details['escalation_attempts'][0]['escalation_attempt_state'],'error')

    def test_unsettled_proof_survives_denied_recheck(self):
        self.review_failed('unsettled')

    def test_historical_adapter_retains_payload_and_real_disagreement(self):
        normal=[branch_fixture(retained=100),branch_fixture()]
        details={'normal_branches':normal,'branches':[dict(normal[0],proof_state='budget_exhausted'),normal[1]],
            'escalation_attempts':[{'branch_index':0,'status':'budget_exhausted','reason':'branch_limit','proof':None}]}
        before=deepcopy(details);adapted=retained_branches(details)
        self.assertEqual(details,before)
        self.assertEqual(adapted[0]['proof_state'],'stable')
        self.assertEqual(summarize_continuations(adapted).reason,'acceptable_continuations_disagree')

    def terminal_row(self):
        board=chess.Board()
        for san in ('f3','e5','g4'):board.push_san(san)
        after=board.copy();after.push_san('Qh4#')
        return {'fen_before':board.fen(),'fen_after':after.fen(),'uci_played':'d8h4','san_played':'Qh4#',
                'color':'black','move_number':2,'game_id':1,'move_id':1}

    def test_played_checkmate_is_explicit_without_engine(self):
        row=self.terminal_row();service=Mock()
        result=analyze_position(row,'b8c6',service)
        self.assertEqual(result.details['terminal_state'],'played_checkmate')
        self.assertEqual(result.details['ownership'],'played_move_terminal')
        self.assertEqual(result.details['proof_state'],'terminal')
        self.assertNotIn('missing',result.details['reason'])
        service.candidate_lines.assert_not_called()

    def test_candidate_checkmate_defers_to_mate_without_engine(self):
        row=self.terminal_row();board=chess.Board(row['fen_before']);board.push_san('Nc6')
        row.update(fen_after=board.fen(),uci_played='b8c6',san_played='Nc6')
        service=Mock();result=analyze_position(row,'d8h4',service)
        self.assertEqual(result.details['terminal_state'],'candidate_checkmate')
        self.assertEqual(result.details['ownership'],'mate')
        self.assertEqual(result.state,'ambiguous')
        self.assertIsNone(result.candidate)
        service.candidate_lines.assert_not_called()

    def test_complete_terminal_cache_evidence_is_not_incomplete(self):
        fen=self.terminal_row()['fen_after'];engine=Mock()
        evidence=ApprovedPositionEvidence(CandidateLineService(CandidateLineGenerator(engine)))
        self.assertEqual(evidence.approved(fen).state,'terminal')
        with self.assertRaises(TerminalPositionEvidence) as raised:evidence.best(fen)
        self.assertTrue(raised.exception.facts.complete)
        self.assertNotIsInstance(raised.exception,IncompleteLineEvidence)
        engine.analyse.assert_not_called()
        self.assertEqual(proof_state('draw'),'terminal')
        self.assertEqual(proof_state('mate_baseline'),'deferred')
        self.assertEqual(proof_state('mate',chess.STARTING_FEN),'deferred')
        self.assertEqual(proof_state('mate',fen),'terminal')

    def test_window_changes_result_identity_not_raw_cache_identity(self):
        base=load_profile('normal_escalation')
        extended=replace(base,escalation=replace(base.escalation,proof=replace(base.escalation.proof,settlement_plies=12)))
        self.assertNotEqual(base.currentness_identity,extended.currentness_identity)
        self.assertEqual(request_identity(verification_profile(base).generator),request_identity(verification_profile(extended).generator))
        self.assertEqual(base.escalation.proof.settlement_plies,8)

    def test_factual_endpoint_records_capture_without_claiming_causality(self):
        fen='r3k3/7p/8/3N4/8/8/P7/4K3 w - - 0 1'
        facts=collect_endpoint_facts(fen,'d5c7',('e8f7','c7a8'),('a8','e8'),PIECE_VALUES)
        self.assertEqual(facts['material_delta_cp'],500)
        self.assertEqual(facts['attacker_captured_original_target_cp'],500)
        self.assertEqual(facts['original_target_fates'][0]['fate'],'captured')
        self.assertEqual(facts['original_target_fates'][1]['current_square'],'f7')
        self.assertEqual(facts['attacker_square'],'a8')
        self.assertIsNone(facts['causal_related_material_cp'])
        self.assertEqual(facts['terminal']['terminal_state'],'none')
        with self.assertRaises(ValueError):collect_endpoint_facts(fen,'d5c7',('e8e4',),('a8',),PIECE_VALUES)

    def test_factual_target_identity_follows_castling_rook(self):
        fen='r3k2r/8/8/8/8/8/P7/4K3 w kq - 0 1'
        facts=collect_endpoint_facts(fen,'a2a3',('e8g8',),('h8',),PIECE_VALUES)
        self.assertEqual(facts['original_target_fates'][0]['current_square'],'f8')

    def test_hit_no_hit_disagreement_cannot_become_common_payoff(self):
        self.assertEqual(summarize_continuations([branch_fixture(),branch_fixture(state='analyzed_no_hit')]).classification,'ambiguous')

