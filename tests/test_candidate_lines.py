from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import Mock

import chess
import chess.engine

from analysis_settings import (AnalysisProfile, EngineSettings, GeneratorSettings, QualityGateSettings,
    ScaleSettings, ScaleWeights, identity, load_profile, load_settings)
from candidate_lines import CandidateLine, CandidateLineSet, LineScore, to_data
from candidate_line_engine import CandidateLineGenerator
from candidate_line_repository import CandidateLineRepository
from candidate_line_service import CandidateLineService
from candidate_line_pipeline import LineAnalysisService
from continuation_quality import (ContinuationEvidence, EvaluationSample, SemanticEvent,
    inspect_continuation, line_identity)
from migrate_candidate_line_cache import migrate
from quality_gate import ApprovedCandidateLineSet, approve_lines
from the_scale import TheScale


SACRIFICE_FEN = '5r1k/5Qpp/7N/8/8/8/8/6K1 w - - 0 1'


def make_lines(scores, *, fen=chess.STARTING_FEN, sans=None, metadata=None, settings=None):
    settings = settings or GeneratorSettings(len(scores))
    board = chess.Board(fen)
    moves = list(board.legal_moves)
    lines = []
    for index, score in enumerate(scores):
        copy = board.copy(stack=False)
        tokens = sans[index].split() if sans else [copy.san(moves[index])]
        pv = []
        for token in tokens:
            move = copy.parse_san(token)
            pv.append(move.uci())
            copy.push(move)
        score = score if isinstance(score, LineScore) else LineScore(score, score_pov='white' if board.turn else 'black')
        lines.append(CandidateLine(index+1, pv[0], score, tuple(pv), 12, identity(settings),
            move_san=tokens[0], pv_san=tuple(tokens), metadata=metadata or {}))
    return CandidateLineSet(fen, 'white' if board.turn else 'black', settings.candidate_line_count,
        settings.engine.profile_id, identity(settings), tuple(lines), {'complete': True, 'source': 'synthetic_fixture'})


class FakeEngine:
    def __init__(self): self.calls = []

    def analyse(self, board, limit, **kwargs):
        self.calls.append((board.fen(), limit, kwargs))
        return [{'multipv': i+1, 'score': chess.engine.PovScore(chess.engine.Cp(100-i*30), board.turn),
                 'pv': [move], 'depth': 12, 'nodes': 123} for i, move in
                enumerate(list(board.legal_moves)[:kwargs['multipv']])]


