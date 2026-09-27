"""Compare historical artifacts to a saved replay; no engine or database access."""
from collections import Counter
from copy import deepcopy
import json
import chess
from pathlib import Path

from proof_evidence_state import proof_state

FIELDS = ('opponent_move_uci', 'player_move_uci', 'proof_state', 'proof_line',
    'final_fen', 'material_gain_cp', 'retained_related_cp', 'final_player_cp',
    'payoff_signature', 'realizable_target_squares')


def retained_facts(details: dict) -> list[dict]:
    """Normalize recorded proof summaries without manufacturing missing evidence.

    Args:
        details: Supplied analyzer details; never regenerated here.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    rows = deepcopy(details.get('branches', []))
    for index, row in enumerate(rows):
        original_state = row.get('proof_state', '')
        attempts = [a for a in details.get('escalation_attempts', []) if a['branch_index'] == index]
        latest = next((a['proof'] for a in reversed(attempts) if a.get('proof')), None)
        # Legacy unresolved summaries retained the short PV despite recording the deeper proof.
        if original_state == 'unresolved' and latest:
            root = row['proof_line'].split()[0]
            row.update(proof_state=latest['state'], final_fen=latest['final_fen'],
                proof_line=' '.join([root, *[step['san'] for step in latest['steps']]]))
        elif original_state == 'budget_exhausted' and not latest:
            row = deepcopy(details.get('normal_branches', rows)[index])
            rows[index] = row
        row['proof_state'] = proof_state(row.get('proof_state', ''), row.get('final_fen'))
    return [{key:row.get(key) for key in FIELDS} for row in rows]


def fact_differences(left: list[dict], right: list[dict]) -> list[dict]:
    """List branch-level differences on the explicit shared factual fields.

    Args:
        left: First factual branch sequence.
        right: Second factual branch sequence.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    changed = []
    for index in range(max(len(left), len(right))):
        a = left[index] if index < len(left) else {}
        b = right[index] if index < len(right) else {}
        changed.extend(dict(branch=index, field=k, before=a.get(k), after=b.get(k))
            for k in FIELDS if a.get(k) != b.get(k))
    return changed


def checkmate_ownership_cleanup(after: dict) -> str | None:
    """Recognize a terminal-routing change only after checking the supplied board.

    Args:
        after: Current supplied result.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    terminal = after['result']['details'].get('terminal') or {}
    state = terminal.get('terminal_state')
    if state not in {'played_checkmate', 'candidate_checkmate'}:
        return None
    row = after['row']
    board = chess.Board(row['fen_before'])
    played = state == 'played_checkmate'
    move = chess.Move.from_uci(row['uci_played'] if played else after['move'])
    assert move in board.legal_moves
    board.push(move)
    assert board.is_checkmate()
    assert terminal['ownership'] == ('played_move_terminal' if played else 'mate')
    assert board.result() == terminal['result'] and terminal['complete']
    return ('played' if played else 'candidate') + '-checkmate ownership cleanup'


def compare_record(before: dict, after: dict, selective: dict) -> dict:
    """Compare supplied prior, baseline and selective results without rerunning analysis.

    Args:
        before: Prior supplied result.
        after: Current supplied result.
        selective: Supplied selective-policy result.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    old, new = before['details'], after['result']['details']
    left, right = retained_facts(old), retained_facts(new)
    changed = fact_differences(left, right)
    raw = [{key:row.get(key) for key in FIELDS} for row in old.get('branches', [])]
    summary_changes = fact_differences(raw, left)
    same_verdict = old['classification'] == new['classification']
    same_gate = old.get('root_move_passes_gate') == new.get('root_move_passes_gate')
    cleanup = checkmate_ownership_cleanup(after)
    category = (cleanup if cleanup else
        'classification changed; review required' if not same_verdict else
        'root admission changed; review required' if not same_gate else
        'retained evidence differs; verdict unchanged' if changed else
        'recorded proof summary cleanup' if summary_changes else
        'same retained facts and verdict')
    return dict(key=after['key'], kind=after['kind'], game_id=after['row']['game_id'],
        source_game_id=after['row']['source_game_id'], move_id=after['row']['move_id'],
        proposed=after['move'], historical_source=before['source'], category=category,
        before_classification=old['classification'], mode_a_classification=new['classification'],
        mode_b_classification=selective['result']['details']['classification'],
        before_reason=old['reason'], mode_a_reason=new['reason'],
        mode_b_reason=selective['result']['details']['reason'],
        same_root_gate=same_gate, retained_fact_differences=changed,
        source_summary_differences=summary_changes,
        mode_a_cache_sources=after.get('cache_sources', {}),
        mode_a_request_costs={k:after.get(k, {}) for k in ('breadth','verification')},
        mode_b_retained_facts_changed=right != retained_facts(selective['result']['details']),
        protected=True)


