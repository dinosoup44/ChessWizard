"""Candidate-only read selection and verification orchestration. No move crawl."""
from analysis_results import HeavyResult


def existing_candidates(connection, analysis_type):
    cursor = connection.execute("SELECT c.*,m.game_id,m.ply_number,m.move_number,m.color,m.san_played,m.uci_played,m.fen_before,m.fen_after,"
        "g.source,g.source_game_id FROM tactic_candidates c JOIN moves m ON m.move_id=c.move_id JOIN games g ON g.game_id=m.game_id "
        "WHERE c.tactic_type=? ORDER BY c.candidate_id",(analysis_type,))
    return [dict(zip((d[0] for d in cursor.description),row)) for row in cursor]


def verify_candidates(rows, definition, positions, on_result=None):
    results = []
    for row in rows:
        try:
            result = definition.heavy(row,positions)
        except Exception as error:
            result = HeavyResult("error",details={"reason":"verification_exception","classification":"error",
                                "error_type":type(error).__name__,"message":str(error)})
        results.append((row,result))
        if on_result: on_result(row,result,len(results),len(rows))
    return results