class CandidateLineContractTests(unittest.TestCase):
    def test_public_policy_fixture_lines_are_legal_and_have_unique_roots(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/candidate_lines_v1.json').read_text())
        for case in fixture['cases']:
            with self.subTest(case=case['name']):
                roots = []
                for line in case['lines']:
                    board = chess.Board(case.get('fen', chess.STARTING_FEN))
                    for index, san in enumerate(line.split()):
                        move = board.parse_san(san)
                        if index == 0: roots.append(move.uci())
                        board.push(move)
                self.assertEqual(len(roots), len(set(roots)))
                self.assertEqual(len(roots), len(case['scores']))

    def test_partial_and_bound_engine_results_are_not_cached_as_complete(self):
        engine = FakeEngine()
        one_info = engine.analyse(chess.Board(), chess.engine.Limit(depth=12), multipv=1)[0]
        engine = Mock()
        engine.analyse.return_value = [one_info]
        with sqlite3.connect(':memory:') as connection:
            migrate(connection)
            service = CandidateLineService(CandidateLineGenerator(engine), write_store=CandidateLineRepository(connection))
            partial = service.candidate_lines(chess.STARTING_FEN, GeneratorSettings(3))
            self.assertEqual(approve_lines(partial).state, 'incomplete')
            self.assertEqual(connection.execute('SELECT count(*) FROM engine_candidate_line_cache').fetchone()[0], 0)
        engine.analyse.return_value = [{**one_info, 'lowerbound': True}]
        with self.assertRaises(ValueError): CandidateLineGenerator(engine).generate(chess.STARTING_FEN)

    def test_counts_order_and_pv_roundtrip(self):
        for count in (1, 3, 7):
            value = make_lines(list(range(count, 0, -1)))
            self.assertEqual(value.generated_line_count, count)
            reversed_value = replace(value, lines=tuple(reversed(value.lines)))
            self.assertEqual(value, reversed_value)
            self.assertEqual(CandidateLineSet.from_json(value.to_json()), value)

    def test_nested_inputs_are_immutable_and_detached(self):
        metadata = {'nested': [{'value': 1}]}
        value = make_lines([50], metadata=metadata)
        metadata['nested'][0]['value'] = 2
        self.assertEqual(value.lines[0].metadata['nested'][0]['value'], 1)
        with self.assertRaises(TypeError): value.lines[0].metadata['nested'][0]['value'] = 3
        with self.assertRaises(Exception): value.lines[0].rank = 2

    def test_cp_mate_and_zero_ownership_pov(self):
        self.assertEqual(LineScore(-200).pov('black').score_cp, 200)
        self.assertEqual(LineScore(mate_score=3).pov('black').mate_score, -3)
        won = LineScore(mate_score=0, mate_winner='white')
        self.assertEqual(won.pov('black').mate_winner, 'white')
        with self.assertRaises(ValueError): LineScore(mate_score=0)
        with self.assertRaises(ValueError): LineScore(20, 3)
        with self.assertRaises(ValueError): LineScore()
        with self.assertRaises(ValueError): LineScore(20, score_pov='unknown')

    def test_rejects_duplicate_illegal_or_incompatible_lines(self):
        source = make_lines([200, 100])
        with self.assertRaises(ValueError): replace(source, lines=(source.lines[0], source.lines[0]))
        with self.assertRaises(ValueError): replace(source, side_to_move='black')
        with self.assertRaises(ValueError): replace(source, engine_identity='wrong')
        bad = replace(source.lines[0], move_uci='e2e5', pv_uci=('e2e5',))
        with self.assertRaises(ValueError): replace(source, lines=(bad,))

    def test_generator_uses_configured_multipv_options_without_mutating_board(self):
        engine = FakeEngine()
        generator = CandidateLineGenerator(engine)
        for n in (1, 3, 7):
            settings = GeneratorSettings(n, engine=EngineSettings(nodes=1000, depth=None, threads=2))
            value = generator.generate(chess.STARTING_FEN, settings)
            self.assertEqual(value.generated_line_count, n)
            self.assertEqual(engine.calls[-1][2]['multipv'], n)
            self.assertEqual(engine.calls[-1][2]['options']['Threads'], 2)
            self.assertEqual(engine.calls[-1][1].nodes, 1000)
            self.assertEqual(value.generation_metadata['generator_settings']['engine']['nodes'], 1000)
            self.assertEqual(value.generation_metadata['generator_settings']['engine']['engine_version'], '18')

    def test_generator_black_pov_and_mate(self):
        engine = FakeEngine()
        board = chess.Board(); board.push_san('e4')
        value = CandidateLineGenerator(engine).generate(board.fen(), GeneratorSettings(1))
        self.assertEqual(value.lines[0].score.score_cp, -100)
        engine = Mock()
        engine.analyse.return_value = [{'multipv': 1, 'score': chess.engine.PovScore(chess.engine.Mate(2), chess.WHITE),
            'pv': [chess.Move.from_uci('f7g8')], 'depth': 12}]
        value = CandidateLineGenerator(engine).generate(SACRIFICE_FEN, GeneratorSettings(1))
        self.assertEqual(value.lines[0].score.mate_winner, 'white')

    def test_terminal_does_not_search_and_incomplete_does_not_fake_full_set(self):
        board = chess.Board(SACRIFICE_FEN)
        for move in 'Qg8+ Rxg8 Nf7#'.split(): board.push_san(move)
        engine = Mock()
        terminal = CandidateLineGenerator(engine).generate(board.fen())
        engine.analyse.assert_not_called()
        self.assertEqual(approve_lines(terminal).state, 'terminal')
        engine = FakeEngine()
        value = CandidateLineGenerator(engine).generate(chess.STARTING_FEN, GeneratorSettings(25))
        self.assertEqual(value.generated_line_count, 20)
        self.assertTrue(value.generation_metadata['complete'])


class QualityGateTests(unittest.TestCase):
    def test_absolute_relative_winning_floor(self):
        cases = [([100, 30, -50], [True, True, False]), ([400, 321, 200], [True, True, False]),
                 ([800, 550, 400], [True, True, False])]
        for scores, expected in cases:
            approved = approve_lines(make_lines(scores))
            self.assertEqual([d.retained for d in approved.decisions], expected)
            self.assertFalse(approved.forced_deterioration)

    def test_losing_defense_and_relative_not_based_on_loss_magnitude(self):
        value = make_lines([-200, -220, -600])
        self.assertEqual(len(approve_lines(value).lines), 2)
        value = make_lines([-1000, -1180])
        self.assertEqual(len(approve_lines(value).lines), 1)

    def test_best_is_retained_even_below_zero(self):
        approved = approve_lines(make_lines([-800, -1500]), QualityGateSettings(absolute_tolerance_cp=0, relative_tolerance=0))
        self.assertEqual([l.rank for l in approved.lines], [1])

    def test_forced_deterioration_needs_explicit_reference_and_keeps_least_bad(self):
        settings = QualityGateSettings(maximum_deterioration_cp=50, least_bad_line_count=2)
        source = make_lines([-200, -220, -600])
        self.assertEqual(approve_lines(source, settings).state, 'incomplete')
        approved = approve_lines(source, settings, reference_score=LineScore(0))
        self.assertTrue(approved.forced_deterioration)
        self.assertEqual([l.rank for l in approved.lines], [1, 2])
        self.assertFalse(any(d.normal_accepted for d in approved.decisions))
        self.assertNotIn('zugzwang', str(to_data(approved)))

    def test_mate_lengths_ownership_avoidance_and_forced_loss(self):
        source = make_lines([LineScore(mate_score=2), LineScore(mate_score=4), LineScore(mate_score=8), 900, LineScore(mate_score=-2)])
        self.assertEqual([l.rank for l in approve_lines(source).lines], [1, 2])
        source = make_lines([LineScore(mate_score=-8), LineScore(mate_score=-7), LineScore(mate_score=-2)])
        approved = approve_lines(source)
        self.assertTrue(approved.forced_deterioration)
        self.assertEqual([l.rank for l in approved.lines], [1, 2])
        normal = approve_lines(source, QualityGateSettings(allow_losing_mate=True))
        self.assertFalse(normal.forced_deterioration)
        source = make_lines([-400, LineScore(mate_score=-8)])
        self.assertEqual([l.rank for l in approve_lines(source).lines], [1])

    def test_mate_zero_and_black_sorting(self):
        board = chess.Board(); board.push_san('e4')
        source = make_lines([LineScore(200), LineScore(100)], fen=board.fen())
        self.assertEqual(approve_lines(source).lines[0].rank, 2)
        score = LineScore(mate_score=0, mate_winner='black')
        self.assertLess(score.ordering('white'), LineScore(-10000).ordering('white'))

    def test_incompatible_partial_and_shallow_evidence_are_not_chess_rejections(self):
        source = make_lines([100, 0])
        values = [approve_lines(source, expected_engine_identity='other'),
                  approve_lines(replace(source, generation_metadata={'complete': False})),
                  approve_lines(source, QualityGateSettings(minimum_depth=18))]
        for result in values:
            self.assertEqual(result.state, 'incomplete')
            self.assertFalse(result.forced_deterioration)
            self.assertEqual(result.lines, ())
        self.assertEqual(approve_lines(source), approve_lines(source))


class ScaleTests(unittest.TestCase):
    def test_long_quiet_continuation_loses_interest(self):
        short = make_lines([200], sans=['Nf3'])
        long = make_lines([200], sans=['Nf3 Nf6 Ng1 Ng8 Nf3 Nf6'])
        self.assertGreater(TheScale().weigh(approve_lines(short)).lines[0].interest_weight,
                           TheScale().weigh(approve_lines(long)).lines[0].interest_weight)

    def test_equal_queen_exchange_does_not_claim_sacrifice(self):
        fen = '3qk3/8/8/8/8/8/8/3QK3 w - - 0 1'
        source = make_lines([200], fen=fen, sans=['Qd2 Qxd2+ Kxd2'])
        facts = inspect_continuation(source.fen, source.lines[0])
        self.assertFalse(any(e.component == 'sacrifice_interest' for e in facts.events))

    def test_critical_lines_can_be_weighted_without_positive_scores(self):
        source = make_lines([-200, -250, -600])
        approved = approve_lines(source, QualityGateSettings(maximum_deterioration_cp=50), reference_score=LineScore(0))
        weighted = TheScale().weigh(approved)
        self.assertEqual(len(weighted.lines), 2)
        self.assertTrue(weighted.approved.forced_deterioration)

    def test_acceptable_queen_investment_can_outrank_quiet_best(self):
        source = make_lines([200, 178], fen=SACRIFICE_FEN, sans=['Kh2', 'Qg8+ Rxg8 Nf7#'])
        approved = approve_lines(source)
        result = TheScale().weigh(approved)
        self.assertEqual(result.lines[0].line.rank, 2)
        self.assertIn('queen_material_investment', [e.event_id for e in result.lines[0].events])
        self.assertEqual(TheScale().weigh(approved), result)
        self.assertGreater(len(result.lines[0].components), 10)
        self.assertIsNone(result.lines[0].continuation.settled)
        self.assertIsNone(result.lines[0].continuation.eval_end)

    def test_failed_sacrifice_never_reaches_scale_or_provider(self):
        source = make_lines([200, -900], fen=SACRIFICE_FEN, sans=['Kh2', 'Qg8+ Rxg8 Nf7#'])
        provider = Mock(provider_id='fixture', version='1')
        provider.events.return_value = ()
        result = TheScale(event_providers=(provider,)).weigh(approve_lines(source))
        self.assertEqual([v.line.rank for v in result.lines], [1])
        self.assertEqual(provider.events.call_count, 1)
        with self.assertRaises(TypeError): TheScale().weigh(source)


    def test_evaluation_trend_and_explicit_settlement(self):
        source = make_lines([200], sans=['e4 e5 Nf3'])
        line = source.lines[0]
        def evidence(end):
            return ContinuationEvidence(line_identity(source.fen, line), line.engine_identity, 'fixture',
                (EvaluationSample(0, LineScore(200)), EvaluationSample(3, LineScore(end))), settled=True)
        improved = TheScale().weigh(approve_lines(source), {line.move_uci: evidence(400)}).lines[0]
        deteriorated = TheScale().weigh(approve_lines(source), {line.move_uci: evidence(0)}).lines[0]
        self.assertGreater(improved.interest_weight, deteriorated.interest_weight)
        self.assertEqual(improved.continuation.eval_trend_cp, 200)
        with self.assertRaises(ValueError): inspect_continuation(source.fen, line, evidence=replace(evidence(0), engine_identity='other'))

    def test_weights_and_event_extension_are_explicit(self):
        source = make_lines([200], sans=['e4 e5'])
        event = SemanticEvent('verified_queen_sacrifice', 'sacrifice_interest', 1, 'fixture_classifier_v1', 'Synthetic certified test evidence')
        provider = Mock(provider_id='fixture_classifier', version='1')
        provider.events.return_value = (event,)
        high = TheScale(event_providers=(provider,)).weigh(approve_lines(source)).lines[0]
        settings = ScaleSettings(weights=replace(ScaleWeights(), sacrifice_interest=0))
        low = TheScale(settings, (provider,)).weigh(approve_lines(source)).lines[0]
        self.assertGreater(high.interest_weight, low.interest_weight)
        with self.assertRaises(ValueError): SemanticEvent('bad', 'rarity', float('nan'), 'fixture', 'test')
        provider.events.return_value = (SemanticEvent('fake_score', 'objective_strength', 1, 'fixture', 'Not engine evidence'),)
        with self.assertRaises(ValueError):
            TheScale(event_providers=(provider,)).weigh(approve_lines(source))

    def test_partial_evaluation_samples_do_not_claim_endpoint_quality(self):
        source = make_lines([200], sans=['e4 e5 Nf3'])
        line = source.lines[0]
        evidence = ContinuationEvidence(line_identity(source.fen, line), line.engine_identity, 'fixture',
            (EvaluationSample(0, LineScore(200)), EvaluationSample(1, LineScore(400))))
        facts = inspect_continuation(source.fen, line, evidence=evidence)
        self.assertEqual(facts.eval_peak_cp, 400)
        self.assertIsNone(facts.eval_end)
        self.assertIsNone(facts.eval_trend_cp)

    def test_guarded_approval_and_unrelated_evidence(self):
        source = make_lines([200, -500])
        approved = approve_lines(source)
        with self.assertRaises(ValueError): replace(approved, lines=source.lines)
        with self.assertRaises(ValueError): TheScale().weigh(approved, {'not_approved': None})


class SettingsAndCacheTests(unittest.TestCase):
    def test_presets_and_admin_share_one_schema(self):
        for name, count in [('quick', 1), ('normal', 3), ('deep', 5)]:
            profile = load_profile(name)
            self.assertEqual(profile.generator.candidate_line_count, count)
            self.assertEqual(load_profile(asdict(profile)), profile)
        schema = {s.setting_id: s for s in AnalysisProfile().schema()}
        self.assertTrue(schema['generator.candidate_line_count'].affects_cache_identity)
        self.assertFalse(schema['quality_gate.absolute_tolerance_cp'].affects_cache_identity)
        self.assertTrue(schema['quality_gate.absolute_tolerance_cp'].affects_analysis_currentness)
        self.assertTrue(all(s.description for s in schema.values()))
        json.dumps([asdict(s) for s in schema.values()])

    def test_validation_and_identity_changes(self):
        for data in ({'extra': 1}, {'generator': {'candidate_line_count': 0}}, {'generator': {'candidate_line_count': True}},
                     {'scale': {'base_interest': float('nan')}}, {'generator': {'engine': {'depth': None}}}):
            with self.assertRaises(ValueError): load_profile(data)
        base = AnalysisProfile()
        gate = replace(base, quality_gate=replace(base.quality_gate, absolute_tolerance_cp=90))
        self.assertEqual(base.engine_identity, gate.engine_identity)
        self.assertNotEqual(base.currentness_identity, gate.currentness_identity)
        self.assertEqual(base.currentness_identity, replace(base, label='Renamed').currentness_identity)
        for generator in (replace(base.generator, candidate_line_count=5),
                          replace(base.generator, engine=replace(base.generator.engine, depth=13))):
            self.assertNotEqual(base.engine_identity, replace(base, generator=generator).engine_identity)

    def test_additive_migration_and_cache_rerun_without_updates(self):
        with sqlite3.connect(':memory:') as c:
            c.executescript('CREATE TABLE tactic_candidates(candidate_id INTEGER PRIMARY KEY); INSERT INTO tactic_candidates VALUES(1828);')
            migrate(c); migrate(c)
            repository = CandidateLineRepository(c)
            engine = FakeEngine()
            service = CandidateLineService(CandidateLineGenerator(engine), write_store=repository)
            first = service.candidate_lines(chess.STARTING_FEN)
            before = c.total_changes
            second = service.candidate_lines(chess.STARTING_FEN)
            self.assertEqual(first, second)
            self.assertEqual(c.total_changes, before)
            self.assertEqual(len(engine.calls), 1)
            self.assertEqual(c.execute('SELECT * FROM tactic_candidates').fetchall(), [(1828,)])
            self.assertEqual(c.execute('PRAGMA quick_check').fetchall(), [('ok',)])
            self.assertFalse(repository.put(first))
            self.assertEqual(c.total_changes, before)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_no_automatic_migration_and_incompatible_cache_not_reused(self):
        with sqlite3.connect(':memory:') as c:
            repo = CandidateLineRepository(c)
            self.assertIsNone(repo.get(chess.STARTING_FEN, 'unknown'))
            self.assertEqual(c.execute('SELECT name FROM sqlite_master').fetchall(), [])
            migrate(c)
            repo.put(make_lines([200]))
            self.assertIsNone(repo.get(chess.STARTING_FEN, 'different_identity'))

    def test_existing_analyzer_versions_unchanged(self):
        from analysis_registry import ANALYZERS
        from candidate_verification_registry import CANDIDATE_VERIFIERS
        self.assertEqual({k: v.analyzer_version for k, v in ANALYZERS.items()},
            {'missed_fork': '2', 'missed_mate': '3', 'missed_pin': '2', 'missed_skewer': '1', 'missed_xray': '1'})
        self.assertEqual(CANDIDATE_VERIFIERS['missed_fork'].analyzer_version, '3')

    def test_pipeline_recomputes_policy_and_scale_without_engine_or_cache_churn(self):
        with sqlite3.connect(':memory:') as connection:
            migrate(connection)
            engine = FakeEngine()
            service = CandidateLineService(CandidateLineGenerator(engine), write_store=CandidateLineRepository(connection))
            pipeline = LineAnalysisService(service)
            first = pipeline.analyze(chess.STARTING_FEN)
            changes = connection.total_changes
            strict = replace(AnalysisProfile(), quality_gate=QualityGateSettings(absolute_tolerance_cp=0, relative_tolerance=0))
            second = pipeline.analyze(chess.STARTING_FEN, strict)
            self.assertEqual(len(engine.calls), 1)
            self.assertEqual(connection.total_changes, changes)
            self.assertNotEqual(first.currentness_identity, second.currentness_identity)
            self.assertEqual(len(second.weighted.lines), 1)

    def test_core_has_no_desktop_or_analyzer_imports(self):
        import ast
        root = Path(__file__).resolve().parents[1]
        modules = ('candidate_lines', 'candidate_line_engine', 'candidate_line_service',
                   'candidate_line_repository', 'candidate_line_pipeline', 'quality_gate',
                   'the_scale', 'continuation_quality', 'analysis_settings')
        for module in modules:
            tree = ast.parse((root/(module+'.py')).read_text())
            imports = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            imports.extend(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
            self.assertFalse(any(name.startswith(('tkinter', 'merlin_ui', 'analyze_forks', 'analyze_pins',
                                                  'analyze_skewers', 'analyze_xrays')) for name in imports), module)


if __name__ == '__main__': unittest.main()
