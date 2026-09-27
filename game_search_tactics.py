"""Active tactic facts projected through the shared occurrence relationship contract."""
from dataclasses import dataclass
from tactic_relationship_repository import TacticRelationshipRepository, decision_from_row, record_from_storage
from tactic_relationships import AcceptedTactic, RecordedDecision, assess_relationship
from tactic_occurrences import TacticOccurrence


@dataclass(frozen=True)
class OccurrenceEvidenceSelection:
    """Explicit accepted revisions from a provider; timestamps never imply currentness.

    No standalone live provider is active in V1. A future provider selects its
    accepted revisions without changing search, or reinterpreting archived facets.
    Selected standalone rows must also carry accepted admission and verified proof.
    """
    revision_ids: frozenset[str] = frozenset()


class GameSearchTactics:
    def __init__(self, connection, selection=OccurrenceEvidenceSelection()):
        self.connection, self.selection = connection, selection

    def facts(self, games):
        """Return (motif, relation) per active claim; mapped legacy rows count once."""
        perspectives = {g["game_id"]: g["user_color"] for g in games}
        facts = {gid: [] for gid in perspectives}
        if not perspectives:
            return facts
        # Exact-ID requests constrain candidate lookup as well as game metadata.
        for item in TacticRelationshipRepository(self.connection).candidates(game_ids=tuple(perspectives)):
            facts[item.recorded.identity.game_id].append((item.motif, item.assessment.relation.value))
        if not self.selection.revision_ids:
            return facts
        placeholders = ",".join("?" for _ in self.selection.revision_ids)
        cursor = self.connection.execute(
            "SELECT DISTINCT o.* FROM tactic_occurrences o JOIN tactic_occurrence_evidence e USING(occurrence_id) "
            f"WHERE e.revision_id IN ({placeholders}) "
            "AND e.admission_status IN ('accepted','admitted') "
            "AND e.proof_status IN ('verified','verified_payoff_changed') "
            "AND NOT EXISTS (SELECT 1 FROM tactic_occurrence_legacy_candidates l WHERE l.occurrence_id=o.occurrence_id)",
            tuple(self.selection.revision_ids))
        columns = [d[0] for d in cursor.description]
        for values in cursor:
            row = dict(zip(columns, values))
            gid = row["game_id"]
            if gid not in perspectives:
                continue
            anchor_cursor = self.connection.execute(
                "SELECT m.*,g.source,g.source_game_id FROM moves m JOIN games g USING(game_id) "
                "WHERE m.move_id=? AND m.game_id=?",
                (row["move_id"], gid))
            anchor_values = anchor_cursor.fetchone()
            anchor = dict(zip((d[0] for d in anchor_cursor.description), anchor_values)) if anchor_values else None
            if not anchor or (anchor['ply_number'], anchor['fen_before'], anchor['uci_played']) != (
                    row['decision_ply'], row['decision_fen'], row['actual_move_uci']):
                continue
            # Validate the decision/line-role invariant before projecting relationship.
            try:
                record_from_storage(row)
                perspective = perspectives[gid]
                value = TacticOccurrence(
                    row["motif_type"], row["occurrence_id"], kind=row["occurrence_kind"],
                    actor_color=row["actor_color"], perspective_color=perspective if perspective in ("white", "black") else None,
                    source_position=row["decision_fen"], actual_move=row["actual_move_uci"],
                    tactical_move=row["tactical_move_uci"], actual_game_line=(row["actual_move_uci"],),
                    counterfactual_line=(row["tactical_move_uci"],))
            except (ValueError, TypeError):
                continue
            decision = decision_from_row(anchor)
            if row['actor_color'] != decision.actor:
                continue
            assessment = assess_relationship(
                AcceptedTactic(decision, value.motif_type, value.tactical_move, value.source_identity,
                               True, value.kind != 'unknown'),
                RecordedDecision(decision, anchor['uci_played'], perspective))
            facts[gid].append((value.motif_type, assessment.relation.value))
        return facts

