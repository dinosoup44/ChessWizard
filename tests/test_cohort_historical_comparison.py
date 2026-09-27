"""Historical comparisons distinguish missing records from changed bounded evidence."""
from copy import deepcopy
import unittest
from tests.support.cohort_historical_comparison import retained_facts, compare_record


class HistoricalCohortComparisonTests(unittest.TestCase):
    def setUp(self):
        self.details=dict(classification='ambiguous',reason='unsettled',root_move_passes_gate=True,
            branches=[dict(proof_state='unsettled',proof_line='e4 e5',final_fen=None,material_gain_cp=0)])
        self.current=dict(key='1:e2e4',kind='discovery',move='e2e4',
            row=dict(game_id=11,source_game_id='example',move_id=1),result=dict(details=deepcopy(self.details)))
        self.before=dict(details=deepcopy(self.details),source='recorded.jsonl')

    def test_same_facts_and_verdict_do_not_claim_an_improvement(self):
        value=compare_record(self.before,self.current,self.current)
        self.assertEqual(value['category'],'same retained facts and verdict')
        self.assertEqual(value['retained_fact_differences'],[])

    def test_material_change_is_retained_even_when_verdict_matches(self):
        self.current['result']['details']['branches'][0]['material_gain_cp']=300
        value=compare_record(self.before,self.current,self.current)
        self.assertEqual(value['category'],'retained evidence differs; verdict unchanged')
        self.assertEqual(value['retained_fact_differences'][0]['field'],'material_gain_cp')

    def test_changed_verdict_requires_review(self):
        self.current['result']['details']['classification']='rejected'
        self.assertEqual(compare_record(self.before,self.current,self.current)['category'],
            'classification changed; review required')

    def test_old_denied_attempt_does_not_erase_prior_proof_or_mutate_source(self):
        self.details['normal_branches']=deepcopy(self.details['branches'])
        self.details['branches'][0]['proof_state']='budget_exhausted'
        self.details['escalation_attempts']=[dict(branch_index=0,status='budget_exhausted',reason='branch_limit')]
        before=deepcopy(self.details)
        self.assertEqual(retained_facts(self.details)[0]['proof_state'],'unsettled')
        self.assertEqual(self.details,before)

    def test_played_mate_is_ownership_cleanup_not_a_changed_gate_policy(self):
        import chess
        board=chess.Board()
        for san in ('f3','e5','g4'):board.push_san(san)
        self.current['row'].update(fen_before=board.fen(),uci_played='d8h4')
        d=self.current['result']['details']
        d.update(root_move_passes_gate=None,terminal=dict(terminal_state='played_checkmate',
            ownership='played_move_terminal',complete=True,result='0-1'))
        self.before['details']['classification']='rejected'
        self.assertEqual(compare_record(self.before,self.current,self.current)['category'],
            'played-checkmate ownership cleanup')

    def test_claimed_played_mate_requires_legal_board_confirmation(self):
        import chess
        self.current['row'].update(fen_before=chess.STARTING_FEN,uci_played='e2e4')
        self.current['result']['details']['terminal']=dict(terminal_state='played_checkmate',
            ownership='played_move_terminal',complete=True,result='1-0')
        with self.assertRaises(AssertionError):compare_record(self.before,self.current,self.current)

    def test_candidate_mate_uses_proposal_not_actual_played_move(self):
        import chess
        board=chess.Board()
        for san in ('f3','e5','g4'):board.push_san(san)
        self.current['row'].update(fen_before=board.fen(),uci_played='b8c6')
        self.current['move']='d8h4'
        self.current['result']['details'].update(root_move_passes_gate=None,
            terminal=dict(terminal_state='candidate_checkmate',ownership='mate',complete=True,result='0-1'))
        self.assertEqual(compare_record(self.before,self.current,self.current)['category'],
            'candidate-checkmate ownership cleanup')

    def test_legacy_unresolved_summary_uses_its_recorded_deeper_proof(self):
        d=deepcopy(self.details)
        d['branches'][0]['proof_state']='unresolved'
        d['escalation_attempts']=[dict(branch_index=0,status='unresolved',reason='unsettled',
            proof=dict(state='unsettled',final_fen='recorded endpoint',steps=[dict(san='e5'),dict(san='Nf3')]))]
        before=deepcopy(d)
        facts=retained_facts(d)[0]
        self.assertEqual(facts['proof_line'],'e4 e5 Nf3')
        self.assertEqual(facts['final_fen'],'recorded endpoint')
        self.assertEqual(facts['proof_state'],'unsettled')
        self.assertEqual(facts['material_gain_cp'],0)
        self.assertEqual(d,before)

    def test_current_retained_proof_is_not_erased_by_later_denial(self):
        d=deepcopy(self.details)
        d['normal_branches']=[dict(proof_state='unsettled',proof_line='e4',final_fen='short')]
        d['branches'][0].update(proof_line='e4 e5 Nf3',final_fen='long')
        d['escalation_attempts']=[dict(branch_index=0,status='budget_exhausted',reason='branch_limit')]
        self.assertEqual(retained_facts(d)[0]['proof_line'],'e4 e5 Nf3')
