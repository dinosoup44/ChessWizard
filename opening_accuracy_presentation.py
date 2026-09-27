"""Numeric opening wording, keeping repertoire and engine quality independent."""
from move_quality_presentation import number
from opening_accuracy_models import OpeningGameAccuracy, OpeningMoveQuality


def opening_metrics_text(result: OpeningGameAccuracy) -> str:
    """Label stored opening scores separately from authored adherence.

    Args:
        result: Existing game opening-accuracy assessment.

    Returns:
        Compact metric labels with evidence completeness and denominators.
    """
    if not result.applicable:
        return 'Opening Accuracy / Opening Adherence: not applicable for this opening (no meaningful entry).'
    user = result.user
    if user is None:
        return 'Opening Accuracy / Opening Adherence: user color unknown; no user score assigned.'
    quality = user.quality
    lines = [f'Opening Accuracy: {number(quality.accuracy)} · {user.status.replace("_"," ")} · {quality.evaluated_moves}/{quality.total_moves} user moves scored',
             f'Opening Adherence: {user.in_book_moves}/{user.book_opportunities} user opening opportunities ({number(user.adherence,"%")})',
             f'Opening window: plies {result.phase.start_ply}–{result.phase.end_ply} · depth-16 evidence only',
             f'Average loss: {number(quality.average_loss_cp)} cp ({quality.cp_loss_moves} finite scores) · Best-move rate: {number(quality.best_move_rate,"%")} ({quality.best_move_count}/{quality.best_evidence_moves})']
    first = user.first_deviation
    if first:
        lines.append(f'First user deviation: {first.book.move_label} · ' + move_evidence_text(first))
    else:
        lines.append('No user deviation within this opening window.')
    return '\n'.join(lines)


def move_evidence_text(row: OpeningMoveQuality) -> str:
    """Describe existing numeric or unresolved move evidence.

    Args:
        row: Actual opening move and its compatible evidence.

    Returns:
        Accuracy/loss text without interpreting an authored departure as a mistake.
    """
    value = row.quality
    if row.accuracy is None:
        return 'Engine evidence: ' + ('unresolved' if row.evidence_complete else 'not analyzed')
    loss = f'{row.eval_loss_cp} cp' if row.eval_loss_cp is not None else value.state.replace('_',' ')
    return f'Accuracy: {row.accuracy:.1f} · Eval loss: {loss}'


def selected_opening_quality(result: OpeningGameAccuracy, ply: int) -> str:
    """Label the selected actual move without evaluating an authored projection.

    Args:
        result: Existing game opening-accuracy assessment.
        ply: One-based actual move to describe.

    Returns:
        Authored membership and compatible actual-move evidence, or an unavailable label.
    """
    row = next((row for row in result.moves if row.book.ply == ply),None)
    if row is None: return 'Selected actual move: outside the scored opening window.'
    book = 'In opening' if row.book.played_move_in_book else 'Out of opening'
    return f'Actual {row.book.move_label} · Opening: {book} · {move_evidence_text(row)}'
