"""Read-only fingerprints for deferred receipts; no engine or tactic calculation."""
from collections.abc import Mapping
import hashlib
import json
import sqlite3
from typing import Any
from existing_position_evidence import ExistingPositionEvidence
from solution_ownership import find_solution_owner


def canonical_json(value: Any) -> str:
    """Serialize receipt data deterministically.

    Args:
        value: JSON-compatible structured data.

    Returns:
        Stable compact JSON; non-finite values are rejected.
    """
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value: Any) -> str:
    """Hash exact structured receipt data.

    Args:
        value: JSON-compatible data whose identity matters.

    Returns:
        SHA256 of the canonical UTF-8 representation.
    """
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def deferred_dependencies(connection: sqlite3.Connection, move: Mapping[str, Any] | sqlite3.Row,
                          record: Mapping[str, Any]) -> dict[str, Any]:
    """Read identities and evidence used by a previously evaluated predicate.

    This validates raw request compatibility, but never reruns geometry/scouting
    or calls the preflight. The repository verifies the predicate when writing.

    Args:
        connection: Caller-owned database connection.
        move: Requested stored move, including its game/FEN/played identity.
        record: Complete preflight record with provenance.

    Returns:
        Exact move/game, evidence and applicable ownership fingerprints.

    Raises:
        ValueError: The requested move or evidence identity changed.
        KeyError: Provenance is incomplete.
        sqlite3.Error: Reading dependencies failed.
    """
    cursor = connection.cursor()
    cursor.row_factory = sqlite3.Row
    stored = cursor.execute('SELECT * FROM moves WHERE move_id=?', (move['move_id'],)).fetchone()
    if stored is None or stored['is_user_move'] != 1:
        raise ValueError('Deferred obligation requires an existing user move')
    for field in ('move_id', 'game_id', 'fen_before', 'fen_after', 'uci_played'):
        if stored[field] != move[field]:
            raise ValueError('Deferred move identity changed')
    game = cursor.execute('SELECT game_id,user_id,account_id,source,source_game_id,user_color '
                          'FROM games WHERE game_id=?', (stored['game_id'],)).fetchone()
    if game is None or game['source'] == 'dev':
        raise ValueError('Deferred obligation requires a real stored game')
    provenance = record['provenance']
    positions = ExistingPositionEvidence(connection)
    evidence = []
    for entry in provenance['evidence']:
        key = entry['key']
        lookup = positions.position(key['fen'], key['analysis_profile'])
        if lookup.key != key:
            raise ValueError('Deferred evidence request identity changed')
        evidence.append({'role':entry['role'], 'key':lookup.key, 'availability':lookup.reason,
                         'record_sha256':fingerprint(lookup.record) if lookup.available else None})
    owners = []
    if record['disposition'] == 'already_owned':
        for alternative in provenance['alternatives']:
            owner = find_solution_owner(connection, stored['move_id'], record['analysis_type'], alternative['move_uci'])
            candidate = cursor.execute('SELECT * FROM tactic_candidates WHERE candidate_id=?',
                                       (owner['candidate_id'],)).fetchone() if owner else None
            owners.append({'move_uci':alternative['move_uci'], 'owner':owner,
                           'revision_sha256':fingerprint(dict(candidate)) if candidate else None})
    move_identity = {k:stored[k] for k in stored.keys() if k != 'created_at'}
    return {'move':move_identity, 'game':dict(game), 'evidence':evidence, 'owners':owners}
