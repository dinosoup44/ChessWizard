"""Proof-state reporting must not turn denied rechecks into new chess evidence."""
import unittest
from copy import deepcopy
from tests.support.fork_first_500_metrics import ambiguity_causes, comparison


def value(branches, attempts=(), reason='incomplete_or_unsettled_counterplay'):
    return dict(key='x',result=dict(details=dict(classification='ambiguous',reason=reason,
        branches=branches,escalation_attempts=attempts,profile=dict(proof=dict(user_moves=4,settlement_plies=4)))))


class ReplayMetricTests(unittest.TestCase):
    def test_control_comparison_preserves_chess_but_ignores_provenance(self):
        left=value([dict(proof_state='stable',proof_line='Nf3 e5')])
        left['root_diagnostic']={}
        left['result']['details']['escalation']={'distinct_requests':1}
        right=deepcopy(left)
        right['result']['details']['branches'][0]['settlement_evidence']={'provenance':'new identity'}
        report=comparison({'x':left},{'x':right})
        self.assertEqual(report['counts'].get('unexpected_control_chess_changes',0),0)
        right['result']['details']['branches'][0]['proof_line']='Nf3 d5'
        report=comparison({'x':left},{'x':right})
        self.assertEqual(report['counts']['unexpected_control_chess_changes'],1)
        self.assertEqual(report['counts']['classification_changes'],0)

    def test_new_extension_deferrals_are_separate_from_resolutions(self):
        left=value([dict(proof_state='unsettled')])
        left['root_diagnostic']={}
        left['result']['details']['escalation']={'distinct_requests':1}
        right=deepcopy(left)
        right['result']['details']['escalation_attempts']=[dict(
            evidence_stage='selective_settlement_extension',status='deferred',proof={'state':'mate'})]
        report=comparison({'x':left},{'x':right})['counts']
        self.assertEqual(report['new_deferral_proposals'],1)
        self.assertEqual(report['new_deferral_branches'],1)
        self.assertEqual(report.get('resolved',0),0)

    def test_denied_settled_branch_does_not_become_unsettled(self):
        record=value([dict(proof_state='stable')],[dict(branch_index=0,status='budget_exhausted',reason='branch_limit')])
        self.assertNotIn('branch_limit_constrained',ambiguity_causes(record))

    def test_denied_unsettled_branch_retains_bound(self):
        record=value([dict(proof_state='unsettled')],[dict(branch_index=0,status='budget_exhausted',reason='branch_limit')])
        self.assertIn('branch_limit_constrained',ambiguity_causes(record))

    def test_genuine_disagreement_is_reported_directly(self):
        record=value([dict(proof_state='stable')],reason='acceptable_continuations_disagree')
        self.assertEqual(ambiguity_causes(record),['genuine_settled_disagreement'])

    def test_exact_window_bound_is_not_inferred_from_any_unsettled_proof(self):
        proof=dict(steps=[{}]*16,window=dict(user_moves=4,settlement_plies=8))
        record=value([dict(proof_state='unsettled')],[dict(branch_index=0,status='complete',reason='unsettled',proof=proof)])
        self.assertNotIn('settlement_window_exhausted',ambiguity_causes(record))
        proof['steps'].append({})
        self.assertIn('settlement_window_exhausted',ambiguity_causes(record))


if __name__=='__main__':unittest.main()
