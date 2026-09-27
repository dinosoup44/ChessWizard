from dataclasses import replace
import json
import sqlite3
import unittest
from unittest.mock import patch

import chess

from analysis_results import HeavyResult
from tactical_opportunities import (
    Attribution, Evaluation, LineRelationship, PayoffTiming, PieceReference,
    PresentationLevel, ProofEvidence, TacticalMotif, TacticalOpportunity,
    TacticalOutcome, TacticalPresentation, opportunity_from_dict, opportunity_to_dict,
)
from tactical_opportunity_repository import (
    METADATA_KEY, prepare_opportunity_payload, read_candidate_opportunity,
)
import test_heavy_services as fixtures


def opportunity():
    return TacticalOpportunity(
        primary_outcome=TacticalOutcome("win_piece", "knight"),
        motifs=(TacticalMotif("check", True, Attribution.SUPPORTED, "Check gains the capturing tempo"),
                TacticalMotif("relative_pin", attribution=Attribution.CONTEXT_ONLY)),
        payoff_timing=PayoffTiming.IMMEDIATE,
        proof=ProofEvidence(played_move_uci="e2e4", tactical_move_uci="d2d4", line_san="d4 d5",
                            window_user_moves=1, score_pov="white", evaluation_after_tactic=Evaluation(cp=300),
                            best_defense_checked=True, retained_material_gain_cp=300),
        presentation=TacticalPresentation(PresentationLevel.STRONG_CALLOUT, "Win a knight"),
        relationships=(LineRelationship("relative_pin", PieceReference("queen", "white", "d5"),
                         PieceReference("rook", "black", "a8"), PieceReference("knight", "black", "c6"),
                         ("d5", "c6", "a8"), (-1, 1)),),
        metadata={"evidence_cache_ids": [42], "unknown_extension": None},
    )


class OpportunityModelTests(unittest.TestCase):
    def test_multi_motif_strong_callout_and_line_round_trip(self):
        value = opportunity()
        self.assertEqual(opportunity_from_dict(opportunity_to_dict(value)), value)
        self.assertEqual(value.motifs[1].attribution, Attribution.CONTEXT_ONLY)
        self.assertEqual(value.relationships[0].ray_direction, (-1, 1))

    def test_delayed_and_positional_are_not_proof_claims(self):
        delayed = replace(opportunity(), payoff_timing=PayoffTiming.DELAYED,
                          proof=ProofEvidence(window_user_moves=4))
        self.assertIsNone(delayed.proof.best_defense_checked)
        self.assertIsNone(delayed.proof.settled_position_reached)
        for level in (PresentationLevel.SECONDARY_MOTIF, PresentationLevel.POSITIONAL_NOTE):
            note = TacticalOpportunity(TacticalOutcome("positional_pressure"),
                payoff_timing=PayoffTiming.POSITIONAL, presentation=TacticalPresentation(level))
            self.assertEqual(opportunity_from_dict(opportunity_to_dict(note)), note)

    def test_defaults_unknown_and_version_is_separate_from_analyzer(self):
        value = opportunity_from_dict({"schema_version": 1})
        self.assertEqual(value, TacticalOpportunity())
        self.assertEqual(value.primary_outcome.kind, "unknown")
        self.assertEqual(value.motifs, ())
        self.assertEqual(HeavyResult("analyzed_no_hit", None, {"reason": "legacy"}).opportunity, None)
        for version in (2, None, True, "1"):
            with self.assertRaises(ValueError):
                opportunity_from_dict({"schema_version": version})

    def test_extensible_vocabulary_without_core_changes(self):
        value = TacticalOpportunity(TacticalOutcome("save_material"),
            (TacticalMotif("future_specialist_motif"),))
        self.assertEqual(opportunity_from_dict(opportunity_to_dict(value)), value)

    def test_invalid_claims_scores_windows_and_geometry_fail(self):
        calls = [lambda: Evaluation(cp=1, mate=2), lambda: Evaluation(cp=True),
                 lambda: ProofEvidence(window_user_moves=-1),
                 lambda: ProofEvidence(evaluation_before=Evaluation(cp=5)),
                 lambda: ProofEvidence(best_defense_checked="yes"),
                 lambda: TacticalMotif("pin", attribution=Attribution.VERIFIED),
                 lambda: TacticalOpportunity(motifs=(TacticalMotif("pin"), TacticalMotif("pin"))),
                 lambda: TacticalOpportunity(motifs=(TacticalMotif("pin", True), TacticalMotif("check", True))),
                 lambda: PieceReference("rook", "white", "z9"),
                 lambda: replace(opportunity().relationships[0], ray_direction=(2, 0)),
                 lambda: TacticalOpportunity(metadata={"score": float("nan")})]
        for call in calls:
            with self.subTest(call=call), self.assertRaises(ValueError):
                call()
        self.assertEqual(ProofEvidence(score_pov="black", evaluation_before=Evaluation(mate=-2)).evaluation_before.mate, -2)

    def test_no_board_mutation_engine_or_database_in_model(self):
        board = chess.Board()
        board.push_san("e4")
        fen, stack = board.fen(), list(board.move_stack)
        with patch("sqlite3.connect", side_effect=AssertionError("DB access")), \
             patch("chess.engine.SimpleEngine.popen_uci", side_effect=AssertionError("Engine access")), \
             patch.object(chess.Board, "push", side_effect=AssertionError("Board mutation")):
            value = opportunity()
            self.assertEqual(opportunity_from_dict(opportunity_to_dict(value)), value)
        self.assertEqual((board.fen(), board.move_stack), (fen, stack))


