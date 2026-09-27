"""Audit regressions for recorded proof status versus retained evidence; no policy changes."""
from copy import deepcopy
from pathlib import Path
import json,unittest
from tests.support.fork_proof_facts import retained_branch_evidence,recorded_cause,common_outcome

class ProofAuditTests(unittest.TestCase):
    def test_denied_recheck_does_not_mean_the_old_proof_was_unsettled(self):
        normal={"proof_state":"stable","final_fen":"saved endpoint","proof_line":"saved line"}
        details={"normal_branches":[normal],"branches":[{**normal,"proof_state":"budget_exhausted"}],
            "escalation_attempts":[{"branch_index":0,"status":"budget_exhausted","reason":"branch_limit","proof":None}],
            "profile":{"proof":{"user_moves":4,"settlement_plies":4,"quiet_plies":2}}}
        before=deepcopy(details)
        evidence=retained_branch_evidence(details,0)
        self.assertEqual(evidence["state"],"stable")
        self.assertEqual(evidence["source"],"retained_normal_proof")
        self.assertEqual(details,before)


    def test_positive_net_material_does_not_prove_common_causal_fork_payoff(self):
        hit={"state":"candidate","proof_state":"stable","payoff_signature":["win_material","supported",300],"retained_related_cp":300,"realizable_target_squares":["h8"]}
        no_hit={"state":"analyzed_no_hit","proof_state":"stable","payoff_signature":["no_retained_payoff","none",0],"retained_related_cp":0,"material_gain_cp":500,"realizable_target_squares":[]}
        result=common_outcome({"branches":[hit,no_hit]})
        self.assertTrue(result["hit_vs_no_hit_disagreement"])
        self.assertFalse(result["conservative_common_outcome_supported"])
        self.assertTrue(common_outcome({"branches":[hit,{**hit,"retained_related_cp":200,"payoff_signature":["win_material","supported",200]}]})["conservative_common_outcome_supported"])
