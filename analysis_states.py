"""Shared evidence states; these are not database coverage statuses."""
from enum import StrEnum


class EvidenceState(StrEnum):
    APPROVED = "approved"
    REJECTED_BY_QUALITY_GATE = "rejected_by_quality_gate"
    FORCED_DETERIORATION = "forced_deterioration"
    INCOMPLETE = "incomplete"
    PROOF_REQUIRED = "proof_required"
    PROOF_STABLE = "proof_stable"
    PROOF_UNSETTLED = "proof_unsettled"
    PROOF_DEFERRED = "proof_deferred"
    EXECUTION_ERROR = "execution_error"


def approval_state(approved, move_uci=None):
    """A set retains the best available line; rejection applies to a selected move."""
    if approved.state == "incomplete":
        return EvidenceState.INCOMPLETE
    if approved.state == "terminal":
        return EvidenceState.PROOF_DEFERRED
    if move_uci is not None:
        decision = next((d for d in approved.decisions if d.move_uci == move_uci), None)
        if decision is None:
            return EvidenceState.INCOMPLETE
        if not decision.retained:
            return EvidenceState.REJECTED_BY_QUALITY_GATE
    return EvidenceState.FORCED_DETERIORATION if approved.forced_deterioration else EvidenceState.APPROVED


def proof_state(proof):
    """Normalize bounded proof states without implying motif acceptance."""
    return {"stable": EvidenceState.PROOF_STABLE, "unsettled": EvidenceState.PROOF_UNSETTLED,
        "mate": EvidenceState.PROOF_DEFERRED, "draw": EvidenceState.PROOF_DEFERRED,
        "missing_continuation": EvidenceState.INCOMPLETE}.get(proof.state, EvidenceState.INCOMPLETE)


def escalation_state(result):
    """Budget exhaustion protects uncertainty; only operational failure means error."""
    return {"complete": EvidenceState.PROOF_STABLE, "unresolved": EvidenceState.PROOF_UNSETTLED,
        "budget_exhausted": EvidenceState.PROOF_UNSETTLED, "deferred": EvidenceState.PROOF_DEFERRED,
        "incomplete": EvidenceState.INCOMPLETE, "not_needed": None,
        "error": EvidenceState.EXECUTION_ERROR}[result.status]
