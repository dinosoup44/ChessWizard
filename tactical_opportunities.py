"""Interpreted tactical conclusions. No board, engine, database, or UI access.

Outcome/motif/relationship codes are open snake_case vocabularies so a new
specialist need not edit this module. Evidence is optional, never inferred.
"""
from dataclasses import asdict, dataclass, field
from enum import StrEnum
import json
import re


SCHEMA_VERSION = 1


class PayoffTiming(StrEnum):
    UNKNOWN = "unknown"
    IMMEDIATE = "immediate"
    DELAYED = "delayed"
    POSITIONAL = "positional"


class PresentationLevel(StrEnum):
    UNKNOWN = "unknown"
    STRONG_CALLOUT = "strong_callout"
    SECONDARY_MOTIF = "secondary_motif"
    POSITIONAL_NOTE = "positional_note"


class Attribution(StrEnum):
    UNKNOWN = "unknown"
    CONTEXT_ONLY = "context_only"
    SUPPORTED = "supported"
    VERIFIED = "verified"


def _code(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", value):
        raise ValueError("Expected a nonempty snake_case code")


def _integer(value, name, minimum=None):
    if value is not None and (type(value) is not int or (minimum is not None and value < minimum)):
        raise ValueError(f"Invalid {name}")


@dataclass(frozen=True)
class TacticalOutcome:
    kind: str = "unknown"
    target_piece: str | None = None

    def __post_init__(self):
        _code(self.kind)
        if self.target_piece is not None:
            _code(self.target_piece)


@dataclass(frozen=True)
class TacticalMotif:
    kind: str
    primary: bool = False
    attribution: Attribution = Attribution.UNKNOWN
    rationale: str | None = None

    def __post_init__(self):
        _code(self.kind)
        if type(self.primary) is not bool:
            raise ValueError("primary must be boolean")
        object.__setattr__(self, "attribution", Attribution(self.attribution))
        if self.attribution in {Attribution.SUPPORTED, Attribution.VERIFIED} and not self.rationale:
            raise ValueError("Causal attribution requires a rationale")


@dataclass(frozen=True)
class Evaluation:
    """Centipawns OR signed mate distance; perspective is ProofEvidence.score_pov."""
    cp: int | None = None
    mate: int | None = None

    def __post_init__(self):
        _integer(self.cp, "evaluation cp")
        _integer(self.mate, "mate distance")
        if self.cp is not None and self.mate is not None:
            raise ValueError("An evaluation cannot contain both cp and mate")


@dataclass(frozen=True)
class ProofEvidence:
    # Canonical fields are supplied by the result/move; omitted from storage.
    played_move_uci: str | None = None
    tactical_move_uci: str | None = None
    line_san: str | None = None
    best_defense_uci: str | None = None
    # Number of further user moves AFTER the tactical move, not full moves/plies.
    window_user_moves: int | None = None
    scope: str | None = None
    score_pov: str = "unknown"
    material_before_cp: int | None = None
    material_after_cp: int | None = None
    material_value_profile: str | None = None
    evaluation_before: Evaluation | None = None
    evaluation_after_played: Evaluation | None = None
    evaluation_after_tactic: Evaluation | None = None
    evaluation_after_settlement: Evaluation | None = None
    best_defense_checked: bool | None = None
    settled_position_reached: bool | None = None
    relationship_survived: bool | None = None
    retained_material_gain_cp: int | None = None

    def __post_init__(self):
        _integer(self.window_user_moves, "proof window", 0)
        if self.score_pov not in {"white", "black", "unknown"}:
            raise ValueError("Proof scores need an explicit white/black perspective")
        for name in ("material_before_cp", "material_after_cp", "retained_material_gain_cp"):
            _integer(getattr(self, name), name)
        for name in ("best_defense_checked", "settled_position_reached", "relationship_survived"):
            if getattr(self, name) is not None and type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean or unknown")
        for name in EVALUATION_FIELDS:
            value = getattr(self, name)
            if value is not None and not isinstance(value, Evaluation):
                raise ValueError(f"{name} must be an Evaluation")
        if self.score_pov == "unknown" and any(getattr(self, name) is not None for name in
                (*EVALUATION_FIELDS, "material_before_cp", "material_after_cp", "retained_material_gain_cp")):
            raise ValueError("Numeric evidence requires an explicit score perspective")


EVALUATION_FIELDS = ("evaluation_before", "evaluation_after_played",
                     "evaluation_after_tactic", "evaluation_after_settlement")


@dataclass(frozen=True)
class PieceReference:
    piece: str
    color: str
    square: str

    def __post_init__(self):
        if self.piece not in {"pawn", "knight", "bishop", "rook", "queen", "king"}:
            raise ValueError("Invalid piece")
        if self.color not in {"white", "black"} or not re.fullmatch(r"[a-h][1-8]", self.square):
            raise ValueError("Invalid piece color/square")


@dataclass(frozen=True)
class LineRelationship:
    """Selected proof participants, not a persisted board-wide geometry map.

Squares/direction describe the position immediately after the tactical move.
Direction is a (file, rank) unit step from attacker toward rear target.
"""
    relationship_type: str
    attacker: PieceReference
    rear_target: PieceReference
    intervening_piece: PieceReference | None = None
    relevant_squares: tuple[str, ...] = ()
    ray_direction: tuple[int, int] | None = None

    def __post_init__(self):
        _code(self.relationship_type)
        for value in (self.attacker, self.rear_target):
            if not isinstance(value, PieceReference):
                raise ValueError("Line endpoints must be PieceReference objects")
        if self.intervening_piece is not None and not isinstance(self.intervening_piece, PieceReference):
            raise ValueError("Invalid intervening piece")
        object.__setattr__(self, "relevant_squares", tuple(self.relevant_squares))
        if any(not re.fullmatch(r"[a-h][1-8]", s) for s in self.relevant_squares):
            raise ValueError("Invalid relevant square")
        if self.ray_direction is not None:
            direction = tuple(self.ray_direction)
            if len(direction) != 2 or any(type(x) is not int or x not in {-1, 0, 1} for x in direction) or direction == (0, 0):
                raise ValueError("Ray direction must be a nonzero unit step")
            object.__setattr__(self, "ray_direction", direction)


@dataclass(frozen=True)
class TacticalPresentation:
    level: PresentationLevel = PresentationLevel.UNKNOWN
    title: str | None = None
    explanation: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "level", PresentationLevel(self.level))


