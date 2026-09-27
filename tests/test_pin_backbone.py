"""Contracts for the opt-in adapter; scripted evidence never launches an engine."""
from dataclasses import replace
import ast
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import chess
from analysis_backbone import AnalysisBackbone
from analysis_settings import identity, load_settings
from candidate_lines import CandidateLine, CandidateLineSet, LineScore, to_data
from candidate_line_request import request_identity
from candidate_line_service import CandidateLineService
from candidate_verification_result import CandidateVerificationResult
from pin_analysis_settings import PinPolicy, PinBackbonePolicy, pin_profile
from tactical_opportunities import TacticalMotif
from pin_backbone import replay_single_position, analyze_candidate_position, branch_consensus
from analyze_pins_v2 import analyze_single_move
from test_pins_v2 import scripted
from test_pins import ABSOLUTE_FEN
from test_heavy_services import move_row
from feedback.context import FeedbackContextBuilder
from feedback.generator import FeedbackGenerator


def recorded(evaluate):
    def lookup(fen, profile):
        raw = evaluate(fen, profile)
        board = chess.Board(fen)
        if not raw["principal_variation"] and not board.is_game_over():
            move = next(iter(board.legal_moves))
            raw = {**raw, "principal_variation": board.san(move), "best_move_uci": move.uci()}
        return {**raw, "depth":10 if profile=="tactic_quick_v1" else 18,
                "engine_name":"fixture", "engine_version":"1", "limit_type":"depth",
                "limit_value":10 if profile=="tactic_quick_v1" else 18}
    return lookup


class FixtureGenerator:
    def __init__(self, evaluate): self.evaluate = evaluate
    def generate(self, fen, settings, *, root_moves=()):
        board = chess.Board(fen)
        raw = self.evaluate(fen, "tactic_quick_v1" if settings.engine.depth == 10 else "tactic_verify_v1")
        copy = board.copy(); pv = []
        for san in raw["principal_variation"].split():
            move = copy.parse_san(san); pv.append(move.uci()); copy.push(move)
        roots = list(root_moves) if root_moves else [pv[0], *[m.uci() for m in board.legal_moves if m.uci()!=pv[0]]]
        request = request_identity(settings, root_moves)
        lines = tuple(CandidateLine(i+1, uci,
            LineScore(raw["score_cp"] if uci==pv[0] else (-10000 if board.turn else 10000)),
            tuple(pv) if uci==pv[0] else (uci,), settings.engine.depth, request)
            for i, uci in enumerate(roots[:settings.candidate_line_count]))
        return CandidateLineSet(fen, "white" if board.turn else "black", settings.candidate_line_count,
            settings.engine.profile_id, request, lines,
            {"complete":True, "generator_settings":to_data(settings), "root_moves":root_moves})


