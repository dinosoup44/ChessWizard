from contextlib import closing
from datetime import datetime
import hashlib
import sqlite3

def coverage_rows(connection):
    return {(r["move_id"], r["analysis_type"]): dict(r)
            for r in connection.execute("SELECT * FROM analysis_coverage")}


def protected_snapshot(connection):
    """Compare full original data, not just counts of candidates/attempts."""
    result = {}
    for (table,) in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "AND name NOT IN ('analysis_coverage','engine_position_cache') ORDER BY name"
    ):
        digest, count = hashlib.sha256(), 0
        quoted = table.replace('"', '""')
        for row in connection.execute(f'SELECT * FROM "{quoted}" ORDER BY rowid'):
            digest.update(repr(tuple(row)).encode("utf-8"))
            digest.update(b"\n")
            count += 1
        result[table] = {"count": count, "sha256": digest.hexdigest()}
    return result


def integrity_check(connection):
    if [tuple(row) for row in connection.execute("PRAGMA quick_check")] != [("ok",)]:
        raise RuntimeError("SQLite quick_check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("SQLite foreign_key_check failed")


def create_backup(connection, database_path, purpose="negative_coverage"):
    integrity_check(connection)
    path = database_path.with_name(
        f"{database_path.stem}_before_{purpose}_{datetime.now():%Y%m%d_%H%M%S_%f}.db"
    )
    with closing(sqlite3.connect(path)) as backup:
        connection.backup(backup)
        integrity_check(backup)
    print(f"Verified safety backup: {path}", flush=True)
    return path


def write_authorizer(*, coverage=False):
    allowed = {"analysis_coverage"} if coverage else {"engine_position_cache"}
    def authorize(action, table, column, db_name, trigger):
        if action == sqlite3.SQLITE_DELETE:
            return sqlite3.SQLITE_DENY
        if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE}:
            return sqlite3.SQLITE_OK if table in allowed | {"sqlite_sequence"} else sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    return authorize



