"""Pure Opening Review projections over established authored/evidence contracts."""
from dataclasses import asdict, dataclass
from opening_analysis_models import OpeningAnalysisGame, OpeningAnalysisResult
from opening_intelligence_models import OpeningGameAssessment, OpeningMoveAssessment, identity
from opening_intelligence_presentation import context_text
from move_quality import MoveQuality


@dataclass(frozen=True)
class OpeningMoment:
    """Retain an exact actual-game decision anchor and its separate opening/evidence facts.

    Args:
        key: Unique per-game presentation key.
        book: Existing legal per-move membership/context facts.
        kind: Neutral event label; a departure is not automatically a mistake.
        quality: Compatible stored engine evidence when available.
        tags: All compatible event classifications at this exact game/ply.
    """
    key: str
    book: OpeningMoveAssessment
    kind: str
    quality: MoveQuality | None = None
    tags: tuple[str, ...] = ()


def opening_moments(assessment: OpeningGameAssessment | None,
                    game: OpeningAnalysisGame | None = None,
                    result: OpeningAnalysisResult | None = None) -> tuple[OpeningMoment, ...]:
    """Combine event tags at each exact game/ply without changing analysis policy.

    Args:
        assessment: Current game's complete legal opening replay.
        game: Matching-side engine/adherence facts, if this game belongs to the result.
        result: Existing aggregate gap signals; their repetition threshold is unchanged.

    Returns:
        One neutral event per actual ply, retaining full Opening provenance and quality.
    """
    if assessment is None or not assessment.meaningful_match:
        return ()
    evidence = {d.book.ply:d.quality for d in game.deviations} if game else {}
    if game:
        evidence.update({m.book.ply:m.quality for m in game.accuracy.moves if m.quality is not None})
    gaps = {(g.position,g.move_uci) for g in result.repertoire_gaps} if result else set()
    events = []
    for row in assessment.moves:
        labels = []
        if row.deviation:
            labels.append({'user':'User deviation','opponent':'Opponent left opening'}.get(row.deviation_relation,'Deviation (side unknown)'))
        if row.deviation_relation == 'opponent' and (row.position,row.played_uci) in gaps:
            labels.append('Opening gap')
        if row.reentry:
            labels.append('Re-entry into opening')
        if row.played_move_in_book and row.preferred_move is not None:
            labels.append('Opening continuation')
        if labels:
            key = identity((assessment.game_identity, asdict(assessment.provenance),
                            row.game_id, row.move_id, row.ply))
            events.append(OpeningMoment(key, row, ' · '.join(labels), evidence.get(row.ply), tuple(labels)))
    return tuple(events)


def book_suggestion(assessment: OpeningGameAssessment | None, ply: int | None) -> str | None:
    """Offer an authored preference only for an actual user departure.

    Args:
        assessment: Current legal game/opening assessment.
        ply: Selected decision ply; None means no opening decision selected.

    Returns:
        Preferred legal opening UCI, or None for opponents, alternatives or missing intent.
    """
    if assessment is None or ply is None or not 1 <= ply <= assessment.total_plies:
        return None
    row = assessment.moves[ply-1]
    return row.preferred_move.move_uci if (row.deviation and row.deviation_relation == 'user'
        and row.preferred_move is not None) else None


def opening_game_sort(games: tuple[OpeningAnalysisGame, ...], column: str,
                      descending: bool = False) -> tuple[OpeningAnalysisGame, ...]:
    """Sort typed values, keeping unknown scores last in either direction.

    Args:
        games: Current selected-opening and opening-side matching set.
        column: Public grid column ID.
        descending: Reverse only known values.

    Returns:
        Stable ordered game facts without changing membership.

    Raises:
        ValueError: The column is not supported.
    """
    keys = {
        'game':lambda g:g.context.game_id,
        'date':lambda g:(g.context.played_at or '').replace('.','-'),
        'opponent':lambda g:(g.context.black_username if g.context.user_color=='white' else g.context.white_username) or '',
        'result':lambda g:g.context.result,
        'variation':lambda g:context_text(g.book.final_variation,g.book.provenance.book_name),
        'accuracy':lambda g:g.accuracy.user.quality.accuracy if g.accuracy.user else None,
        'adherence':lambda g:g.adherence.percentage,
        'user':lambda g:g.first_user_deviation.book.ply if g.first_user_deviation else None,
        'opponent_deviation':lambda g:g.first_opponent_deviation.book.ply if g.first_opponent_deviation else None,
        'reentry':lambda g:g.book.reentry_count,
    }
    if column not in keys:
        raise ValueError('Unknown opening grid column.')
    key=keys[column]
    present=[g for g in games if key(g) is not None]
    missing=[g for g in games if key(g) is None]
    return tuple(sorted(present,key=key,reverse=descending)+missing)


def opening_metric_text(result: OpeningAnalysisResult) -> str:
    """Label aggregate scores and denominators without hiding partial evidence.

    Args:
        result: Current shared Opening Analysis result.

    Returns:
        Compact multi-line metric summary suitable for any frontend.
    """
    q=result.accuracy.quality
    number=lambda v:'Not analyzed' if v is None else f'{v:.2f}'
    percent=lambda v:'n/a' if v is None else f'{v:.2f}%'
    return (f'Games {len(result.games)}   Opening Accuracy {number(q.accuracy)} ({result.accuracy.status})\n'
        f'Opening Adherence {result.adherence.in_book_moves} / {result.adherence.opportunities} · {percent(result.adherence.percentage)}\n'
        f'Accuracy evidence {q.evaluated_moves} / {q.total_moves} · {percent(result.accuracy.coverage_percentage)}'
        f'   Missing {result.accuracy.missing_evidence} · Unresolved {result.accuracy.unresolved_moves}\n'
        f'Opening gaps {len(result.repertoire_gaps)}   Re-entry games {len({r.game_id for r in result.reentries})}')
