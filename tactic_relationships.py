"""Pure ownership/move comparison over supplied accepted tactic truth; no analysis."""
from dataclasses import dataclass
from enum import StrEnum

from position_range_evidence import LegalReplay
from tactic_occurrences import OccurrenceKind, TacticColor, TacticOccurrence, TacticOccurrenceRelation


class TacticTruthScope(StrEnum):
    VERIFIED_ROOT = 'verified_root'
    LEGACY_MISSED = 'legacy_missed'


@dataclass(frozen=True)
class DecisionIdentity:
    """Exact persisted source binding; signed IDs are references, never sentinels."""
    game_id: int
    move_id: int
    source: str
    source_game_id: str
    ply: int
    fen: str
    actor: TacticColor

    def valid(self) -> bool:
        return (all(type(v) is int and v != 0 for v in (self.game_id, self.move_id))
                and type(self.ply) is int and self.ply > 0
                and all(isinstance(v, str) and v.strip() for v in (self.source, self.source_game_id, self.fen))
                and self.actor in ('white', 'black'))


@dataclass(frozen=True)
class RecordedDecision:
    identity: DecisionIdentity
    actual_move: str | None
    user_color: TacticColor | None


@dataclass(frozen=True)
class AcceptedTactic:
    """Provider owns admission, motif and currentness. Equality cannot supply proof.

    Legacy missed claims retain their narrower meaning: matching roots require
    independent verified-root evidence, not a reinterpretation of a type prefix.
    """
    identity: DecisionIdentity
    motif: str
    tactical_move: str | None
    source_identity: str
    active: bool
    accepted: bool
    scope: TacticTruthScope = TacticTruthScope.VERIFIED_ROOT


@dataclass(frozen=True)
class RelationshipAssessment:
    relation: TacticOccurrenceRelation
    kind: OccurrenceKind
    reason: str
    provenance: tuple[tuple[str, str], ...]

    @property
    def known(self) -> bool:
        return self.relation != TacticOccurrenceRelation.UNKNOWN


def assess_relationship(tactic: AcceptedTactic, recorded: RecordedDecision) -> RelationshipAssessment:
    """Compare initiating moves only; never infer payoff, mate or motif from the board."""
    provenance = (('source_identity', tactic.source_identity), ('truth_scope', str(tactic.scope)),
                  ('game_id', str(recorded.identity.game_id)), ('move_id', str(recorded.identity.move_id)))

    def unknown(reason):
        return RelationshipAssessment(TacticOccurrenceRelation.UNKNOWN, OccurrenceKind.UNKNOWN, reason, provenance)

    if not tactic.active:
        return unknown('inactive_tactic')
    if not tactic.accepted or not tactic.source_identity:
        return unknown('unaccepted_tactic_evidence')
    if not tactic.identity.valid() or not recorded.identity.valid():
        return unknown('invalid_source_identity')
    if tactic.identity != recorded.identity:
        return unknown('decision_identity_mismatch')
    if recorded.user_color not in ('white', 'black'):
        return unknown('unknown_user_color')
    if not recorded.actual_move or not tactic.tactical_move:
        return unknown('missing_move_evidence')
    if tactic.scope not in tuple(TacticTruthScope):
        return unknown('unsupported_truth_scope')
    if tactic.scope == TacticTruthScope.LEGACY_MISSED and recorded.actual_move == tactic.tactical_move:
        return unknown('legacy_missed_claim_requires_verified_played_evidence')
    try:
        actual = LegalReplay(recorded.identity.fen, (recorded.actual_move,))
        actor = TacticColor.WHITE if actual.board_at(0).turn else TacticColor.BLACK
        if actor != recorded.identity.actor:
            return unknown('actor_disagrees_with_decision_position')
        LegalReplay(recorded.identity.fen, (tactic.tactical_move,))
        kind = OccurrenceKind.PLAYED if recorded.actual_move == tactic.tactical_move else OccurrenceKind.MISSED
        occurrence = TacticOccurrence(tactic.motif, tactic.source_identity, kind=kind,
            actor_color=actor, perspective_color=recorded.user_color,
            source_position=recorded.identity.fen, actual_move=recorded.actual_move,
            tactical_move=tactic.tactical_move, actual_game_line=(recorded.actual_move,),
            counterfactual_line=(tactic.tactical_move,))
    except (ValueError, TypeError):
        return unknown('invalid_decision_evidence')
    return RelationshipAssessment(occurrence.relation, kind,
        'exact_verified_root_played' if kind == OccurrenceKind.PLAYED else 'different_recorded_move', provenance)
