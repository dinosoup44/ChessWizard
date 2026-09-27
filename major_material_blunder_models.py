"""Immutable contracts for bounded, report-only material-loss checks."""
from dataclasses import dataclass
from typing import Literal

from analysis_settings import Settings, setting
from critical_moment_context import EvaluationEvidence
from position_range_evidence import (AttackState, LegalCapture, MaterialTransition,
    PieceIdentity, RangeEvidence, RelevantRecapture, TargetFate, TerminalState)

Classification = Literal["confirmed", "not_blunder", "unresolved", "error"]
BlunderType = Literal["hung_queen", "hung_rook", "hung_minor_piece"]


@dataclass(frozen=True)
class MaterialBlunderPolicy(Settings):
    """Local report policy; never modifies shared settings or analyzer admission."""
    continuation_plies: int = setting(4, "Maximum supplied plies after the played move; never silently truncated.", minimum=1, maximum=4)
    recovery_pawns: int = setting(1, "Maximum bounded compensation, measured using the shared pawn value.", minimum=0, maximum=1)


@dataclass(frozen=True, slots=True)
class DirectEscape:
    """A legal alternative avoids direct capture, not a claim of long-term safety."""
    uci: str
    san: str
    fen_after: str
    target_fate: TargetFate


@dataclass(frozen=True, slots=True)
class MajorMaterialBlunderResult:
    classification: Classification
    reason: str
    blunder_type: BlunderType | None
    player_color: bool | None
    move_id: int | None
    played_move: str
    target_piece_id: PieceIdentity | None = None
    target_piece_type: int | None = None
    target_start_square: int | None = None
    capture_square: int | None = None
    capturing_piece: PieceIdentity | None = None
    material_loss_cp: int | None = None
    material_recovered_cp: int | None = None
    net_loss_cp: int | None = None
    immediate_recapture_available: bool | None = None
    exposure_cause: str | None = None
    avoidance_witness: DirectEscape | None = None
    attack_before: AttackState | None = None
    attack_after: AttackState | None = None
    recapture_options: tuple[RelevantRecapture, ...] = ()
    immediate_recovery_options: tuple[LegalCapture, ...] = ()
    unresolved_forcing_moves: tuple[str, ...] = ()
    target_fate: TargetFate | None = None
    material_transition: MaterialTransition | None = None
    range_evidence: RangeEvidence | None = None
    eval_before: EvaluationEvidence | None = None
    eval_after: EvaluationEvidence | None = None
    eval_delta: int | None = None
    terminal_state: TerminalState | None = None
    evidence_completeness: str = "incomplete"
    provenance: tuple[str, ...] = ()
    explanation_facts: tuple[str, ...] = ()
    policy_identity: str = ""
