"""Pure authored-window selection and reuse of Accuracy V1 aggregation."""
from dataclasses import replace
from move_quality import aggregate
from opening_book_models import position_identity
from opening_intelligence_models import OpeningGameAssessment, OpeningMatchPolicy, VariationContext, identity
from dataclasses import asdict
from opening_accuracy_settings import OpeningAccuracySettings
from opening_accuracy_models import (OpeningPhase, OpeningMoveQuality, OpeningSideMetrics,
                                     OpeningGameAccuracy, VariationAccuracy)


def opening_phase(assessment: OpeningGameAssessment, match_policy: OpeningMatchPolicy = OpeningMatchPolicy(),
                  settings: OpeningAccuracySettings = OpeningAccuracySettings()) -> OpeningPhase | None:
    """Select the existing bounded window after meaningful opening entry.

    Args:
        assessment: Legal game replay with legacy run or explicit position entry.
        match_policy: Matching policy used to derive the supplied facts.
        settings: Unchanged accuracy-window and numerical scoring settings.

    Returns:
        Eligible decision window, or None before entry or when no decisions remain.
        Explicit entry starts at the next decision; legacy authored runs retain
        their original window. Numerical Accuracy formulas are unchanged.

    Raises:
        ValueError: Policy identity or meaningful-match facts are inconsistent.
    """
    if identity(asdict(match_policy)) != assessment.provenance.policy_identity:
        raise ValueError('Opening match policy must match the assessed book facts.')
    if not assessment.meaningful_match: return None
    run = 0
    start = assessment.entry_ply + 1 if assessment.entry_ply is not None else None
    for row in assessment.moves if start is None else ():
        run = run+1 if row.played_move_in_book else 0
        if run >= match_policy.min_consecutive_plies:
            start = row.ply-run+1
            break
    if start is None: raise ValueError('Meaningful match has no confirming authored run.')
    if start > assessment.total_plies: return None
    last_known = start-1
    end = start-1
    for row in assessment.moves[start-1:]:
        if row.ply > last_known + settings.continuation_plies: break
        end = row.ply
        if row.after_position_id is not None: last_known = row.ply
    return OpeningPhase(start, end, last_known, 'game_end' if end == assessment.total_plies else 'book_gap_limit')


def side_metrics(rows, color):
    """Pool per-move V1 scores; unknown positions are never adherence failures."""
    rows = tuple(rows)
    scored = aggregate(row.quality for row in rows if row.quality is not None)
    quality = replace(scored, total_moves=len(rows))
    opportunities = tuple(row for row in rows if row.book.position_in_book)
    return OpeningSideMetrics(color, quality, sum(row.book.played_move_in_book for row in opportunities),
        len(opportunities), next((row for row in rows if row.book.deviation), None),
        sum(not row.evidence_complete for row in rows),
        sum(row.evidence_complete and row.accuracy is None for row in rows))


def derive_opening_accuracy(assessment, qualities, *, match_policy=OpeningMatchPolicy(), settings=OpeningAccuracySettings()):
    """Join exact actual moves, rejecting incompatible quality/profile identities.

    Supplied MoveQuality values must come from the shared evidence assessment path;
    this layer never turns book weights or absent engine results into scores.
    """
    phase = opening_phase(assessment, match_policy, settings)
    by_ply = {value.move.step:value for value in qualities}
    rows = []
    for book in assessment.moves[phase.start_ply-1:phase.end_ply] if phase else ():
        quality = by_ply.get(book.ply)
        if quality is not None:
            move = quality.move
            if (move.game_id != assessment.game_id or move.move_id != book.move_id
                    or move.played_move != book.played_uci or move.mover_color != book.actor_color
                    or position_identity(move.fen) != book.position):
                raise ValueError('Quality evidence does not describe the same actual game move.')
            if (quality.result_identity != settings.quality.currentness_identity
                    or quality.best_request_identity != settings.quality.raw_identity):
                quality = None
        party = 'unknown' if assessment.user_color is None else 'user' if book.actor_color == assessment.user_color else 'opponent'
        rows.append(OpeningMoveQuality(book, quality, party))
    return OpeningGameAccuracy(assessment, phase, tuple(rows),
        side_metrics((row for row in rows if row.book.actor_color == 'white'), 'white'),
        side_metrics((row for row in rows if row.book.actor_color == 'black'), 'black'),
        settings.currentness_identity, settings.quality.currentness_identity)


def opening_variation_context(result: OpeningGameAccuracy) -> VariationContext:
    """Label an accuracy window without borrowing a later excluded transposition.

    Args:
        result: Existing book-derived opening accuracy result.

    Returns:
        Last known named context inside the scored window, preserving ambiguity.
    """
    context = result.opening.initial_variation
    for row in result.moves:
        if row.book.after_position_id is not None:
            context = row.book.variation_after
    return context


def variation_accuracy(results: tuple[OpeningGameAccuracy, ...]) -> tuple[VariationAccuracy, ...]:
    """Pool user moves, not game means; group by authored anchor IDs and full path.

    Args:
        results: Compatible game results from the existing opening accuracy service.

    Returns:
        Existing variation summaries with pooled user-move accuracy.
    """
    groups = {}
    for result in results:
        if not result.applicable: continue
        context = opening_variation_context(result)
        ids = tuple(node.move_id for node in context.path)
        names = tuple(node.name for node in context.path)
        key = (result.opening.provenance, result.policy_identity, result.quality_identity, ids, names, context.ambiguous)
        groups.setdefault(key, []).append(result)
    output = []
    for (provenance, policy_id, quality_id, ids, names, ambiguous), games in groups.items():
        user_rows = tuple(row for game in games for row in game.moves if row.party == 'user')
        output.append(VariationAccuracy(provenance, policy_id, quality_id, names, ids, ambiguous, len(games),
            sum(game.user is not None and game.user.quality.complete for game in games),
            sum(game.user is None for game in games), side_metrics(user_rows, 'user')))
    return tuple(sorted(output, key=lambda group:(group.variation_path,group.variation_ids,group.ambiguous)))
