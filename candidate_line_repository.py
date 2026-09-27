"""One compact engine result per exact request. No candidates/coverage writes."""
import json
import sqlite3
from collections.abc import Iterable
from threading import Event
from analysis_control import check_cancelled

CACHE_READ_BATCH = 200
from candidate_lines import CandidateLine, CandidateLineSet, LineScore, to_data


def insert_only_authorizer(action, table, detail, database, trigger):
    """Optional caller-installed boundary: cache inserts and read/transaction operations only."""
    if action == sqlite3.SQLITE_INSERT:
        return sqlite3.SQLITE_OK if table == 'engine_candidate_line_cache' and database == 'main' and trigger is None else sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_PRAGMA:
        inspection = {'table_info', 'index_list', 'index_info', 'foreign_key_list'}
        read_only = {'quick_check', 'foreign_key_check', 'page_count', 'page_size', 'freelist_count', 'schema_version'}
        return sqlite3.SQLITE_OK if table in inspection or table in read_only and detail is None else sqlite3.SQLITE_DENY
    allowed = {sqlite3.SQLITE_READ, sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION,
               sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT, sqlite3.SQLITE_RECURSIVE}
    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


def _encode(line_set):
    # Shared identity and derived SAN are omitted from each stored line.
    data = to_data(line_set)
    for line in data['lines']:
        for key in ('engine_identity', 'move_san', 'pv_san'): line.pop(key)
    return json.dumps(data, sort_keys=True, separators=(',', ':'))


def _decode(payload):
    data = json.loads(payload)
    data['lines'] = tuple(CandidateLine(**{**line, 'engine_identity': data['engine_identity'],
        'score': LineScore(**line['score'])}) for line in data['lines'])
    return CandidateLineSet(**data)


class CandidateLineRepository:
    """Read/write exact immutable cache evidence without owning transactions.

    Args:
        connection: Caller-owned database connection; schema must already exist
            before writes. Reads tolerate an unmigrated database.
    """
    def __init__(self, connection: sqlite3.Connection) -> None:
        """Bind the repository without opening or modifying a database.

        Args:
            connection: Caller-owned SQLite cache connection.
        """
        self.connection = connection

    def get(self, fen, engine_identity):
        """Read an exact request, tolerating an unmigrated read-only database."""
        if not self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='engine_candidate_line_cache'").fetchone():
            return None
        row = self.connection.execute("SELECT schema_version,payload_json FROM engine_candidate_line_cache WHERE fen=? AND engine_identity=?",
                                      (fen, engine_identity)).fetchone()
        if row is None: return None
        if row[0] != 1: raise ValueError("Unsupported cached line schema")
        value = _decode(row[1])
        if value.fen != fen or value.engine_identity != engine_identity: raise ValueError("Corrupt cache identity")
        return value

    def put(self, line_set):
        """Insert complete evidence once; caller commits and authorizes its destination."""
        if line_set.generation_metadata.get('complete') is not True:
            raise ValueError("Do not persist incomplete evidence")
        cursor = self.connection.execute("INSERT INTO engine_candidate_line_cache(fen,engine_identity,schema_version,payload_json) VALUES(?,?,?,?) ON CONFLICT(fen,engine_identity) DO NOTHING",
            (line_set.fen, line_set.engine_identity, line_set.schema_version, _encode(line_set)))
        return cursor.rowcount == 1

    def get_many(self, requests: Iterable[tuple[str, str]], *, cancel: Event | None = None
                 ) -> dict[tuple[str, str], CandidateLineSet | None]:
        """Read exact requests in batches and validate every returned PV normally.

        Args:
            requests: FEN/engine-identity pairs; incompatible profiles never alias.
            cancel: Optional cooperative stop signal.

        Returns:
            Requested keys mapped to immutable evidence, or None when absent,
            unsupported or malformed. No invalid row is considered completed.

        Raises:
            AnalysisCancelled: The caller requested Stop.
            sqlite3.Error: Database read failed.
        """
        keys = tuple(dict.fromkeys(requests))
        result = dict.fromkeys(keys)
        if not keys or not self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='engine_candidate_line_cache'").fetchone():
            return result
        for offset in range(0, len(keys), CACHE_READ_BATCH):
            check_cancelled(cancel)
            batch = keys[offset:offset+CACHE_READ_BATCH]
            values = ','.join('(?,?)' for _ in batch)
            rows = self.connection.execute(
                'WITH requests(fen,identity) AS (VALUES ' + values + ') '
                'SELECT c.fen,c.engine_identity,c.schema_version,c.payload_json FROM requests r '
                'JOIN engine_candidate_line_cache c ON c.fen=r.fen AND c.engine_identity=r.identity',
                tuple(value for key in batch for value in key))
            for fen, identity, schema, payload in rows:
                check_cancelled(cancel)
                try:
                    if schema != 1:
                        continue
                    value = _decode(payload)
                    if value.fen == fen and value.engine_identity == identity:
                        result[fen, identity] = value
                except (ValueError, KeyError, TypeError):
                    continue
        return result
