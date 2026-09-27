"""Pure factual aggregation for Opening Analysis, independent of UI and storage."""
from collections import Counter
from dataclasses import asdict, replace
from datetime import date
from statistics import mean, median
from move_quality import aggregate, QualityAggregate
from opening_accuracy import opening_variation_context, side_metrics
from opening_analysis_models import (OpeningAdherence, OpeningAccuracySummary, OpeningAnalysisGame,
    OpeningAnalysisResult, OpeningContextBreakdown, OpeningDeviation, OpeningDeviationMove,
    OpeningDeviationPosition, OpeningMatchingSet, OpeningReentry, OpeningRepertoireGap,
    OpeningVariationAccuracy, OpeningVariationGroup)
from opening_analysis_settings import OpeningAnalysisSettings
from opening_intelligence_models import VariationContext, identity


def _context_key(context: VariationContext) -> tuple:
    return context.paths, context.complete


def _contexts(rows: tuple[OpeningDeviation, ...]) -> tuple[VariationContext, ...]:
    return tuple(dict.fromkeys(row.book.variation_before for row in rows))


def _departure_quality(rows: tuple[OpeningDeviation, ...]) -> QualityAggregate:
    return replace(aggregate(row.quality for row in rows if row.quality is not None), total_moves=len(rows))


def summarize_adherence(games: tuple[OpeningAnalysisGame, ...]) -> OpeningAdherence:
    """Pool full-game known-position opportunities on each game's user side.

    Args:
        games: Matching games on the explicit repertoire side.

    Returns:
        Raw summed numerator and denominator, with no opponent/unknown penalties.
    """
    return OpeningAdherence(sum(game.adherence.in_book_moves for game in games),
                            sum(game.adherence.opportunities for game in games))


def summarize_accuracy(games: tuple[OpeningAnalysisGame, ...]) -> OpeningAccuracySummary:
    """Reuse Accuracy V1 arithmetic means over eligible user opening moves.

    Args:
        games: Matching game results with unchanged book-derived accuracy windows.

    Returns:
        Pooled score, raw losses/best matches and explicit evidence coverage.
    """
    values = side_metrics((row for game in games for row in game.accuracy.moves if row.party == 'user'), 'user')
    return OpeningAccuracySummary(values.quality, values.missing_evidence, values.unresolved_moves)


def summarize_variations(games: tuple[OpeningAnalysisGame, ...]) -> tuple[OpeningVariationGroup, ...]:
    """Group full-game final contexts by complete named-anchor paths.

    Args:
        games: Matching full-game results.

    Returns:
        Stable groups, retaining ambiguous paths and explicit unnamed trunks.
    """
    grouped = {}
    for game in games:
        grouped.setdefault(_context_key(game.book.final_variation), []).append(game)
    return tuple(OpeningVariationGroup(VariationContext(paths, False, complete),
        tuple(game.context.game_id for game in members)) for (paths, complete), members in grouped.items())


def summarize_variation_accuracy(games: tuple[OpeningAnalysisGame, ...]) -> tuple[OpeningVariationAccuracy, ...]:
    """Summarize scores by the last known context inside each opening window.

    Args:
        games: Matching games with shared Accuracy V1 evidence.

    Returns:
        Pooled move means and separately labeled mean/median game scores.
    """
    grouped = {}
    for game in games:
        grouped.setdefault(_context_key(opening_variation_context(game.accuracy)), []).append(game)
    output = []
    for (paths, complete), members in grouped.items():
        scores = tuple(game.accuracy.user.quality.accuracy for game in members
                       if game.accuracy.user and game.accuracy.user.quality.accuracy is not None)
        games_in_group = tuple(members)
        output.append(OpeningVariationAccuracy(VariationContext(paths, False, complete),
            tuple(game.context.game_id for game in members), len(scores),
            sum(bool(game.accuracy.user and game.accuracy.user.quality.complete) for game in members),
            summarize_accuracy(games_in_group), mean(scores) if scores else None,
            median(scores) if scores else None, summarize_adherence(games_in_group)))
    return tuple(output)


