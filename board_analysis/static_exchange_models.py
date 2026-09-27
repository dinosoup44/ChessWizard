"""Immutable contracts for advisory local exchange facts, never tactic admission."""
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal
from analysis_settings import MaterialValues


class ExchangeVerdict(StrEnum):
    FAVORABLE = "favorable"
    NEUTRAL = "neutral"
    UNFAVORABLE = "unfavorable"
    UNKNOWN = "unknown"


class ExchangeCompleteness(StrEnum):
    COMPLETE_LVA_CHAIN_ONLY = "complete_lva_chain_only"
    INCOMPLETE = "incomplete"


class ExchangeUncertainty(StrEnum):
    """Stable codes retain the feasibility corpus's original vocabulary."""
    OFF_SQUARE_CHECK_EVASION_REQUIRED = "unexamined_off_square_check_evasion"
    TERMINAL_MATERIAL_NOT_GAME_OUTCOME = "terminal_material_is_not_game_outcome"
    EXCHANGE_BOUND_EXHAUSTED = "exchange_cap_reached"


class ExchangeLimitation(StrEnum):
    SINGLE_SQUARE_ONLY = "single_square_only"
    ALTERNATIVE_ATTACKERS_NOT_SEARCHED = "alternative_attackers_not_searched"
    OFF_SQUARE_RESOURCES_NOT_PROVED = "off_square_checks_mate_intermezzi_and_compensation_not_proved"
    OPTIONAL_STOP_IS_NOT_A_PASS = "optional_stop_is_a_material_model_not_a_legal_pass"
    NOT_MOVE_OR_TACTIC_TRUTH = "not_a_tactic_or_move_quality_proof"


@dataclass(frozen=True, slots=True)
class StaticExchangePolicy:
    """Bound the local chain; no option can authorize screening or tactic truth."""
    max_plies: int = 32

    def __post_init__(self):
        if type(self.max_plies) is not int or not 1 <= self.max_plies <= 64:
            raise ValueError("max_plies must be an integer in [1, 64]")


@dataclass(frozen=True, slots=True)
class ExchangeStep:
    """One legal capture and its initiating-side material ledger."""
    fen_before: str
    move_uci: str
    move_san: str
    attacker_type: int
    captured_type: int
    captured_square: int
    captured_value_cp: int
    promotion_gain_cp: int
    cumulative_net_cp: int
    legal_choices: tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, "legal_choices", tuple(self.legal_choices))


@dataclass(frozen=True, slots=True)
class StaticExchangeResult:
    """Local material estimate; complete LVA enumeration is not complete chess proof.

    None means unknown, whereas zero means a neutral local estimate. Provisional
    material is diagnostic only. Optional stopping is neither a legal pass nor a
    guarantee of harmless abandonment, and never yields a safe general bound.
    """
    source_fen: str
    initiating_move: str
    target_square: int
    initiating_side: bool
    captured_piece_type: int
    captured_piece_value: int
    exchange_sequence: tuple[ExchangeStep, ...]
    participant_piece_types: tuple[int, ...]
    estimated_net_cp: int | None
    provisional_net_cp: int
    selected_prefix_plies: int
    verdict: ExchangeVerdict
    completeness: ExchangeCompleteness
    legality_notes: tuple[str, ...]
    pin_xray_notes: tuple[str, ...]
    promotion_notes: tuple[str, ...]
    limitations: tuple[ExchangeLimitation, ...]
    material_values: MaterialValues
    policy: StaticExchangePolicy
    uncertainty_reasons: tuple[ExchangeUncertainty, ...]
    provenance: str = field(default="static_exchange_v1:legal_lva_optional_stop_v1", init=False)
    safe_for_hard_rejection: Literal[False] = field(default=False, init=False)
    authoritative_for_tactic_truth: Literal[False] = field(default=False, init=False)

    def __post_init__(self):
        for name in ("exchange_sequence", "participant_piece_types", "legality_notes", "pin_xray_notes", "promotion_notes"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "uncertainty_reasons", tuple(ExchangeUncertainty(r) for r in self.uncertainty_reasons))
        object.__setattr__(self, "limitations", tuple(ExchangeLimitation(r) for r in self.limitations))
        object.__setattr__(self, "verdict", ExchangeVerdict(self.verdict))
        object.__setattr__(self, "completeness", ExchangeCompleteness(self.completeness))
        if self.estimated_net_cp is not None and type(self.estimated_net_cp) is not int:
            raise ValueError("Material estimate must be integer cp or None")
        unknown = self.estimated_net_cp is None
        if unknown != bool(self.uncertainty_reasons) or unknown != (self.completeness == ExchangeCompleteness.INCOMPLETE):
            raise ValueError("Unknown estimates require explicit incomplete evidence reasons")
        expected = (ExchangeVerdict.UNKNOWN if unknown else ExchangeVerdict.FAVORABLE if self.estimated_net_cp > 0
                    else ExchangeVerdict.UNFAVORABLE if self.estimated_net_cp < 0 else ExchangeVerdict.NEUTRAL)
        if self.verdict != expected:
            raise ValueError("Verdict must describe the optional local material estimate")
