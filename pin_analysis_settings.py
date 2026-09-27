"""Pin interpretation settings use the shared schema, separately from line admission."""
from dataclasses import dataclass, replace
from analysis_settings import Settings, setting, AnalysisProfile, ProofDefaults, load_profile
from tactical_proof import ProofWindow
from threshold_review import ThresholdReviewSettings


@dataclass(frozen=True)
class PinPolicy(Settings):
    quick_min_gain_cp: int = setting(120, "V2 improvement over the played move at quick depth.", minimum=0)
    quick_max_drop_cp: int = setting(300, "V2 quick loss from best; not a shared gate tolerance.", minimum=0)
    verify_min_gain_cp: int = setting(150, "V2 verified improvement over played.", minimum=0)
    verify_max_drop_cp: int = setting(200, "V2 verified loss from best.", minimum=0)
    min_retained_material_cp: int = setting(100, "Both total and pin-related retained payoff floor.", minimum=0)
    min_final_eval_cp: int = setting(-100, "V2 final evaluation floor from the player perspective.")
    proof: ProofDefaults = ProofDefaults()
    proof_mode: str = setting("each_ply", "Fresh evaluation at each ply, including settlement.", options=("each_ply",))

    @property
    def proof_window(self):
        return ProofWindow(user_moves=self.proof.user_moves, settlement_plies=self.proof.settlement_plies,
                           quiet_plies=self.proof.quiet_plies)


def pin_profile(multiline=True):
    """Normal breadth, original V2 proof window and bounded shared escalation."""
    base = load_profile("normal_escalation" if multiline else "quick")
    return replace(base, proof=ProofDefaults(), escalation=replace(base.escalation, proof=ProofDefaults()))


def pin_evaluation_profiles(profile=None, quick_profile=None):
    """Exact new-cache requests; never alias legacy cache rows to these identities."""
    from proof_escalation import verification_profile
    quick = quick_profile or load_profile("quick")
    verify = verification_profile(profile or pin_profile())
    return {"tactic_quick_v1": quick, "tactic_verify_v1": verify}


@dataclass(frozen=True)
class PinBackbonePolicy(Settings):
    """Proposal-only policy; live Pin V2 interpretation and thresholds stay unchanged."""
    motif_consensus: str = setting("primary_causality", "Compare causal Pin identity; retain secondary annotations separately.",
        options=("primary_causality", "all_motifs"))
    boundary: ThresholdReviewSettings = ThresholdReviewSettings()
