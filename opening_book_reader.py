"""Read selected authoring snapshots without upgrading or modifying their files."""
from contextlib import closing
from pathlib import Path
import sqlite3
from opening_book_schema import APPLICATION_ID, SCHEMA_VERSION
from opening_book_repository import OpeningBookRepository


def _connect(path):
    path=Path(path).resolve()
    db=sqlite3.connect(path.as_uri()+"?mode=ro",uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA application_id").fetchone()[0]!=APPLICATION_ID or db.execute("PRAGMA user_version").fetchone()[0] not in (1,SCHEMA_VERSION):
            raise ValueError("Not a supported opening library.")
        return db
    except BaseException:
        db.close();raise


def read_books(path):
    """List books without a write-capable authoring connection."""
    with closing(_connect(path)) as db:
        return OpeningBookRepository(db,path,read_only=True).books()


def read_book(path, book_id):
    """V1 rows use model defaults for unnamed variations; no migration is needed."""
    if type(book_id) is not int or book_id<=0:raise ValueError("Select a positive book ID.")
    with closing(_connect(path)) as db:
        return OpeningBookRepository(db,path,read_only=True).snapshot(book_id)


def read_library(path):
    """Read a coherent multi-book library without upgrades or writes."""
    with closing(_connect(path)) as db:
        return OpeningBookRepository(db,path,read_only=True).library_snapshot()


def open_readonly_library(path):
    """External Studio inspection must not silently upgrade or save an owner file."""
    return OpeningBookRepository(_connect(path),path,read_only=True)
