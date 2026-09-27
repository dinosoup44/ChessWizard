"""Portable immutable opening-analysis outputs; book facts and engine facts stay separate."""
from dataclasses import dataclass
from move_quality import MoveQuality, QualityAggregate
from opening_accuracy_models import OpeningGameAccuracy
from opening_book_models import OpeningMove, PositionIdentity
from opening_intelligence_models import (BookProvenance, OpeningFailure, OpeningGameAssessment,
                                         OpeningMoveAssessment, VariationContext)
from opening_repertoire import RepertoireSide


@dataclass(frozen=True)
class OpeningGameContext:
    """Identify a stored game without guessing player ownership from usernames.

    Args:
        game_id: Database-local identifier.
        user_id: Stored owner identifier.
        source: Import source.
        source_game_id: Source-native identifier, when available.
        played_at: Original recorded date/time.
        white_username: White player.
        black_username: Black player.
        user_color: Stored user side, or None when unknown.
        result: Original result token.
        time_control: Original time-control text.
        time_class: Stored speed category.
    """
    game_id: int
    user_id: int | None
    source: str | None
    source_game_id: str | None
    played_at: str | None
    white_username: str | None
    black_username: str | None
    user_color: str | None
    result: str | None
    time_control: str | None
    time_class: str | None


@dataclass(frozen=True)
class OpeningAdherence:
    """Count active user moves divided by known-position user opportunities.

    Args:
        in_book_moves: User moves matching an active authored alternative.
        opportunities: User decisions from active root-reachable known positions.
    """
    in_book_moves: int
    opportunities: int

    @property
    def percentage(self) -> float | None:
        """Expose adherence without inventing a denominator.

        Returns:
            Percentage, or None when there were no opportunities.
        """
        return 100 * self.in_book_moves / self.opportunities if self.opportunities else None


@dataclass(frozen=True)
class OpeningAccuracySummary:
    """Reuse Accuracy V1 aggregation with explicit missing/unresolved denominators.

    Args:
        quality: Pooled per-move Accuracy V1 metrics; never an average of game means.
        missing_evidence: Eligible moves lacking complete compatible evidence.
        unresolved_moves: Complete evidence with no defensible numeric accuracy.
    """
    quality: QualityAggregate
    missing_evidence: int
    unresolved_moves: int

    @property
    def coverage_percentage(self) -> float | None:
        """Expose the numeric evidence denominator.

        Returns:
            Scored/eligible percentage, or None for no eligible moves.
        """
        return 100 * self.quality.evaluated_moves / self.quality.total_moves if self.quality.total_moves else None

    @property
    def status(self) -> str:
        """Describe completeness independently of the numeric score.

        Returns:
            Complete, partial, unresolved, not_analyzed or no_moves status.
        """
        if not self.quality.total_moves:
            return 'no_moves'
        if self.quality.complete:
            return 'complete'
        if self.quality.evaluated_moves:
            return 'partial'
        return 'unresolved' if self.unresolved_moves else 'not_analyzed'


@dataclass(frozen=True)
class OpeningDeviation:
    """Describe an actual departure, without assigning a chess judgment.

    Args:
        book: Existing per-move authored facts, alternatives, weights and provenance.
        fen_before: Exact played-game FEN, including clocks for evidence identity.
        party: User or opponent according to stored ownership.
        first_for_party: Whether this is that party's first known-position departure.
        quality: Compatible existing engine facts, or None outside requested evidence.
        in_accuracy_window: Whether this move lies in the book-derived scoring window.
        continuations: Active authored moves from the actual resulting position.
    """
    book: OpeningMoveAssessment
    fen_before: str
    party: str
    first_for_party: bool
    quality: MoveQuality | None
    in_accuracy_window: bool
    continuations: tuple[OpeningMove, ...]


