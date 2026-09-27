"""Additive line-cache migration. Explicit connection only; never auto-migrate live DB."""
import re
CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS engine_candidate_line_cache (
    line_set_id INTEGER PRIMARY KEY,
    fen TEXT NOT NULL,
    engine_identity TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK(schema_version = 1),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(fen, engine_identity)
)
"""


def migrate(connection):
    """Caller owns authorization, backup and transaction; existing tables are never rebuilt."""
    connection.execute(CREATE_TABLE)
    validate_schema(connection)


def validate_schema(connection):
    """Require the approved columns and constraints, not just familiar column names."""
    expected = (
        (0, 'line_set_id', 'INTEGER', 0, None, 1),
        (1, 'fen', 'TEXT', 1, None, 0),
        (2, 'engine_identity', 'TEXT', 1, None, 0),
        (3, 'schema_version', 'INTEGER', 1, None, 0),
        (4, 'payload_json', 'TEXT', 1, None, 0),
        (5, 'created_at', 'TEXT', 1, 'CURRENT_TIMESTAMP', 0),
    )
    columns = tuple(tuple(row) for row in connection.execute('PRAGMA table_info(engine_candidate_line_cache)'))
    sql = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='engine_candidate_line_cache'").fetchone()
    def normalized(value):
        return re.sub(r'\s+', '', value.lower().replace('IF NOT EXISTS'.lower(), '')).rstrip(';')
    if columns != expected or sql is None or normalized(sql[0]) != normalized(CREATE_TABLE):
        raise ValueError("Incompatible existing candidate-line cache")
    indexes = list(connection.execute('PRAGMA index_list(engine_candidate_line_cache)'))
    if len(indexes) != 1 or tuple(indexes[0][2:]) != (1, 'u', 0):
        raise ValueError('Expected only the exact-request UNIQUE constraint')
    index_name = indexes[0][1].replace('"', '""')
    keys = tuple(row[2] for row in connection.execute(f'PRAGMA index_info("{index_name}")'))
    if keys != ('fen', 'engine_identity'):
        raise ValueError('Incompatible exact-request key')


if __name__ == "__main__":
    raise SystemExit("No live apply command. Call migrate(connection) in an approved migration transaction.")
