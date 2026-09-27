"""Uncertainty is control information, never reusable engine evidence."""


class IncompleteLineEvidence(ValueError):
    """Signal insufficient exact evidence; leave the obligation retryable.

    No numeric score or principal variation can be inferred from this exception.
    Existing callers catching ValueError remain compatible.
    """


class EngineIdentityMismatch(ValueError):
    """Signal that the active engine cannot satisfy the configured cache identity."""
