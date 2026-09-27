"""Conservative presentation context over supplied evidence, never analyzer truth."""
from dataclasses import dataclass
from enum import StrEnum

from analysis_settings import Settings, setting, identity


@dataclass(frozen=True)
class ContextPolicy(Settings):
    """Experimental report-only defaults, not live display or analyzer settings."""
    early_fullmove: int = setting(10, "Experimental early-game boundary; not opening identification.", minimum=1, maximum=30)
    minimal_payoff_cp: int = setting(0, "Experimental maximum neutral retained payoff for low display priority.", minimum=0, maximum=100)
    major_loss_cp: int = setting(300, "Experimental minimum observed unrecouped material loss.", minimum=100, maximum=1500)
    high_payoff_cp: int = setting(500, "Experimental retained payoff for high display importance.", minimum=100, maximum=1500)
    near_equal_cp: int = setting(100, "Experimental near-equal band; never a theoretical draw.", minimum=0, maximum=300)
    winning_cp: int = setting(300, "Experimental winning/nonwinning evaluation signal.", minimum=100, maximum=1000)
    low_material_cp: int = setting(2600, "Experimental total material ceiling for near-equal endgame context.", minimum=100, maximum=5000)
    observation_plies: int = setting(3, "Recorded-game window after a capture; no best-defense claim.", minimum=2, maximum=6)


class ContextType(StrEnum):
    TACTICAL = "tactical_opportunity"
    MATERIAL_BLUNDER = "major_material_blunder"
    DEFENSIVE = "defensive_resource"
    SIMPLIFICATION = "forced_simplification"
    LOW_GEOMETRY = "low_importance_tactical_geometry"
    DRAWISH = "drawish_endgame_context"
    UNRESOLVED = "unresolved_complex_position"


class ImportanceBand(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class EvaluationEvidence:
    """One existing score, with explicit POV, exact request family and provenance."""
    fen: str
    request_identity: str
    source: str
    player_cp: int | None = None
    mate_for_player: bool | None = None

    def __post_init__(self):
        if not self.fen or not self.request_identity or not self.source:
            raise ValueError("Evaluation requires position, exact request identity and provenance")
        if (self.player_cp is None) == (self.mate_for_player is None):
            raise ValueError("Supply one known cp or mate score; missing evidence is None")
        if self.player_cp is not None and type(self.player_cp) is not int:
            raise ValueError("Centipawns must be an integer")
        if self.mate_for_player is not None and type(self.mate_for_player) is not bool:
            raise ValueError("Mate outcome must have explicit player perspective")


@dataclass(frozen=True)
class EvaluationSwing:
    eval_before: int | None
    eval_after: int | None
    player_pov_delta: int | None
    crossed_equal: bool | None
    winning_to_nonwinning: bool | None
    losing_to_recoverable: bool | None
    mate_appeared: bool | None
    mate_disappeared: bool | None
    comparable: bool


def evaluation_swing(before, after, policy=ContextPolicy()) -> EvaluationSwing:
    comparable = bool(before and after and before.request_identity == after.request_identity)
    b = before.player_cp if before else None
    a = after.player_cp if after else None
    numeric = comparable and b is not None and a is not None
    return EvaluationSwing(b, a, a-b if numeric else None,
        ((b < 0 <= a) or (a < 0 <= b)) if numeric else None,
        b >= policy.winning_cp and a < policy.winning_cp if numeric else None,
        b <= -policy.winning_cp and a >= -policy.near_equal_cp if numeric else None,
        before.mate_for_player is None and after.mate_for_player is not None if comparable else None,
        before.mate_for_player is not None and after.mate_for_player is None if comparable else None,
        comparable)


@dataclass(frozen=True)
class MomentEvidence:
    source_identity: str
    fullmove_number: int
    analyzer_state: str
    analyzer_sources: tuple[str, ...] = ()
    tactic_verified: bool | None = None
    proof_complete: bool = False
    retained_payoff_cp: int | None = None
    larger_outcome_proven: bool | None = None
    final_eval_range_cp: tuple[int, int] | None = None
    total_material_cp: int | None = None
    rook_pawn_only: bool = False
    terminal_state: str | None = None
    terminal_proven: bool = False
    defensive_proof: str | None = None
    forced_simplification_proven: bool = False
    observed_loss_cp: int | None = None
    observed_victim_type: str | None = None
    loss_supported: bool = False
    eval_before: EvaluationEvidence | None = None
    eval_after: EvaluationEvidence | None = None
    facts: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True)
