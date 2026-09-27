"""Read-only actual-root discovery adapter over the shared Fork V3.1 proof."""
from dataclasses import dataclass
from typing import Mapping

from analyze_forks_v31 import evaluate_fork_move
from candidate_line_proof import IncompleteLineEvidence
from candidate_verification_result import CandidateVerificationResult
from position_range_evidence import LegalReplay
from stored_line import StoredLine
from tactic_occurrences import OccurrenceKind, TacticColor, TacticOccurrence


@dataclass(frozen=True)
class ForkOccurrenceResult:
    classification: str
    reason: str
    occurrence: TacticOccurrence | None = None
    proof: CandidateVerificationResult | None = None


def evaluate_recorded_fork(
    row: Mapping, line_service, *, perspective_color: TacticColor,
    actual_game_line: tuple[str, ...], source_identity: str, profile=None,
) -> ForkOccurrenceResult:
    """Inspect an actual user move without inventing candidates or changing proof truth.

    Missing exact evidence stays unresolved. A context-only Fork annotation is
    retained in proof, but does not qualify as a verified played-Fork occurrence.
    """
    perspective = TacticColor(perspective_color)
    if row['color'] != perspective.value:
        raise ValueError('This pilot accepts only actual moves by the explicit perspective')
    if row.get('candidate_id') is not None:
        raise ValueError('Played discovery must not reinterpret an existing candidate')
    if not isinstance(actual_game_line, tuple) or not actual_game_line or actual_game_line[0] != row['uci_played']:
        raise ValueError('Actual game evidence must start with the recorded move')
    LegalReplay(row['fen_before'], actual_game_line)
    try:
        result = evaluate_fork_move(row, row['uci_played'], line_service, profile=profile)
    except IncompleteLineEvidence as error:
        return ForkOccurrenceResult('unresolved', str(error))
    if result.state in {'error', 'ambiguous'}:
        return ForkOccurrenceResult('unresolved', result.details['reason'], proof=result)
    if result.state != 'candidate':
        return ForkOccurrenceResult('rejected', result.details['reason'], proof=result)
    motif = next((m for m in result.opportunity.motifs if m.kind == 'fork'), None)
    if motif is None or motif.attribution not in {'supported', 'verified'}:
        return ForkOccurrenceResult('rejected', 'fork_is_context_only', proof=result)
    line = StoredLine.from_san(row['fen_before'], result.candidate['solution_line'])
    if not line.moves_uci or line.validation_error:
        raise ValueError('Fork proof did not return a legally replayable line')
    occurrence = TacticOccurrence(
        'fork', source_identity, kind=OccurrenceKind.PLAYED,
        actor_color=TacticColor(row['color']), perspective_color=perspective,
        source_position=row['fen_before'], actual_move=row['uci_played'], tactical_move=row['uci_played'],
        actual_game_line=actual_game_line, counterfactual_line=line.moves_uci,
        proof_source_identity=source_identity+':fork_v31_proof',
        source_verdict=result.details['classification'],
        provenance=(('proof_provider', 'fork_v3.1'), ('profile_currentness', result.details['profile_currentness']),
                    ('line_roles', 'actual_recorded_and_counterfactual_proof')),
    )
    return ForkOccurrenceResult('verified', 'supported_fork_with_retained_payoff', occurrence, result)