def summarize_deviations(games: tuple[OpeningAnalysisGame, ...], party: str) -> tuple[OpeningDeviationPosition, ...]:
    """Group actual departures by full canonical position, then actual move.

    Args:
        games: Matching game results.
        party: User or opponent.

    Returns:
        Most frequent positions first, with distinct-game counts and raw quality facts.

    Raises:
        ValueError: Party is neither user nor opponent.
    """
    if party not in ('user', 'opponent'):
        raise ValueError('Departure party must be user or opponent.')
    grouped = {}
    for game in games:
        for departure in game.deviations:
            if departure.party == party:
                grouped.setdefault(departure.book.position.canonical_fen, []).append(departure)
    output = []
    for members in grouped.values():
        rows = tuple(members)
        moves = {}
        for row in rows:
            moves.setdefault(row.book.played_uci, []).append(row)
        details = []
        for uci, move_rows in moves.items():
            values = tuple(move_rows)
            details.append(OpeningDeviationMove(uci, values[0].book.played_san, len(values),
                tuple(dict.fromkeys(row.book.game_id for row in values)), values[0].continuations,
                _departure_quality(values), tuple(row.quality.accuracy for row in values
                    if row.quality is not None and row.quality.accuracy is not None)))
        first = rows[0].book
        output.append(OpeningDeviationPosition(party, first.position, len(rows),
            tuple(dict.fromkeys(row.book.game_id for row in rows)), _contexts(rows),
            first.available_moves, first.preferred_move,
            tuple(sorted(details, key=lambda value: (-value.count, value.move_uci))), _departure_quality(rows)))
    return tuple(sorted(output, key=lambda value: (-value.count, value.position.canonical_fen)))


def summarize_gaps(games: tuple[OpeningAnalysisGame, ...],
                   settings: OpeningAnalysisSettings = OpeningAnalysisSettings()) -> tuple[OpeningRepertoireGap, ...]:
    """Find repeated opponent moves lacking an active authored resulting continuation.

    Args:
        games: Matching games with actual opponent departures.
        settings: Shared typed distinct-game threshold; no coaching policy.

    Returns:
        Neutral repertoire_gap_candidate facts, never claims of chess weakness.
    """
    grouped = {}
    for game in games:
        for row in game.deviations:
            if row.party == 'opponent' and not row.continuations:
                grouped.setdefault((row.book.position.canonical_fen, row.book.played_uci), []).append(row)
    result = []
    for members in grouped.values():
        rows = tuple(members)
        game_ids = tuple(dict.fromkeys(row.book.game_id for row in rows))
        if len(game_ids) >= settings.gap_minimum_games:
            first = rows[0].book
            result.append(OpeningRepertoireGap(first.position, first.played_uci, first.played_san,
                len(rows), game_ids, _contexts(rows)))
    return tuple(sorted(result, key=lambda value: (-len(value.game_ids), value.position.canonical_fen, value.move_uci)))


def _breakdowns(games: tuple[OpeningAnalysisGame, ...]) -> OpeningContextBreakdown:
    results, dates = Counter(), []
    for game in games:
        context = game.context
        if context.result == '1/2-1/2':
            outcome = 'draw'
        elif context.result in ('1-0', '0-1'):
            winner = 'white' if context.result == '1-0' else 'black'
            outcome = 'win' if winner == context.user_color else 'loss'
        else:
            outcome = 'unknown'
        results[outcome] += 1
        try:
            dates.append(date.fromisoformat((context.played_at or '')[:10].replace('.', '-')).isoformat())
        except ValueError:
            pass
    def counts(field: str) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(Counter(getattr(game.context, field) or 'unknown' for game in games).items()))
    return OpeningContextBreakdown(tuple(sorted(results.items())), counts('user_color'), counts('source'),
        counts('time_class'), counts('time_control'), min(dates) if dates else None,
        max(dates) if dates else None, len(games) - len(dates))


def summarize_opening_analysis(matching: OpeningMatchingSet, games: tuple[OpeningAnalysisGame, ...],
                               settings: OpeningAnalysisSettings, policy_identity: str) -> OpeningAnalysisResult:
    """Compose factual summaries with scope/book/policy/evidence currentness.

    Args:
        matching: Explicit transient scope with exclusions and errors.
        games: Successful matching game results.
        settings: Neutral aggregation settings.
        policy_identity: Combined summary and existing accuracy policy identity.

    Returns:
        Immutable result suitable for future frontends, Collections and lessons.
    """
    reentries = []
    for game in games:
        phase = game.accuracy.phase
        for row in game.book.moves:
            if row.reentry:
                reentries.append(OpeningReentry(game.context.game_id, row.ply, row.after_position,
                    row.variation_after, bool(phase and phase.start_ply <= row.ply <= phase.end_ply)))
    evidence = tuple((asdict(game.context), game.book.game_identity,
        asdict(game.accuracy.phase) if game.accuracy.phase else None,
        tuple(asdict(row.quality) if row.quality else None for row in game.accuracy.moves),
        tuple(asdict(row.quality) if row.quality else None for row in game.deviations)) for game in games)
    result_id = identity((asdict(matching), policy_identity, evidence))
    return OpeningAnalysisResult(matching, games, summarize_adherence(games), summarize_accuracy(games),
        summarize_variations(games), summarize_variation_accuracy(games), summarize_deviations(games, 'user'),
        summarize_deviations(games, 'opponent'), summarize_gaps(games, settings), tuple(reentries),
        _breakdowns(games), result_id)