@dataclass(frozen=True)
class OpeningAnalysisGame:
    """Compose context, full-game book facts and the unchanged opening score window.

    Args:
        context: Stored game/source/user metadata.
        book: Full legal replay against the selected authored book.
        accuracy: Existing bounded-window Accuracy V1 result.
        adherence: Full-game known-position user opportunities, including re-entry.
        deviations: All known-position user/opponent departures in actual order.
    """
    context: OpeningGameContext
    book: OpeningGameAssessment
    accuracy: OpeningGameAccuracy
    adherence: OpeningAdherence
    deviations: tuple[OpeningDeviation, ...]

    @property
    def first_user_deviation(self) -> OpeningDeviation | None:
        """Find the first user departure, including one before meaningful entry.

        Returns:
            First departure record, or None when no user departure occurred.
        """
        return next((row for row in self.deviations if row.party == 'user'), None)

    @property
    def first_opponent_deviation(self) -> OpeningDeviation | None:
        """Find the first opponent departure independently of the user's first.

        Returns:
            First opponent departure, or None.
        """
        return next((row for row in self.deviations if row.party == 'opponent'), None)

    @property
    def meaningful_match_depth(self) -> int:
        """Expose the depth supporting this game's meaningful match.

        Returns:
            Longest consecutive active authored run, measured in plies.
        """
        return self.book.max_consecutive_in_book_plies


@dataclass(frozen=True)
class OpeningDeviationMove:
    """Summarize one actual move at a canonical departure position.

    Args:
        move_uci: Actual legal move.
        move_san: SAN in this canonical position.
        count: Departure visits, including repeat visits in a game.
        game_ids: Distinct affected games.
        continuations: Active authored replies after this move, if any.
        quality: Existing per-move engine aggregate; missing observations stay counted.
        accuracies: Available raw accuracy values for transparent distributions.
    """
    move_uci: str
    move_san: str
    count: int
    game_ids: tuple[int, ...]
    continuations: tuple[OpeningMove, ...]
    quality: QualityAggregate
    accuracies: tuple[float, ...]


@dataclass(frozen=True)
class OpeningDeviationPosition:
    """Group departures by full canonical position, retaining distinct variation contexts.

    Args:
        party: User or opponent.
        position: Full canonical state; the 64-bit key alone is not used for grouping.
        count: Number of departure visits.
        game_ids: Distinct affected games.
        variations: All observed or inferred contexts, including ambiguity.
        alternatives: Active authored moves and their author weights.
        preferred_move: Author preference, separate from engine best.
        moves: Frequency and engine facts by actual move.
        quality: Pooled existing engine facts across these departures.
    """
    party: str
    position: PositionIdentity
    count: int
    game_ids: tuple[int, ...]
    variations: tuple[VariationContext, ...]
    alternatives: tuple[OpeningMove, ...]
    preferred_move: OpeningMove | None
    moves: tuple[OpeningDeviationMove, ...]
    quality: QualityAggregate


@dataclass(frozen=True)
class OpeningRepertoireGap:
    """Flag repeated opponent departures with no active authored continuation.

    Args:
        position: Opponent's known repertoire decision position.
        move_uci: Repeated actual opponent move.
        move_san: SAN for that position.
        count: Departure visits.
        game_ids: Distinct affected games; this count controls eligibility.
        variations: All retained authored contexts.
        signal: Neutral machine-readable signal, never a claim of weakness.
    """
    position: PositionIdentity
    move_uci: str
    move_san: str
    count: int
    game_ids: tuple[int, ...]
    variations: tuple[VariationContext, ...]
    signal: str = 'repertoire_gap_candidate'


@dataclass(frozen=True)
class OpeningReentry:
    """Describe a real unknown-to-known return without relabeling its approach move.

    Args:
        game_id: Affected stored game.
        ply: Actual ply that reaches the known position.
        position: Reached canonical position.
        variation: Context after re-entry, including unresolved transpositions.
        within_accuracy_window: Whether the existing bounded window still applies.
    """
    game_id: int
    ply: int
    position: PositionIdentity
    variation: VariationContext
    within_accuracy_window: bool


@dataclass(frozen=True)
class OpeningVariationGroup:
    """Retain complete authored paths rather than flattening equal names.

    Args:
        context: Full named-anchor path alternatives, or explicit unnamed trunk.
        game_ids: Distinct games grouped by their final known context.
    """
    context: VariationContext
    game_ids: tuple[int, ...]


