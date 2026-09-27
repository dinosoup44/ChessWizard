"""Small candidate-scoped composition boundary; specialists still own motif decisions."""
from dataclasses import dataclass
from analysis_settings import AnalysisProfile, identity
from candidate_lines import to_data
from candidate_line_proof import ApprovedPositionEvidence
from candidate_line_request import request_identity
from candidate_line_selection import admit_required_move
from quality_gate import approve_lines
from proof_escalation import ProofEscalationService
from the_scale import TheScale


@dataclass(frozen=True)
class AnalysisProvenance:
    """Deterministic result identity, separate from exact raw-engine request identities."""
    profile_currentness: str
    breadth_engine_identity: str
    verification_engine_identity: str
    analyzer_id: str
    analyzer_version: str
    interpretation_policy_identity: str
    scale_identity: str
    evidence_identities: tuple[str, ...]
    scale_evidence_identities: tuple[str, ...]
    currentness_identity: str


class AnalysisBackbone:
    """One instance per candidate; injected services determine storage and engine access.

    Construction performs no I/O. Request, proof escalation, Scale and interpretation
    remain explicit stages; requesting breadth never automatically requests proof.
    """
    def __init__(self, line_service, profile=AnalysisProfile(), *, verification_service=None, event_providers=(), escalation_solver=None):
        self.profile, self.line_service = profile, line_service
        self.evidence = ApprovedPositionEvidence(line_service, profile)
        self.escalation = ProofEscalationService(verification_service or line_service, profile, proof_solver=escalation_solver)
        self.scale = TheScale(profile.scale, event_providers)
        self._root_approvals = []
        self._scale_evidence = []

    def request(self, fen, *, root_moves=(), reference_score=None):
        """Request breadth through the exact cache contract, then the shared gate."""
        if not root_moves and reference_score is None:
            # Preserve the evidence adapter's incomplete result while exposing it as data.
            from candidate_line_proof import IncompleteLineEvidence
            try:
                return self.evidence.approved(fen)
            except IncompleteLineEvidence:
                if fen not in self.evidence.positions:
                    raise
                return self.evidence.positions[fen]
        lines = self.line_service.candidate_lines(fen, self.profile.generator, root_moves=root_moves)
        result = approve_lines(lines, self.profile.quality_gate,
            expected_engine_identity=request_identity(self.profile.generator, root_moves), reference_score=reference_score)
        self._root_approvals.append(result)
        return result

    def approve_recorded(self, lines, source_identity):
        """Gate recorded evidence in its own namespace, without claiming a new cache hit."""
        approval = approve_lines(lines, self.profile.quality_gate, expected_engine_identity=source_identity)
        self._root_approvals.append(approval)
        return approval

    def admit(self, fen, move_uci):
        """Verify a required move without mistaking top-N omission for rejection."""
        admission = admit_required_move(self.line_service, fen, move_uci, self.profile)
        self._root_approvals.append(admission.approved)
        return admission

    def weigh(self, approved, continuation_evidence=None):
        """Only the gate's retained lines may receive human-interest weights."""
        weighted = self.scale.weigh(approved, continuation_evidence)
        self._scale_evidence.append(identity({"approval": approved.currentness_identity,
            "policy": weighted.scale_identity, "lines": to_data(weighted.lines)}))
        return weighted

    def provenance(self, analyzer_id, analyzer_version, *, interpretation_policy=None):
        """Include analyzer/attribution policy without changing raw engine keys."""
        if not analyzer_id or not analyzer_version:
            raise ValueError("Analyzer identity and version are required")
        approvals = (*self._root_approvals, *self.evidence.positions.values(), *self.escalation.evidence_approvals())
        evidence_ids = tuple(sorted({approval.currentness_identity for approval in approvals}))
        policy_id = identity(to_data(interpretation_policy or {}))
        scale_id = identity({"settings": to_data(self.profile.scale),
            "providers": [(p.provider_id, p.version) for p in self.scale.event_providers]})
        scale_evidence = tuple(sorted(set(self._scale_evidence)))
        data = {"profile": self.profile.currentness_identity, "analyzer": analyzer_id,
            "version": str(analyzer_version), "interpretation_policy": policy_id,
            "scale": scale_id, "evidence": evidence_ids, "scale_evidence": scale_evidence}
        return AnalysisProvenance(self.profile.currentness_identity, self.profile.engine_identity,
            self.escalation.profile.engine_identity, analyzer_id, str(analyzer_version),
            policy_id, scale_id, evidence_ids, scale_evidence, identity(data))
