"""Create an empty current database once; never migrate or replace an existing file."""
from contextlib import closing
from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4

from database_schema import BASE_SCHEMA_SHA256, REQUIRED_COLUMNS, SCHEMA_STATEMENTS, SCHEMA_VERSION

METADATA_SQL = "CREATE TABLE application_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"


class BootstrapError(RuntimeError):
    """Startup failure with a target path and cause suitable for a user-facing error."""


@dataclass(frozen=True)
class BootstrapResult:
    path: Path
    created: bool


def _validate_structure(connection: sqlite3.Connection) -> None:
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = set(REQUIRED_COLUMNS) - tables
    if missing:
        raise BootstrapError("Existing schema is incomplete; missing tables: " + ", ".join(sorted(missing)))
    for table, required in REQUIRED_COLUMNS.items():
        columns = {row[1] for row in connection.execute('PRAGMA table_info("' + table + '")')}
        if not set(required) <= columns:
            raise BootstrapError("Existing schema is incomplete in " + table + "; no automatic migration was attempted")
    if "application_metadata" in tables:
        version = connection.execute("SELECT value FROM application_metadata WHERE key='bootstrap_version'").fetchone()
        if version != (str(SCHEMA_VERSION),):
            raise BootstrapError("Unsupported database bootstrap version; existing file was left unchanged")


def _validate_existing(path: Path) -> None:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        _validate_structure(connection)


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("BEGIN IMMEDIATE")
    try:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        connection.execute(METADATA_SQL)
        metadata = {
            "bootstrap_version": str(SCHEMA_VERSION),
            "base_schema_sha256": BASE_SCHEMA_SHA256,
            "occurrence_storage_version": "1",
            "occurrence_identity_versions": "[1,2]",
            "source_namespace": str(uuid4()),
        }
        connection.executemany("INSERT INTO application_metadata(key,value) VALUES (?,?)", metadata.items())
        _validate_structure(connection)
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise BootstrapError("New database failed quick_check")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise BootstrapError("New database failed foreign_key_check")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _publish_new(temporary: Path, destination: Path) -> None:
    # Windows rename fails if the destination exists. POSIX rename would overwrite;
    # a same-directory hard link provides atomic, exclusive publication there.
    if os.name == "nt":
        os.rename(temporary, destination)
    else:
        os.link(temporary, destination)


def ensure_database(path) -> BootstrapResult:
    """Validate existing files read-only, or atomically publish a fully checked empty DB."""
    destination = Path(path).expanduser().resolve()
    temporary = None
    try:
        if destination.exists():
            _validate_existing(destination)
            return BootstrapResult(destination, False)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".chesswizard-bootstrap-", suffix=".db",
                                         dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
        with closing(sqlite3.connect(temporary)) as connection:
            _initialize(connection)
        try:
            _publish_new(temporary, destination)
        except FileExistsError:
            # Another launcher won the race. Its completed DB is never replaced.
            _validate_existing(destination)
            return BootstrapResult(destination, False)
        return BootstrapResult(destination, True)
    except (OSError, sqlite3.Error, BootstrapError) as error:
        raise BootstrapError(f"Cannot open ChessWizard database at {destination}: {error}. "
                             "Existing databases were not changed.") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
