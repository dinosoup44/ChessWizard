"""Existing-candidate Fork V3 adoption of shared approved lines; pure read-only proposals."""
from dataclasses import asdict, replace
import json
import chess
from analysis_results import HeavyResult
from analysis_settings import AnalysisProfile
from analysis_scout import validate_stored_move
from analyze_forks_v3 import POLICY, PIECE_VALUES, interpret_proof
from board_analysis import attacked_pieces, attackers
from candidate_lines import to_data
from candidate_line_selection import admit_required_move
from candidate_line_proof import ApprovedPositionEvidence, IncompleteLineEvidence
from fork_robustness import summarize_continuations
from fork_verification_branches import ForkBranchContext, summarize_branch
from tactical_proof import ProofWindow, verify_bounded_line
from tactical_opportunities import TacticalOpportunity, TacticalOutcome, TacticalMotif, TacticalPresentation, ProofEvidence
from the_scale import TheScale
from proof_evidence_state import terminal_facts, proof_state

PROOF_SCOPE = 'fork_v3_approved_counterplay_branches_v1'
REALIZABLE_SCOPE = 'approved_counterplay_branches_v1'


def analyze_existing_candidate(row, line_service, profile=AnalysisProfile(), *, review_branches=None, backbone=None):
    """Verify only the stored fork; admission and engine access remain shared services."""
    board, move = _candidate_position(row)
    return analyze_position(row, move.uci(), line_service, profile,
                            review_branches=review_branches, backbone=backbone)


def analyze_position(row, move_uci, line_service, profile=AnalysisProfile(), *, review_branches=None, backbone=None):
    """Calculate one explicit legal fork proposal without requiring a persisted candidate."""
    validate_stored_move(row)
    board = chess.Board(row['fen_before'])
    move = board.parse_uci(move_uci)
    if move_uci == row['uci_played']:
        raise ValueError('Discovery requires an unplayed move')
    return _evaluate_fork_move(row, board, move, move_uci, line_service, profile,
                               review_branches=review_branches, backbone=backbone)


def evaluate_fork_move(row, move_uci, line_service, profile=AnalysisProfile(), *, review_branches=None, backbone=None):
    """Evaluate one legal Fork move; discovery owns its relation to the actual move."""
    validate_stored_move(row)
    board = chess.Board(row['fen_before'])
    move = board.parse_uci(move_uci)
    return _evaluate_fork_move(row, board, move, move_uci, line_service, profile,
                               review_branches=review_branches, backbone=backbone)


