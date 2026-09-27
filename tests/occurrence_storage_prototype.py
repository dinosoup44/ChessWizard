"""Test-only SQLite sketch. No file path or external connection can be supplied."""
from dataclasses import asdict
import json
import sqlite3

from position_range_evidence import LegalReplay
from tactic_occurrence_storage import (
    OccurrenceEvidence, OccurrenceKey, NamedOccurrenceKey, LegacyDecisionReference, OccurrenceLine, OccurrenceLineType,
    TacticOccurrenceRecord, canonical_json,
)
from tactic_occurrences import TacticColor, TacticOccurrenceRelation


SCHEMA = """
CREATE TABLE tactic_occurrences (
    occurrence_id TEXT PRIMARY KEY,
    identity_version INTEGER NOT NULL CHECK(identity_version IN (1,2)),
    identity_json TEXT NOT NULL UNIQUE,
    source_namespace TEXT NOT NULL,
    game_id INTEGER NOT NULL,
    move_id INTEGER NOT NULL,
    occurrence_kind TEXT NOT NULL CHECK(occurrence_kind IN ('played','missed','unknown')),
    actor_color TEXT NOT NULL CHECK(actor_color IN ('white','black')),
    motif_type TEXT NOT NULL,
    tactical_move_uci TEXT NOT NULL,
    instance_key TEXT NOT NULL,
    decision_ply INTEGER NOT NULL CHECK(decision_ply > 0),
    decision_fen TEXT NOT NULL,
    actual_move_uci TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX occurrence_motif_relation ON tactic_occurrences
    (motif_type, occurrence_kind, actor_color, game_id, decision_ply);
CREATE TABLE tactic_occurrence_evidence (
    revision_id TEXT PRIMARY KEY,
    occurrence_id TEXT NOT NULL REFERENCES tactic_occurrences(occurrence_id),
    detector_name TEXT NOT NULL,
    detector_version TEXT NOT NULL,
    result_currentness_identity TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    perspective_color TEXT CHECK(perspective_color IN ('white','black')),
    geometry_status TEXT NOT NULL,
    admission_status TEXT NOT NULL,
    proof_status TEXT NOT NULL,
    recorded_consequence_status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK(schema_version = 1),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(occurrence_id, revision_id)
);
CREATE TABLE tactic_occurrence_lines (
    line_id TEXT PRIMARY KEY,
    occurrence_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    branch_key TEXT NOT NULL,
    line_type TEXT NOT NULL CHECK(line_type IN ('actual','proof')),
    purpose TEXT NOT NULL CHECK(purpose IN ('main','verification','settlement')),
    moves_json TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    extent TEXT NOT NULL,
    CHECK(line_type != 'actual' OR purpose = 'main'),
    UNIQUE(revision_id, branch_key, line_type, purpose),
    FOREIGN KEY(occurrence_id, revision_id)
        REFERENCES tactic_occurrence_evidence(occurrence_id, revision_id)
);
CREATE TABLE tactic_occurrence_legacy_candidates (
    candidate_id INTEGER PRIMARY KEY REFERENCES tactic_candidates(candidate_id),
    occurrence_id TEXT NOT NULL REFERENCES tactic_occurrences(occurrence_id)
);
CREATE TABLE tactic_occurrence_review_links (
    review_identity TEXT PRIMARY KEY,
    occurrence_id TEXT NOT NULL REFERENCES tactic_occurrences(occurrence_id),
    revision_id TEXT,
    FOREIGN KEY(occurrence_id, revision_id)
        REFERENCES tactic_occurrence_evidence(occurrence_id, revision_id)
);
"""


