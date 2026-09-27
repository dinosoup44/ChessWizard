"""Shared Fork branch records for breadth and targeted verification consumers."""
from dataclasses import asdict, dataclass
import chess
from analysis_settings import AnalysisProfile
from candidate_line_proof import ApprovedPositionEvidence


@dataclass(frozen=True)
class ForkBranchContext:
    """In-memory evidence for an optional branch review; never a database handle."""
    row: dict
    after: chess.Board
    evidence: ApprovedPositionEvidence
    baseline: dict
    details: dict
    profile: AnalysisProfile


def summarize_branch(reply, response, proof, line, result, index):
    payoff = result.details['realized_payoff']
    outcome = result.opportunity.primary_outcome.kind if result.opportunity else 'no_retained_payoff'
    targets = tuple(sorted(target['square'] for target in result.details['realizable_targets']))
    attribution = str(result.opportunity.motifs[0].attribution) if result.opportunity else 'none'
    retained = min(payoff['net_material_cp'], payoff['move_sequence_retained_cp'])
    return {
        'opponent_move_uci': reply.move_uci, 'opponent_move_san': reply.move_san,
        'player_move_uci': response.move_uci, 'player_move_san': response.move_san,
        'proof_state': proof.state, 'state': result.state, 'classification': result.details['classification'],
        'reason': result.details['reason'], 'outcome': outcome,
        'realizable_target_squares': targets,
        'payoff_signature': (outcome, attribution, retained),
        'material_gain_cp': payoff['net_material_cp'], 'retained_related_cp': retained,
        'final_player_cp': result.details['evaluation_player_cp']['final'],
        'proof_line': line, 'proof_steps': [asdict(step) for step in proof.steps],
        'final_fen': proof.final_fen, 'interpretation': result.details,
        'result_index': index,
    }

