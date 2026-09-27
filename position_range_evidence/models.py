"""Immutable factual contracts. Squares/types/colors use python-chess values; plies are 1-based."""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True, order=True)
class PieceIdentity:
    initial_square: int
    initial_piece_type: int
    color: bool


@dataclass(frozen=True, slots=True)
class SideMaterial:
    white: int
    black: int

    def for_color(self, color: bool) -> int:
        return self.white if color else self.black


@dataclass(frozen=True, slots=True)
class CaptureEvent:
    ply: int
    capturer: PieceIdentity
    victim: PieceIdentity
    victim_type: int
    victim_color: bool
    square: int
    destination: int
    value: int
    en_passant: bool


@dataclass(frozen=True, slots=True)
class PromotionEvent:
    ply: int
    piece: PieceIdentity
    square: int
    from_type: int
    to_type: int
    material_delta: int


@dataclass(frozen=True, slots=True)
class PieceIdentityTransition:
    ply: int
    piece: PieceIdentity
    from_square: int
    to_square: int | None
    from_type: int
    to_type: int
    reason: Literal["move", "capture", "promotion", "castling_king", "castling_rook"]


@dataclass(frozen=True, slots=True)
class CheckEvent:
    ply: int
    checked_color: bool
    checker_squares: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class MoveEvent:
    ply: int
    uci: str
    san: str
    actor: PieceIdentity
    from_square: int
    to_square: int
    castling: bool
    capture: CaptureEvent | None
    promotion: PromotionEvent | None
    check: CheckEvent | None
    transitions: tuple[PieceIdentityTransition, ...]


@dataclass(frozen=True, slots=True)
class MaterialTransition:
    before: SideMaterial
    after: SideMaterial
    delta: SideMaterial
    captured_by_side: SideMaterial
    lost_by_side: SideMaterial
    promotion_delta: SideMaterial
    captures: tuple[CaptureEvent, ...]
    promotions: tuple[PromotionEvent, ...]
    snapshots: tuple[SideMaterial, ...] | None
    piece_values: tuple[tuple[int, int], ...]


TerminalKind = Literal["nonterminal", "checkmate", "stalemate", "insufficient_material",
    "repetition_claimable", "fifty_move_claimable", "other_draw", "unknown_history_dependent"]


@dataclass(frozen=True, slots=True)
class TerminalState:
    state: TerminalKind
    side_to_move: bool
    in_check: bool
    legal_move_count: int
    is_terminal: bool
    winner: bool | None
    draw_reason: str | None
    history_complete: bool
    repetition_claimable: bool | None
    fifty_move_claimable: bool
    history_requirements: tuple[str, ...]
    determined_from_position_alone: bool


@dataclass(frozen=True, slots=True)
class LegalCapture:
    side_to_move: bool
    uci: str
    san: str
    capturer: PieceIdentity
    victim: PieceIdentity
    victim_type: int
    victim_square: int
    destination: int
    value: int
    en_passant: bool
    legal: bool = True


@dataclass(frozen=True, slots=True)
class RelevantRecapture:
    capture: LegalCapture
    relations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AttackState:
    square: int
    piece: PieceIdentity | None
    geometric_attackers: tuple[int, ...]
    geometric_defenders: tuple[int, ...]
    legal_attackers: tuple[int, ...] | None
    legal_capture_reason: str
    pinned_geometric_sources: tuple[int, ...]
    white_control_sources: tuple[int, ...]
    black_control_sources: tuple[int, ...]
    legal_capture_squares: tuple[int, ...]
    legal_captures_against: tuple[LegalCapture, ...]
    legal_captures_by: tuple[LegalCapture, ...]
    side_to_move_in_check: bool

    @property
    def attacked(self) -> bool | None:
        return bool(self.geometric_attackers) if self.piece else None

    @property
    def defended(self) -> bool | None:
        return bool(self.geometric_defenders) if self.piece else None

    @property
    def attacker_count(self) -> int:
        return len(self.geometric_attackers)

    @property
    def defender_count(self) -> int:
        return len(self.geometric_defenders)

    @property
    def legal_attacker_count(self) -> int | None:
        return len(self.legal_attackers) if self.legal_attackers is not None else None

    @property
    def legal_capture_available(self) -> bool | None:
        return bool(self.legal_attackers) if self.legal_attackers is not None else None


@dataclass(frozen=True, slots=True)
class TargetFate:
    piece: PieceIdentity
    current_square: int | None
    final_piece_type: int
    capture_ply: int | None
    captured_by: PieceIdentity | None
    move_count: int
    promotions: tuple[PromotionEvent, ...]
    attack_state: AttackState | None
    terminal_state: TerminalKind
    is_checked_king: bool

    @property
    def alive(self) -> bool:
        return self.current_square is not None

    @property
    def moved(self) -> bool:
        return self.move_count > 0

    @property
    def promoted(self) -> bool:
        return bool(self.promotions)


@dataclass(frozen=True, slots=True)
class AttackerSurvival:
    fate: TargetFate
    destination_after_tactic: int
    moved_again: bool
    legal_capture_involvement: tuple[RelevantRecapture, ...]


@dataclass(frozen=True, slots=True)
class PositionEvidence:
    fen: str
    side_to_move: bool
    material: SideMaterial
    terminal_state: TerminalState
    attack_states: tuple[AttackState, ...]


@dataclass(frozen=True, slots=True)
class RangeEvidence:
    start_fen: str
    end_fen: str
    moves: tuple[MoveEvent, ...]
    material_transition: MaterialTransition
    tracked_piece_fates: tuple[TargetFate, ...]
    attacker_survival: AttackerSurvival | None
    terminal_state: TerminalState
    relevant_recaptures: tuple[RelevantRecapture, ...]

    @property
    def ply_count(self) -> int:
        return len(self.moves)

    def get_piece_fate(self, piece: PieceIdentity) -> TargetFate:
        """Find a requested original identity; unknown/unrequested IDs raise KeyError."""
        for fate in self.tracked_piece_fates:
            if fate.piece == piece:
                return fate
        raise KeyError(piece)
