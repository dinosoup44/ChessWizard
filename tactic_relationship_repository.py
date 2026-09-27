"""Read-only relationship provider and immutable occurrence reconciliation plans."""
from dataclasses import dataclass
import json

from tactic_query import TacticQuery
from tactic_occurrence_storage import (
    LegacyDecisionReference, NamedOccurrenceKey, OccurrenceKey, TacticOccurrenceRecord,
)
from tactic_relationships import (
    AcceptedTactic, DecisionIdentity, RecordedDecision, RelationshipAssessment,
    TacticTruthScope, assess_relationship,
)


SUPPORTED_MOTIFS = frozenset(('fork', 'mate', 'pin', 'skewer', 'xray'))


@dataclass(frozen=True)
class CandidateRelationship:
    candidate_id: int
    motif: str
    recorded: RecordedDecision
    tactical_move: str
    assessment: RelationshipAssessment


@dataclass(frozen=True)
class OccurrencePlan:
    """Existing keys are immutable. Conflicts need review, never automatic relinking."""
    candidate_id: int
    action: str
    reason: str
    record: TacticOccurrenceRecord | None


def decision_from_row(row) -> DecisionIdentity:
    return DecisionIdentity(row['game_id'], row['move_id'], row['source'], row['source_game_id'],
                            row['ply_number'], row['fen_before'], row['color'])


def assess_legacy_row(row, perspective) -> CandidateRelationship:
    """Only call with rows selected by TacticQuery's active canonical policy."""
    motif = row['tactic_type'].removeprefix('missed_')
    identity = decision_from_row(row)
    recorded = RecordedDecision(identity, row['uci_played'], perspective)
    tactic = AcceptedTactic(identity, motif, row['solution_move_uci'], f"candidate:{row['candidate_id']}",
        row['candidate_status'] in ('candidate', 'confirmed'), motif in SUPPORTED_MOTIFS,
        TacticTruthScope.LEGACY_MISSED)
    return CandidateRelationship(row['candidate_id'], motif, recorded, row['solution_move_uci'],
                                 assess_relationship(tactic, recorded))


def record_from_storage(row) -> TacticOccurrenceRecord:
    """Validate UUID/columns against the frozen versioned identity contract."""
    identity = json.loads(row['identity_json'])
    reference = None
    if row['identity_version'] == 2 and identity[:2] == [2, 'named_source']:
        key = NamedOccurrenceKey(*identity[2:])
        reference = LegacyDecisionReference(row['game_id'], row['move_id'])
    elif row['identity_version'] == 1 and identity[0] == 1:
        key = OccurrenceKey(*identity[1:])
    else:
        raise ValueError('Unsupported stored occurrence identity')
    record = TacticOccurrenceRecord(key, row['decision_ply'], row['decision_fen'], row['actual_move_uci'], reference)
    expected = dict(occurrence_id=record.occurrence_id, identity_json=key.identity_json,
        source_namespace=key.source_namespace, game_id=record.game_id, move_id=record.move_id,
        occurrence_kind=key.kind, actor_color=key.actor_color, motif_type=key.motif_type,
        tactical_move_uci=key.tactical_move_uci, instance_key=key.instance_key)
    if any(row[name] != value for name, value in expected.items()):
        raise ValueError('Stored occurrence identity conflict')
    return record


class TacticRelationshipRepository:
    """No writes or engine dependency. Caller owns a read transaction/snapshot."""
    def __init__(self, connection):
        self.connection = connection

    def candidates(self, *, game_ids=None) -> tuple[CandidateRelationship, ...]:
        perspectives = dict(self.connection.execute('SELECT game_id,user_color FROM games'))
        return tuple(assess_legacy_row(row, perspectives.get(row['game_id']))
                     for row in TacticQuery(self.connection).candidates(game_ids=game_ids))

    def plan(self, candidate: CandidateRelationship, source_namespace: str) -> OccurrencePlan:
        assessment, decision = candidate.assessment, candidate.recorded.identity
        if not assessment.known:
            return OccurrencePlan(candidate.candidate_id, 'unknown', assessment.reason, None)
        cursor = self.connection.execute('SELECT o.* FROM tactic_occurrences o JOIN '
            'tactic_occurrence_legacy_candidates l USING(occurrence_id) WHERE l.candidate_id=?',
            (candidate.candidate_id,))
        values = cursor.fetchone()
        existing = dict(zip((d[0] for d in cursor.description), values)) if values else None
        try:
            if existing:
                record = record_from_storage(existing)
                if (record.game_id, record.move_id, record.decision_ply, record.decision_fen,
                    record.actual_move_uci, record.key.kind, record.key.actor_color, record.key.motif_type,
                    record.key.tactical_move_uci) != (decision.game_id, decision.move_id, decision.ply, decision.fen,
                    candidate.recorded.actual_move, assessment.kind, decision.actor, candidate.motif, candidate.tactical_move):
                    raise ValueError('Existing immutable anchor differs')
                if isinstance(record.key, NamedOccurrenceKey) and (
                    record.key.source, record.key.source_game_id) != (decision.source, decision.source_game_id):
                    raise ValueError('Named source binding differs')
                return OccurrencePlan(candidate.candidate_id, 'unchanged', 'existing_identity_preserved', record)
            # New signed references need an explicitly registered named source; never abs(id).
            if decision.game_id <= 0 or decision.move_id <= 0 or candidate.candidate_id <= 0:
                return OccurrencePlan(candidate.candidate_id, 'unknown', 'named_source_registration_required', None)
            key = OccurrenceKey(source_namespace, decision.game_id, decision.move_id,
                assessment.kind, decision.actor, candidate.motif, candidate.tactical_move)
            record = TacticOccurrenceRecord(key, decision.ply, decision.fen, candidate.recorded.actual_move)
            return OccurrencePlan(candidate.candidate_id, 'insert', 'new_canonical_mapping', record)
        except (ValueError, TypeError):
            return OccurrencePlan(candidate.candidate_id, 'conflict', 'immutable_identity_requires_review', None)
