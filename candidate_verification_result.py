"""Candidate-only proposals separate chess uncertainty from operational failure."""
from dataclasses import dataclass, field
from tactical_opportunities import TacticalOpportunity


@dataclass(frozen=True)
class CandidateVerificationResult:
    """Read-only proposal. Ambiguous is not a heavy coverage status or an exception."""
    state: str
    candidate: dict | None = None
    details: dict = field(default_factory=dict)
    opportunity: TacticalOpportunity | None = None

    def __post_init__(self):
        if self.state not in {"candidate", "analyzed_no_hit", "ambiguous", "error"}:
            raise ValueError("Unknown candidate verification state")

    @property
    def classification(self):
        """Canonical analyzer vocabulary; state retains the existing proposal transport API."""
        value = self.details.get("classification")
        if value is None:
            value = {"candidate": "verified", "analyzed_no_hit": "rejected",
                     "ambiguous": "ambiguous", "error": "error"}[self.state]
        if value not in {"verified", "verified_payoff_changed", "rejected", "ambiguous", "error"}:
            raise ValueError("Unknown analyzer classification")
        expected = {"verified": "candidate", "verified_payoff_changed": "candidate",
                    "rejected": "analyzed_no_hit", "ambiguous": "ambiguous", "error": "error"}[value]
        if self.state != expected:
            raise ValueError("Analyzer classification conflicts with result state")
        return value


def verification_result(result):
    """Normalize the legacy HeavyResult ambiguity transport only at opt-in boundaries."""
    state = "ambiguous" if result.details.get("classification") == "ambiguous" else result.state
    normalized = CandidateVerificationResult(state, result.candidate, result.details, result.opportunity)
    normalized.classification
    return normalized
