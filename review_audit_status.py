"""Original audit disposition for review presentation, independent of human verdicts."""
from dataclasses import dataclass
import json

from human_analyzer_reviews import HumanReviewCase


@dataclass(frozen=True)
class ReviewAuditStatus:
    classification: str
    label: str
    explanation: str
    details: str = ""


_CHECKER_STATUSES = {
    "confirmed": ReviewAuditStatus(
        "confirmed", "CONFIRMED BLUNDER",
        "Checker result: confirmed major material blunder."),
    "unresolved": ReviewAuditStatus(
        "unresolved", "UNRESOLVED",
        "Checker result: unresolved — evidence was insufficient for confirmation."),
    "not_blunder": ReviewAuditStatus(
        "not_blunder", "CONTROL — NOT BLUNDER",
        "Checker result: not blunder — included as a negative control to test false-positive resistance."),
}


def audit_status_for_case(case: HumanReviewCase | None) -> ReviewAuditStatus | None:
    """Render explicit checker metadata only; never infer status from a verdict or reason."""
    if case is None or case.audit_case_id is None:
        return None
    presentations = {value for key, value in case.analyzer_provenance if key == "review_presentation"}
    if presentations:
        if len(presentations) != 1:
            return None
        try:
            data = json.loads(next(iter(presentations)))
            heading, fields, description, details = (data[k] for k in ('heading', 'fields', 'description', 'details'))
            if not all(isinstance(v, str) for v in (heading, description, details)) or not isinstance(fields, list):
                return None
            if not all(isinstance(pair, list) and len(pair) == 2 and all(isinstance(v, str) for v in pair) for pair in fields):
                return None
            label = '\n'.join([heading, *(f'{name}: {value}' for name, value in fields)])
            return ReviewAuditStatus('layered_assessment', label, description, details)
        except (ValueError, KeyError, TypeError):
            return None
    classifications = {value for key, value in case.analyzer_provenance
                       if key == "checker_classification"}
    # Grouped audit sources can disagree. Do not silently let the last one win.
    if len(classifications) != 1:
        return None
    return _CHECKER_STATUSES.get(next(iter(classifications)))
