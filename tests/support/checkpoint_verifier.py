"""Supplemental read-only verification; copying remains owned by backup_merlin.

SQLite backup.c increments the destination schema cookie, and committing updates
its change/version-valid-for counters. No other bytes are exempt from equality.
Sources: https://www.sqlite.org/fileformat.html and SQLite src/backup.c.
"""
from contextlib import closing
from pathlib import Path
import hashlib
import sqlite3

HEADER_FIELDS = ((24, 4, "file_change_counter"), (40, 4, "schema_cookie"),
                 (92, 4, "version_valid_for"))
PERMITTED_OFFSETS = frozenset(i for start, size, _ in HEADER_FIELDS for i in range(start, start + size))


def digest(path: Path) -> str:
    """Hash a supplied file without changing it.

    Args:
        path: Caller-selected file to inspect.

    Returns:
        File content SHA256.
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def compare_database_files(source: Path, backup: Path, *, destination_schema_before: int | None=None) -> dict:
    """Compare backup bytes while exempting only the documented SQLite header counters.

    Args:
        source: Original checkpoint file or directory.
        backup: Backup file or directory to compare.
        destination_schema_before: Destination schema cookie before the SQLite backup operation, when known.

    Returns:
        Structured comparison or factual result for the supplied inputs.

    Raises:
        ValueError: Supplied files, positions or evidence fail the validation contract.
    """
    if source.stat().st_size != backup.stat().st_size:
        raise ValueError("Database size mismatch")
    differences = []
    with source.open("rb") as a, backup.open("rb") as b:
        headers = [a.read(100), b.read(100)]
        if any(len(h) != 100 or h[:16] != b"SQLite format 3\x00" for h in headers):
            raise ValueError("Invalid SQLite header")
        fields = [{"field": name, "offset": start, "size": size,
                   "source": int.from_bytes(headers[0][start:start+size], "big"),
                   "backup": int.from_bytes(headers[1][start:start+size], "big")}
                  for start, size, name in HEADER_FIELDS]
        if destination_schema_before is not None and fields[1]["backup"] != (destination_schema_before + 1) % (2**32):
            raise ValueError("Unexpected destination schema-cookie transition")
        for index in (0, 1):
            if headers[index][24:28] != headers[index][92:96]:
                raise ValueError("Incoherent change/version-valid-for counters")
        a.seek(0); b.seek(0)
        offset = 0
        while True:
            x, y = a.read(1024 * 1024), b.read(1024 * 1024)
            if len(x) != len(y):
                raise ValueError("Database changed size during verification")
            if not x:
                break
            if x != y:
                for i, (left, right) in enumerate(zip(x, y)):
                    if left != right:
                        absolute = offset + i
                        if absolute not in PERMITTED_OFFSETS:
                            raise ValueError(f"Unexplained differing byte at offset {absolute}")
                        differences.append({"offset": absolute, "source": left, "backup": right})
            offset += len(x)
    return {"source_bytes": source.stat().st_size, "backup_bytes": backup.stat().st_size,
            "fields": fields, "different_bytes": differences, "unexplained_differences": 0,
            "source_sha256": digest(source), "backup_sha256": digest(backup)}


def integrity(path: Path) -> dict:
    """Check a supplied SQLite file through a read-only, query-only connection.

    Args:
        path: Caller-selected file to inspect.

    Returns:
        Structured comparison or factual result for the supplied inputs.

    Raises:
        ValueError: Supplied files, positions or evidence fail the validation contract.
    """
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        quick = connection.execute("PRAGMA quick_check").fetchall()
        foreign = connection.execute("PRAGMA foreign_key_check").fetchall()
    if quick != [("ok",)] or foreign:
        raise ValueError(f"SQLite integrity failure: {quick!r}, {foreign!r}")
    return {"quick_check": quick, "foreign_key_check": foreign}


def verify_project_files(source: Path, backup: Path, expected_hashes: dict[str, str]) -> dict:
    """Verify both copies against the same explicit checkpoint inventory.

    Args:
        source: Original checkpoint file or directory.
        backup: Backup file or directory to compare.
        expected_hashes: Relative paths and required content digests.

    Returns:
        Structured comparison or factual result for the supplied inputs.

    Raises:
        ValueError: Supplied files, positions or evidence fail the validation contract.
    """
    total = 0
    for relative, expected in expected_hashes.items():
        a, b = source / relative, backup / relative
        if a.stat().st_size != b.stat().st_size or digest(a) != expected or digest(b) != expected:
            raise ValueError(f"Project file mismatch: {relative}")
        total += b.stat().st_size
    return {"verified_files": len(expected_hashes), "verified_bytes": total, "hash_mismatches": 0}
