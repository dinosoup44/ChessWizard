"""Evidence-based eligibility for extending an existing bounded proof."""
from dataclasses import dataclass
import chess
from analysis_settings import identity
from tactical_proof import BoundedProof


@dataclass(frozen=True)
class SettlementExtensionContext:
    root_admitted: bool
    blocker_states: tuple[str, ...] = ()
    provenance: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SettlementExtensionEligibility:
    eligible: bool
    reasons: tuple[str, ...]
    blocker_states: tuple[str, ...]
    source_proof_state: str
    provenance: tuple[tuple[str, str], ...]


def settlement_extension_eligibility(proof: BoundedProof | None, context: SettlementExtensionContext,
                                      policy) -> SettlementExtensionEligibility:
    """Require complete cp evidence at the exact unchanged source-window boundary.

    The specialist supplies semantic blockers; this layer never infers causality
    from net material or an ambiguous classification.
    """
    blockers = set(context.blocker_states)
    if not policy.enabled:
        blockers.add("extension_disabled")
    if not context.root_admitted:
        blockers.add("root_not_admitted")
    if proof is None:
        blockers.add("missing_proof")
    else:
        if proof.state != "unsettled":
            blockers.add("source_" + proof.evidence_state)
        if proof.window.settlement_plies != policy.source_settlement_plies:
            blockers.add("incompatible_source_window")
        maximum = 2 * proof.window.user_moves + 1 + proof.window.settlement_plies
        if len(proof.steps) != maximum:
            blockers.add("not_exact_window_boundary")
        if chess.Board(proof.final_fen).is_game_over():
            blockers.add("terminal_board")
        raw = proof.final_evidence
        if raw.get("score_pov") != "white":
            blockers.add("incomplete_score_perspective")
        if raw.get("score_type") == "mate":
            blockers.add("mate_ownership")
        elif raw.get("score_type") != "cp" or type(raw.get("score_cp")) is not int or not raw.get("principal_variation"):
            blockers.add("incomplete_engine_evidence")
    eligible = not blockers
    provenance = (*context.provenance, ("extension_policy_identity", identity(policy)),
        ("source_proof_identity", identity(proof) if proof else "missing"))
    return SettlementExtensionEligibility(eligible,
        ("settlement_window_exhausted",) if eligible else tuple(sorted(blockers)),
        tuple(sorted(blockers)), proof.evidence_state if proof else "incomplete", provenance)
