"""Opt-in composition boundary for future analyzers; no existing crawler integration."""
from dataclasses import dataclass
from analysis_settings import AnalysisProfile, identity
from candidate_lines import to_data
from analysis_backbone import AnalysisBackbone
from the_scale import WeightedCandidateLines


@dataclass(frozen=True)
class LineAnalysisResult:
    weighted: WeightedCandidateLines
    currentness_identity: str


class LineAnalysisService:
    """Compose expensive cached generation with cheap acceptance and interest."""

    def __init__(self, candidate_line_service, event_providers=()):
        self.candidate_line_service = candidate_line_service
        self.event_providers = tuple(event_providers)

    def analyze(self, fen, profile=AnalysisProfile(), *, reference_score=None, continuation_evidence=None):
        backbone = AnalysisBackbone(self.candidate_line_service, profile, event_providers=self.event_providers)
        approved = backbone.request(fen, reference_score=reference_score)
        weighted = backbone.weigh(approved, continuation_evidence)
        currentness = identity({
            'profile': profile.currentness_identity,
            'approval': approved.currentness_identity,
            'scale': weighted.scale_identity,
            'continuation_evidence': to_data(continuation_evidence or {}),
            'events': [to_data(line.events) for line in weighted.lines],
        })
        return LineAnalysisResult(weighted, currentness)