def _evaluate_fork_move(row, board, move, move_uci, line_service, profile, *, review_branches, backbone):
    row = {**row, 'solution_move_uci':move_uci, 'solution_move_san':board.san(move)}
    after = board.copy(stack=False)
    after.push(move)
    geometry = _geometry(after, move.to_square, board.turn)
    details = {
        'candidate_id': row.get('candidate_id'), 'analyzer_version': '3',
        'verification_mode': PROOF_SCOPE, 'profile': asdict(profile),
        'profile_currentness': profile.currentness_identity,
        'geometric_targets': geometry,
        'realizable_scope': REALIZABLE_SCOPE,
        'branching_scope': 'all_approved_first_opponent_replies_and_first_player_responses_then_best_approved_per_ply',
    }
    for terminal_board, role in ((chess.Board(row['fen_after']), 'played'), (after, 'candidate')):
        terminal = terminal_facts(terminal_board, role=role)
        if terminal.complete:
            details.update(terminal=asdict(terminal), proof_state='terminal',
                           terminal_state=terminal.terminal_state, ownership=terminal.ownership)
            return _unfinished(row, details, 'terminal_ownership_deferred')
    admission = (backbone.admit(row['fen_before'], move.uci()) if backbone else
                 admit_required_move(line_service, row['fen_before'], move.uci(), profile))
    details['root_admission'] = to_data(admission)
    details['root_gate'] = admission.approved.state
    if admission.approved.state in {'incomplete', 'terminal'} or admission.decision is None:
        return _unfinished(row, details, 'incomplete_root_evidence')
    details['root_move_passes_gate'] = admission.decision.retained
    details['forced_deterioration'] = admission.approved.forced_deterioration
    if not admission.decision.retained:
        return _non_hit(row, details, 'rejected', 'stored_move_failed_shared_quality_gate')
    if len(geometry) < 2:
        return _non_hit(row, details, 'rejected', 'stored_move_has_no_fork_geometry')

    evidence = backbone.evidence if backbone else ApprovedPositionEvidence(line_service, profile)
    weigh = backbone.weigh if backbone else TheScale(profile.scale).weigh
    try:
        replies = evidence.approved(after.fen())
        details['child_replies'] = to_data(replies)
        baseline = _baseline(row, admission, evidence, board.turn)
        branches, results = _verify_branches(row, after, replies, evidence, baseline, details, profile, weigh)
    except IncompleteLineEvidence as error:
        details['incomplete_evidence'] = str(error)
        return _unfinished(row, details, 'incomplete_continuation_evidence')
    details['branches'] = branches
    details['forced_deterioration'] |= bool(evidence.critical_positions)
    if admission.approved.forced_deterioration:
        for branch in branches:
            branch['critical_fallback'] = True
    if review_branches is not None:
        context = ForkBranchContext(row, after, evidence, baseline, details, profile)
        review_branches(context, branches, results)
    for branch in branches:
        legacy_state = branch['proof_state']
        branch['proof_state'] = proof_state(legacy_state, branch.get('final_fen'))
        if legacy_state != branch['proof_state']:
            branch['legacy_proof_state'] = legacy_state
        if branch.get('final_fen'):
            terminal = terminal_facts(chess.Board(branch['final_fen']))
            if terminal.complete:
                branch['terminal'] = asdict(terminal)
        if legacy_state in {'mate', 'mate_baseline'}:
            branch['ownership'] = 'mate'
    robustness = summarize_continuations(branches)
    details['counterplay_robustness'] = asdict(robustness)
    # Interest is computed after the proof classification and never selects its outcome.
    details['root_scale'] = _scale_summary(weigh(admission.approved))
    if robustness.classification in {'verified', 'verified_payoff_changed'}:
        return _consensus_proposal(row, details, branches, results, robustness)
    return _non_hit(row, details, robustness.classification, robustness.reason)


def _candidate_position(row):
    if not row.get('candidate_id') or row.get('tactic_type') != 'missed_fork':
        raise ValueError('Existing fork candidate required; discovery is prohibited')
    if row.get('candidate_status') != 'candidate' or str(row.get('detector_version')) != '2':
        raise ValueError('Only explicitly selected active V2 candidates are eligible')
    if row.get('source') == 'dev':
        raise ValueError('Development candidates remain protected')
    validate_stored_move(row)
    board = chess.Board(row['fen_before'])
    move = board.parse_uci(row['solution_move_uci'])
    if board.san(move) != row['solution_move_san']:
        raise ValueError('Stored move identity conflicts')
    return board, move


def _geometry(after, square, player):
    targets = attacked_pieces(after, square, target_color=not player,
        piece_types=(chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING))
    return [{'piece': chess.piece_name(target.piece_type), 'square': chess.square_name(target.square),
             'defenders': [chess.square_name(s) for s in attackers(after, target.square, not player)]}
            for target in targets]


def _legacy_score(score):
    return {'score_type': 'cp' if score.score_cp is not None else 'mate',
            'score_cp': score.score_cp, 'mate': score.mate_score}


def _baseline(row, admission, evidence, player):
    color = 'white' if player else 'black'
    root_best = max(admission.approved.source.lines, key=lambda line: line.score.ordering(color))
    selected = next(line for line in admission.approved.lines if line.move_uci == row['solution_move_uci'])
    return {'before': _legacy_score(root_best.score.pov(color)),
            'played': _legacy_score(evidence.best(row['fen_after']).score.pov(color)),
            'tactic': _legacy_score(selected.score.pov(color))}


