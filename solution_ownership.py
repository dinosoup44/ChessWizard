"""Shared canonical solution lookup; persistence callers own transactions."""


def find_solution_owner(connection, move_id, analysis_type, solution_move_uci):
    row = connection.execute(
        "SELECT candidate_id,tactic_type FROM tactic_candidates WHERE move_id=? "
        "AND tactic_type<>? AND solution_move_uci=? ORDER BY candidate_id LIMIT 1",
        (move_id, analysis_type, solution_move_uci)).fetchone()
    return {"candidate_id":row[0], "tactic_type":row[1]} if row is not None else None


class SolutionOwnershipService:
    """Read through every call; ownership snapshots are never cached as truth."""
    def __init__(self, connection):
        self._connection = connection

    def owner(self, move_id, analysis_type, solution_move_uci):
        return find_solution_owner(self._connection, move_id, analysis_type, solution_move_uci)
