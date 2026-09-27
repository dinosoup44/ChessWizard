"""Immutable views of supplied Fork proof; no proof generation or admission decisions."""
from dataclasses import dataclass
import json
from typing import Literal, Mapping
from stored_line import StoredLine

ProofStatus = Literal['verified', 'verified_payoff_changed', 'rejected', 'ambiguous', 'deferred', 'unavailable', 'error']
AdmissionStatus = Literal['admitted', 'rejected', 'unknown']


@dataclass(frozen=True)
class ForkProofBranch:
    line_uci: tuple[str, ...]
    line_san: str
    state: str
    status: str
    retained_related_cp: int | None
    net_material_cp: int | None


@dataclass(frozen=True)
class ForkPayoffEvidence:
    """Existing provider claims, scoped to one exact root and a supplied source reference."""
    decision_fen: str
    actual_move: str
    source_identity: str
    status: ProofStatus = 'unavailable'
    reason: str | None = None
    admission_status: AdmissionStatus = 'unknown'
    admission_reason: str | None = None
    branches: tuple[ForkProofBranch, ...] = ()
    retained_payoff_cp: int | None = None
    completeness: str = 'unavailable'
    provenance: tuple[tuple[str, str], ...] = ()

    @property
    def proof_line_count(self) -> int:
        return sum(bool(branch.line_uci) for branch in self.branches)


def payoff_evidence_from_saved(result: Mapping | None, *, decision_fen: str,
                               actual_move: str, source_identity: str) -> ForkPayoffEvidence:
    """Decode a saved neutral-root result, rejecting evidence bound to another position/move.

    Completeness describes the sampled branches, not exhaustive proof. An ambiguous
    result can have complete, settled branches; its successful branch is not promoted.
    """
    if not source_identity.strip():
        raise ValueError('Proof source identity is required')
    if result is None:
        return ForkPayoffEvidence(decision_fen, actual_move, source_identity)
    details = result.get('details', {})
    admission = details.get('root_admission', {})
    if admission.get('root', {}).get('fen') != decision_fen or admission.get('required_move') != actual_move:
        raise ValueError('Saved proof must identify this exact FEN and root move')
    status = details.get('classification')
    if status not in {'verified', 'verified_payoff_changed', 'rejected', 'ambiguous', 'deferred', 'unavailable', 'error'}:
        raise ValueError('Unknown supplied proof classification')
    passed = details.get('root_move_passes_gate')
    if passed is not None and type(passed) is not bool:
        raise ValueError('Admission evidence must be boolean or absent')
    admission_status = 'unknown' if passed is None else 'admitted' if passed else 'rejected'
    decision = next((d for d in admission.get('approved', {}).get('decisions', ())
                     if d.get('move_uci') == actual_move), {})
    admission_reason = decision.get('reason') or ('selected_root_admitted' if passed else
                         'stored_move_failed_shared_quality_gate' if passed is False else None)
    branches = []
    for branch in details.get('branches', ()):
        line = StoredLine.from_san(decision_fen, branch.get('proof_line'))
        if line.validation_error or line.moves_uci and line.moves_uci[0] != actual_move:
            raise ValueError('Invalid supplied proof continuation')
        branches.append(ForkProofBranch(line.moves_uci, line.raw_text, branch.get('proof_state', 'unknown'),
            branch.get('classification', 'unavailable'), branch.get('retained_related_cp'), branch.get('material_gain_cp')))
    complete = bool(branches) and all(b.state == 'stable' and b.status != 'error' and b.line_uci for b in branches)
    completeness = 'complete_sampled_branches' if complete else 'partial_or_deferred' if branches else 'not_assessed'
    retained = None
    if status in {'verified', 'verified_payoff_changed'} and complete:
        values = [b.retained_related_cp for b in branches]
        if all(v is not None for v in values):
            retained = min(values)
    provenance = tuple((key, json.dumps(details[key], sort_keys=True, separators=(',', ':')))
        for key in ('analyzer_version', 'profile_currentness', 'verification_mode', 'backbone_provenance') if key in details)
    return ForkPayoffEvidence(decision_fen, actual_move, source_identity, status, details.get('reason'),
        admission_status, admission_reason, tuple(branches), retained, completeness, provenance)