@dataclass(frozen=True)
class TacticalOpportunity:
    primary_outcome: TacticalOutcome = field(default_factory=TacticalOutcome)
    motifs: tuple[TacticalMotif, ...] = ()
    payoff_timing: PayoffTiming = PayoffTiming.UNKNOWN
    proof: ProofEvidence = field(default_factory=ProofEvidence)
    presentation: TacticalPresentation = field(default_factory=TacticalPresentation)
    relationships: tuple[LineRelationship, ...] = ()
    # Small JSON evidence extensions only; no engine payloads or board maps.
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        for value, expected in ((self.primary_outcome, TacticalOutcome), (self.proof, ProofEvidence),
                                (self.presentation, TacticalPresentation)):
            if not isinstance(value, expected):
                raise ValueError(f"Expected {expected.__name__}")
        object.__setattr__(self, "motifs", tuple(self.motifs))
        object.__setattr__(self, "relationships", tuple(self.relationships))
        object.__setattr__(self, "payoff_timing", PayoffTiming(self.payoff_timing))
        if any(not isinstance(m, TacticalMotif) for m in self.motifs):
            raise ValueError("Expected TacticalMotif objects")
        if any(not isinstance(r, LineRelationship) for r in self.relationships):
            raise ValueError("Expected LineRelationship objects")
        if len({m.kind for m in self.motifs}) != len(self.motifs) or sum(m.primary for m in self.motifs) > 1:
            raise ValueError("Motifs must be unique with at most one primary motif")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be a JSON object")
        json.dumps(self.metadata, allow_nan=False)


def opportunity_to_dict(opportunity):
    """Versioned, detached JSON-compatible value; never modifies its input."""
    if not isinstance(opportunity, TacticalOpportunity):
        raise ValueError("Expected a TacticalOpportunity")
    return json.loads(json.dumps({"schema_version": SCHEMA_VERSION, **asdict(opportunity)}, allow_nan=False))


def opportunity_from_dict(document):
    """Reject unknown versions/fields explicitly rather than losing evidence."""
    data = json.loads(json.dumps(document, allow_nan=False))
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data.pop("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported tactical opportunity schema version")
    if "primary_outcome" in data:
        data["primary_outcome"] = TacticalOutcome(**data["primary_outcome"])
    if "motifs" in data:
        data["motifs"] = tuple(TacticalMotif(**m) for m in data["motifs"])
    if "proof" in data:
        proof = data["proof"]
        for name in EVALUATION_FIELDS:
            if proof.get(name) is not None:
                proof[name] = Evaluation(**proof[name])
        data["proof"] = ProofEvidence(**proof)
    if "presentation" in data:
        data["presentation"] = TacticalPresentation(**data["presentation"])
    if "relationships" in data:
        for relationship in data["relationships"]:
            for name in ("attacker", "intervening_piece", "rear_target"):
                if relationship.get(name) is not None:
                    relationship[name] = PieceReference(**relationship[name])
        data["relationships"] = tuple(LineRelationship(**r) for r in data["relationships"])
    return TacticalOpportunity(**data)
