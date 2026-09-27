from dataclasses import asdict, replace
from pathlib import Path
import ast
from contextlib import closing
import json
import sqlite3
import unittest
from unittest.mock import Mock, patch
import chess

from analysis_settings import AnalysisProfile, load_profile, identity
from candidate_lines import CandidateLine, CandidateLineSet, LineScore
from candidate_line_request import request_identity
from candidate_line_repository import CandidateLineRepository, insert_only_authorizer
from candidate_line_service import CandidateLineService
from migrate_candidate_line_cache import migrate
from proof_escalation import ProofEscalationService, ProofEscalationRequest, ApprovedPrefixMove, verification_profile
from candidate_line_settlement import verify_candidate_line_settlement
from candidate_line_proof import ApprovedPositionEvidence
from tactical_proof import ProofWindow
from board_analysis import material_balance
from analyze_forks_v31 import analyze_existing_candidate
from candidate_verification import verify_candidates
from candidate_verification_registry import escalating_fork_verifier
import test_forks_v3 as fixtures
from test_fork_multiline import FixtureService, selected_two_ply_proof


def pv_set(fen, settings, root_moves=(), *, score=None, complete=True):
    board = chess.Board(fen)
    moves = []
    for _ in range(22):
        if board.is_game_over():
            break
        quiet = [move for move in board.legal_moves if not board.is_capture(move) and not board.gives_check(move)]
        move = (quiet or list(board.legal_moves))[0]
        moves.append(move.uci())
        board.push(move)
    key = request_identity(settings, root_moves)
    return CandidateLineSet(fen, "white" if chess.Board(fen).turn else "black", settings.candidate_line_count,
        settings.engine.profile_id, key, (CandidateLine(1, moves[0], score or LineScore(400), tuple(moves), 18, key),),
        {"complete": complete, "generator_settings": asdict(settings)})


class PVService:
    def __init__(self, *, complete=True, score=None):
        self.calls, self.complete, self.score = [], complete, score
    def candidate_lines(self, fen, settings, *, root_moves=()):
        self.calls.append((fen, settings, root_moves))
        return pv_set(fen, settings, root_moves, complete=self.complete, score=self.score)


def request(reason="proof_unsettled", observed="unsettled"):
    board = chess.Board(); board.push_san("e4")
    return ProofEscalationRequest(board.fen(), "white", reason, observed)


class EscalationTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile("normal_escalation")

    def test_stable_failed_root_and_scale_do_not_trigger(self):
        raw = PVService(); service = ProofEscalationService(raw, self.profile)
        for req in (request(observed="stable"), request("high_scale_interest"), replace(request(), root_admitted=False)):
            self.assertEqual(service.escalate(req, fixtures.PIECE_VALUES).status, "not_needed")
        self.assertEqual(raw.calls, [])

    def test_unsettled_settles_legally_at_fresh_endpoint(self):
        raw = PVService(); service = ProofEscalationService(raw, self.profile)
        result = service.escalate(request(), fixtures.PIECE_VALUES)
        self.assertEqual(result.status, "complete")
        proof = result.proof
        self.assertGreaterEqual(len(proof.steps), 9)
        self.assertLessEqual(len(proof.steps), 17)
        self.assertEqual(raw.calls[-1][0], proof.final_fen)
        self.assertEqual(proof.final_evidence["score_pov"], "white")
        board = chess.Board(request().after_tactic_fen)
        for step in proof.steps:
            self.assertEqual(board.fen(), step.before_fen)
            board.push_uci(step.uci)
            self.assertEqual(board.fen(), step.after_fen)
            self.assertEqual(material_balance(board, chess.WHITE, fixtures.PIECE_VALUES), step.material_cp)

    def test_branch_request_and_child_limits_protect(self):
        profile = replace(self.profile, escalation=replace(self.profile.escalation, max_escalated_branches_per_candidate=1))
        service = ProofEscalationService(PVService(), profile)
        service.escalate(request(), fixtures.PIECE_VALUES)
        self.assertEqual(service.escalate(request(), fixtures.PIECE_VALUES).reason, "branch_limit")
        profile = replace(self.profile, escalation=replace(self.profile.escalation, max_requests_per_candidate=1))
        service = ProofEscalationService(PVService(), profile)
        result = service.escalate(request(), fixtures.PIECE_VALUES)
        self.assertEqual(result.status, "budget_exhausted")
        self.assertEqual(len(service.requests.attempted), 1)
        raw = PVService(); evidence = ApprovedPositionEvidence(raw, self.profile)
        approval = evidence.approved(request().after_tactic_fen)
        entry = ApprovedPrefixMove(approval, approval.lines[0].move_uci)
        profile = replace(self.profile, escalation=replace(self.profile.escalation, max_child_depth_levels=0))
        service = ProofEscalationService(raw, profile)
        self.assertEqual(service.escalate(replace(request(), prefix=(entry,)), fixtures.PIECE_VALUES).reason, "child_depth_limit")
        self.assertEqual(service.branches_escalated, 0)

    def test_missing_and_mate_are_not_false_rejections(self):
        result = ProofEscalationService(PVService(complete=False), self.profile).escalate(request(), fixtures.PIECE_VALUES)
        self.assertEqual(result.status, "incomplete")
        result = ProofEscalationService(PVService(score=LineScore(mate_score=-3)), self.profile).escalate(request(), fixtures.PIECE_VALUES)
        self.assertEqual(result.status, "deferred")
        self.assertEqual(result.proof.final_evidence["mate_winner"], "black")
        raw = PVService()
        result = ProofEscalationService(raw, self.profile).escalate(request(observed="mate"), fixtures.PIECE_VALUES)
        self.assertEqual(result.status, "deferred"); self.assertEqual(raw.calls, [])

    def test_exact_cache_reuse_and_policy_identity_separation(self):
        with closing(sqlite3.connect(":memory:")) as db:
            migrate(db)
            db.set_authorizer(insert_only_authorizer)
            generator = Mock(); generator.generate.side_effect = pv_set
            cached = CandidateLineService(generator, write_store=CandidateLineRepository(db))
            first = ProofEscalationService(cached, self.profile).escalate(request(), fixtures.PIECE_VALUES)
            changes, searches = db.total_changes, generator.generate.call_count
            second = ProofEscalationService(cached, self.profile).escalate(request(), fixtures.PIECE_VALUES)
            self.assertEqual(first, second)
            self.assertEqual(db.total_changes, changes)
            self.assertEqual(generator.generate.call_count, searches)
            self.assertEqual(cached.stats["cache_hits"], searches)
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("DELETE FROM engine_candidate_line_cache")
        changed = replace(self.profile, quality_gate=replace(self.profile.quality_gate, absolute_tolerance_cp=100))
        self.assertNotEqual(changed.currentness_identity, self.profile.currentness_identity)
        self.assertEqual(verification_profile(changed).engine_identity, verification_profile(self.profile).engine_identity)
        self.assertNotEqual(self.profile.engine_identity, verification_profile(self.profile).engine_identity)
        old = {name: asdict(getattr(AnalysisProfile(), name)) for name in ("generator", "quality_gate", "scale", "proof")}
        self.assertEqual(AnalysisProfile().currentness_identity, identity(old))
        schema = {item.setting_id: item for item in self.profile.schema()}
        self.assertTrue(schema["escalation.verification.engine.depth"].affects_raw_cache_identity)
        self.assertFalse(schema["escalation.max_requests_per_candidate"].affects_raw_cache_identity)


    def test_short_pv_requires_new_evidence_and_unsettled_window_is_bounded(self):
        calls = []
        settings = verification_profile(self.profile).generator
        def short(fen):
            calls.append(fen)
            return replace(pv_set(fen, settings).lines[0], pv_uci=(pv_set(fen, settings).lines[0].move_uci,), pv_san=())
        proof = verify_candidate_line_settlement(chess.Board(request().after_tactic_fen), chess.WHITE, (), short,
            fixtures.PIECE_VALUES, ProofWindow(user_moves=1, settlement_plies=0))
        self.assertEqual(proof.state, "unsettled")
        self.assertEqual(len(proof.steps), 3)
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[-1], proof.final_fen)

    def test_no_recursive_or_desktop_or_database_dependencies(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("proof_escalation.py", "candidate_line_settlement.py", "analyze_forks_v31.py", "fork_verification_branches.py", "candidate_verification_result.py"):
            tree = ast.parse((root/name).read_text())
            imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            self.assertFalse(any(name.startswith(("tkinter", "sqlite3", "subprocess", "merlin_ui")) for name in imports))


class ForkEscalationTests(unittest.TestCase):
    def test_settled_consensus_no_escalation_and_input_preserved(self):
        raw = FixtureService(fixtures.candidate()); verification = Mock()
        before = json.dumps(raw.row, sort_keys=True)
        with patch("analyze_forks_v3_multiline.verify_bounded_line", side_effect=selected_two_ply_proof):
            result = analyze_existing_candidate(raw.row, raw, verification)
        self.assertEqual(result.state, "candidate")
        self.assertEqual(result.details["escalation"]["branches_escalated"], 0)
        verification.candidate_lines.assert_not_called()
        self.assertEqual(json.dumps(raw.row, sort_keys=True), before)
        self.assertEqual(len(result.details["geometric_targets"]), 2)
        self.assertEqual(len(result.details["realizable_targets"]), 1)


    def test_unsettled_and_disagreement_resolve_or_remain(self):
        from proof_escalation import ProofEscalationResult
        for remains in (False, True):
            raw = FixtureService(fixtures.candidate())
            def unsettled(*args):
                return replace(selected_two_ply_proof(*args), state="unsettled")
            def deep(service, req, values):
                after = chess.Board(req.after_tactic_fen)
                tokens = []
                for entry in req.prefix:
                    move = after.parse_uci(entry.move_uci); tokens.append(after.san(move)); after.push(move)
                proof = fixtures.proof_for(chess.Board(req.after_tactic_fen), " ".join(tokens))
                proof = replace(proof, final_evidence={"score_cp":400,"score_pov":"white","score_type":"cp"})
                service.branches_escalated += 1
                return ProofEscalationResult("unresolved" if remains else "complete", "test", proof)
            with patch("analyze_forks_v3_multiline.verify_bounded_line", side_effect=unsettled), patch("proof_escalation.ProofEscalationService.escalate", new=deep):
                result = analyze_existing_candidate(raw.row, raw)
            self.assertEqual(result.state, "ambiguous" if remains else "candidate")
            self.assertEqual(result.details["escalation"]["branches_escalated"], 2)
            self.assertEqual(result.details["normal_robustness"]["classification"], "ambiguous")

    def test_disagreement_remains_conservative_after_deep_proof(self):
        raw = FixtureService(fixtures.candidate("r3k3/7p/8/3N4/8/8/P7/4K3 w - - 0 1"), responses=("Nxa8", "Nd5"))
        profile = load_profile("normal_escalation")
        profile = replace(profile, escalation=replace(profile.escalation, max_requests_per_candidate=0))
        with patch("analyze_forks_v3_multiline.verify_bounded_line", side_effect=selected_two_ply_proof):
            result = analyze_existing_candidate(raw.row, raw, profile=profile)
        self.assertEqual(result.state, "ambiguous")
        self.assertEqual(result.details["normal_robustness"]["reason"], "acceptable_continuations_disagree")
        self.assertEqual(result.details["escalation_attempts"][0]["status"], "budget_exhausted")

    def test_actual_disagreement_resolution_keeps_every_branch(self):
        from analyze_forks_v31 import review_counterplay
        from fork_verification_branches import ForkBranchContext
        from test_fork_multiline import branch_fixture
        from proof_escalation import ProofEscalationResult
        raw = FixtureService(fixtures.candidate())
        after = chess.Board(raw.row["fen_before"]); after.push_uci(raw.row["solution_move_uci"])
        evidence = ApprovedPositionEvidence(raw)
        branches = [dict(branch_fixture(retained=100), player_move_uci="c7a8"),
                    dict(branch_fixture(), player_move_uci="c7a8")]
        details = {"geometric_targets": []}
        context = ForkBranchContext(raw.row, after, evidence,
            {key:{"score_type":"cp", "score_cp":400} for key in ("before","played","tactic")}, details, load_profile("normal_escalation"))
        proof = replace(fixtures.proof_for(after,"Kf7 Nxa8"), final_evidence={"score_cp":400})
        esc = Mock(); esc.profile = verification_profile(context.profile)
        esc.escalate.return_value = ProofEscalationResult("complete", "stable", proof)
        esc.escalate_selected.side_effect = lambda selections, values: ((key, esc.escalate(req, values)) for key, req in selections)
        replacement = dict(branch_fixture(), player_move_uci="c7a8")
        with patch("analyze_forks_v31.interpret_proof", return_value=Mock()), patch("analyze_forks_v31.summarize_branch", return_value=replacement):
            review_counterplay(context, branches, [], esc)
        self.assertEqual(len(branches), 2)
        self.assertEqual(esc.escalate.call_count, 1)
        from fork_robustness import summarize_continuations
        self.assertEqual(summarize_continuations(branches).classification, "verified")
        self.assertEqual(details["normal_robustness"]["classification"], "ambiguous")

    def test_operational_error_is_distinct_from_chess_ambiguity(self):
        raw = Mock(); raw.candidate_lines.side_effect = RuntimeError("engine unavailable")
        rows = [fixtures.candidate()]
        result = verify_candidates(rows, escalating_fork_verifier(load_profile("normal_escalation")), raw)[0][1]
        self.assertEqual(result.state, "error")
        self.assertEqual(result.details["classification"], "error")


if __name__ == "__main__":
    unittest.main()
