from dataclasses import asdict, replace
from pathlib import Path
import ast
import json
import sqlite3
import unittest
from unittest.mock import Mock, patch

import chess
import chess.engine
from analysis_settings import AnalysisProfile, GeneratorSettings, QualityGateSettings, load_profile, identity
from candidate_lines import CandidateLine, CandidateLineSet, LineScore, to_data
from candidate_line_engine import CandidateLineGenerator
from candidate_line_request import request_identity
from candidate_line_selection import admit_required_move
from candidate_line_proof import ApprovedPositionEvidence
from candidate_line_repository import CandidateLineRepository
from candidate_line_service import CandidateLineService
from migrate_candidate_line_cache import migrate
from analyze_forks_v3_multiline import analyze_existing_candidate
from fork_robustness import summarize_continuations
from feedback import FeedbackContextBuilder, FeedbackGenerator
import test_forks_v3 as fixtures


def line_set(fen, settings, choices, root_moves=(), complete=True):
    request_id = request_identity(settings, root_moves)
    board = chess.Board(fen)
    lines = []
    for index, (san, cp) in enumerate(choices, 1):
        move = board.parse_san(san)
        lines.append(CandidateLine(index, move.uci(), LineScore(cp), (move.uci(),),
                                   12, request_id))
    return CandidateLineSet(fen, 'white' if board.turn else 'black', settings.candidate_line_count,
        settings.engine.profile_id, request_id, tuple(lines),
        {'complete': complete, 'generator_settings': asdict(settings), 'root_moves': list(root_moves)})


class FixtureService:
    def __init__(self, row, root_choices=None, replies=('Kf7', 'Kd7'), responses=('Nxa8',), cp=400):
        self.row, self.calls, self.cp = row, [], cp
        self.choices = {row['fen_before']: root_choices or [('Nc7+', cp)]}
        after = chess.Board(row['fen_before'])
        after.push_uci(row['solution_move_uci'])
        self.choices[after.fen()] = [(reply, cp) for reply in replies]
        for reply in replies:
            child = after.copy(stack=False)
            child.push_san(reply)
            self.choices[child.fen()] = [(response, cp) for response in responses]

    def candidate_lines(self, fen, settings, *, root_moves=()):
        self.calls.append((fen, settings, root_moves))
        board = chess.Board(fen)
        choices = self.choices.get(fen, [(board.san(move), self.cp) for move in list(board.legal_moves)[:settings.candidate_line_count]])
        if root_moves:
            choices = [(board.san(board.parse_uci(root_moves[0])), self.cp)]
        return line_set(fen, settings, choices[:settings.candidate_line_count], root_moves)


def selected_two_ply_proof(after, color, evaluate, values, window):
    board = after.copy(stack=False)
    moves = []
    for _ in range(2):
        move = evaluate(board.fen())['principal_variation'].split()[0]
        moves.append(move)
        board.push_san(move)
    proof = fixtures.proof_for(after, ' '.join(moves))
    return replace(proof, window=window)


