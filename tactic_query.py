"""Shared read-only candidate visibility and game filtering; no analyzer imports."""
from dataclasses import dataclass


@dataclass(frozen=True)
class TacticReadPolicy:
    label: str
    statuses: tuple[str, ...] = ("candidate",)
    episode_primary: bool = False


TACTIC_POLICIES = {
    "missed_fork": TacticReadPolicy("Fork"),
    "missed_mate": TacticReadPolicy("Mate", ("candidate", "confirmed"), True),
    "missed_pin": TacticReadPolicy("Pin"),
    "missed_skewer": TacticReadPolicy("Skewer"),
    "missed_xray": TacticReadPolicy("X-ray"),
}


def tactic_label(tactic_type):
    policy = TACTIC_POLICIES.get(tactic_type)
    return policy.label if policy else tactic_type.removeprefix("missed_").replace("_", " ").capitalize()


def active_predicate():
    """One visibility rule for lists, counts, filters and training consumers.

    Protected historical candidates remain visible without analyzer-version
    reconciliation. Coverage rejection always wins. Unknown future missed-tactic
    types use active canonical rows automatically.
    """
    special = {k:p for k,p in TACTIC_POLICIES.items() if p.statuses != ("candidate",) or p.episode_primary}
    clauses, params = [], []
    if special:
        clauses.append(f"(tc.tactic_type NOT IN ({','.join('?' for _ in special)}) AND tc.candidate_status='candidate')")
        params.extend(special)
    else:
        clauses.append("tc.candidate_status='candidate'")
    for kind, policy in special.items():
        clause = f"(tc.tactic_type=? AND tc.candidate_status IN ({','.join('?' for _ in policy.statuses)})"
        params.extend((kind, *policy.statuses))
        if policy.episode_primary:
            clause += " AND EXISTS (SELECT 1 FROM tactic_episodes te WHERE te.primary_candidate_id=tc.candidate_id AND te.tactic_type=tc.tactic_type AND te.episode_status='candidate')"
        clauses.append(clause+")")
    return ("substr(tc.tactic_type,1,7)='missed_' AND (" + " OR ".join(clauses) + ")"
            " AND NOT EXISTS (SELECT 1 FROM analysis_coverage ac WHERE ac.move_id=tc.move_id"
            " AND ac.analysis_type=tc.tactic_type AND ac.coverage_status='rejected')"
            " AND NOT EXISTS (SELECT 1 FROM tactic_candidates duplicate WHERE duplicate.move_id=tc.move_id"
            " AND duplicate.tactic_type=tc.tactic_type AND duplicate.candidate_id<>tc.candidate_id)"), params


class TacticQuery:
    def __init__(self, connection):
        self.connection = connection

    def candidates(self, *, game_id=None, game_ids=None, tactic_types=None, candidate_id=None):
        predicate, params = active_predicate()
        if candidate_id is not None:
            predicate += " AND tc.candidate_id=?"
            params.append(candidate_id)
        if game_id is not None:
            predicate += " AND m.game_id=?"
            params.append(game_id)
        for column, values in (("m.game_id", game_ids), ("tc.tactic_type", tactic_types)):
            if values is not None:
                values = tuple(values)
                if not values:
                    return []
                predicate += f" AND {column} IN ({','.join('?' for _ in values)})"
                params.extend(values)
        cursor = self.connection.execute(
            "SELECT tc.*,m.game_id,m.ply_number,m.move_number,m.color,m.san_played,m.uci_played,m.fen_before,m.fen_after,"
            "g.source,g.source_game_id,g.white_username,g.black_username,"
            "(SELECT te.episode_id FROM tactic_episodes te WHERE te.primary_candidate_id=tc.candidate_id "
            "AND te.tactic_type=tc.tactic_type AND te.episode_status='candidate' ORDER BY te.episode_id LIMIT 1) AS episode_id "
            "FROM tactic_candidates tc JOIN moves m ON m.move_id=tc.move_id JOIN games g ON g.game_id=m.game_id "
            f"WHERE {predicate} ORDER BY m.game_id,m.ply_number,tc.candidate_id", params)
        return [dict(zip((d[0] for d in cursor.description), row)) for row in cursor]

    def game_ids(self, tactic_type="any", *, within=None):
        return {r["game_id"] for r in self.candidates(game_ids=within,
            tactic_types=None if tactic_type=="any" else (tactic_type,))}

    def filter_options(self):
        kinds = set(TACTIC_POLICIES)
        kinds.update(r[0] for r in self.connection.execute(
            "SELECT DISTINCT tactic_type FROM tactic_candidates WHERE substr(tactic_type,1,7)='missed_'"))
        ordered = list(TACTIC_POLICIES) + sorted(kinds-set(TACTIC_POLICIES))
        return [(None,"All games"),("any","Any missed tactic"),*((k,tactic_label(k)) for k in ordered)]
