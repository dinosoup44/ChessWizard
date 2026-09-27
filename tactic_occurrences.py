"""Portable event relationships; supplied tactic truth is never calculated here."""
from dataclasses import dataclass
from enum import StrEnum
import re


class TacticColor(StrEnum):
    WHITE = "white"
    BLACK = "black"


class OccurrenceKind(StrEnum):
    UNKNOWN = "unknown"
    PLAYED = "played"
    MISSED = "missed"


class TacticOccurrenceRelation(StrEnum):
    UNKNOWN = "unknown"
    PLAYED_BY_PERSPECTIVE = "played_by_perspective"
    MISSED_BY_PERSPECTIVE = "missed_by_perspective"
    PLAYED_BY_OPPONENT = "played_by_opponent"
    MISSED_BY_OPPONENT = "missed_by_opponent"


def _move(value: str | None) -> None:
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[a-h][1-8][a-h][1-8][qrbn]?", value)):
        raise ValueError("Moves must be UCI or absent")


@dataclass(frozen=True)
class TacticOccurrence:
    """One supplied motif claim anchored to a decision, with two distinct line roles.

    Lines include their root move. UCI/FEN legality and tactic proof belong to
    shared evidence/analyzers, not this structural contract. A proof reference
    never implies its continuation occurred in the game.
    """
    motif_type: str
    source_identity: str
    kind: OccurrenceKind = OccurrenceKind.UNKNOWN
    actor_color: TacticColor | None = None
    perspective_color: TacticColor | None = None
    source_position: str | None = None
    actual_move: str | None = None
    tactical_move: str | None = None
    actual_game_line: tuple[str, ...] | None = None
    counterfactual_line: tuple[str, ...] | None = None
    proof_source_identity: str | None = None
    candidate_id: int | None = None
    source_verdict: str | None = None
    provenance: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        if not isinstance(self.motif_type, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", self.motif_type):
            raise ValueError("Motif requires an independent snake_case code")
        if self.motif_type.startswith(("missed_", "played_")):
            raise ValueError("Motif must not encode occurrence kind")
        for name in ("source_identity", "source_position", "proof_source_identity", "source_verdict"):
            value = getattr(self, name)
            if (name == "source_identity" or value is not None) and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"Invalid {name}")
        object.__setattr__(self, "kind", OccurrenceKind(self.kind))
        for name in ("actor_color", "perspective_color"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, TacticColor(value))
        if self.candidate_id is not None and (type(self.candidate_id) is not int or self.candidate_id <= 0):
            raise ValueError("Candidate ID must be an existing positive ID or absent")
        _move(self.actual_move)
        _move(self.tactical_move)
        for name, root in (("actual_game_line", self.actual_move), ("counterfactual_line", self.tactical_move)):
            line = getattr(self, name)
            if line is not None:
                if not isinstance(line, tuple) or not line or root is None or line[0] != root:
                    raise ValueError(f"{name} must be an immutable nonempty line including its root")
                for move in line:
                    _move(move)
                    if move is None:
                        raise ValueError("Line moves cannot be absent")
        if not isinstance(self.provenance, tuple) or any(
            not isinstance(pair, tuple) or len(pair) != 2 or not all(isinstance(v, str) for v in pair)
            for pair in self.provenance
        ):
            raise ValueError("Provenance must be immutable text pairs")
        if self.kind != OccurrenceKind.UNKNOWN:
            if None in (self.actor_color, self.source_position, self.actual_move, self.tactical_move):
                raise ValueError("Known occurrence needs actor, decision position and both moves")
            if self.kind == OccurrenceKind.PLAYED:
                if not self.actual_move_matches_tactical_move or self.actual_game_line is None:
                    raise ValueError("Played tactic requires matching moves and actual game evidence")
            elif self.actual_move_matches_tactical_move or self.counterfactual_line is None:
                raise ValueError("Missed tactic requires a different move and counterfactual evidence")

    @property
    def actual_move_matches_tactical_move(self) -> bool | None:
        if self.actual_move is None or self.tactical_move is None:
            return None
        return self.actual_move == self.tactical_move

    @property
    def relation(self) -> TacticOccurrenceRelation:
        """Changing review perspective changes this view, never source identity or truth."""
        if self.kind == OccurrenceKind.UNKNOWN or self.actor_color is None or self.perspective_color is None:
            return TacticOccurrenceRelation.UNKNOWN
        same_side = self.actor_color == self.perspective_color
        if self.kind == OccurrenceKind.PLAYED:
            return (TacticOccurrenceRelation.PLAYED_BY_PERSPECTIVE if same_side
                    else TacticOccurrenceRelation.PLAYED_BY_OPPONENT)
        return (TacticOccurrenceRelation.MISSED_BY_PERSPECTIVE if same_side
                else TacticOccurrenceRelation.MISSED_BY_OPPONENT)
