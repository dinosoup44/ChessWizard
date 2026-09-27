"""Contract demonstrations with synthetic history; no tactic truth is calculated."""
from dataclasses import FrozenInstanceError, replace
import json
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

import chess
from tactic_occurrence_storage import (
    OccurrenceEvidence, OccurrenceKey, OccurrenceLine, OccurrenceLinePurpose,
    OccurrenceLineType, TacticOccurrenceRecord,
)
from tactic_occurrences import OccurrenceKind, TacticColor, TacticOccurrenceRelation as Relation
from tests.occurrence_storage_prototype import MemoryOccurrenceStore


NAMESPACE = "00000000-0000-4000-8000-000000000001"
FEN = "4k3/8/8/4n1Q1/8/8/8/6K1 b - - 0 17"
AUDIT_REVIEW = 'audit:[21,201,"synthetic-assessment.json#game:21:move:201:assessment","e5f3"]'


def example_records() -> tuple[TacticOccurrenceRecord, ...]:
    """Build storage cases from a hand-authored king-and-queen knight fork.

    Returns:
        Missed, played, check and mirrored-opponent records; labels are supplied data,
        not an analyzer validation or a recorded personal game.
    """
    missed = TacticOccurrenceRecord(OccurrenceKey(NAMESPACE, 1, 101, OccurrenceKind.MISSED,
        TacticColor.BLACK, "fork", "e5f3"), 34, FEN, "e8f8")
    played = TacticOccurrenceRecord(OccurrenceKey(NAMESPACE, 2, 201, OccurrenceKind.PLAYED,
        TacticColor.BLACK, "fork", "e5f3"), 34, FEN, "e5f3")
    check = replace(played, key=replace(played.key, motif_type="check"))
    opponent = TacticOccurrenceRecord(OccurrenceKey(NAMESPACE, 3, 301, OccurrenceKind.PLAYED,
        TacticColor.WHITE, "fork", "e4f6"), 33, chess.Board(FEN).mirror().fen(), "e4f6")
    return missed, played, check, opponent


def example_evidence(record):
    return OccurrenceEvidence(record.occurrence_id, "fixture_supplier", "1", "fixture-policy-v1",
        "synthetic-storage-fixture", TacticColor.BLACK, "supplied", "not_assessed",
        "not_assessed", "recorded_prefix", json.dumps({"complete": False,
        "targets": [], "retained_payoff": None, "recorded_consequence": None,
        "attribution": [], "provenance": ["synthetic; no engine or truth assessment"]}))


def populate(store):
    missed, played, check, opponent = example_records()
    for record in (missed, played, check, opponent):
        history = (record.actual_move_uci, "g1h1") if record.key.game_id == 2 else (record.actual_move_uci,)
        store.register_history(NAMESPACE, record.key.game_id, record.key.move_id,
            record.decision_ply, record.decision_fen, history)
        store.add_occurrence(record)
    store.connection.execute("INSERT INTO tactic_candidates VALUES (42,'legacy fixture; preserve')")
    store.connection.commit()
    store.link_candidate(42, missed.occurrence_id)
    evidence = example_evidence(played)
    store.add_evidence(evidence)
    store.link_review("candidate:42", missed.occurrence_id)
    store.link_review(AUDIT_REVIEW, played.occurrence_id, evidence.revision_id)
    actual = OccurrenceLine(played.occurrence_id, evidence.revision_id, "recorded", "actual", "main",
        ("e5f3", "g1h1"), "synthetic-history", "bounded_prefix")
    proof = OccurrenceLine(played.occurrence_id, evidence.revision_id, "branch-1", "proof", "verification",
        ("e5f3", "g1g2"), "supplied-proof-fixture", "incomplete")
    store.add_line(actual)
    store.add_line(proof)
    return (missed, played, check, opponent), evidence, (actual, proof)


class OccurrenceStorageTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryOccurrenceStore()
        self.addCleanup(self.store.close)
        self.records, self.evidence, self.lines = populate(self.store)

    def test_all_and_relation_queries(self):
        self.assertEqual(len(self.store.query("fork")), 3)
        for relation, expected in ((Relation.PLAYED_BY_PERSPECTIVE, self.records[1]),
                (Relation.MISSED_BY_PERSPECTIVE, self.records[0]),
                (Relation.PLAYED_BY_OPPONENT, self.records[3])):
            self.assertEqual(self.store.query("fork", relation=relation, perspective=TacticColor.BLACK), (expected,))
        self.assertEqual(self.store.query("pin"), ())
        self.assertEqual(self.store.query("fork", relation=Relation.MISSED_BY_OPPONENT,
            perspective=TacticColor.WHITE), (self.records[0],))

    def test_perspective_changes_view_not_identity(self):
        record = self.records[1]
        identity = record.occurrence_id
        self.assertEqual(record.relationship(TacticColor.BLACK), Relation.PLAYED_BY_PERSPECTIVE)
        self.assertEqual(record.relationship(TacticColor.WHITE), Relation.PLAYED_BY_OPPONENT)
        self.assertEqual(record.relationship(None), Relation.UNKNOWN)
        self.assertEqual(identity, record.occurrence_id)
        with self.assertRaises(ValueError):
            self.store.query("fork", relation=Relation.PLAYED_BY_PERSPECTIVE)

    def test_kind_motif_root_and_instance_identity(self):
        key = self.records[1].key
        for altered in (replace(key, kind=OccurrenceKind.MISSED), replace(key, motif_type="check"),
                replace(key, tactical_move_uci="e8f8"), replace(key, instance_key="attacker:rook:f8")):
            self.assertNotEqual(key.occurrence_id, altered.occurrence_id)
        self.assertEqual(self.records[1].key.move_id, self.records[2].key.move_id)
        self.assertNotEqual(self.records[1].occurrence_id, self.records[2].occurrence_id)

    def test_same_motif_distinct_roots_and_instances_can_coexist(self):
        played = self.records[1]
        missed = replace(played, key=replace(played.key, kind="missed", tactical_move_uci="e8f8"))
        distinct = replace(played, key=replace(played.key, instance_key="fixture-distinct-instance"))
        self.assertTrue(self.store.add_occurrence(missed))
        self.assertTrue(self.store.add_occurrence(distinct))
        self.assertEqual(len(self.store.query("fork")), 5)

    def test_identity_deterministic_and_namespace_scoped(self):
        key = self.records[1].key
        reconstructed = OccurrenceKey(**json.loads(json.dumps(key.__dict__)))
        self.assertEqual(key.occurrence_id, "5845d919-d768-54b0-b8c5-057fad85520c")
        self.assertEqual(key.identity_json, reconstructed.identity_json)
        self.assertEqual(key.occurrence_id, reconstructed.occurrence_id)
        self.assertNotEqual(key.occurrence_id, replace(key, source_namespace="00000000-0000-0000-0000-000000000001").occurrence_id)
        code = "from tests.test_tactic_occurrence_storage import example_records; print(example_records()[1].occurrence_id)"
        result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), key.occurrence_id)

    def test_version_and_wording_append_evidence_not_events(self):
        newer = replace(self.evidence, detector_version="2", payload_json='{"wording":"changed"}')
        self.assertNotEqual(newer.revision_id, self.evidence.revision_id)
        self.assertEqual(newer.occurrence_id, self.evidence.occurrence_id)
        self.assertTrue(self.store.add_evidence(newer))
        self.assertEqual(len(self.store.query("fork")), 3)
        self.assertEqual(self.store.read_evidence(self.evidence.revision_id), self.evidence)
        self.assertEqual(self.store.read_evidence(newer.revision_id), newer)

    def test_facets_independent_and_payload_canonical(self):
        changed = replace(self.evidence, geometry_status="present", admission_status="rejected",
            proof_status="ambiguous", recorded_consequence_status="target_captured",
            payload_json='{"material":-900,"forced":false}')
        self.store.add_evidence(changed)
        self.assertEqual(self.store.read_evidence(changed.revision_id), changed)
        self.assertEqual(changed.revision_id, replace(changed, payload_json=' {"forced": false, "material": -900} ').revision_id)
        with self.assertRaises(FrozenInstanceError):
            changed.proof_status = "verified"
        for value in ('[]', '{"value":NaN}'):
            with self.assertRaises(ValueError):
                replace(changed, payload_json=value)

    def test_actual_proof_roles_survive_roundtrip(self):
        self.assertEqual(set(self.store.read_lines(self.evidence.revision_id)), set(self.lines))
        self.assertEqual(self.lines[0].moves_uci[0], self.lines[1].moves_uci[0])
        self.assertNotEqual(self.lines[0].moves_uci[1], self.lines[1].moves_uci[1])
        self.assertNotEqual(self.lines[0].line_id, self.lines[1].line_id)

    def test_missed_actual_and_counterfactual_roots_remain_distinct(self):
        record = self.records[0]
        evidence = example_evidence(record)
        self.store.add_evidence(evidence)
        for role, move in (("actual", "e8f8"), ("proof", "e5f3")):
            line = OccurrenceLine(record.occurrence_id, evidence.revision_id, "root", role, "main",
                (move,), "fixture", "root_only")
            self.assertTrue(self.store.add_line(line))
        self.assertEqual(len(self.store.read_lines(evidence.revision_id)), 2)

    def test_actual_history_cannot_be_counterfactual(self):
        proof = self.lines[1]
        with self.assertRaises(ValueError):
            self.store.add_line(replace(proof, line_type="actual", purpose="main"))
        with self.assertRaises(ValueError):
            replace(proof, line_type="actual")

    def test_line_root_legality_and_revision_binding(self):
        with self.assertRaises(ValueError):
            self.store.add_line(replace(self.lines[1], moves_uci=("e8f8",)))
        with self.assertRaises(ValueError):
            self.store.add_line(replace(self.lines[1], moves_uci=("e5f3", "g1g7")))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.add_line(replace(self.lines[1], occurrence_id=self.records[2].occurrence_id))

    def test_idempotence_no_writes_or_timestamp_churn(self):
        dump = tuple(self.store.connection.iterdump())
        changes = self.store.connection.total_changes
        for record in self.records:
            self.assertFalse(self.store.add_occurrence(record))
        self.assertFalse(self.store.add_evidence(self.evidence))
        for line in self.lines:
            self.assertFalse(self.store.add_line(line))
        self.assertFalse(self.store.link_candidate(42, self.records[0].occurrence_id))
        self.assertFalse(self.store.link_review("candidate:42", self.records[0].occurrence_id))
        self.assertFalse(self.store.link_review(AUDIT_REVIEW, self.records[1].occurrence_id, self.evidence.revision_id))
        self.assertEqual(self.store.connection.total_changes, changes)
        self.assertEqual(tuple(self.store.connection.iterdump()), dump)

    def test_conflicting_anchor_or_line_cannot_overwrite(self):
        with self.assertRaises(ValueError):
            self.store.add_occurrence(replace(self.records[1], decision_ply=99))
        with self.assertRaises(ValueError):
            self.store.add_line(replace(self.lines[1], moves_uci=("e5f3",)))
        self.assertEqual(set(self.store.read_lines(self.evidence.revision_id)), set(self.lines))

    def test_candidate_and_review_identity_preserved(self):
        before = tuple(self.store.connection.execute("SELECT * FROM tactic_candidates").fetchone())
        with self.assertRaises(ValueError):
            self.store.link_candidate(42, self.records[1].occurrence_id)
        with self.assertRaises(ValueError):
            self.store.link_review("candidate:42", self.records[1].occurrence_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.link_candidate(999, self.records[0].occurrence_id)
        self.assertEqual(tuple(self.store.connection.execute("SELECT * FROM tactic_candidates").fetchone()), before)
        row = self.store.connection.execute("SELECT review_identity,revision_id FROM tactic_occurrence_review_links WHERE review_identity=?", (AUDIT_REVIEW,)).fetchone()
        self.assertEqual(tuple(row), (AUDIT_REVIEW, self.evidence.revision_id))

    def test_review_revision_cannot_reference_another_occurrence(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.link_review("audit:wrong-binding", self.records[0].occurrence_id, self.evidence.revision_id)

    def test_unknown_is_not_silently_promoted(self):
        record = replace(self.records[1], key=replace(self.records[1].key, kind="unknown"))
        self.store.add_occurrence(record)
        self.assertEqual(record.relationship(TacticColor.BLACK), Relation.UNKNOWN)
        self.assertNotEqual(record.occurrence_id, self.records[1].occurrence_id)

    def test_invalid_contract_inputs(self):
        for kwargs in ({"motif_type":"missed_fork"}, {"game_id":True}, {"move_id":0},
                {"tactical_move_uci":"Nf3+"}, {"source_namespace":"D:/ChessWizard"}):
            with self.assertRaises(ValueError):
                replace(self.records[1].key, **kwargs)
        with self.assertRaises(ValueError):
            replace(self.records[1], actual_move_uci="e8f8")
        with self.assertRaises(ValueError):
            replace(self.lines[0], moves_uci=["e5f3"])

    def test_actor_and_source_history_binding(self):
        with self.assertRaises(ValueError):
            self.store.add_occurrence(replace(self.records[1], key=replace(self.records[1].key, actor_color="white")))
        with self.assertRaises(ValueError):
            self.store.register_history(NAMESPACE, 2, 201, 34, FEN, ("e5f3",))

    def test_schema_integrity(self):
        self.assertEqual(self.store.connection.execute("PRAGMA quick_check").fetchone()[0], "ok")
        self.assertEqual(list(self.store.connection.execute("PRAGMA foreign_key_check")), [])

    def test_prototype_can_open_only_memory(self):
        connect = sqlite3.connect
        with patch("sqlite3.connect", side_effect=lambda path: connect(path) if path == ":memory:" else self.fail("Non-memory DB")) as guard:
            store = MemoryOccurrenceStore()
            try:
                populate(store)
            finally:
                store.close()
        guard.assert_called_once_with(":memory:")
        with self.assertRaises(TypeError):
            MemoryOccurrenceStore("merlin.db")

    def test_fresh_core_import_without_database_engine_or_ui(self):
        code = '''import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == "sqlite3" or name == "chess.engine" or name.startswith(("tkinter", "merlin_ui", "analyze_")):
        raise AssertionError(name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import tactic_occurrence_storage
assert tactic_occurrence_storage.IDENTITY_VERSION == 1
'''
        subprocess.run([sys.executable, "-B", "-c", code], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