class OpportunityRepositoryTests(unittest.TestCase):
    setUp = fixtures.RepositoryTests.setUp
    save = fixtures.RepositoryTests.save
    seed_old_candidate = fixtures.RepositoryTests.seed_old_candidate

    def prepare_moves(self):
        self.c.execute("ALTER TABLE moves ADD COLUMN uci_played TEXT")
        self.c.execute("UPDATE moves SET uci_played='e2e4'")
        self.c.commit()

    def test_id_training_timestamps_metadata_and_atomic_rerun(self):
        self.prepare_moves()
        self.c.execute("PRAGMA foreign_keys=ON")
        self.seed_old_candidate()
        self.c.execute("UPDATE tactic_candidates SET metadata_json=?,reviewed_at='reviewed'", ('{"legacy_note":"keep"}',))
        self.c.commit()
        result = HeavyResult("candidate", fixtures.candidate_payload(), opportunity=opportunity())
        self.assertEqual(self.save(result)["candidate_id"], 42)
        row = self.c.execute("SELECT * FROM tactic_candidates").fetchone()
        self.assertEqual((row["created_at"], row["reviewed_at"]), ("original", "reviewed"))
        self.assertEqual(self.c.execute("SELECT candidate_id FROM training_attempts").fetchone()[0], 42)
        metadata = json.loads(row["metadata_json"])
        self.assertEqual(metadata["legacy_note"], "keep")
        for name in ("played_move_uci", "tactical_move_uci", "line_san"):
            self.assertNotIn(name, metadata[METADATA_KEY]["proof"])
        self.assertEqual(read_candidate_opportunity(self.c, 42).opportunity, opportunity())
        changes = self.c.total_changes
        self.assertEqual(self.save(result)["action"], "unchanged")
        self.assertEqual(self.c.total_changes, changes)
        self.assertEqual(tuple(self.c.execute("SELECT * FROM tactic_candidates").fetchone()), tuple(row))
        self.assertEqual(self.c.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.c.execute("PRAGMA quick_check").fetchone()[0], "ok")

    def test_legacy_fork_mate_pin_and_null_metadata_are_readable_without_writes(self):
        self.prepare_moves()
        for i, (tactic, raw) in enumerate((("missed_fork", None), ("missed_mate", "{}"), ("missed_pin", "null")), 1):
            self.c.execute("INSERT INTO tactic_candidates(candidate_id,move_id,tactic_type,metadata_json) VALUES(?,1,?,?)", (i, tactic, raw))
        self.c.commit()
        self.c.row_factory = None
        changes = self.c.total_changes
        for i in (1, 2, 3):
            value = read_candidate_opportunity(self.c, i)
            self.assertEqual(value.candidate_id, i)
            self.assertIsNone(value.opportunity)
        self.assertIsNone(read_candidate_opportunity(self.c, 999))
        self.assertEqual(self.c.total_changes, changes)

    def test_legacy_payload_unchanged_and_input_not_mutated(self):
        payload = fixtures.candidate_payload()
        payload["metadata_json"] = '{ "legacy" : 1 }'
        snapshot = dict(payload)
        self.assertEqual(prepare_opportunity_payload(payload, None, fixtures.move_row()), payload)
        prepare_opportunity_payload(payload, opportunity(), fixtures.move_row())
        self.assertEqual(payload, snapshot)

    def test_canonical_evidence_mismatch_and_non_candidate_are_rejected(self):
        for proof in (replace(opportunity().proof, played_move_uci="a2a3"),
                      replace(opportunity().proof, tactical_move_uci="a2a3"),
                      replace(opportunity().proof, line_san="a3")):
            with self.assertRaises(ValueError):
                self.save(HeavyResult("candidate", fixtures.candidate_payload(), opportunity=replace(opportunity(), proof=proof)))
        with self.assertRaises(ValueError):
            self.save(HeavyResult("analyzed_no_hit", opportunity=opportunity()))
        self.assertEqual(self.c.execute("SELECT count(*) FROM tactic_candidates").fetchone()[0], 0)
        self.assertEqual(self.c.execute("SELECT count(*) FROM analysis_coverage").fetchone()[0], 0)

    def test_opportunity_rolls_back_with_coverage_failure(self):
        self.seed_old_candidate()
        before = tuple(self.c.execute("SELECT * FROM tactic_candidates").fetchone())
        self.c.executescript("CREATE TRIGGER fail BEFORE INSERT ON analysis_coverage BEGIN SELECT RAISE(ABORT,'fixture'); END;")
        with self.assertRaises(sqlite3.IntegrityError):
            self.save(HeavyResult("candidate", fixtures.candidate_payload(), opportunity=opportunity()))
        self.assertEqual(tuple(self.c.execute("SELECT * FROM tactic_candidates").fetchone()), before)
        self.assertEqual(self.c.execute("SELECT candidate_id FROM training_attempts").fetchone()[0], 42)

    def test_legacy_rerun_cannot_silently_erase_or_stale_an_opportunity(self):
        payload = prepare_opportunity_payload(fixtures.candidate_payload(), opportunity(), fixtures.move_row())
        saved = prepare_opportunity_payload(fixtures.candidate_payload(), None, fixtures.move_row(), payload)
        self.assertEqual(saved, payload)
        changed = {**fixtures.candidate_payload(), "detector_version": 3}
        with self.assertRaises(ValueError):
            prepare_opportunity_payload(changed, None, fixtures.move_row(), payload)
        with self.assertRaises(ValueError):
            prepare_opportunity_payload(payload, None, fixtures.move_row())

    def test_defaults_hydrate_existing_canonical_evidence(self):
        self.prepare_moves()
        saved = self.save(HeavyResult("candidate", fixtures.candidate_payload(), opportunity=TacticalOpportunity()))
        value = read_candidate_opportunity(self.c, saved["candidate_id"]).opportunity
        self.assertEqual(value.primary_outcome.kind, "unknown")
        self.assertEqual(value.proof.played_move_uci, "e2e4")
        self.assertEqual(value.proof.line_san, "d4 d5")

    def test_new_specialist_uses_same_dispatch_and_repository_without_engine(self):
        self.prepare_moves()
        result = HeavyResult("candidate", fixtures.candidate_payload(), opportunity=TacticalOpportunity(
            TacticalOutcome("win_exchange"), (TacticalMotif("skewer"),)))
        definition = replace(self.definition, analysis_type="missed_future_skewer",
                             heavy=lambda row, positions: result)
        with patch("analysis_engine.get_or_analyze", side_effect=AssertionError("Engine request")):
            dispatched = fixtures.dispatch_heavy(definition, self.c, None, fixtures.move_row(), fixtures.Counter())
            self.assertEqual(dispatched, result)
            saved = fixtures.save_heavy_result(self.c, definition, fixtures.move_row(), dispatched,
                {(1, definition.analysis_type)}, fixtures.coverage_decision)
        read = read_candidate_opportunity(self.c, saved["candidate_id"])
        self.assertEqual(read.opportunity.primary_outcome.kind, "win_exchange")
        self.assertEqual(read.tactic_type, "missed_future_skewer")


if __name__ == "__main__":
    unittest.main()