class MemoryOccurrenceStore:
    """Bounded prototype with source-history fixtures, insert-once writes and FKs.

    The legacy table is a fixture stand-in, never a proposal to replace it.
    There is deliberately no production migration, update, delete or path API.
    """
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("CREATE TABLE tactic_candidates(candidate_id INTEGER PRIMARY KEY, marker TEXT)")
        self.connection.executescript(SCHEMA)
        self._history = {}

    def close(self) -> None:
        self.connection.close()

    def register_history(self, namespace, game_id, move_id, ply, fen, moves):
        """Supply a legal frozen history prefix; this is fixture input, not analysis."""
        LegalReplay(fen, moves)
        key = (namespace, game_id, move_id)
        value = (ply, fen, moves)
        if key in self._history and self._history[key] != value:
            raise ValueError("Conflicting source history")
        self._history[key] = value

    def _insert_once(self, table, key, values):
        columns = tuple(values)
        row = self.connection.execute(
            f"SELECT {','.join(columns)} FROM {table} WHERE {key}=?", (values[key],)
        ).fetchone()
        if row is not None:
            if tuple(row) != tuple(values.values()):
                raise ValueError("Immutable storage identity conflict")
            return False
        with self.connection:
            self.connection.execute(
                f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(values.values()),
            )
        return True

    def add_occurrence(self, record: TacticOccurrenceRecord) -> bool:
        k = record.key
        history = self._history[(k.source_namespace, record.game_id, record.move_id)]
        if history[:2] != (record.decision_ply, record.decision_fen) or history[2][0] != record.actual_move_uci:
            raise ValueError("Occurrence does not match source decision")
        board = LegalReplay(record.decision_fen, (k.tactical_move_uci,)).board_at(0)
        if board.turn != (k.actor_color == TacticColor.WHITE):
            raise ValueError("Actor must be the player to move")
        values = dict(occurrence_id=record.occurrence_id, identity_version=k.identity_version,
            identity_json=k.identity_json, source_namespace=k.source_namespace,
            game_id=record.game_id, move_id=record.move_id, occurrence_kind=k.kind,
            actor_color=k.actor_color, motif_type=k.motif_type, tactical_move_uci=k.tactical_move_uci,
            instance_key=k.instance_key, decision_ply=record.decision_ply,
            decision_fen=record.decision_fen, actual_move_uci=record.actual_move_uci)
        return self._insert_once("tactic_occurrences", "occurrence_id", values)

    def add_evidence(self, evidence: OccurrenceEvidence) -> bool:
        return self._insert_once("tactic_occurrence_evidence", "revision_id",
            dict(revision_id=evidence.revision_id, **asdict(evidence)))

    def _record(self, row):
        reference = None
        if row["identity_version"] == 2:
            identity = json.loads(row["identity_json"])
            if identity[:2] != [2, "named_source"] or len(identity) != 11:
                raise ValueError("Unknown named identity encoding")
            key = NamedOccurrenceKey(*identity[2:])
            reference = LegacyDecisionReference(row["game_id"], row["move_id"])
            for name, value in (("source_namespace", key.source_namespace), ("occurrence_kind", key.kind),
                    ("actor_color", key.actor_color), ("motif_type", key.motif_type),
                    ("tactical_move_uci", key.tactical_move_uci), ("instance_key", key.instance_key)):
                if row[name] != value:
                    raise ValueError("Named identity differs from stored columns")
        else:
            key = OccurrenceKey(*(row[name] for name in ("source_namespace", "game_id", "move_id",
                "occurrence_kind", "actor_color", "motif_type", "tactical_move_uci", "instance_key")))
        record = TacticOccurrenceRecord(key, row["decision_ply"], row["decision_fen"], row["actual_move_uci"], reference)
        if record.occurrence_id != row["occurrence_id"] or key.identity_json != row["identity_json"]:
            raise ValueError("Stored occurrence identity mismatch")
        return record

    def add_line(self, line: OccurrenceLine) -> bool:
        row = self.connection.execute("SELECT * FROM tactic_occurrences WHERE occurrence_id=?",
            (line.occurrence_id,)).fetchone()
        if row is None:
            raise ValueError("Line occurrence is missing")
        record = self._record(row)
        root = record.actual_move_uci if line.line_type == OccurrenceLineType.ACTUAL else record.key.tactical_move_uci
        if line.moves_uci[0] != root:
            raise ValueError("Wrong root for line role")
        LegalReplay(record.decision_fen, line.moves_uci)
        if line.line_type == OccurrenceLineType.ACTUAL:
            key = record.key
            history = self._history[(key.source_namespace, record.game_id, record.move_id)][2]
            if line.moves_uci != history[:len(line.moves_uci)]:
                raise ValueError("Actual line must match supplied recorded history")
        values = asdict(line)
        values["moves_json"] = canonical_json(values.pop("moves_uci"))
        return self._insert_once("tactic_occurrence_lines", "line_id", dict(line_id=line.line_id, **values))

    def link_candidate(self, candidate_id: int, occurrence_id: str) -> bool:
        return self._insert_once("tactic_occurrence_legacy_candidates", "candidate_id",
            dict(candidate_id=candidate_id, occurrence_id=occurrence_id))

    def link_review(self, review_identity: str, occurrence_id: str, revision_id: str | None = None) -> bool:
        if not isinstance(review_identity, str) or not review_identity.strip():
            raise ValueError("Review identity must be retained verbatim and nonempty")
        return self._insert_once("tactic_occurrence_review_links", "review_identity",
            dict(review_identity=review_identity, occurrence_id=occurrence_id, revision_id=revision_id))

    def query(self, motif_type: str, *, relation: TacticOccurrenceRelation | None = None,
              perspective: TacticColor | None = None) -> tuple[TacticOccurrenceRecord, ...]:
        if relation is not None and perspective is None:
            raise ValueError("Relation query requires explicit perspective")
        if relation is not None:
            relation = TacticOccurrenceRelation(relation)
        records = tuple(self._record(row) for row in self.connection.execute(
            "SELECT * FROM tactic_occurrences WHERE motif_type=? ORDER BY game_id,decision_ply,occurrence_id",
            (motif_type,)))
        return tuple(r for r in records if relation is None or r.relationship(perspective) == relation)

    def read_evidence(self, revision_id: str) -> OccurrenceEvidence:
        row = dict(self.connection.execute("SELECT * FROM tactic_occurrence_evidence WHERE revision_id=?",
            (revision_id,)).fetchone())
        row.pop("revision_id")
        row.pop("created_at")
        return OccurrenceEvidence(**row)

    def read_lines(self, revision_id: str) -> tuple[OccurrenceLine, ...]:
        result = []
        for row in self.connection.execute("SELECT * FROM tactic_occurrence_lines WHERE revision_id=? ORDER BY line_id",
                (revision_id,)):
            values = dict(row)
            values.pop("line_id")
            values["moves_uci"] = tuple(json.loads(values.pop("moves_json")))
            result.append(OccurrenceLine(**values))
        return tuple(result)
