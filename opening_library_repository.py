"""Lazy profile catalog; filenames are generated identities, never imported metadata."""
from contextlib import contextmanager, closing
from pathlib import Path
import sqlite3
import uuid
from application_paths import application_data_directory
from theme_core.assets import reject_links

CATALOG_SCHEMA = """CREATE TABLE IF NOT EXISTS installed_books (
    installation_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    is_primary INTEGER NOT NULL CHECK(is_primary IN (0,1)), origin TEXT NOT NULL,
    provenance_json TEXT NOT NULL)"""


class OpeningLibraryRepository:
    def __init__(self, root=None):
        self.root=Path(root) if root is not None else application_data_directory()/'opening_books'
        self.root=self.root.absolute()
        if '..' in self.root.parts:raise ValueError('Invalid managed root.')
        reject_links(self.root)
        self.catalog=self.root/'catalog.sqlite'

    def path(self, installation_id):
        if str(uuid.UUID(installation_id))!=installation_id:raise ValueError('Invalid installation identity.')
        path=self.root/(installation_id+'.cwbook');reject_links(path)
        return path

    def rows(self):
        reject_links(self.catalog)
        if not self.catalog.exists():return ()
        with closing(sqlite3.connect(self.catalog.as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
            return tuple(dict(r) for r in db.execute('SELECT * FROM installed_books ORDER BY installation_id'))

    @contextmanager
    def write(self):
        reject_links(self.root);reject_links(self.catalog)
        self.root.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.catalog)) as db:
            with db:
                db.execute('BEGIN IMMEDIATE')
                db.execute(CATALOG_SCHEMA)
                db.execute('CREATE UNIQUE INDEX IF NOT EXISTS one_primary_book ON installed_books(is_primary) WHERE is_primary=1')
                db.execute("""CREATE TABLE IF NOT EXISTS removed_books (
                    installation_id TEXT PRIMARY KEY, provenance_json TEXT NOT NULL,
                    origin TEXT NOT NULL, removed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
                yield db