class CriticalMomentContext:
    source_identity: str
    primary_context: ContextType
    supporting_contexts: tuple[ContextType, ...]
    importance_band: ImportanceBand
    evidence: tuple[str, ...]
    explanation_key: str
    analyzer_sources: tuple[str, ...]
    provenance: tuple[str, ...]
    completeness: str
    early_game: bool
    eval_swing: EvaluationSwing
    final_position_label: str
    policy_identity: str


def interpret_context(e: MomentEvidence, policy=ContextPolicy()) -> CriticalMomentContext:
    """Only supplied complete proof permits payoff/defense priority. Unknown stays unknown."""
    primary, importance = ContextType.UNRESOLVED, ImportanceBand.NORMAL
    supporting = []
    explanation = "more_evidence_needed"
    facts = list(e.facts)
    early = e.fullmove_number <= policy.early_fullmove
    if e.tactic_verified is True:
        primary, explanation = ContextType.TACTICAL, "stored_tactic_verified"
    if e.tactic_verified and e.proof_complete and e.retained_payoff_cp is not None:
        if e.retained_payoff_cp >= policy.high_payoff_cp:
            importance = ImportanceBand.HIGH
        elif early and e.larger_outcome_proven is False and 0 <= e.retained_payoff_cp <= policy.minimal_payoff_cp:
            primary, importance, explanation = ContextType.LOW_GEOMETRY, ImportanceBand.LOW, "verified_early_neutral_payoff"
    if e.loss_supported and e.observed_loss_cp is not None and e.observed_loss_cp >= policy.major_loss_cp:
        if e.tactic_verified:
            supporting.append(ContextType.TACTICAL)
        primary, importance, explanation = ContextType.MATERIAL_BLUNDER, ImportanceBand.HIGH, "observed_unrecouped_material_loss"
        if e.observed_victim_type == "queen" and e.observed_loss_cp >= policy.high_payoff_cp:
            importance = ImportanceBand.CRITICAL
        facts.append("Recorded-game loss only; later compensation and best defense are not inferred.")
    if e.proof_complete and e.defensive_proof in ("mate_prevented", "playable_position_preserved"):
        primary, importance, explanation = ContextType.DEFENSIVE, ImportanceBand.HIGH, "explicit_defensive_proof"
        if e.defensive_proof == "mate_prevented":
            importance = ImportanceBand.CRITICAL
        if e.forced_simplification_proven:
            supporting.append(ContextType.SIMPLIFICATION)
    elif e.proof_complete and e.forced_simplification_proven:
        primary, explanation = ContextType.SIMPLIFICATION, "explicit_forced_simplification_proof"
    final_label = "unknown"
    if e.final_eval_range_cp:
        lo, hi = e.final_eval_range_cp
        final_label = "unfavorable" if hi < -policy.near_equal_cp else "near_equal" if max(abs(lo),abs(hi)) <= policy.near_equal_cp else "mixed_or_outside_equal_band"
        if final_label == "near_equal" and e.total_material_cp is not None and e.total_material_cp <= policy.low_material_cp and e.rook_pawn_only:
            supporting.append(ContextType.DRAWISH)
            if primary == ContextType.UNRESOLVED:
                primary, explanation = ContextType.DRAWISH, "near_equal_low_material_not_theoretical_draw"
    if e.terminal_proven:
        if e.terminal_state == "checkmate":
            primary, importance, explanation = ContextType.TACTICAL, ImportanceBand.CRITICAL, "proven_mate_is_primary_story"
        elif e.terminal_state in ("stalemate", "insufficient_material", "other_draw"):
            explanation = "proven_terminal_draw_not_a_winning_claim"
            importance = ImportanceBand.NORMAL
    return CriticalMomentContext(e.source_identity,primary,tuple(dict.fromkeys(s for s in supporting if s != primary)),importance,
        tuple(facts),explanation,e.analyzer_sources,e.provenance,"complete_within_supplied_scope" if e.proof_complete else "partial_or_missing",
        early,evaluation_swing(e.eval_before,e.eval_after,policy),final_label,identity(policy))
