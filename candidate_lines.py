"""Immutable, serializable candidate-line contracts. No engine or database I/O."""
from dataclasses import dataclass, field, fields, is_dataclass, replace
import json
import math
from types import MappingProxyType
from collections.abc import Mapping
import chess


def freeze(value):
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) for k in value):
            raise ValueError("JSON keys must be strings")
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(freeze(v) for v in value)
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError("Metadata must contain finite JSON data")


def to_data(value):
    if is_dataclass(value):
        return {f.name: to_data(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {k: to_data(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_data(v) for v in value]
    return value


def _metadata(value):
    if not isinstance(value, Mapping):
        raise ValueError('Metadata must be an object')
    return freeze(value)


@dataclass(frozen=True)
class LineScore:
    """Exactly one score type, with mate ownership preserved even at distance zero."""
    score_cp: int | None = None
    mate_score: int | None = None
    score_pov: str = "white"
    mate_winner: str | None = None

    def __post_init__(self):
        if self.score_pov not in {"white", "black"}:
            raise ValueError("Explicit score POV required")
        if (self.score_cp is None) == (self.mate_score is None):
            raise ValueError("Exactly one cp or mate score required")
        for v in (self.score_cp, self.mate_score):
            if v is not None and type(v) is not int:
                raise ValueError("Scores must be integers")
        if self.mate_score is None:
            if self.mate_winner is not None:
                raise ValueError("CP score cannot have a mate owner")
        else:
            other = "black" if self.score_pov == "white" else "white"
            owner = self.score_pov if self.mate_score > 0 else other if self.mate_score < 0 else self.mate_winner
            if owner not in {"white", "black"} or self.mate_winner not in (None, owner):
                raise ValueError("Mate zero needs ownership; signed mate must agree with ownership")
            object.__setattr__(self, "mate_winner", owner)

    def pov(self, color):
        if color not in {"white", "black"}:
            raise ValueError("Unknown POV")
        sign = 1 if color == self.score_pov else -1
        return LineScore(self.score_cp * sign if self.score_cp is not None else None,
            self.mate_score * sign if self.mate_score is not None else None, color, self.mate_winner)

    def ordering(self, color):
        score = self.pov(color)
        if score.mate_score is None:
            return (1, score.score_cp)
        return (2, -abs(score.mate_score)) if score.mate_winner == color else (0, abs(score.mate_score))


@dataclass(frozen=True)
class CandidateLine:
    """One distinct root move and its engine PV; no motif or interest conclusions."""
    rank: int
    move_uci: str
    score: LineScore
    pv_uci: tuple[str, ...]
    depth: int
    engine_identity: str
    analysis_version: int = 1
    move_san: str | None = None
    pv_san: tuple[str, ...] = ()
    nodes: int | None = None
    metadata: Mapping = field(default_factory=dict)

    def __post_init__(self):
        if type(self.rank) is not int or self.rank < 1:
            raise ValueError("Positive rank required")
        if not isinstance(self.score, LineScore):
            raise ValueError("LineScore required")
        if type(self.depth) is not int or self.depth < 1:
            raise ValueError("Positive depth required")
        if type(self.analysis_version) is not int or self.analysis_version < 1:
            raise ValueError("Invalid analysis version")
        if self.nodes is not None and (type(self.nodes) is not int or self.nodes < 0):
            raise ValueError("Invalid node count")
        if not isinstance(self.engine_identity, str) or not self.engine_identity:
            raise ValueError("Engine request identity required")
        object.__setattr__(self, "pv_uci", tuple(self.pv_uci))
        object.__setattr__(self, "pv_san", tuple(self.pv_san))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        if not self.pv_uci or self.pv_uci[0] != self.move_uci:
            raise ValueError("PV must begin with candidate move")


@dataclass(frozen=True)
class CandidateLineSet:
    """One position/request; normalizes order and validates every supplied PV legally."""
    fen: str
    side_to_move: str
    requested_line_count: int
    analysis_profile: str
    engine_identity: str
    lines: tuple[CandidateLine, ...]
    generation_metadata: Mapping = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("Unknown line schema")
        board = chess.Board(self.fen)
        if not board.is_valid():
            raise ValueError("Invalid position")
        if not isinstance(self.analysis_profile, str) or not self.analysis_profile:
            raise ValueError('Analysis profile identity required')
        if not isinstance(self.generation_metadata, Mapping):
            raise ValueError('Generation metadata must be an object')
        if self.generation_metadata.get('terminal') and not board.is_game_over():
            raise ValueError('Terminal metadata conflicts with position')
        if self.side_to_move != ("white" if board.turn else "black"):
            raise ValueError("Side/FEN mismatch")
        if type(self.requested_line_count) is not int or not 1 <= self.requested_line_count <= 256:
            raise ValueError("Invalid requested line count")
        ordered = tuple(sorted(self.lines, key=lambda line: line.rank))
        if len(ordered) > self.requested_line_count:
            raise ValueError("Too many lines")
        if [line.rank for line in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError("Ranks must be unique and contiguous")
        if len({line.move_uci for line in ordered}) != len(ordered):
            raise ValueError("Duplicate root moves")
        normalized = tuple(_validated_line(board, line, self.engine_identity) for line in ordered)
        object.__setattr__(self, "lines", normalized)
        object.__setattr__(self, "generation_metadata", _metadata(self.generation_metadata))

    @property
    def generated_line_count(self):
        return len(self.lines)

    def to_json(self):
        return json.dumps(to_data(self), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, value):
        data = json.loads(value)
        data["lines"] = tuple(CandidateLine(**{**l, "score": LineScore(**l["score"])}) for l in data["lines"])
        return cls(**data)


def _validated_line(board, line, engine_identity):
    if line.engine_identity != engine_identity:
        raise ValueError('Mixed engine identities')
    position = board.copy(stack=False)
    san = []
    for uci in line.pv_uci:
        move = position.parse_uci(uci)
        san.append(position.san(move))
        position.push(move)
    if line.move_san is not None and line.move_san != san[0]:
        raise ValueError('SAN identity mismatch')
    if line.pv_san and tuple(san) != line.pv_san:
        raise ValueError('SAN/PV mismatch')
    return replace(line, move_san=san[0], pv_san=tuple(san))
