"""Deterministic qualified report wording; never changes chess facts or proof status."""
from dataclasses import dataclass
import chess
from played_fork_assessment import PlayedForkAssessment


@dataclass(frozen=True)
class PlayedForkDescription:
    summary: str
    recorded_context: str
    proof_context: str
    admission_context: str


def describe_played_fork(assessment: PlayedForkAssessment) -> PlayedForkDescription:
    """Describe recorded observations separately from the supplied counterfactual verdict."""
    a = assessment
    subject = 'You' if a.actor_color == a.perspective_color else 'Your opponent'
    g, recorded = a.geometry, a.recorded
    if g.status == 'confirmed_fork':
        names = [chess.piece_name(t.initial_piece_type) for t in sorted(g.targets, key=lambda t: -t.initial_piece_type)]
        label = '-and-'.join(names) if len(names) == 2 else 'multiple-target'
        summary = f'{subject} played a {label} Fork with {a.actual_move_san}'
        if a.proof.admission_status == 'rejected':
            summary = f'{subject} created Fork geometry with {a.actual_move_san}'
        direct = next((c for c in recorded.target_captures if c.by_forking_piece), None)
        if direct:
            piece = chess.piece_name(direct.capture.victim_type)
            summary += f' and captured the {piece}'
            if direct.capture.ply == 3:
                summary += f' after {recorded.line_san[1]}'
            else:
                summary += f' later with {direct.move_san}'
        summary += '.'
    else:
        summary = f'{a.actual_move_san} does not establish Fork geometry under the current target scope.'
    if recorded.status == 'unresolved':
        context = 'Recorded consequence is unresolved: no opponent response was supplied.'
    else:
        context = f'Recorded-window material: gained {recorded.gained_cp} cp, lost {recorded.lost_cp} cp, net {recorded.net_cp:+d} cp (actor perspective).'
        if recorded.target_captures and not any(c.by_forking_piece for c in recorded.target_captures):
            context += ' An original target was captured by another piece; Fork causality is not established.'
        if recorded.terminal and recorded.terminal.state == 'checkmate':
            winner = 'White' if recorded.terminal.winner else 'Black'
            context += f' The recorded line ends in checkmate for {winner}.'
        context += ' This is recorded history, not forced or settled payoff proof.'
    admission = {'admitted': 'The move passed the existing admission check.',
                 'rejected': 'The move did not pass the existing admission check.',
                 'unknown': 'Move admission evidence is unavailable.'}[a.proof.admission_status]
    return PlayedForkDescription(summary, context,
        f'Best-defense payoff proof: {a.proof.status}. Scope: supplied provider evidence; {a.proof.completeness}.', admission)
