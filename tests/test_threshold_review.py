"""Boundary confirmation is evidence review, never a threshold discount."""
from dataclasses import replace
import unittest
from unittest.mock import Mock
import chess
from analysis_settings import load_settings, identity
from candidate_lines import to_data
from candidate_line_service import CandidateLineService
from pin_analysis_settings import PinBackbonePolicy, pin_evaluation_profiles
from threshold_review import ThresholdReviewSettings, ThresholdReviewService
from test_pin_backbone import FixtureGenerator


class ThresholdReviewTests(unittest.TestCase):
    def setUp(self):
        board = chess.Board()
        self.fens = [board.fen()]
        board.push_san("e4"); self.fens.append(board.fen())
        board = chess.Board(); board.push_san("d4"); self.fens.append(board.fen())
        self.base = pin_evaluation_profiles()["tactic_verify_v1"]

    def service(self, gain):
        scores = dict(zip(self.fens, [228, 19, 19+gain]))
        def evidence(fen, profile):
            board = chess.Board(fen)
            return {"score_cp":scores[fen], "principal_variation":board.san(next(iter(board.legal_moves)))}
        lines = CandidateLineService(FixtureGenerator(evidence))
        return ThresholdReviewService(lines, self.base), lines

    def test_margin_is_inclusive_below_but_not_at_acceptance_threshold(self):
        settings = ThresholdReviewSettings()
        self.assertEqual([settings.requires_review(n, 150) for n in (134,135,146,149,150,180)],
                         [False,True,True,True,False,False])

    def test_clear_values_and_disabled_policy_make_no_requests(self):
        for value in (134,150,180):
            review = ThresholdReviewService(Mock(), self.base)
            result = review.review_gain(*self.fens, "white", value, 150)
            self.assertEqual(result.state, "not_needed")
            self.assertEqual(review.requests.attempted, [])
        self.assertFalse(ThresholdReviewSettings(enabled=False).requires_review(146,150))

    def test_near_boundary_requires_confirmation_and_can_still_fail(self):
        review, lines = self.service(146)
        result = review.review_gain(*self.fens, "white", 146,150)
        self.assertEqual(result.state,"rejected")
        self.assertEqual(result.confirmed_gain_cp,146)
        self.assertEqual(lines.stats["engine_searches"],3)
        self.assertEqual(review.backbone.profile.generator.engine.depth,22)

    def test_confirmed_threshold_pass_only_permits_proof(self):
        review, _ = self.service(150)
        result = review.review_gain(*self.fens,"white",146,150)
        self.assertEqual(result.state,"comparison_passed")
        self.assertFalse(hasattr(result,"candidate"))
        with self.assertRaises(ValueError): review.review_gain(*self.fens,"white",146,150)

    def test_settings_schema_roundtrip_and_identity_separation(self):
        policy = PinBackbonePolicy()
        self.assertEqual(load_settings(PinBackbonePolicy,to_data(policy)),policy)
        changed = replace(policy,boundary=replace(policy.boundary,margin_cp=3))
        self.assertFalse(changed.boundary.requires_review(146,150))
        self.assertNotEqual(identity(policy),identity(changed))
        self.assertEqual(policy.boundary.confirmation,changed.boundary.confirmation)
        fields = {s.setting_id:s for s in policy.schema("pin_backbone.")}
        margin = fields["pin_backbone.boundary.margin_cp"]
        self.assertEqual((margin.default,margin.minimum,margin.maximum,margin.level),(15,0,100,"basic"))
        self.assertTrue(margin.description and margin.label and margin.affects_result_currentness)
        self.assertFalse(margin.affects_raw_cache_identity)
        self.assertTrue(fields["pin_backbone.boundary.confirmation.engine.depth"].affects_raw_cache_identity)
        for value in (-1,101):
            with self.assertRaises(ValueError): ThresholdReviewSettings(margin_cp=value)

    def test_confirmation_requires_stronger_comparable_evidence(self):
        settings = ThresholdReviewSettings()
        for depth in (10,18):
            config=replace(settings,confirmation=replace(settings.confirmation,engine=replace(settings.confirmation.engine,depth=depth)))
            with self.assertRaises(ValueError): ThresholdReviewService(Mock(),self.base,config)
        config=replace(settings,confirmation=replace(settings.confirmation,engine=replace(settings.confirmation.engine,threads=2)))
        with self.assertRaises(ValueError): ThresholdReviewService(Mock(),self.base,config)

    def test_player_perspective_changes_comparison_not_threshold(self):
        review,_=self.service(-151)
        result=review.review_gain(*self.fens,"black",146,150)
        self.assertEqual(result.confirmed_gain_cp,151)
        self.assertEqual(result.state,"comparison_passed")


