"""Reporting rates preserve population boundaries and account for missing evidence."""
from copy import deepcopy
import unittest
from tests.support.cohort_report_metrics import fraction, population_rates, selective_rates, cohort_comparison


class CohortReportMetricsTests(unittest.TestCase):
    def metrics(self):
        return dict(entries=10, classifications={'verified':1, 'ambiguous':2, 'rejected':7},
                    gate={'admitted':3, 'rejected':5, 'not_reached':2},
                    proof_complete=2, escalated_proposals=3, escalation_resolved=1,
                    mate_terminal_deferrals=2, rank={'1':3, 'outside_top_3':5, 'not_reached':2},
                    ambiguity_causes_nonexclusive={'settlement_window_exhausted':2, 'genuine_settled_disagreement':1})

    def test_gate_denominators_do_not_silently_drop_terminal_positions(self):
        r=population_rates(self.metrics())
        self.assertEqual(r['gate_admitted'], fraction(3,10))
        self.assertEqual(r['gate_admitted_when_reached'], fraction(3,8))
        self.assertEqual(r['proof_complete'], fraction(2,10))

    def test_ambiguity_causes_keep_both_denominators_and_can_overlap(self):
        r=population_rates(self.metrics())['ambiguity_causes']
        self.assertEqual(r['settlement_window_exhausted']['per_ambiguous'], fraction(2,2))
        self.assertEqual(r['genuine_settled_disagreement']['per_entry'], fraction(1,10))

    def test_empty_population_is_unavailable(self):
        self.assertIsNone(fraction(0,0)['rate'])
        self.assertEqual(fraction(0,10)['rate'],0)

    def test_selective_resolution_uses_eligible_and_extended_denominators(self):
        r=selective_rates(dict(paired=100,eligible_proposals=10,proposals_extended=8,resolved=4,new_deferral_proposals=1))
        self.assertEqual(r['resolution'],fraction(4,10))
        self.assertEqual(r['resolution_when_extended'],fraction(4,8))
        self.assertEqual(r['new_deferral'],fraction(1,10))

    def test_cohorts_are_separate_read_only_and_count_physical_searches(self):
        session=dict(cache_sources={},session_seconds=1)
        cost=dict(journal={'total_searches':4},execution_session=session,no_engine_rerun=session)
        s=dict(scope={'game_ids':[1]}, mode_a={'discovery':self.metrics()}, mode_b={'discovery':self.metrics()},
               selective={'counts':dict(paired=10,eligible_proposals=2,resolved=1)},
               parity=dict(categories={'A':5,'B':1},observations=6,ranges=2), engine_cost={'a':cost,'b':cost})
        before=deepcopy(s)
        r=cohort_comparison(s,s)['cohorts']
        self.assertEqual(s,before)
        self.assertEqual(r['first'],r['second'])
        self.assertEqual(r['first']['costs']['b']['fresh_searches'],fraction(4,10))
        self.assertEqual(r['first']['parity']['H'],fraction(0,6))