def _verify_branches(row, after, replies, evidence, baseline, details, profile, weigh):
    branches, results = [], []
    details['response_sets'] = []
    window = ProofWindow(user_moves=profile.proof.user_moves,
                         settlement_plies=profile.proof.settlement_plies,
                         quiet_plies=profile.proof.quiet_plies)
    policy = replace(POLICY, window=window, profile=profile.generator.engine.profile_id)
    for reply in replies.lines:
        child = after.copy(stack=False)
        child.push_uci(reply.move_uci)
        if child.is_game_over():
            branch = _incomplete_branch(reply, None, 'terminal_after_reply')
            branch.update(final_fen=child.fen(), terminal=asdict(terminal_facts(child)))
            branches.append(branch)
            continue
        responses = evidence.approved(child.fen())
        for response in responses.lines:
            selected = {after.fen(): reply, child.fen(): response}
            def evaluate(fen):
                return evidence.raw(fen, selected.get(fen))
            proof = verify_bounded_line(after, not after.turn, evaluate, PIECE_VALUES, window)
            line = ' '.join([row['solution_move_san'], *(step.san for step in proof.steps)])
            if proof.state != 'stable' or any(score['score_type'] != 'cp' for score in baseline.values()):
                branch = _incomplete_branch(reply, response, proof.state if proof.state != 'stable' else 'mate_baseline')
                branch.update(proof_line=line, proof_steps=[asdict(step) for step in proof.steps], final_fen=proof.final_fen)
                branches.append(branch)
                continue
            final = evidence.best(proof.final_fen).score.pov(row['color'])
            branch_details = {'geometric_targets': details['geometric_targets'],
                'realizable_scope': 'observed_bounded_best_defense_line_only'}
            result = interpret_proof(row, proof, baseline, final.score_cp, branch_details, policy,
                objective_acceptance='shared_quality_gate', proof_scope=PROOF_SCOPE)
            index = len(results)
            results.append(result)
            branches.append(summarize_branch(reply, response, proof, line, result, index))
        response_weights = weigh(responses)
        details['response_sets'].append({'opponent_move_uci': reply.move_uci,
            'approved': to_data(responses), 'scale': _scale_summary(response_weights)})
        for branch in branches:
            if branch['opponent_move_uci'] == reply.move_uci:
                branch['critical_fallback'] = bool(evidence.critical_positions)
    return branches, results


def _incomplete_branch(reply, response, reason):
    return {'opponent_move_uci': reply.move_uci, 'opponent_move_san': reply.move_san,
            'player_move_uci': response.move_uci if response else None,
            'player_move_san': response.move_san if response else None,
            'proof_state': reason, 'state': 'error', 'classification': 'ambiguous'}



def _consensus_proposal(row, details, branches, results, robustness):
    worst = min(branches, key=lambda branch: (branch['retained_related_cp'], branch['material_gain_cp'], branch['final_player_cp']))
    original = results[worst['result_index']]
    opportunity = replace(original.opportunity, metadata={**original.opportunity.metadata,
        'realizable_scope': REALIZABLE_SCOPE, 'counterplay_robustness': asdict(robustness)})
    details.update(classification=robustness.classification, reason=robustness.reason,
        realizable_targets=original.details['realizable_targets'],
        realized_payoff=original.details['realized_payoff'],
        geometric_vs_realizable_differ=original.details['geometric_vs_realizable_differ'])
    metadata = json.loads(original.candidate['metadata_json'])
    metadata['fork_v3_multiline'] = {'classification': robustness.classification,
        'reason': robustness.reason, 'profile_currentness': details['profile_currentness'],
        'counterplay_robustness': asdict(robustness)}
    payload = {**original.candidate, 'metadata_json': json.dumps(metadata, sort_keys=True)}
    return HeavyResult('candidate', payload, details, opportunity)


def _unfinished(row, details, reason):
    return _non_hit(row, details, 'ambiguous', reason)


def _non_hit(row, details, classification, reason):
    details.update(classification=classification, reason=reason)
    opportunity = TacticalOpportunity(TacticalOutcome('unknown'),
        (TacticalMotif('fork', False, 'context_only', 'Geometry does not establish robust retained payoff.'),),
        proof=ProofEvidence(scope=PROOF_SCOPE, score_pov=row['color']),
        presentation=TacticalPresentation('positional_note'),
        metadata={'geometric_targets': details['geometric_targets'], 'realizable_targets': [],
                  'realizable_scope': REALIZABLE_SCOPE,
                  'counterplay_robustness': details.get('counterplay_robustness'),
                  'verification_classification': classification, 'verification_reason': reason})
    return HeavyResult('error' if classification == 'ambiguous' else 'analyzed_no_hit', details=details, opportunity=opportunity)


def _scale_summary(weighted):
    return [{'move_uci': line.line.move_uci, 'engine_rank': line.line.rank,
             'interest_weight': line.interest_weight, 'components': to_data(line.components)}
            for line in weighted.lines]
