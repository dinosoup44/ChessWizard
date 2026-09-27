"""Proposed portable occurrence storage contract; no production writer or migration.

Identity names a supplied motif claim, not an analyzer verdict. Evidence revisions
retain independent truth facets; storing a claim does not verify it.
"""
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from typing import Protocol
from uuid import UUID, uuid5

from tactic_occurrences import (
    OccurrenceKind, TacticColor, TacticOccurrence, TacticOccurrenceRelation,
)


IDENTITY_VERSION = 1
EVIDENCE_SCHEMA_VERSION = 1
_ID_NAMESPACE = UUID("bb19bff3-0195-5e2c-9527-27979eb3a10c")


def canonical_json(value: object) -> str:
    """Stable JSON for identity and immutable payload comparison; reject NaN."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} requires nonempty text")


def _positive(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} requires a positive integer")


@dataclass(frozen=True)
class OccurrenceKey:
    """Version-independent event key within a persistent source lineage.

    instance_key defaults to one motif per tactical root. A non-default value
    requires a documented semantic discriminator, never an analyzer run ID.
    Perspective, targets, proof, wording and detector versions are not identity.
    """
    source_namespace: str
    game_id: int
    move_id: int
    kind: OccurrenceKind
    actor_color: TacticColor
    motif_type: str
    tactical_move_uci: str
    instance_key: str = "root"

    def __post_init__(self):
        object.__setattr__(self, "source_namespace", str(UUID(self.source_namespace)))
        object.__setattr__(self, "kind", OccurrenceKind(self.kind))
        object.__setattr__(self, "actor_color", TacticColor(self.actor_color))
        _positive(self.game_id, "game_id")
        _positive(self.move_id, "move_id")
        _text(self.instance_key, "instance_key")
        _text(self.tactical_move_uci, "tactical_move_uci")
        TacticOccurrence(self.motif_type, "storage-key-validation", tactical_move=self.tactical_move_uci)

    @property
    def identity_version(self) -> int:
        return IDENTITY_VERSION

    @property
    def identity_json(self) -> str:
        return canonical_json([IDENTITY_VERSION, self.source_namespace, self.game_id,
            self.move_id, self.kind, self.actor_color, self.motif_type,
            self.tactical_move_uci, self.instance_key])

    @property
    def occurrence_id(self) -> str:
        return str(uuid5(_ID_NAMESPACE, self.identity_json))


@dataclass(frozen=True)
class NamedOccurrenceKey:
    """An explicit named-source decision, independent of signed legacy row IDs.

    Repositories must bind source/name/ply to persisted source rows. This identity
    family cannot alias ordinary local-ID keys, even for identical chess content.
    """
    source_namespace: str
    source: str
    source_game_id: str
    decision_ply: int
    kind: OccurrenceKind
    actor_color: TacticColor
    motif_type: str
    tactical_move_uci: str
    instance_key: str = "root"

    def __post_init__(self):
        object.__setattr__(self, "source_namespace", str(UUID(self.source_namespace)))
        object.__setattr__(self, "kind", OccurrenceKind(self.kind))
        object.__setattr__(self, "actor_color", TacticColor(self.actor_color))
        for name in ("source", "source_game_id", "instance_key", "tactical_move_uci"):
            _text(getattr(self, name), name)
        _positive(self.decision_ply, "decision_ply")
        TacticOccurrence(self.motif_type, "named-storage-key-validation", tactical_move=self.tactical_move_uci)

    @property
    def identity_version(self) -> int:
        return 2

    @property
    def identity_json(self) -> str:
        return canonical_json([2, "named_source", self.source_namespace, self.source,
            self.source_game_id, self.decision_ply, self.kind, self.actor_color,
            self.motif_type, self.tactical_move_uci, self.instance_key])

    @property
    def occurrence_id(self) -> str:
        return str(uuid5(_ID_NAMESPACE, self.identity_json))


@dataclass(frozen=True)
class LegacyDecisionReference:
    """Signed SQLite references, never an occurrence identity or a missing marker.

    An actual source-row match is mandatory at the repository boundary. Absence
    cannot be represented by inventing a reference to a nonexistent row.
    """
    game_id: int
    move_id: int

    def __post_init__(self):
        for name in ("game_id", "move_id"):
            value = getattr(self, name)
            if type(value) is not int or value == 0:
                raise ValueError(f"{name} must reference a nonzero persisted SQLite ID")


@dataclass(frozen=True)
class TacticOccurrenceRecord:
    """Immutable decision anchor. Repositories must also check legal/source binding."""
    key: OccurrenceKey | NamedOccurrenceKey
    decision_ply: int
    decision_fen: str
    actual_move_uci: str
    legacy_reference: LegacyDecisionReference | None = None

    def __post_init__(self):
        if isinstance(self.key, NamedOccurrenceKey):
            if not isinstance(self.legacy_reference, LegacyDecisionReference) or self.decision_ply != self.key.decision_ply:
                raise ValueError("Named source requires an explicit legacy binding at the same decision")
        elif self.legacy_reference is not None:
            raise ValueError("Normal local-ID keys cannot override their source references")
        _positive(self.decision_ply, "decision_ply")
        _text(self.decision_fen, "decision_fen")
        _text(self.actual_move_uci, "actual_move_uci")
        self.relationship(None)

    @property
    def occurrence_id(self) -> str:
        return self.key.occurrence_id

    @property
    def game_id(self) -> int:
        return self.legacy_reference.game_id if self.legacy_reference else self.key.game_id

    @property
    def move_id(self) -> int:
        return self.legacy_reference.move_id if self.legacy_reference else self.key.move_id

    def relationship(self, perspective: TacticColor | None) -> TacticOccurrenceRelation:
        """Reuse the shared relationship contract; prefixes do not imply complete lines."""
        return TacticOccurrence(
            motif_type=self.key.motif_type, source_identity=self.occurrence_id,
            kind=self.key.kind, actor_color=self.key.actor_color, perspective_color=perspective,
            source_position=self.decision_fen, actual_move=self.actual_move_uci,
            tactical_move=self.key.tactical_move_uci, actual_game_line=(self.actual_move_uci,),
            counterfactual_line=(self.key.tactical_move_uci,),
        ).relation


@dataclass(frozen=True)
class OccurrenceEvidence:
    """Immutable supplied facets and versioned evidence; no inferred admission.

    payload_json retains targets, attribution, completeness, material, actual
    consequences and provenance using existing analyzer/assessment codecs. The
    four facet strings retain their provider vocabulary, not a new truth policy.
    """
    occurrence_id: str
    detector_name: str
    detector_version: str
    result_currentness_identity: str
    source_identity: str
    perspective_color: TacticColor | None
    geometry_status: str
    admission_status: str
    proof_status: str
    recorded_consequence_status: str
    payload_json: str
    schema_version: int = EVIDENCE_SCHEMA_VERSION

    def __post_init__(self):
        UUID(self.occurrence_id)
        if type(self.schema_version) is not int or self.schema_version != EVIDENCE_SCHEMA_VERSION:
            raise ValueError("Unsupported evidence schema")
        for name in ("detector_name", "detector_version", "result_currentness_identity",
                     "source_identity", "geometry_status", "admission_status", "proof_status",
                     "recorded_consequence_status"):
            _text(getattr(self, name), name)
        if self.perspective_color is not None:
            object.__setattr__(self, "perspective_color", TacticColor(self.perspective_color))
        payload = json.loads(self.payload_json)
        if not isinstance(payload, dict):
            raise ValueError("Evidence payload must be a JSON object")
        object.__setattr__(self, "payload_json", canonical_json(payload))

    @property
    def revision_id(self) -> str:
        return hashlib.sha256(canonical_json(asdict(self)).encode("utf-8")).hexdigest()


class OccurrenceLineType(StrEnum):
    ACTUAL = "actual"
    PROOF = "proof"


class OccurrenceLinePurpose(StrEnum):
    MAIN = "main"
    VERIFICATION = "verification"
    SETTLEMENT = "settlement"


@dataclass(frozen=True)
class OccurrenceLine:
    """Decision-rooted prefix with explicit history/proof role and supplied extent.

    Verification/settlement describe purpose, not whether moves actually occurred.
    Repositories validate legality and root binding; actual lines also need a
    trusted source-history match in a future production repository.
    """
    occurrence_id: str
    revision_id: str
    branch_key: str
    line_type: OccurrenceLineType
    purpose: OccurrenceLinePurpose
    moves_uci: tuple[str, ...]
    source_identity: str
    extent: str

    def __post_init__(self):
        UUID(self.occurrence_id)
        for name in ("revision_id", "branch_key", "source_identity", "extent"):
            _text(getattr(self, name), name)
        object.__setattr__(self, "line_type", OccurrenceLineType(self.line_type))
        object.__setattr__(self, "purpose", OccurrenceLinePurpose(self.purpose))
        if not isinstance(self.moves_uci, tuple) or not self.moves_uci:
            raise ValueError("Line must be an immutable nonempty decision-rooted prefix")
        TacticOccurrence("line_validation", self.source_identity,
            tactical_move=self.moves_uci[0], counterfactual_line=self.moves_uci)
        if self.line_type == OccurrenceLineType.ACTUAL and self.purpose != OccurrenceLinePurpose.MAIN:
            raise ValueError("Verification/settlement are proof purposes, not recorded history")

    @property
    def line_id(self) -> str:
        return str(uuid5(_ID_NAMESPACE, canonical_json([self.occurrence_id,
            self.revision_id, self.branch_key, self.line_type, self.purpose])))


class OccurrenceStore(Protocol):
    """Proposed insert-once boundary, not wired into any production caller.

    Identical writes return False without timestamp churn. Conflicting immutable
    anchors/links raise ValueError. No automatic latest-evidence selection.
    """
    def add_occurrence(self, record: TacticOccurrenceRecord) -> bool: ...
    def add_evidence(self, evidence: OccurrenceEvidence) -> bool: ...
    def add_line(self, line: OccurrenceLine) -> bool: ...
    def link_candidate(self, candidate_id: int, occurrence_id: str) -> bool: ...
    def link_review(self, review_identity: str, occurrence_id: str,
                    revision_id: str | None = None) -> bool: ...
    def query(self, motif_type: str, *, relation: TacticOccurrenceRelation | None = None,
              perspective: TacticColor | None = None) -> tuple[TacticOccurrenceRecord, ...]: ...
