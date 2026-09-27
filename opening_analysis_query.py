"""Portable Explorer filters over an already computed transient opening result."""
from dataclasses import dataclass
import math
from opening_analysis_models import OpeningAnalysisGame, OpeningAnalysisResult


@dataclass(frozen=True)
class OpeningAnalysisQuery:
    """Filter factual results without new analysis, saved collections or coaching labels.

    Args:
        library_identity: Optional exact library namespace.
        book_id: Optional stable library-local book ID.
        variation_name: Authored name observed during active book play.
        variation_move_id: Optional named anchor ID to disambiguate equal names.
        include_ambiguous_variations: Allow any retained ambiguous path to match.
        accuracy_min: Inclusive minimum available user opening accuracy.
        accuracy_max: Inclusive maximum available user opening accuracy.
        require_complete_accuracy: Require complete scores when a numeric accuracy bound is set.
        adherence_min: Inclusive minimum full-game known-position adherence.
        adherence_max: Inclusive maximum full-game known-position adherence.
        user_deviated: Filter whether any user departure occurred.
        opponent_deviated: Filter whether any opponent departure occurred.
        repertoire_gap: Filter membership in a repeated-gap candidate.
        minimum_deviation_loss_cp: Caller-specified user loss boundary, never a hidden label.
    """
    library_identity: str | None = None
    book_id: int | None = None
    variation_name: str = ''
    variation_move_id: int | None = None
    include_ambiguous_variations: bool = False
    accuracy_min: float | None = None
    accuracy_max: float | None = None
    require_complete_accuracy: bool = True
    adherence_min: float | None = None
    adherence_max: float | None = None
    user_deviated: bool | None = None
    opponent_deviated: bool | None = None
    repertoire_gap: bool | None = None
    minimum_deviation_loss_cp: float | None = None

    def __post_init__(self) -> None:
        """Reject invalid ranges rather than silently creating misleading filters."""
        for field in ('accuracy', 'adherence'):
            low, high = getattr(self, field + '_min'), getattr(self, field + '_max')
            for value in (low, high):
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100):
                    raise ValueError('Percentage filters must be finite values from 0 to 100.')
            if low is not None and high is not None and low > high:
                raise ValueError('Minimum cannot exceed maximum.')
        for value in (self.book_id, self.variation_move_id):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError('Book and anchor IDs must be positive integers.')
        for value in (self.user_deviated, self.opponent_deviated, self.repertoire_gap):
            if value is not None and type(value) is not bool:
                raise ValueError('Departure/gap filters must be Boolean or None.')
        if (type(self.include_ambiguous_variations) is not bool or type(self.require_complete_accuracy) is not bool
                or not isinstance(self.variation_name, str)):
            raise ValueError('Invalid variation filter.')
        if self.library_identity is not None and (not isinstance(self.library_identity, str) or not self.library_identity):
            raise ValueError('Use a nonempty library identity.')
        loss = self.minimum_deviation_loss_cp
        if loss is not None and (type(loss) not in (int, float) or not math.isfinite(loss) or loss < 0):
            raise ValueError('Deviation loss threshold must be finite and nonnegative.')


def filter_opening_games(result: OpeningAnalysisResult,
                         query: OpeningAnalysisQuery = OpeningAnalysisQuery()) -> tuple[OpeningAnalysisGame, ...]:
    """Filter a computed result; missing scores never satisfy a numeric constraint.

    Args:
        result: Immutable selected-book analysis, including its own errors/exclusions.
        query: Explicit factual filters for future Explorer or Professor clients.

    Returns:
        Matching detailed games in their original scope order. No persistence occurs.
    """
    book = result.matching_set.provenance
    if ((query.library_identity is not None and query.library_identity != book.library_identity)
            or (query.book_id is not None and query.book_id != book.book_id)):
        return ()
    gaps = {gid for gap in result.repertoire_gaps for gid in gap.game_ids}
    matches = []
    for game in result.games:
        if any(expected is not None and observed != expected for expected, observed in (
            (query.user_deviated, game.first_user_deviation is not None),
            (query.opponent_deviated, game.first_opponent_deviation is not None),
            (query.repertoire_gap, game.context.game_id in gaps))):
            continue
        accuracy = game.accuracy.user.quality.accuracy if game.accuracy.user else None
        if (query.require_complete_accuracy and (query.accuracy_min is not None or query.accuracy_max is not None)
                and (game.accuracy.user is None or not game.accuracy.user.quality.complete)):
            continue
        if any((low is not None and (value is None or value < low))
               or (high is not None and (value is None or value > high))
               for value, low, high in ((accuracy, query.accuracy_min, query.accuracy_max),
                   (game.adherence.percentage, query.adherence_min, query.adherence_max))):
            continue
        if query.variation_name or query.variation_move_id is not None:
            if not any((not query.variation_name or node.name == query.variation_name)
                       and (query.variation_move_id is None or node.move_id == query.variation_move_id)
                       for row in game.book.moves if row.played_move_in_book
                       for context in (row.variation_after,)
                       if query.include_ambiguous_variations or not context.ambiguous
                       for path in context.paths for node in path):
                continue
        if query.minimum_deviation_loss_cp is not None and not any(
            row.party == 'user' and row.quality is not None and row.quality.eval_loss_cp is not None
            and row.quality.eval_loss_cp >= query.minimum_deviation_loss_cp for row in game.deviations):
            continue
        matches.append(game)
    return tuple(matches)
