"""Explicit additive schema for conservative completed obligations; no auto-migration."""
import sqlite3

TABLE = 'analysis_deferred_checks'
SCHEMA_SQL = """CREATE TABLE analysis_deferred_checks (
    move_id INTEGER NOT NULL REFERENCES moves(move_id) ON DELETE CASCADE,
    analysis_type TEXT NOT NULL,
    completion_state TEXT NOT NULL CHECK(completion_state = 'complete_deferred'),
    disposition TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    contract_version INTEGER NOT NULL CHECK(contract_version = 1),
    contract_json TEXT NOT NULL,
    dependency_json TEXT NOT NULL,
    details_json TEXT NOT NULL,
    receipt_sha256 TEXT NOT NULL CHECK(length(receipt_sha256) = 64),
    checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(move_id, analysis_type)
)"""


def deferred_schema_available(connection: sqlite3.Connection) -> bool:
    """Detect the optional reviewed schema without creating it.

    Args:
        connection: Caller-owned read connection.

    Returns:
        Whether the exact optional ledger exists.

    Raises:
        ValueError: An incompatible object uses the ledger name.
    """
    row = connection.execute('SELECT type,sql FROM sqlite_master WHERE name=?', (TABLE,)).fetchone()
    if row is None:
        return False
    normalize = lambda value: ''.join(value.lower().split()).replace('"', '')
    if row[0] != 'table' or normalize(row[1]) != normalize(SCHEMA_SQL):
        raise ValueError('Unrecognized deferred-check ledger schema; explicit migration required')
    return True


def create_deferred_schema(connection: sqlite3.Connection) -> bool:
    """Create only the optional ledger inside an explicitly owned transaction.

    Args:
        connection: Connection with an active migration transaction.

    Returns:
        True if the table was created; False for an exact existing schema.

    Raises:
        ValueError: Transaction ownership or an existing schema is invalid.
        sqlite3.Error: Creation failed; the caller must roll back.
    """
    if not connection.in_transaction:
        raise ValueError('An explicit migration transaction is required')
    if deferred_schema_available(connection):
        return False
    connection.execute(SCHEMA_SQL)
    deferred_schema_available(connection)
    return True
