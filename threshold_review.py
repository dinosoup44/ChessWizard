"""Bounded confirmation of near-threshold score evidence; never tactic acceptance."""
from dataclasses import dataclass, replace
from analysis_settings import Settings, setting, GeneratorSettings, EngineSettings
from analysis_backbone import AnalysisBackbone
from proof_escalation import ProofEscalationService, verification_profile


@dataclass(frozen=True)
class ThresholdReviewSettings(Settings):
    enabled: bool = setting(True, "Review just-below-threshold evidence before final rejection.", basic=True)
    margin_cp: int = setting(15, "Review deficits up to this margin; the acceptance threshold is unchanged.", minimum=0, maximum=100, basic=True)
    confirmation: GeneratorSettings = GeneratorSettings(1,
        engine=EngineSettings(profile_id="candidate_lines_boundary_v1", depth=22))
    max_requests: int = setting(64, "Candidate-wide exact requests for confirmation and subsequent proof, including hits.", minimum=3, maximum=256)
    policy_version: int = setting(1, "One confirmation pass; no threshold discount or repeated search until passing.", minimum=1)

    def requires_review(self, observed_cp, threshold_cp):
        return self.enabled and threshold_cp-self.margin_cp <= observed_cp < threshold_cp


@dataclass(frozen=True)
class ThresholdReviewResult:
    """Comparison passed only permits specialist proof; it never means a tactic exists."""
    state: str
    observed_gain_cp: int
    threshold_cp: int
    confirmed_gain_cp: int | None = None
    before_cp: int | None = None
    played_cp: int | None = None
    tactic_cp: int | None = None


class ThresholdReviewService:
    """Use the existing bounded shared requests, gate and evidence services without I/O ownership."""
    def __init__(self, line_service, base_profile, settings=ThresholdReviewSettings()):
        self.settings = settings
        stronger = settings.confirmation
        base = base_profile.generator
        comparable = replace(stronger.engine, profile_id=base.engine.profile_id, depth=base.engine.depth)
        if (base.engine.depth is None or stronger.engine.depth is None or stronger.engine.depth <= base.engine.depth
                or comparable != base.engine or stronger.candidate_line_count != base.candidate_line_count
                or stronger.analysis_version != base.analysis_version):
            raise ValueError("Boundary confirmation must increase depth with otherwise matching engine settings")
        configuration = replace(base_profile, escalation=replace(base_profile.escalation,
            verification=stronger, max_requests_per_candidate=settings.max_requests))
        budget = ProofEscalationService(line_service, configuration)
        self.requests = budget.requests
        self.backbone = AnalysisBackbone(self.requests, verification_profile(configuration))
        self.result = None

    def review_gain(self, before_fen, played_fen, tactic_fen, player, observed_cp, threshold_cp):
        if self.result is not None:
            raise ValueError("Boundary review is single-use per candidate")
        if not self.settings.requires_review(observed_cp, threshold_cp):
            self.result = ThresholdReviewResult("not_needed", observed_cp, threshold_cp)
            return self.result
        scores = [self.backbone.evidence.best(fen).score.pov(player) for fen in (before_fen, played_fen, tactic_fen)]
        if any(s.score_cp is None for s in scores):
            self.result = ThresholdReviewResult("deferred", observed_cp, threshold_cp)
            return self.result
        before, played, tactic = (s.score_cp for s in scores)
        gain = tactic-played
        self.result = ThresholdReviewResult("comparison_passed" if gain >= threshold_cp else "rejected",
            observed_cp, threshold_cp, gain, before, played, tactic)
        return self.result

    def audit(self):
        from candidate_lines import to_data
        return {"entered":True, "settings":to_data(self.settings), "result":to_data(self.result),
            "profile":to_data(self.backbone.profile), "requests":to_data(self.requests.attempted)}
