"""Scoped, additive mate presentation using the existing episode grouping rules."""
import sqlite3
from sqlite_transaction import SqliteTransaction
from build_mate_episodes import build_candidate, build_episodes, save_episodes


CANDIDATE_COLUMNS = ('candidate_id', 'move_id', 'solution_move_san', 'solution_move_uci',
    'solution_line', 'detector_version')
MOVE_COLUMNS = ('game_id', 'ply_number', 'move_number', 'color', 'san_played', 'uci_played', 'fen_before')
GAME_COLUMNS = ('source', 'source_game_id', 'white_username', 'black_username', 'result', 'time_control')


def refresh_mate_episodes(connection: sqlite3.Connection, game_id: int) -> None:
    """Refresh additive mate presentation without changing protected episode IDs.

    Args:
        connection: Caller-owned connection; nesting retains outer commit ownership.
        game_id: Exact game whose presentation may be refreshed.

    Raises:
        ValueError: A proof is invalid or refresh would merge/reinterpret history.
        sqlite3.Error: The presentation transaction failed.
    """
    columns = ','.join([*('c.'+n for n in CANDIDATE_COLUMNS), *('m.'+n for n in MOVE_COLUMNS), *('g.'+n for n in GAME_COLUMNS)])
    rows = connection.execute(f'SELECT {columns} FROM tactic_candidates c JOIN moves m ON m.move_id=c.move_id '
        'JOIN games g ON g.game_id=m.game_id WHERE m.game_id=? AND c.tactic_type=? '
        "AND c.candidate_status IN ('candidate','confirmed') AND NOT EXISTS "
        "(SELECT 1 FROM analysis_coverage a WHERE a.move_id=c.move_id AND a.analysis_type=c.tactic_type AND a.coverage_status='rejected') "
        'ORDER BY m.ply_number,c.candidate_id', (game_id, 'missed_mate')).fetchall()
    if not rows:
        return
    candidates = [build_candidate(tuple(row)) for row in rows]
    if any(not c['fingerprint']['valid'] for c in candidates):
        raise ValueError('Mate presentation contains an invalid stored proof; no episode was changed')
    episodes = build_episodes(candidates)
    with SqliteTransaction(connection):
        links = {}
        for candidate_id, episode_id in connection.execute('SELECT em.candidate_id,em.episode_id FROM tactic_episode_members em '
                'JOIN tactic_episodes e ON e.episode_id=em.episode_id WHERE e.game_id=? AND e.tactic_type=?', (game_id, 'missed_mate')):
            links.setdefault(candidate_id, set()).add(episode_id)
        for episode in episodes:
            members = episode['candidates']
            missing = [c for c in members if c['candidate_id'] not in links]
            if not missing:
                continue
            existing = set().union(*(links.get(c['candidate_id'], set()) for c in members))
            if len(existing) > 1:
                raise ValueError('Mate presentation would merge protected episodes; explicit reconciliation required')
            if not existing:
                save_episodes(connection, [episode])
                continue
            episode_id = next(iter(existing))
            stored = connection.execute('SELECT * FROM tactic_episodes WHERE episode_id=?', (episode_id,)).fetchone()
            if stored['episode_status'] != 'candidate' or members[0]['candidate_id'] != stored['primary_candidate_id']:
                raise ValueError('Mate presentation would change a protected primary/status; explicit reconciliation required')
            sequence = connection.execute('SELECT COALESCE(max(sequence_order),0) FROM tactic_episode_members WHERE episode_id=?', (episode_id,)).fetchone()[0]
            for number, candidate in enumerate(missing, sequence+1):
                connection.execute('INSERT INTO tactic_episode_members(episode_id,candidate_id,sequence_order,match_reason) VALUES(?,?,?,?)',
                    (episode_id, candidate['candidate_id'], number, episode['match_reasons'][candidate['candidate_id']]))
            connection.execute('UPDATE tactic_episodes SET candidate_count=candidate_count+?,last_ply_number=max(last_ply_number,?),updated_at=CURRENT_TIMESTAMP WHERE episode_id=?',
                (len(missing), members[-1]['ply_number'], episode_id))
