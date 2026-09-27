"""Consumer-neutral feedback contracts. None means no stored evidence."""
from dataclasses import dataclass, field
from exchange_presentation import ExchangePresentation
from tactical_opportunities import TacticalMotif, TacticalOutcome, LineRelationship, ProofEvidence


@dataclass(frozen=True)
class FeedbackFact:
    """An adapter-normalized fact and the stored fields supporting it."""
    kind: str
    values: tuple[tuple[str, str], ...]
    sources: tuple[str, ...]


@dataclass(frozen=True)
class FeedbackContext:
    candidate_id: int | None = None
    move_id: int | None = None
    game_id: int | None = None
    player_color: str | None = None
    move_number: int | None = None
    fen_before: str | None = None
    played_move: str | None = None
    recommended_move: str | None = None
    tactic_type: str | None = None
    primary_outcome: TacticalOutcome | None = None
    motifs: tuple[TacticalMotif, ...] = ()
    payoff_timing: str | None = None
    proof: ProofEvidence = field(default_factory=ProofEvidence)
    proof_line: str | None = None
    relationships: tuple[LineRelationship, ...] = ()
    presentation_level: str | None = None
    confidence: float | None = None
    facts: tuple[FeedbackFact, ...] = ()
    # JSON snapshots retain optional evidence without exposing mutable dictionaries.
    source_metadata_json: str | None = None
    opportunity_metadata_json: str | None = None
    legacy_metadata_json: str | None = None
    notes: str | None = None
    provenance: tuple[tuple[str, str], ...] = ()
    warnings: tuple[str, ...] = ()
    exchange_presentation: ExchangePresentation | None = None
    recorded_evaluation_delta_cp: int | None = None


@dataclass(frozen=True)
class FeedbackResult:
    title: str
    short_summary: str
    explanation: str
    outcome_label: str | None
    motif_labels: tuple[str, ...]
    context_motif_labels: tuple[str, ...]
    played_move_label: str
    recommended_move_label: str
    proof_summary: str | None
    presentation_level: str
    detail_level: str
    teaching_note: str | None = None
    warning_note: str | None = None
    provenance: tuple[tuple[str, str], ...] = ()
    attribution_labels: tuple[str, ...] = ()
    relationship_labels: tuple[str, ...] = ()
    proof_line: str | None = None
    exchange_continuation: str | None = None
    exchange_summary: str | None = None
