"""Portable text presentation of numeric move quality; no chess calculation or UI."""
from board_analysis.phase import GamePhase


def number(value, suffix=''):
    return '—' if value is None else f'{value:.1f}{suffix}'


def score_label(score):
    if score is None:
        return '—'
    score = score.pov('white')
    if score.mate_score is not None:
        return ('' if score.mate_winner == 'white' else '-') + f'M{abs(score.mate_score)}'
    return f'{score.score_cp/100:+.2f}'


def game_summary(game):
    coverage = game.overall
    state = 'Complete' if coverage.complete else 'Partial' if coverage.evaluated_moves else 'Not analyzed'
    return (f'Accuracy · {state} · {coverage.evaluated_moves}/{coverage.total_moves} moves'
            f'\nYou: {number(game.user.accuracy)} · Opponent: {number(game.opponent.accuracy)}')


def game_details(game):
    missing = sum(not value.evidence_complete for value in game.moves)
    unresolved = sum(value.evidence_complete and value.accuracy is None for value in game.moves)
    rows = [f'Missing evidence: {missing} · Unresolved estimates: {unresolved}']
    if game.moves:
        rows.append(game.moves[0].evidence_profile)
    for label, value in (('Overall', game.overall), ('White', game.for_color('white')), ('Black', game.for_color('black'))):
        rows.append(f'{label}: {number(value.accuracy)} · {value.evaluated_moves}/{value.total_moves} moves')
    user = game.user
    rows.append(f'Your best-move rate: {number(user.best_move_rate, "%")} ({user.best_move_count}/{user.best_evidence_moves})')
    overall = game.overall
    rows.append(f'Overall best-move rate: {number(overall.best_move_rate, "%")} ({overall.best_move_count}/{overall.best_evidence_moves})')
    rows.append(f'Your average / median loss: {number(user.average_loss_cp)} / {number(user.median_loss_cp)} cp ({user.cp_loss_moves} finite-score moves)')
    for phase in GamePhase:
        value = game.for_phase(phase, game.user_color)
        rows.append(f'Your {phase.lower()}: {number(value.accuracy)} · {value.evaluated_moves}/{value.total_moves} moves')
    rows.append('Engine estimates; missing or contradictory evidence is excluded. 100 does not mean a winning position.')
    return '\n'.join(rows)


def move_details(value):
    if value is None:
        return 'Move quality: select an actual move.'
    base = f'Move quality · {value.move.mover_color.capitalize()} · {value.phase}\nPlayed: {value.move.played_san} · Best: {value.best_san or "—"}'
    if value.accuracy is None:
        state = 'Move quality not analyzed' if not value.evidence_complete else 'Move quality unresolved'
        return base + f'\n{state} ({value.state.replace("_", " ")})'
    loss = f'{value.eval_loss_cp} cp' if value.eval_loss_cp is not None else value.state.replace('_', ' ')
    return base + f'\nEval loss: {loss} · Accuracy: {value.accuracy:.1f}\nContinuations (White): best {score_label(value.before_eval)} · played {score_label(value.played_continuation_eval)}'
