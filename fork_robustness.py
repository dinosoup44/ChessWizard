"""Conservative cross-continuation interpretation, independent of engine and storage."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ForkRobustness:
    continuation_count_considered: int
    settled_continuation_count: int
    payoff_consensus: bool
    target_consensus: bool
    worst_acceptable_outcome: str | None
    best_acceptable_outcome: str | None
    evaluation_range: tuple[int, int] | None
    material_gain_range: tuple[int, int] | None
    opponent_reply_diversity: int
    proof_stability: str
    classification: str
    reason: str


def summarize_continuations(branches):
    """Agreement requires every inspected continuation to settle; no optimistic branch selection."""
    settled = [b for b in branches if b['proof_state'] == 'stable' and b['state'] != 'error']
    hits = [b for b in settled if b['state'] == 'candidate']
    payoffs = {b['payoff_signature'] for b in settled}
    targets = {tuple(b['realizable_target_squares']) for b in settled}
    gains = [b['material_gain_cp'] for b in settled]
    evaluations = [b['final_player_cp'] for b in settled]
    all_stable = bool(branches) and len(settled) == len(branches)
    critical = any(b.get('critical_fallback') for b in branches)
    if not all_stable:
        classification, reason = 'ambiguous', 'incomplete_or_unsettled_counterplay'
    elif critical:
        classification, reason = 'ambiguous', 'critical_fallback_requires_review'
    elif not hits:
        classification, reason = 'rejected', 'no_retained_fork_payoff_across_approved_branches'
    elif len(hits) != len(branches) or len(payoffs) != 1 or len(targets) != 1:
        classification, reason = 'ambiguous', 'acceptable_continuations_disagree'
    else:
        changed = any(b['classification'] == 'verified_payoff_changed' for b in hits)
        classification = 'verified_payoff_changed' if changed else 'verified'
        reason = 'retained_payoff_agrees_across_sampled_counterplay'
    ordered = sorted(settled, key=lambda b: (b['retained_related_cp'], b['material_gain_cp'], b['final_player_cp']))
    return ForkRobustness(
        len(branches), len(settled), all_stable and len(payoffs) == 1,
        all_stable and len(targets) == 1,
        ordered[0]['outcome'] if ordered else None,
        ordered[-1]['outcome'] if ordered else None,
        (min(evaluations), max(evaluations)) if evaluations else None,
        (min(gains), max(gains)) if gains else None,
        len({b['opponent_move_uci'] for b in branches}),
        'all_stable' if all_stable else 'partial_or_unsettled', classification, reason)
