"""Fact fidelity, source precedence, extensibility and read/UI boundaries."""
import ast
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from feedback import FeedbackContext, FeedbackContextBuilder, FeedbackGenerator, FeedbackResult
from feedback.adapters import LegacyAdapterRegistry, LegacyEvidence
from feedback.models import FeedbackFact
from feedback.registry import DataTemplateProvider, FeedbackRegistry
from feedback.templates import DEFAULT_PACK
from tactical_opportunities import (TacticalOpportunity, TacticalOutcome, TacticalMotif,
    TacticalPresentation, ProofEvidence, Evaluation, PieceReference, LineRelationship,
    opportunity_to_dict)
from tactic_presentation import TacticReadService
from test_game_review_tactics import fixture_db, add


def row(kind="missed_fork", metadata=None):
    return dict(candidate_id=1, move_id=101, game_id=1, color="black", move_number=17,
                tactic_type=kind, san_played="Nf6", uci_played="g8f6", solution_move_san="Qf5+",
                solution_move_uci="f2f5", solution_line="Qf5+ Kc3 Qxe5+",
                metadata_json=json.dumps(metadata) if metadata is not None else None)


def opportunity(kind="xray", attribution="supported", outcome="win_exchange"):
    return TacticalOpportunity(TacticalOutcome(outcome),
        (TacticalMotif(kind, True, attribution, "The stored recapture retains material."),),
        proof=ProofEvidence(score_pov="black", retained_material_gain_cp=200,
                            evaluation_after_settlement=Evaluation(cp=846)),
        presentation=TacticalPresentation("strong_callout", "Do not copy this title", "Do not blindly copy presentation prose"),
        relationships=(LineRelationship(kind, PieceReference("rook", "black", "h2"),
            PieceReference("rook", "white", "h4"), PieceReference("bishop", "black", "h3")),))


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.builder = FeedbackContextBuilder()
        self.generator = FeedbackGenerator()

    def test_opportunity_priority_and_canonical_identity(self):
        r = row(metadata={"targets": [{"piece":"queen","square":"a1"},{"piece":"rook","square":"b1"}]})
        c = self.builder.build(r, opportunity())
        f = self.generator.generate(c)
        self.assertEqual(f.title, "Win the exchange")
        self.assertEqual(f.motif_labels, ("X-ray",))
        self.assertNotIn("a1", f.explanation)
        self.assertNotIn("Do not", f.explanation)
        self.assertEqual(c.facts, ())
        self.assertEqual(c.proof.line_san, r["solution_line"])
        self.assertIn("Continuation: Qf5+ → Kc3 → Qxe5+", f.explanation)
        self.assertNotIn("retains material", f.explanation)

    def test_legacy_fork_targets_conversion_and_no_inferred_net_gain(self):
        metadata = {"targets": [{"piece":"king","square":"d3"},{"piece":"bishop","square":"e5"}],
                    "realization": {"opponent_reply":"Kc3","conversion_move":"Qxe5+","won_piece":"bishop","won_square":"e5"}}
        c = self.builder.build(row(metadata=metadata))
        f = self.generator.generate(c)
        self.assertIn("Qf5+ forks the king on d3 and bishop on e5", f.explanation)
        self.assertIn("capturing the bishop on e5", f.explanation)
        self.assertIsNone(c.proof.retained_material_gain_cp)
        self.assertIsNone(f.outcome_label)
        self.assertNotIn("winning material", f.explanation)

    def test_fork_numeric_evidence_requires_known_schema_and_pov(self):
        metadata = {"detector":"fork_v2_post_conversion", "evaluation_after_conversion":{"cp":687},
                    "evaluation_after_fork":{"cp":700}}
        c = self.builder.build(row(metadata=metadata))
        f = self.generator.generate(c, "teaching")
        self.assertIn("after-conversion evaluation: 687 cp (black perspective)", f.explanation)
        self.assertIsNone(c.proof.evaluation_after_settlement)
        r = row(metadata=metadata); r.pop("color")
        self.assertNotIn("687", self.generator.generate(self.builder.build(r), "teaching").explanation)

    def test_legacy_pin_uses_stored_square_indices_without_movement_claims(self):
        metadata = {"pin":{"pin_type":"relative", "attacker":{"piece_type":5,"square":35},
                            "pinned":{"piece_type":2,"square":42},"behind":{"piece_type":4,"square":56}},
                    "player_color":"white", "retained_material_gain_cp":300}
        r = row("missed_pin", metadata); r["color"] = "white"
        c = self.builder.build(r)
        f = self.generator.generate(c, "teaching")
        self.assertIn("relative pin: queen on d5", f.explanation)
        self.assertIn("knight on c6", f.explanation)
        self.assertIn("rook on a8", f.explanation)
        self.assertIn("300 cp (white perspective)", f.explanation)
        self.assertNotIn("cannot move", f.explanation)

    def test_mate_canonical_line_no_distance_inference(self):
        r = row("missed_mate"); r.update(solution_move_san="Qxd2#", solution_line="Qxd2#", notes="Forced mate in 1 was lost.")
        f = self.generator.generate(self.builder.build(r))
        self.assertEqual(f.title, "Missed Mate")
        self.assertEqual(f.proof_summary, "Stored line: Qxd2#")
        self.assertNotIn("mate in 1", f.explanation)

    def test_pin_skewer_xray_modern_relationships(self):
        for kind in ("absolute_pin", "skewer", "xray"):
            with self.subTest(kind=kind):
                f = self.generator.generate(self.builder.build(row(), opportunity(kind)), "teaching")
                self.assertIn("black rook on h2", f.explanation)
                self.assertIn("white rook on h4", f.explanation)
                self.assertIn("846 cp (black perspective)", f.explanation)

    def test_legacy_skewer_adapter(self):
        metadata = {"skewer":{"attacker":{"piece":"bishop","square":"f5"},
                    "front":{"piece":"king","square":"d3"},"rear":{"piece":"queen","square":"c2"}}}
        f = self.generator.generate(self.builder.build(row("missed_skewer", metadata)))
        self.assertIn("Recorded skewer: bishop on f5", f.explanation)
        self.assertIn("rear target: queen on c2", f.explanation)

    def test_context_only_never_promoted_even_with_unknown_outcome(self):
        for outcome in ("win_exchange", "unknown"):
            c = self.builder.build(row("missed_xray"), opportunity(attribution="context_only", outcome=outcome))
            f = self.generator.generate(c)
            self.assertEqual(f.motif_labels, ())
            self.assertEqual(f.context_motif_labels, ("X-ray",))
            self.assertNotIn("X-ray", f.title)
            self.assertNotIn("retains material", f.explanation)

    def test_unknown_and_secondary_attribution_never_become_primary_causality(self):
        c = self.builder.build(row(), opportunity(attribution="unknown"))
        for style in DEFAULT_PACK["styles"]:
            f = self.generator.generate(c, style)
            self.assertNotIn("retains material", f.explanation)
            self.assertEqual(f.motif_labels, ())
        secondary = replace(opportunity(), motifs=(TacticalMotif("xray", False, "supported", "Secondary rationale"),))
        self.assertNotIn("Secondary rationale", self.generator.generate(self.builder.build(row(), secondary)).explanation)

    def test_styles_are_deterministic_and_do_not_mutate_context(self):
        c = self.builder.build(row(), opportunity())
        before = deepcopy(c)
        results = [self.generator.generate(c, style) for style in DEFAULT_PACK["styles"]]
        self.assertEqual(results, [self.generator.generate(c, style) for style in DEFAULT_PACK["styles"]])
        self.assertEqual(c, before)
        self.assertEqual([f.detail_level for f in results], ["concise","expanded","minimal","summary"])
        self.assertIsNotNone(results[1].teaching_note)
        self.assertNotIn("846", results[0].explanation)
        self.assertLess(len(results[2].explanation), len(results[0].explanation))
        self.assertIn("on move 17 Black", results[3].short_summary)

    def test_missing_and_invalid_metadata_fallback(self):
        for raw in (None, "null", "[]", "{bad", '{"targets":[{"piece_type":[]}]}'):
            r = row(); r["metadata_json"] = raw
            f = self.generator.generate(self.builder.build(r))
            self.assertEqual(f.title, "Missed Fork")
            self.assertIn("Qf5+", f.explanation)
        c = self.builder.build({})
        self.assertIsNone(c.primary_outcome)
        self.assertIsNone(c.confidence)
        f = self.generator.generate(c)
        self.assertEqual(f.title, "Stored opportunity")
        self.assertEqual(f.explanation, "No recommended move is recorded.")
        self.assertIsNone(f.proof_summary)

    def test_canonical_conflict_rejects_opportunity_without_overwriting(self):
        op = replace(opportunity(), proof=ProofEvidence(tactical_move_uci="a1a8"))
        r = row(metadata={"tactical_opportunity":opportunity_to_dict(op)})
        c = self.builder.build(r)
        self.assertIsNone(c.primary_outcome)
        self.assertEqual(c.recommended_move, "Qf5+")
        self.assertTrue(c.warnings)

    def test_generator_never_opens_engine_database_or_network(self):
        with patch("sqlite3.connect", side_effect=AssertionError("No database")), \
             patch("chess.engine.SimpleEngine.popen_uci", side_effect=AssertionError("No engine")), \
             patch("socket.create_connection", side_effect=AssertionError("No network")):
            f = self.generator.generate(self.builder.build(row(), opportunity()))
            self.assertIsInstance(f, FeedbackResult)

    def test_feedback_dependency_boundary(self):
        forbidden = {"sqlite3", "chess", "subprocess", "socket", "tkinter", "heavy_repository", "position_analysis"}
        for path in (Path(__file__).resolve().parents[1] / "feedback").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                self.assertFalse({name.split('.')[0] for name in names} & forbidden, path.name)

    def test_read_service_returns_feedback_and_preserves_episode_visibility_without_writes(self):
        c = fixture_db()
        try:
            add(c, "missed_fork")
            mate = add(c, "missed_mate", status="confirmed", episode=True)
            add(c, "missed_mate", ply=2, status="confirmed")
            before = tuple(c.iterdump()), c.total_changes
            c.execute("PRAGMA query_only=ON")
            moments = TacticReadService(c).moments_for_game(1)
            self.assertEqual(len(moments), 2)
            self.assertIn(mate, [m.candidate_id for m in moments])
            self.assertTrue(all(isinstance(m.feedback, FeedbackResult) for m in moments))
            self.assertEqual(before, (tuple(c.iterdump()), c.total_changes))
        finally:
            c.close()

    def test_new_provider_and_style_do_not_change_generator(self):
        pack = deepcopy(DEFAULT_PACK); pack["pack_id"] = "minimal"
        pack["styles"]["dashboard"] = dict(pack["styles"]["alert"])
        pack["templates"]["alert"] = "{recommended} — {title}"
        registry = FeedbackRegistry(); registry.register(DataTemplateProvider(pack))
        pack["templates"]["alert"] = "MUTATED"
        f = FeedbackGenerator(registry).generate(self.builder.build(row()), "dashboard", "minimal")
        self.assertEqual(f.short_summary, "Qf5+ — Missed Fork")
        with self.assertRaises(ValueError): registry.register(DataTemplateProvider(DEFAULT_PACK)); registry.register(DataTemplateProvider(DEFAULT_PACK))
        with self.assertRaises(ValueError): registry.get("unknown")
        with self.assertRaises(ValueError): self.generator.generate(FeedbackContext(), "unknown")

    def test_pack_rejects_logic_extra_fields_and_unsafe_placeholders(self):
        for template in ("{recommended.__class__} {title}", "{recommended[secret]} {title}", "{recommended!r} {title}", "{recommended:>10} {title}", "{invented}"):
            pack = deepcopy(DEFAULT_PACK); pack["templates"]["alert"] = template
            with self.assertRaises(ValueError): DataTemplateProvider(pack)
        pack = deepcopy(DEFAULT_PACK); pack["script"] = "plugin.py"
        with self.assertRaises(ValueError): DataTemplateProvider(pack)
        pack = deepcopy(DEFAULT_PACK); pack["schema_version"] = True
        with self.assertRaises(ValueError): DataTemplateProvider(pack)

    def test_new_legacy_adapter_does_not_change_generator_or_ui(self):
        registry = LegacyAdapterRegistry()
        registry.register("missed_future", lambda metadata, color: LegacyEvidence((
            FeedbackFact("classification", (("classification", "stored future outcome"),), ("metadata_json.classification",)),)))
        c = FeedbackContextBuilder(registry).build(row("missed_future"))
        self.assertIn("stored future outcome", self.generator.generate(c).explanation)

    def test_provisional_example_matches_runtime_contract(self):
        root = Path(__file__).resolve().parents[1]
        example = json.loads((root / "docs/feedback_pack_v1_example.json").read_text(encoding="utf-8"))
        self.assertEqual(example, DEFAULT_PACK)
        self.assertEqual(DataTemplateProvider(example).pack_id, "merlin_default")
        schema = json.loads((root / "docs/FEEDBACK_PACK_V1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(schema["required"]), set(example))

    def test_unknown_outcome_does_not_invent_material_or_discard_extensions(self):
        op = replace(opportunity(outcome="unknown", attribution="context_only"),
                     metadata={"related_retained_material_cp":200})
        c = self.builder.build(row(), op)
        self.assertEqual(json.loads(c.opportunity_metadata_json)["related_retained_material_cp"], 200)
        self.assertEqual(self.generator.generate(c).title, "Stored opportunity")
        self.assertNotIn("wins", self.generator.generate(c).explanation)