@dataclass(frozen=True)
class OpeningVariationAccuracy:
    """Describe opening-window scores without ranking variations.

    Args:
        context: Last known context inside the scored window.
        game_ids: Games whose opening windows belong to this context.
        scored_games: Games with at least one scored user opening move.
        complete_games: Games with complete user opening scores.
        accuracy: Pooled user-move statistics.
        average_game_accuracy: Unweighted mean of scored game means, explicitly separate.
        median_game_accuracy: Median of scored game means.
        adherence: Full-game known-position adherence for these games.
    """
    context: VariationContext
    game_ids: tuple[int, ...]
    scored_games: int
    complete_games: int
    accuracy: OpeningAccuracySummary
    average_game_accuracy: float | None
    median_game_accuracy: float | None
    adherence: OpeningAdherence


@dataclass(frozen=True)
class OpeningContextBreakdown:
    """Return descriptive counts without conclusions about opening strength.

    Args:
        results: User-perspective win/loss/draw/unknown counts.
        colors: Stored user-color counts.
        sources: Import-source counts.
        time_classes: Stored speed categories.
        time_controls: Original time-control values.
        first_date: Earliest parseable played date, in ISO format.
        last_date: Latest parseable played date, in ISO format.
        undated_games: Games without a parseable date.
    """
    results: tuple[tuple[str, int], ...]
    colors: tuple[tuple[str, int], ...]
    sources: tuple[tuple[str, int], ...]
    time_classes: tuple[tuple[str, int], ...]
    time_controls: tuple[tuple[str, int], ...]
    first_date: str | None
    last_date: str | None
    undated_games: int


@dataclass(frozen=True)
class OpeningAnalysisExclusion:
    """Explain why a selected game did not enter the transient matching set.

    Args:
        game_id: Database-local ID.
        reason: Nonmatching book, wrong side, unknown color, or explicit scope exclusion.
        meaningful_match: Whether replay meaningfully matched before side filtering.
    """
    game_id: int
    reason: str
    meaningful_match: bool = False


@dataclass(frozen=True)
class OpeningMatchingSet:
    """Hold a transient collection-ready scope; constructing it never persists a Collection.

    Args:
        provenance: Exact selected book/library/version/content contract.
        repertoire_side: Explicit intended side; unspecified legacy books are not guessed.
        database_identity: Namespace for database-local game IDs.
        user_id: Selected owner; None only for an empty/unknown-owner scope.
        requested_game_ids: Validated input scope before book/side matching.
        game_ids: Meaningful matches on the intended user side.
        meaningful_before_side: Meaningful matches before side filtering.
        exclusions: Transparent nonmatching or wrong-side records.
        errors: Invalid/missing games that could not be assessed.
    """
    provenance: BookProvenance
    repertoire_side: RepertoireSide
    database_identity: str
    user_id: int | None
    requested_game_ids: tuple[int, ...]
    game_ids: tuple[int, ...]
    meaningful_before_side: int
    exclusions: tuple[OpeningAnalysisExclusion, ...]
    errors: tuple[OpeningFailure, ...]


@dataclass(frozen=True)
class OpeningAnalysisResult:
    """Share one immutable computation across Review, Explorer, Collections and Professor.

    Args:
        matching_set: Transient selected-book game scope and exclusions.
        games: Detailed matching game results.
        adherence: Full-game known-position user numerator/denominator.
        accuracy: Pooled bounded-window user Accuracy V1.
        variations: Full-game final known variation distribution.
        variation_accuracy: Independently labeled opening-window variation statistics.
        user_deviations: Repeated-position user departure summaries.
        opponent_deviations: Repeated-position opponent departure summaries.
        repertoire_gaps: Repeated opponent moves lacking active continuation.
        reentries: All actual unknown-to-known returns.
        contexts: Descriptive result/source/date/speed breakdowns.
        result_identity: Book/side/scope/policy/evidence identity of this computation.
    """
    matching_set: OpeningMatchingSet
    games: tuple[OpeningAnalysisGame, ...]
    adherence: OpeningAdherence
    accuracy: OpeningAccuracySummary
    variations: tuple[OpeningVariationGroup, ...]
    variation_accuracy: tuple[OpeningVariationAccuracy, ...]
    user_deviations: tuple[OpeningDeviationPosition, ...]
    opponent_deviations: tuple[OpeningDeviationPosition, ...]
    repertoire_gaps: tuple[OpeningRepertoireGap, ...]
    reentries: tuple[OpeningReentry, ...]
    contexts: OpeningContextBreakdown
    result_identity: str