class ForkMultilineTests(unittest.TestCase):
    def verify(self, service, profile=AnalysisProfile()):
        with patch('analyze_forks_v3_multiline.verify_bounded_line', side_effect=selected_two_ply_proof):
            return analyze_existing_candidate(service.row, service, profile)

    def test_rank_one_two_three_and_winning_floor_use_shared_gate(self):
        for choices in ([('Nc7+', 400)], [('Kf1', 420), ('Nc7+', 400)],
                        [('Kf1', 450), ('Kd1', 425), ('Nc7+', 400)],
                        [('Kf1', 1000), ('Nc7+', 550)]):
            service = FixtureService(fixtures.candidate(), choices)
            result = self.verify(service)
            self.assertEqual(result.state, 'candidate')
            self.assertTrue(result.details['root_move_passes_gate'])
            self.assertEqual(result.details['root_admission']['native_rank'], len(choices))
            self.assertEqual(result.details['counterplay_robustness']['continuation_count_considered'], 2)
            self.assertEqual(result.details['realizable_targets'][0]['square'], 'a8')

    def test_rejected_root_stops_before_proof(self):
        row = fixtures.candidate()
        service = FixtureService(row, [('Kf1', 800), ('Nc7+', 0)])
        with patch('analyze_forks_v3_multiline.verify_bounded_line') as proof:
            result = analyze_existing_candidate(row, service)
        proof.assert_not_called()
        self.assertEqual(result.details['classification'], 'rejected')
        self.assertFalse(result.details['root_move_passes_gate'])

    def test_negative_defensive_fork_has_no_parallel_positive_eval_floor(self):
        service = FixtureService(fixtures.candidate(), cp=-220)
        self.assertEqual(self.verify(service).state, 'candidate')

    def test_missing_top_n_move_gets_explicit_shared_supplement_not_automatic_rejection(self):
        service = FixtureService(fixtures.candidate(), [('Kf1', 440), ('Kd1', 420), ('Kf2', 410)])
        result = self.verify(service)
        admission = result.details['root_admission']
        self.assertTrue(admission['supplemented'])
        self.assertIsNone(admission['native_rank'])
        self.assertTrue(result.details['root_move_passes_gate'])
        self.assertEqual(len({line['move_uci'] for line in admission['approved']['source']['lines']}), 4)
        self.assertIn(('d5c7',), [call[2] for call in service.calls])

    def test_child_replies_and_player_alternatives_are_distinct_branches(self):
        service = FixtureService(fixtures.candidate(), responses=('Nxa8', 'Nd5'))
        result = self.verify(service)
        robustness = result.details['counterplay_robustness']
        self.assertEqual(robustness['opponent_reply_diversity'], 2)
        self.assertEqual(robustness['continuation_count_considered'], 4)
        self.assertFalse(robustness['payoff_consensus'])
        self.assertEqual(result.details['classification'], 'ambiguous')
        feedback_row = {**service.row, 'solution_line': None}
        feedback = FeedbackGenerator().generate(FeedbackContextBuilder().build(feedback_row, result.opportunity))
        self.assertNotIn('wins the rook', feedback.explanation)
        self.assertIn('no robust retained payoff', feedback.explanation)

    def test_profile_controls_best_line_only_and_windows(self):
        service = FixtureService(fixtures.candidate())
        profile = load_profile('quick')
        with patch('analyze_forks_v3_multiline.verify_bounded_line', side_effect=selected_two_ply_proof) as proof:
            result = analyze_existing_candidate(service.row, service, profile)
        self.assertEqual(result.details['counterplay_robustness']['continuation_count_considered'], 1)
        self.assertTrue(all(call[1].candidate_line_count == 1 for call in service.calls))
        self.assertEqual(proof.call_args.args[-1].user_moves, profile.proof.user_moves)
        self.assertEqual(proof.call_args.args[-1].settlement_plies, profile.proof.settlement_plies)

    def test_unsettled_and_critical_evidence_stay_protected(self):
        service = FixtureService(fixtures.candidate())
        def unsettled(*args):
            return replace(selected_two_ply_proof(*args), state='unsettled')
        with patch('analyze_forks_v3_multiline.verify_bounded_line', side_effect=unsettled):
            result = analyze_existing_candidate(service.row, service)
        self.assertEqual(result.details['classification'], 'ambiguous')
        partial_profile = replace(AnalysisProfile(), quality_gate=QualityGateSettings(maximum_deterioration_cp=50))
        partial = analyze_existing_candidate(service.row, service, partial_profile)
        self.assertEqual(partial.details['reason'], 'incomplete_root_evidence')
        branches = [branch_fixture(critical=True)]
        self.assertEqual(summarize_continuations(branches).classification, 'ambiguous')

    def test_scale_cannot_select_optimistic_proof(self):
        service = FixtureService(fixtures.candidate(), responses=('Nxa8', 'Nd5'))
        normal = self.verify(service)
        profile = replace(AnalysisProfile(), scale=replace(AnalysisProfile().scale, base_interest=100))
        weighted = self.verify(service, profile)
        self.assertEqual(normal.details['classification'], weighted.details['classification'])
        self.assertEqual(normal.details['counterplay_robustness'], weighted.details['counterplay_robustness'])

    def test_no_crawl_mutation_or_desktop_dependency(self):
        service = FixtureService(fixtures.candidate())
        before = json.dumps(service.row, sort_keys=True)
        self.verify(service)
        self.assertEqual(json.dumps(service.row, sort_keys=True), before)
        for field, value in (('candidate_id', None), ('candidate_status', 'rejected'), ('detector_version', 999)):
            with self.assertRaises(ValueError):
                analyze_existing_candidate({**service.row, field: value}, service)
        root = Path(__file__).resolve().parents[1]
        for filename in ('analyze_forks_v3_multiline.py', 'fork_robustness.py', 'candidate_line_selection.py', 'candidate_line_proof.py'):
            tree = ast.parse((root/filename).read_text())
            imports = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            imports += [a.name for node in ast.walk(tree) if isinstance(node, ast.Import) for a in node.names]
            self.assertFalse(any(name.startswith(('tkinter', 'sqlite3', 'merlin_ui', 'subprocess')) for name in imports))


def branch_fixture(*, retained=500, targets=('a8',), state='candidate', critical=False):
    return {'opponent_move_uci': 'e8f7', 'proof_state': 'stable', 'state': state,
            'classification': 'verified', 'payoff_signature': ('win_rook', 'supported', retained),
            'realizable_target_squares': targets, 'material_gain_cp': retained,
            'final_player_cp': 400, 'retained_related_cp': retained, 'outcome': 'win_rook',
            'critical_fallback': critical}


class RobustnessAndRequestTests(unittest.TestCase):
    def test_consensus_and_optimistic_branch_disagreement(self):
        robust = summarize_continuations([branch_fixture(), branch_fixture()])
        self.assertEqual(robust.classification, 'verified')
        mixed = summarize_continuations([branch_fixture(), branch_fixture(retained=100)])
        self.assertEqual(mixed.classification, 'ambiguous')
        self.assertEqual(mixed.material_gain_range, (100, 500))
        self.assertFalse(mixed.payoff_consensus)

    def test_restriction_has_separate_cache_identity_and_reuses_scratch(self):
        engine = Mock()
        engine.analyse.return_value = [{'multipv': 1, 'score': chess.engine.PovScore(chess.engine.Cp(100), chess.WHITE),
            'pv': [chess.Move.from_uci('e2e4')], 'depth': 12}]
        settings = GeneratorSettings(3)
        with sqlite3.connect(':memory:') as scratch:
            migrate(scratch)
            service = CandidateLineService(CandidateLineGenerator(engine), write_store=CandidateLineRepository(scratch))
            first = service.candidate_lines(chess.STARTING_FEN, settings, root_moves=('e2e4',))
            changes = scratch.total_changes
            second = service.candidate_lines(chess.STARTING_FEN, settings, root_moves=('e2e4',))
            self.assertEqual(first, second)
            self.assertEqual(scratch.total_changes, changes)
            self.assertEqual(engine.analyse.call_count, 1)
            self.assertNotEqual(first.engine_identity, identity(settings))
            self.assertEqual(engine.analyse.call_args.kwargs['root_moves'], [chess.Move.from_uci('e2e4')])


if __name__ == '__main__':
    unittest.main()
