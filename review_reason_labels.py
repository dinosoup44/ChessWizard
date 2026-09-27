"""Human wording for stable audit reason codes; no chess judgments are inferred."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewReasonLabel:
    reason_code: str
    reason_label: str
    explanation: str


_WORDING = {
    "clean_verified": ("Tactic supported by the recorded proof", "A curated positive example from the audit."),
    "payoff_changed": ("Tactic holds, but the payoff differs", "The recorded proof supports a different material outcome."),
    "rejected_geometry": ("The proposed tactic did not pass validation", "The audit rejected this proposal; this is not a new judgment."),
    "genuine_settled_disagreement": ("Tested replies lead to different outcomes", "Completed branches disagreed about the tactical payoff."),
    "settlement_limited": ("The exchanges were not fully resolved", "The recorded proof ended before the material outcome settled."),
    "selective_12_no_hit": ("Longer analysis did not confirm the tactic", "Extending the proof changed the audit proposal to no hit."),
    "selective_12_new_deferral": ("Longer analysis reached a mate or draw line", "The audit deferred interpretation; this does not prove the proposed tactic or a theoretical draw."),
    "compatible_incomplete_outcome": ("Engine evidence was incomplete here", "A bounded engine result was incomplete; no fresh analysis was run."),
    "rank_2_admitted": ("This move passed the engine-quality check", "The second-ranked root move qualified for proof checking, not automatic tactic acceptance."),
    "rank_3_admitted": ("This move passed the engine-quality check", "The third-ranked root move qualified for proof checking, not automatic tactic acceptance."),
    "outside_top_3": ("This move was outside the top three choices", "It was not among the recorded engine's three leading root moves."),
    "terminal_mate": ("Mate may be the main story here", "The recorded line reached terminal or mate-related interpretation; the motif is not necessarily the primary story."),
    "special_identity": ("A special move needs careful review", "The shortlist flags a promotion or other special move-identity case."),
    "high_scale_unverified": ("Interesting idea, but the proof is uncertain", "The Scale rated the idea highly; that does not verify its tactical payoff."),
    "historical_numeric_evidence_difference": ("Current proof differs from the older saved proof", "Numerical/payoff evidence changed; neither version is automatically better."),
    "selective_12_new_acceptance": ("Longer analysis confirmed a tactical payoff", "This is an audit result, not a new production candidate."),
}


def review_reason_label(code: str) -> ReviewReasonLabel:
    label, explanation = _WORDING.get(code, ("This audit case needs review", "No human description is registered for this reason yet."))
    return ReviewReasonLabel(code, label, explanation)
