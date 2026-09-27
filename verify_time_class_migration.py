"""Read-only comparison against the pre-time-class SQLite backup."""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path


def digest(connection, table, columns):
    result = hashlib.sha256()
    for row in connection.execute(f'SELECT {columns} FROM "{table}" ORDER BY rowid'):
        result.update(json.dumps(row, ensure_ascii=True).encode("utf-8"))
        result.update(b"\n")
    return result.hexdigest()


def verify(database_path, backup_path):
    with closing(sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True)) as current, \
         closing(sqlite3.connect(backup_path.resolve().as_uri() + "?mode=ro", uri=True)) as before:
        for (table,) in before.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            columns = ",".join('"' + row[1].replace('"','""') + '"' for row in before.execute(f'PRAGMA table_info("{table}")'))
            # Scout preview is allowed to append reusable engine evidence only.
            if table == "engine_position_cache":
                print("engine_position_cache: checked separately; scout evidence may be appended")
                continue
            if digest(current,table,columns) != digest(before,table,columns):
                raise RuntimeError(f"Original data changed in {table}")
            print(f"{table}: original data identical")
        current.execute("ATTACH DATABASE ? AS original", (backup_path.resolve().as_uri() + "?mode=ro",))
        missing_cache = current.execute(
            "SELECT COUNT(*) FROM (SELECT * FROM original.engine_position_cache EXCEPT SELECT * FROM main.engine_position_cache)"
        ).fetchone()[0]
        if missing_cache:
            raise RuntimeError("Original engine evidence changed")
        print("engine_position_cache: original evidence preserved")
        if current.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise RuntimeError("SQLite quick_check failed")
        print("SQLite quick_check: ok")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    parser.add_argument("--db", type=Path, default=Path(__file__).resolve().parent / "merlin.db")
    args = parser.parse_args()
    verify(args.db,args.backup)
