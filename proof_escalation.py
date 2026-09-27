"""Targeted stronger evidence with per-candidate budgets; no tactic or persistence policy."""
from dataclasses import dataclass, replace
import chess
from analysis_settings import AnalysisProfile, identity
from candidate_line_proof import ApprovedPositionEvidence, IncompleteLineEvidence
from candidate_line_request import request_identity
from candidate_line_settlement import verify_candidate_line_settlement
from candidate_lines import to_data
from quality_gate import ApprovedCandidateLineSet
from tactical_proof import BoundedProof, ProofWindow
from proof_evidence_state import attempt_state, proof_state
from settlement_cache import SettlementCacheAdapter, settlement_settings


@dataclass(frozen=True)
class ApprovedPrefixMove:
    approval: ApprovedCandidateLineSet
    move_uci: str

    def __post_init__(self):
        if self.approval.state == "incomplete" or self.move_uci not in {line.move_uci for line in self.approval.lines}:
            raise ValueError("Prefix move must belong to complete approved evidence")


@dataclass(frozen=True)
class ProofEscalationRequest:
    after_tactic_fen: str
    player: str
    reason: str
    observed_state: str
    prefix: tuple[ApprovedPrefixMove, ...] = ()
    root_admitted: bool = True

    def __post_init__(self):
        object.__setattr__(self, "prefix", tuple(self.prefix))
        if self.player not in {"white", "black"}:
            raise ValueError("Explicit player perspective required")
        board = chess.Board(self.after_tactic_fen)
        if not board.is_valid() or board.turn == (self.player == "white"):
            raise ValueError("Valid position after the tactical move required")
        for entry in self.prefix:
            if entry.approval.source.fen != board.fen():
                raise ValueError("Prefix approval does not match its position")
            board.push_uci(entry.move_uci)


@dataclass(frozen=True)
class ProofEscalationResult:
    status: str
    reason: str
    proof: BoundedProof | None = None
    profile_identity: str | None = None
    request_identities: tuple[tuple[str, str], ...] = ()

    @property
    def escalation_attempt_state(self):
        """Independent attempt disposition; legacy status remains serialization-compatible."""
        return attempt_state(self.status, self.reason)

    @property
    def evidence_state(self):
        return proof_state(self.proof.state, self.proof.final_fen) if self.proof is not None else None


class EscalationBudgetReached(Exception):
    pass


class _BoundedRequests:
    def __init__(self, service, maximum):
        self.service, self.maximum = service, maximum
        self.values = {}
        self.attempted = []

    def candidate_lines(self, fen, settings, *, root_moves=()):
        key = (fen, request_identity(settings, root_moves))
        if key in self.values:
            return self.values[key]
        if len(self.attempted) >= self.maximum:
            raise EscalationBudgetReached("verification_request_limit")
        self.attempted.append(key)
        try:
            result = self.service.candidate_lines(fen, settings, root_moves=root_moves)
        except ValueError as error:
            raise IncompleteLineEvidence(str(error)) from error
        self.values[key] = result
        return result


def verification_profile(profile):
    """Use the same typed generator, gate and proof schema, with recursion disabled."""
    return replace(profile, profile_id="verification", label="Targeted verification",
        generator=profile.escalation.verification, proof=profile.escalation.proof,
        escalation=replace(profile.escalation, enabled=False))