class BoundaryAdapterTests(unittest.TestCase):
    def run_case(self, initial_gain=146, confirmed_gain=180, *, margin=15, scale_weight=5.0, unsettled=False):
        from unittest.mock import patch
        from test_pins import ABSOLUTE_FEN
        from test_heavy_services import move_row
        from test_pins_v2 import scripted
        from test_pin_backbone import recorded
        from pin_analysis_settings import pin_profile
        from pin_backbone import analyze_candidate_position
        from approved_bounded_proof import verify_approved_bounded_line
        from analysis_settings import ScaleSettings, ScaleWeights
        row=move_row(ABSOLUTE_FEN,"h1h2")
        evaluate=recorded(scripted(row,"Bb2 a6 Bxc3+ Kc5")[0])
        depths=[]
        class Scores(FixtureGenerator):
            def generate(self,fen,settings,**kwargs):
                depths.append(settings.engine.depth)
                result=super().generate(fen,settings,**kwargs)
                if fen==row["fen_after"] and settings.engine.depth in (18,22):
                    gain=initial_gain if settings.engine.depth==18 else confirmed_gain
                    result=replace(result,lines=tuple(replace(line,score=replace(line.score,score_cp=300-gain)) for line in result.lines))
                return result
        service=CandidateLineService(Scores(evaluate))
        policy=PinBackbonePolicy(boundary=ThresholdReviewSettings(margin_cp=margin))
        profile=replace(pin_profile(),scale=ScaleSettings(weights=ScaleWeights(material_payoff=scale_weight)))
        def prove(*args):
            proof=verify_approved_bounded_line(*args)
            return replace(proof,state="unsettled") if unsettled else proof
        with patch("pin_backbone.verify_approved_bounded_line",side_effect=prove):
            result=analyze_candidate_position(row,"c1b2",service,profile=profile,backbone_policy=policy)
        return result,depths

    def test_near_boundary_runs_proof_only_after_confirmed_threshold(self):
        result,depths=self.run_case()
        self.assertEqual(result.classification,"verified",result.details)
        self.assertIn(22,depths)
        self.assertEqual(result.details["boundary_review"]["result"]["confirmed_gain_cp"],180)
        self.assertIn("depth22",result.opportunity.proof.scope)

    def test_scale_cannot_override_confirmed_rejection_or_unsettled_proof(self):
        for weight in (0.0,100.0):
            result,_=self.run_case(confirmed_gain=146,scale_weight=weight)
            self.assertEqual(result.classification,"rejected",result.details)
            self.assertEqual(result.details["branches_settled"],0)
            result,_=self.run_case(scale_weight=weight,unsettled=True)
            self.assertEqual(result.classification,"ambiguous",result.details)
            self.assertIsNone(result.candidate)

    def test_setting_and_clear_comparison_paths_skip_boundary(self):
        for gain,margin,expected in ((134,15,"rejected"),(146,3,"rejected"),(180,15,"verified")):
            result,depths=self.run_case(initial_gain=gain,margin=margin)
            self.assertEqual(result.classification,expected,result.details)
            self.assertNotIn(22,depths)


