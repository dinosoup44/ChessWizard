"""Immutable book and engine facts; neither dimension substitutes for the other."""
from dataclasses import dataclass
from move_quality import MoveQuality, QualityAggregate
from opening_intelligence_models import OpeningGameAssessment, OpeningMoveAssessment, OpeningFailure, BookProvenance


@dataclass(frozen=True)
class OpeningPhase:
    start_ply: int
    end_ply: int
    last_known_ply: int
    end_reason: str


@dataclass(frozen=True)
class OpeningMoveQuality:
    book: OpeningMoveAssessment
    quality: MoveQuality | None
    party: str

    @property
    def evidence_complete(self):
        return self.quality is not None and self.quality.evidence_complete

    @property
    def accuracy(self):
        return self.quality.accuracy if self.quality else None

    @property
    def eval_loss_cp(self):
        return self.quality.eval_loss_cp if self.quality else None


@dataclass(frozen=True)
class OpeningSideMetrics:
    color: str
    quality: QualityAggregate
    in_book_moves: int
    book_opportunities: int
    first_deviation: OpeningMoveQuality | None
    missing_evidence: int
    unresolved_moves: int

    @property
    def adherence(self):
        return 100*self.in_book_moves/self.book_opportunities if self.book_opportunities else None

    @property
    def status(self):
        if not self.quality.total_moves: return 'no_moves'
        if self.quality.complete: return 'complete'
        if self.quality.evaluated_moves: return 'partial'
        return 'unresolved' if self.unresolved_moves else 'not_analyzed'


@dataclass(frozen=True)
class OpeningGameAccuracy:
    opening: OpeningGameAssessment
    phase: OpeningPhase | None
    moves: tuple[OpeningMoveQuality, ...]
    white: OpeningSideMetrics
    black: OpeningSideMetrics
    policy_identity: str
    quality_identity: str

    @property
    def applicable(self): return self.phase is not None

    @property
    def user(self):
        return getattr(self, self.opening.user_color) if self.opening.user_color else None

    @property
    def opponent(self):
        return getattr(self, 'black' if self.opening.user_color == 'white' else 'white') if self.opening.user_color else None


@dataclass(frozen=True)
class OpeningAccuracyBatch:
    results: tuple[OpeningGameAccuracy, ...]
    errors: tuple[OpeningFailure, ...]


@dataclass(frozen=True)
class VariationAccuracy:
    provenance: BookProvenance
    policy_identity: str
    quality_identity: str
    variation_path: tuple[str, ...]
    variation_ids: tuple[int, ...]
    ambiguous: bool
    games: int
    complete_games: int
    unknown_user_games: int
    user: OpeningSideMetrics


@dataclass(frozen=True)
class OpeningVariationAccuracySummary:
    groups: tuple[VariationAccuracy, ...]
    errors: tuple[OpeningFailure, ...]
    results: tuple[OpeningGameAccuracy, ...]


@dataclass(frozen=True)
class OpeningDeviationQualitySummary:
    deviations: tuple[OpeningMoveQuality, ...]
    errors: tuple[OpeningFailure, ...]
    results: tuple[OpeningGameAccuracy, ...]
