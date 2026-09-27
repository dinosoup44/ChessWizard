"""Portable provisional wording for opening facts; no engine-quality vocabulary."""

def context_text(context, book_name):
    if not context.paths:return 'No known variation context'
    paths=[' > '.join((book_name,*(v.name for v in path))) for path in context.paths]
    if context.ambiguous:return 'Ambiguous context: '+ ' | '.join(paths) + (' (bounded/incomplete)' if not context.complete else '')
    return paths[0]+(' (position-derived context)' if not context.observed else '')


def opening_summary(assessment,step=0,*,proof=False):
    book=assessment.provenance
    lines=['OPENING BOOK',f'{book.book_name} · v{book.book_version} · revision {book.book_revision}',
           f'Meaningful book entry: {"yes" if assessment.entered_book else "not established"}']
    if proof:lines.append('Current board is a proof line; these facts describe the actual game only.')
    else:
        row=assessment.moves[step-1] if 0<step<=assessment.total_plies else None
        context=row.variation_after if row else assessment.initial_variation
        lines.append(context_text(context,book.book_name))
        if row:
            status='in book' if row.played_move_in_book else row.state.replace('_',' ')
            lines.append(f'Actual {row.move_label}: {status}')
            if row.played_weight is not None:lines.append(f'Authored played-move weight: {row.played_weight}')
    first=assessment.first_deviation
    if first:
        owner=first.deviation_relation or first.actor_color
        lines.append(f'First deviation: {first.move_label} ({owner})')
        if first.state=='continuation_not_authored':lines.append('Authored continuation ended here.')
        if first.preferred_move:lines.append(f'Preferred there: {first.preferred_move.san} · authored weight {first.preferred_move.weight}')
        last=assessment.last_known_before_deviation
        lines.append(f'Last known position before deviation: after {last.after_move}')
    else:lines.append('No deviation from a known position.' if not assessment.in_book_moves else 'All encountered known-position moves followed the book.')
    entries=[m.move_label for m in assessment.moves if m.reentry]
    if entries:lines.append('Re-entered after: '+', '.join(entries))
    lines.extend((f'In-book moves: {assessment.in_book_moves} / {assessment.total_plies} actual plies',
                  f'Moves with authored alternatives: {assessment.moves_with_alternatives}',
                  f'Known-position visits: {len(assessment.known_book_positions)} · re-entries: {assessment.reentry_count}',
                  'Book weights express author preference. Outside-book is not a move-quality judgment.'))
    return '\n'.join(lines)


def compact_opening_summary(assessment, step=0, *, proof=False):
    """Small actual-game block; full per-move evidence remains available in Facts."""
    if assessment is None:
        return ''
    row = assessment.moves[step-1] if 0 < step <= assessment.total_plies else None
    context = row.variation_after if row else assessment.initial_variation
    name = assessment.provenance.book_name
    title = context_text(context, name) if context.paths else name + ' · No known variation context'
    lines = ['OPENING · ' + title]
    if proof:
        lines.append('Actual-game facts only; proof line is separate.')
    elif row:
        state = 're-entered book' if row.reentry else row.state.replace('_', ' ')
        lines.append(f'{row.move_label}: {state}')
    else:
        lines.append('Meaningful entry: ' + ('yes' if assessment.entered_book else 'not established'))
    first = assessment.first_deviation
    if first:
        detail = f'First deviation: {first.move_label} ({first.deviation_relation or "unknown owner"})'
        if first.preferred_move:
            detail += f' · Preferred: {first.preferred_move.san}'
        elif first.state == 'continuation_not_authored':
            detail += ' · Authored line ended'
        lines.append(detail)
    lines.append(f'{assessment.in_book_moves}/{assessment.total_plies} actual plies in book · '
                 f'{assessment.reentry_count} re-entries · Book facts, not move quality')
    return '\n'.join(lines)
