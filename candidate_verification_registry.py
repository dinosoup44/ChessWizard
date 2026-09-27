"""Explicit existing-candidate specialists, separate from discovery activation."""
from dataclasses import replace
from analysis_registry import ANALYZERS
from analyze_forks_v3 import analyze_existing_candidate, ANALYZER_VERSION


def fork_verifier(row, positions):
    return analyze_existing_candidate(row, positions.position)


CANDIDATE_VERIFIERS = {
    "missed_fork": replace(ANALYZERS["missed_fork"],analyzer_version=ANALYZER_VERSION,heavy=fork_verifier)
}


def multiline_fork_verifier(profile):
    """Explicit read-only adoption; normal discovery and the single-line registry stay unchanged."""
    from analyze_forks_v3_multiline import analyze_existing_candidate as analyze_multiline

    def verify(row, line_service):
        return analyze_multiline(row, line_service, profile)

    return replace(CANDIDATE_VERIFIERS['missed_fork'], heavy=verify)


def escalating_fork_verifier(profile, verification_service=None):
    """Explicit candidate-only V3.1 preview; no discovery or live reconciliation activation."""
    from analyze_forks_v31 import analyze_existing_candidate as analyze_escalating

    def verify(row, breadth_service):
        return analyze_escalating(row, breadth_service, verification_service, profile)

    return replace(CANDIDATE_VERIFIERS["missed_fork"], analyzer_version="3.1", heavy=verify)


def pin_backbone_verifier(profile=None):
    """Opt-in Pin V2 proposals only; preserve the live discovery registry and version."""
    from pin_backbone import analyze_existing_candidate as analyze_pin

    def verify(row, line_service):
        return analyze_pin(row, line_service, profile)

    return replace(ANALYZERS["missed_pin"], heavy=verify)