class ProofEscalationService:
    """One instance per candidate; callers supply the shared cache/engine service."""
    def __init__(self, line_service, profile: AnalysisProfile, *, proof_solver=None):
        self.proof_solver = proof_solver or verify_candidate_line_settlement
        self.policy = profile.escalation
        self.profile = verification_profile(profile)
        self.settlement_cache = None
        if self.policy.settlement_extension.enabled:
            self.settlement_cache = SettlementCacheAdapter(line_service, self.policy.verification,
                (self.policy.settlement_extension.source_settlement_plies, self.policy.settlement_extension.target_settlement_plies))
            self.profile = replace(self.profile, generator=settlement_settings(self.policy.verification, self.profile.proof.settlement_plies))
            line_service = self.settlement_cache
        self.requests = _BoundedRequests(line_service, self.policy.max_requests_per_candidate)
        self.evidence = ApprovedPositionEvidence(self.requests, self.profile)
        self.branches_escalated = 0
        self._continuations = {}
        self.extension_audit = []
        self._extension_evidence = []
        self._extension_results = {}

    def _decision(self, request):
        if not self.policy.enabled or not request.root_admitted:
            return "not_needed", "disabled_or_failed_root_admission"
        if request.observed_state in {"mate", "mate_baseline", "draw"}:
            return "deferred", "mate_or_terminal_evidence_requires_owner"
        if any(entry.approval.forced_deterioration for entry in request.prefix):
            return "deferred", "critical_prefix_requires_review"
        unsettled = request.reason in {"proof_unsettled", "material_unsettled", "counter_capture_unresolved", "missing_evidence"}
        disagreement = request.reason == "payoff_disagreement"
        eligible = unsettled and self.policy.escalate_unsettled and request.observed_state != "stable"
        eligible |= disagreement and self.policy.escalate_disagreement
        if not eligible:
            return "not_needed", "settled_or_unapproved_trigger"
        if len(request.prefix) > self.policy.max_child_depth_levels:
            return "budget_exhausted", "child_depth_limit"
        if self.branches_escalated >= self.policy.max_escalated_branches_per_candidate:
            return "budget_exhausted", "branch_limit"
        return None

    def escalate(self, request: ProofEscalationRequest, piece_values) -> ProofEscalationResult:
        decision = self._decision(request)
        if decision:
            return ProofEscalationResult(*decision, profile_identity=self.profile.currentness_identity)
        self.branches_escalated += 1
        before = len(self.requests.attempted)
        window = ProofWindow(version="approved_pv_endpoint_v1", user_moves=self.profile.proof.user_moves,
            settlement_plies=self.profile.proof.settlement_plies, quiet_plies=self.profile.proof.quiet_plies)
        try:
            def best(fen):
                approved = self.evidence.approved(fen)
                if not approved.lines:
                    raise IncompleteLineEvidence("No complete nonterminal line")
                return approved.lines[0]
            checkpoint = []
            options = ({"checkpoint_sink": checkpoint.append}
                if self.policy.settlement_extension.enabled and self.proof_solver is verify_candidate_line_settlement else {})
            proof = self.proof_solver(chess.Board(request.after_tactic_fen),
                request.player == "white", request.prefix, best, piece_values, window, **options)
            if checkpoint:
                self._continuations[self._continuation_key(request)] = (request, proof, checkpoint[-1])
            status = "complete" if proof.state == "stable" else "deferred" if proof.state in {"mate", "draw"} else "unresolved"
            return ProofEscalationResult(status, proof.state, proof, self.profile.currentness_identity,
                tuple(self.requests.attempted[before:]))
        except EscalationBudgetReached as error:
            return ProofEscalationResult("budget_exhausted", str(error), profile_identity=self.profile.currentness_identity,
                request_identities=tuple(self.requests.attempted[before:]))
        except IncompleteLineEvidence as error:
            return ProofEscalationResult("incomplete", str(error), profile_identity=self.profile.currentness_identity,
                request_identities=tuple(self.requests.attempted[before:]))

        except Exception as error:
            return ProofEscalationResult("error", f"{type(error).__name__}: {error}",
                profile_identity=self.profile.currentness_identity,
                request_identities=tuple(self.requests.attempted[before:]))

    @staticmethod
    def _continuation_key(request):
        return (request.after_tactic_fen, request.player, tuple(entry.move_uci for entry in request.prefix))

    def extend_settlement(self, request, previous, eligibility, piece_values):
        """Resume the same branch without replenishing branch or request budgets."""
        key = self._continuation_key(request)
        if (not eligibility.eligible or previous.status != "unresolved" or previous.proof is None
                or previous.proof.state != "unsettled"):
            return previous
        if key in self._extension_results:
            return self._extension_results[key]
        record = self._continuations.get(key)
        if record is None or record[0] != request or record[1] is not previous.proof:
            raise ValueError("Extension requires this service's original proof checkpoint")
        target = self.policy.settlement_extension.target_settlement_plies
        extended = replace(self.profile, generator=settlement_settings(self.policy.verification, target),
            proof=replace(self.profile.proof, settlement_plies=target))
        extended_evidence = ApprovedPositionEvidence(self.requests, extended)
        self._extension_evidence.append(extended_evidence)
        window = replace(previous.proof.window, settlement_plies=extended.proof.settlement_plies)
        start = len(self.requests.attempted)
        try:
            def best(fen):
                approved = extended_evidence.approved(fen)
                if not approved.lines:
                    raise IncompleteLineEvidence("No complete nonterminal line")
                return approved.lines[0]
            proof = verify_candidate_line_settlement(chess.Board(request.after_tactic_fen),
                request.player == "white", request.prefix, best, piece_values, window, resume=record[2])
            status = "complete" if proof.state == "stable" else "deferred" if proof.state in {"mate", "draw"} else "unresolved"
            result = ProofEscalationResult(status, proof.state, proof, extended.currentness_identity,
                tuple(self.requests.attempted[start:]))
        except EscalationBudgetReached as error:
            result = ProofEscalationResult("budget_exhausted", str(error), profile_identity=extended.currentness_identity,
                request_identities=tuple(self.requests.attempted[start:]))
        except IncompleteLineEvidence as error:
            result = ProofEscalationResult("incomplete", str(error), profile_identity=extended.currentness_identity,
                request_identities=tuple(self.requests.attempted[start:]))
        except Exception as error:
            result = ProofEscalationResult("error", f"{type(error).__name__}: {error}",
                profile_identity=extended.currentness_identity, request_identities=tuple(self.requests.attempted[start:]))
        self.extension_audit.append({"eligibility": to_data(eligibility),
            "source_proof_identity": identity({"branch": key, "window": to_data(previous.proof.window), "profile": self.profile.currentness_identity}),
            "extended_proof_identity": identity({"branch": key, "window": to_data(window), "profile": extended.currentness_identity}),
            "source_raw_identity": self.profile.engine_identity, "extended_raw_identity": extended.engine_identity,
            "approved_requests": [to_data(v) for v in extended_evidence.positions.values()],
            "approved_request_identities": [v.currentness_identity for v in extended_evidence.positions.values()],
            "status": result.status, "reason": result.reason, "request_identities": result.request_identities})
        self._extension_results[key] = result
        return result

    def escalate_selected(self, selections, piece_values):
        """Lazily consume (branch_key, request) pairs; the specialist owns selection.

        Laziness lets the specialist reconsider consensus after each result without
        pre-scheduling every branch. All limits remain in this service.
        """
        for key, request in selections:
            yield key, self.escalate(request, piece_values)

    def evidence_approvals(self):
        """All approved evidence contributing to normal or extended proof provenance."""
        return tuple(self.evidence.positions.values()) + tuple(
            approval for evidence in self._extension_evidence for approval in evidence.positions.values())

    def audit(self):
        result = {"branches_escalated": self.branches_escalated,
                "distinct_requests": len(self.requests.attempted),
                "verification_profile": to_data(self.profile), "policy": to_data(self.policy),
                "approved_requests": [to_data(value) for value in self.evidence.positions.values()]}
        if self.policy.settlement_extension.enabled:
            result["settlement_extensions"] = self.extension_audit
            result["settlement_cache"] = dict(self.settlement_cache.stats)
        return result