class PinBackboneTests(unittest.TestCase):
    def setUp(self):
        self.row = move_row(ABSOLUTE_FEN, "h1h2")
        self.lookup = recorded(scripted(self.row, "Bb2 a6 Bxc3+ Kc5")[0])

    def test_replay_immediate_delayed_and_feedback_equal(self):
        for prefix in ("Bb2 a6 Bxc3+ Kc5", "Bb2 a6 Kh2 a5 Bxc3+ Kc5"):
            lookup = recorded(scripted(self.row, prefix)[0])
            before = dict(self.row)
            expected = analyze_single_move(self.row, lookup)
            replay = replay_single_position(self.row, lookup)
            self.assertEqual(to_data(expected), to_data(replay.result))
            self.assertTrue(replay.settlements)
            generator, contexts = FeedbackGenerator(), FeedbackContextBuilder()
            self.assertEqual(generator.generate(contexts.build({**self.row, **expected.candidate}, expected.opportunity)),
                generator.generate(contexts.build({**self.row, **replay.result.candidate}, replay.result.opportunity)))
            self.assertEqual(before, self.row)


    def test_mate_defer_is_equal(self):
        def lookup(fen, profile):
            return {**self.lookup(fen, profile), "score_type":"mate", "score_cp":None, "mate":3}
        self.assertEqual(to_data(analyze_single_move(self.row, lookup)),
                         to_data(replay_single_position(self.row, lookup).result))

    def test_best_line_and_normal_share_policy(self):
        for multiline in (False, True):
            result = analyze_candidate_position(self.row, "c1b2", CandidateLineService(FixtureGenerator(self.lookup)),
                profile=pin_profile(multiline))
            self.assertEqual(result.classification, "verified", result.details)
            self.assertEqual(result.opportunity.payoff_timing, "immediate")
            self.assertEqual(result.details["continuation_count_considered"], 1)
            self.assertEqual(result.details["escalation"]["branches_escalated"], 0)

    def hit(self):
        result = analyze_single_move(self.row, self.lookup)
        return CandidateVerificationResult(result.state, result.candidate, result.details, result.opportunity)

    def test_consensus_uses_least_payoff_and_never_scale(self):
        hit = self.hit()
        changed = replace(hit, opportunity=replace(hit.opportunity,
            metadata={**hit.opportunity.metadata, "related_retained_material_cp":100}))
        state, chosen = branch_consensus([hit, changed])
        self.assertEqual(state, "verified_payoff_changed")
        self.assertEqual(chosen.opportunity.metadata["related_retained_material_cp"], 100)
        self.assertEqual(chosen.opportunity.primary_outcome.kind, "win_material")
        self.assertEqual(branch_consensus([hit, hit])[0], "verified")

    def test_primary_consensus_preserves_secondary_motif_variance(self):
        hit = self.hit()
        annotated = replace(hit, opportunity=replace(hit.opportunity,
            motifs=(*hit.opportunity.motifs, TacticalMotif('sacrifice', attribution='context_only'))))
        state, selected = branch_consensus([hit, annotated, hit])
        self.assertEqual(state, 'verified')
        metadata = selected.opportunity.metadata
        self.assertTrue(metadata['primary_motif_consensus'])
        self.assertTrue(metadata['secondary_motif_variance'])
        self.assertEqual(len(metadata['branch_motif_evidence']), 3)
        self.assertTrue(any(m['kind'] == 'sacrifice'
            for m in metadata['branch_motif_evidence'][1]['motifs']))
        self.assertEqual(branch_consensus([hit, annotated],
            PinBackbonePolicy(motif_consensus='all_motifs'))[0], 'ambiguous')

    def test_hit_nohit_conflict_is_ambiguous(self):
        self.assertEqual(branch_consensus([self.hit(), CandidateVerificationResult("analyzed_no_hit")])[0], "ambiguous")

    def test_causality_disagreement_is_ambiguous(self):
        hit = self.hit()
        op = hit.opportunity
        changed = replace(hit, opportunity=replace(op, motifs=(replace(op.motifs[0], attribution="context_only"),)))
        self.assertEqual(branch_consensus([hit, changed])[0], "ambiguous")

    def test_unsettled_and_execution_error_are_distinct(self):
        self.assertEqual(branch_consensus([CandidateVerificationResult("ambiguous")])[0], "ambiguous")
        self.assertEqual(branch_consensus([CandidateVerificationResult("error")])[0], "error")

    def test_settings_schema_keeps_pin_thresholds_separate(self):
        policy = PinPolicy()
        self.assertEqual(load_settings(PinPolicy, to_data(policy)), policy)
        self.assertEqual(policy.proof_window.settlement_plies, 4)
        self.assertTrue(all(not s.affects_raw_cache_identity for s in policy.schema()))
        self.assertEqual(policy.quick_min_gain_cp, 120)
        self.assertEqual(policy.verify_min_gain_cp, 150)

    def test_window_mismatch_rejected_before_requests(self):
        service = CandidateLineService(None)
        with self.assertRaises(ValueError):
            analyze_candidate_position(self.row, "c1b2", service,
                profile=replace(pin_profile(), proof=replace(PinPolicy().proof, settlement_plies=8)))
        self.assertFalse(service.stats)

    def test_provenance_deterministic_and_recorded_namespace_explicit(self):
        first = replay_single_position(self.row, self.lookup)
        second = replay_single_position(self.row, self.lookup)
        self.assertEqual(first.provenance, second.provenance)
        self.assertIn("not_new_cache", first.provenance["source"])

    def test_portability_no_engine_or_database_side_effects(self):
        for name in ("pin_backbone", "pin_analysis_settings", "position_line_replay", "approved_bounded_proof", "threshold_review", "pin_consensus"):
            source = (Path(__file__).resolve().parents[1]/(name+".py")).read_text(encoding="utf-8")
            tree = ast.parse(source)
            imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            imports += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
            self.assertFalse(any(m.startswith(("tkinter", "sqlite3", "subprocess", "chess.engine")) for m in imports))
        with patch("sqlite3.connect", side_effect=AssertionError("No DB")), patch("chess.engine.SimpleEngine.popen_uci", side_effect=AssertionError("No engine")):
            replay_single_position(self.row, self.lookup)

    def test_root_gate_rejection_never_requests_proof(self):
        parent = self
        class RejectedRoot(FixtureGenerator):
            def generate(self, fen, settings, **kwargs):
                result = super().generate(fen, settings, **kwargs)
                parent.assertEqual(fen, parent.row["fen_before"])
                lines = list(result.lines)
                lines[1] = replace(lines[1], score=LineScore(1500))
                lines = sorted(lines, key=lambda line: line.score.score_cp, reverse=True)
                return replace(result, lines=tuple(replace(line, rank=i+1) for i,line in enumerate(lines)))
        result = analyze_candidate_position(self.row, "c1b2", CandidateLineService(RejectedRoot(self.lookup)))
        self.assertEqual(result.classification, "rejected", result.details)
        self.assertFalse(result.details["root_move_passes_gate"])
        self.assertEqual(result.details["escalation"]["branches_escalated"], 0)

    def test_shared_escalation_can_resolve_or_protect(self):
        from approved_bounded_proof import verify_approved_bounded_line
        for budget, expected in ((3, "verified"), (0, "ambiguous")):
            calls = []
            def solver(*args):
                proof = verify_approved_bounded_line(*args)
                calls.append(proof)
                return replace(proof, state="unsettled") if len(calls)==1 else proof
            profile = pin_profile()
            profile = replace(profile, escalation=replace(profile.escalation,
                max_escalated_branches_per_candidate=budget))
            with patch("pin_backbone.verify_approved_bounded_line", side_effect=solver):
                result = analyze_candidate_position(self.row, "c1b2", CandidateLineService(FixtureGenerator(self.lookup)), profile=profile)
            self.assertEqual(result.classification, expected, result.details)
            self.assertEqual(len(calls), 2 if budget else 1)

    def test_scale_weight_changes_cannot_change_pin_truth(self):
        from analysis_settings import ScaleSettings, ScaleWeights
        outputs = []
        for weight in (0.0, 100.0):
            profile = replace(pin_profile(), scale=ScaleSettings(weights=ScaleWeights(material_payoff=weight)))
            outputs.append(analyze_candidate_position(self.row, "c1b2", CandidateLineService(FixtureGenerator(self.lookup)), profile=profile))
        self.assertEqual(outputs[0].classification, outputs[1].classification)
        self.assertEqual(outputs[0].opportunity, outputs[1].opportunity)
        self.assertNotEqual(outputs[0].details["backbone_provenance"], outputs[1].details["backbone_provenance"])

    def test_registry_adoption_is_explicit_and_preserves_v2(self):
        from analysis_registry import ANALYZERS
        from candidate_verification_registry import pin_backbone_verifier
        original = ANALYZERS["missed_pin"]
        adapter = pin_backbone_verifier()
        self.assertIs(ANALYZERS["missed_pin"], original)
        self.assertEqual(adapter.analyzer_version, "2")
        self.assertIsNot(adapter.heavy, original.heavy)
