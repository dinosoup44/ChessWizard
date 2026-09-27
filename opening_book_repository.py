"""Transactional authoring persistence in an explicitly created separate library."""
from dataclasses import asdict
from opening_book_line import BookLinePlan, plan_book_line
from pathlib import Path
import sqlite3
from opening_book_schema import APPLICATION_ID, SCHEMA_VERSION, SCHEMA
from opening_book_models import (OpeningBook, OpeningPosition, OpeningMove, SourceReference,
                                 BookSnapshot, json_metadata, text)


READ_ONLY_LIBRARY_MESSAGE = (
    "This library is read-only. Open or copy it into My ChessWizard Library to edit it."
)


class ReadOnlyLibraryError(sqlite3.OperationalError):
    """Authoring was requested on an explicitly read-only library handle."""


class OpeningBookRepository:
    def __init__(self, connection, path, *, read_only=False):
        self.connection, self.path = connection, Path(path)
        self.read_only = read_only
        connection.row_factory = sqlite3.Row

    @classmethod
    def in_memory(cls):
        """Unsaved Studio drafts share authoring contracts without touching a file."""
        db = sqlite3.connect(":memory:")
        db.execute("PRAGMA foreign_keys=ON")
        for statement in SCHEMA:db.execute(statement)
        return cls(db, ":memory:")

    @classmethod
    def create(cls, path):
        """Exclusive creation: existing libraries or production files are never overwritten."""
        path = Path(path).resolve()
        if path.suffix.lower() != ".cwbook":
            raise ValueError("Choose a separate .cwbook authoring file.")
        with path.open("xb"):
            pass
        db = None
        try:
            db = sqlite3.connect(path.as_uri()+"?mode=rw", uri=True)
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            for statement in SCHEMA:
                db.execute(statement)
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            db.commit()
            return cls(db, path)
        except BaseException:
            if db is not None:
                db.close()
            path.unlink()
            raise

    @classmethod
    def open(cls, path):
        path = Path(path).resolve()
        # Only an explicitly opened authoring library may receive the additive upgrade.
        db = sqlite3.connect(path.as_uri()+"?mode=ro", uri=True)
        try:
            if db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID or db.execute("PRAGMA user_version").fetchone()[0] not in (1, SCHEMA_VERSION):
                raise ValueError("Not a supported ChessWizard opening library. No migration was attempted.")
            if db.execute("PRAGMA quick_check").fetchall() != [("ok",)] or db.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Opening library integrity check failed.")
            expected = {"books", "positions", "book_positions", "book_moves", "source_references"}
            found = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if found != expected:
                raise ValueError("Unexpected authoring schema.")
        finally:
            db.close()
        db = sqlite3.connect(path.as_uri()+"?mode=rw", uri=True)
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("PRAGMA user_version").fetchone()[0] == 1:
                    for name in ("variation_name", "variation_description"):
                        db.execute(f"ALTER TABLE book_moves ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
                    db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                columns = {row[1]: row for row in db.execute("PRAGMA table_info(book_moves)")}
                for name in ("variation_name", "variation_description"):
                    if name not in columns or columns[name][2:5] != ("TEXT", 1, "''"):
                        raise ValueError("Invalid variation metadata schema.")
                if db.execute("PRAGMA quick_check").fetchall() != [("ok",)] or db.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("Opening library upgrade integrity check failed.")
        except BaseException:
            db.close()
            raise
        return cls(db, path)

    def require_writable(self):
        """Reject preview mutations before issuing any SQL; never upgrade a preview."""
        if self.read_only:
            raise ReadOnlyLibraryError(READ_ONLY_LIBRARY_MESSAGE)

    def close(self):
        self.connection.close()

    def books(self):
        return tuple(OpeningBook(**dict(row)) for row in self.connection.execute("SELECT * FROM books ORDER BY book_id"))

    def _position(self, identity):
        self.connection.execute("INSERT INTO positions(canonical_fen,polyglot_key,side_to_move) VALUES(?,?,?) ON CONFLICT(canonical_fen) DO NOTHING",
                                tuple(asdict(identity).values()))
        return self.connection.execute("SELECT position_id FROM positions WHERE canonical_fen=?", (identity.canonical_fen,)).fetchone()[0]

    def _touch(self, book_id):
        self.connection.execute("UPDATE books SET revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE book_id=?", (book_id,))

    def create_book(self, details, root):
        self.require_writable()
        with self.connection:
            root_id = self._position(root)
            cursor = self.connection.execute("INSERT INTO books(root_position_id,name,description,version,status,metadata_json) VALUES(?,?,?,?,?,?)",
                (root_id, *asdict(details).values()))
            book_id = cursor.lastrowid
            self.connection.execute("INSERT INTO book_positions(book_id,position_id) VALUES(?,?)", (book_id, root_id))
        return book_id

    def update_book(self, book_id, details):
        self.require_writable()
        with self.connection:
            cursor = self.connection.execute("UPDATE books SET name=?,description=?,version=?,status=?,metadata_json=? WHERE book_id=?",
                                    (*asdict(details).values(), book_id))
            if not cursor.rowcount:
                raise ValueError("Book not found.")
            self._touch(book_id)

    def library_snapshot(self):
        """Read every book at one committed library revision, including empty libraries."""
        with self.connection:
            self.connection.execute("BEGIN")
            return tuple(self._snapshot(book.book_id) for book in self.books())

    def snapshot(self, book_id):
        # One coherent revision for exports/application even if another editor is open.
        with self.connection:
            self.connection.execute("BEGIN")
            return self._snapshot(book_id)

    def _snapshot(self, book_id):
        row = self.connection.execute("SELECT * FROM books WHERE book_id=?", (book_id,)).fetchone()
        if row is None:
            raise ValueError("Book not found.")
        positions = tuple(OpeningPosition(**dict(r)) for r in self.connection.execute(
            "SELECT p.*,bp.position_note,bp.metadata_json FROM positions p JOIN book_positions bp USING(position_id) WHERE bp.book_id=? ORDER BY p.position_id", (book_id,)))
        moves = tuple(OpeningMove(**{**dict(r), "preferred":bool(r["preferred"]), "active":bool(r["active"])})
                      for r in self.connection.execute("SELECT * FROM book_moves WHERE book_id=? ORDER BY move_id", (book_id,)))
        sources = tuple(SourceReference(**dict(r)) for r in self.connection.execute("SELECT * FROM source_references WHERE book_id=? ORDER BY source_ref_id", (book_id,)))
        return BookSnapshot(OpeningBook(**dict(row)), positions, moves, sources)

    def save_branch(self, book_id, from_id, uci, san, target, details):
        self.require_writable()
        with self.connection:
            if not self.connection.execute("SELECT 1 FROM book_positions WHERE book_id=? AND position_id=?", (book_id, from_id)).fetchone():
                raise ValueError("Source position is not in this book.")
            target_id = self._position(target)
            self.connection.execute("INSERT INTO book_positions(book_id,position_id) VALUES(?,?) ON CONFLICT DO NOTHING", (book_id, target_id))
            if details.preferred:
                self.connection.execute("UPDATE book_moves SET preferred=0 WHERE book_id=? AND from_position_id=?", (book_id, from_id))
            self.connection.execute(
                "INSERT INTO book_moves(book_id,from_position_id,move_uci,san,to_position_id,weight,preferred,active,move_note,instructional_note,metadata_json,variation_name,variation_description) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(book_id,from_position_id,move_uci) DO UPDATE SET "
                "weight=excluded.weight,preferred=excluded.preferred,active=excluded.active,move_note=excluded.move_note,"
                "instructional_note=excluded.instructional_note,metadata_json=excluded.metadata_json,"
                "variation_name=excluded.variation_name,variation_description=excluded.variation_description",
                (book_id, from_id, uci, san, target_id, *asdict(details).values()))
            move_id = self.connection.execute("SELECT move_id FROM book_moves WHERE book_id=? AND from_position_id=? AND move_uci=?", (book_id, from_id, uci)).fetchone()[0]
            self._touch(book_id)
        return move_id

    def apply_line(self, plan: BookLinePlan) -> tuple[int, ...]:
        """Atomically insert only the confirmed missing edges of a full continuation.

        Args:
            plan: Frozen legal authoring plan confirmed by the caller.

        Returns:
            Stable move IDs for every ply, reusing existing edges and transpositions.

        Raises:
            ReadOnlyLibraryError: The library is intentionally read-only.
            ValueError: Book contents changed after preview or the plan is inconsistent.
            sqlite3.Error: An insert fails; the whole operation rolls back.
        """
        self.require_writable()
        db = self.connection
        with db:
            db.execute('BEGIN IMMEDIATE')
            current = self._snapshot(plan.book_id)
            expected = plan_book_line(current, plan.anchor_position_id, plan.fen, plan.moves,
                variation_name=plan.variation_name, provenance_json=plan.provenance_json)
            if expected != plan:
                raise ValueError('The book changed. Review a fresh Add as Variation preview.')
            ids = []
            for step in plan.steps:
                source_id = db.execute('SELECT position_id FROM positions WHERE canonical_fen=?',
                                       (step.source.canonical_fen,)).fetchone()[0]
                if step.create:
                    target_id = self._position(step.target)
                    db.execute('INSERT INTO book_positions(book_id,position_id) VALUES(?,?) ON CONFLICT DO NOTHING',
                               (plan.book_id, target_id))
                    db.execute('INSERT INTO book_moves(book_id,from_position_id,move_uci,san,to_position_id,'
                        'weight,preferred,active,move_note,instructional_note,metadata_json,variation_name,variation_description) '
                        'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (plan.book_id, source_id, step.uci, step.san, target_id, *asdict(step.details).values()))
                row = db.execute('SELECT move_id FROM book_moves WHERE book_id=? AND from_position_id=? AND move_uci=?',
                                 (plan.book_id, source_id, step.uci)).fetchone()
                ids.append(row[0])
            if plan.new_edges:
                self._touch(plan.book_id)
            return tuple(ids)

    def set_position_note(self, book_id, position_id, note, metadata_json="{}"):
        self.require_writable()
        text(note, "Position note")
        metadata_json = json_metadata(metadata_json)
        with self.connection:
            if not self.connection.execute("UPDATE book_positions SET position_note=?,metadata_json=? WHERE book_id=? AND position_id=?",
                (note, metadata_json, book_id, position_id)).rowcount:
                raise ValueError("Position not found in book.")
            self._touch(book_id)

    def delete_branch(self, book_id, move_id):
        """Delete only this edge and its move sources; shared descendants remain intact."""
        self.require_writable()
        with self.connection:
            if not self.connection.execute("DELETE FROM book_moves WHERE book_id=? AND move_id=?", (book_id, move_id)).rowcount:
                raise ValueError("Branch not found.")
            self._touch(book_id)

    def apply_deletion(self, plan):
        """Apply exactly the previewed graph change or reject a stale confirmation."""
        self.require_writable()
        from opening_book_deletion import deletion_plan
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            current = self._snapshot(plan.book_id)
            if deletion_plan(current, plan.selected_move_id, subtree=plan.subtree) != plan:
                raise ValueError("The book changed. Review a fresh deletion preview.")
            for source_id in plan.source_ids:
                self.connection.execute("DELETE FROM source_references WHERE book_id=? AND source_ref_id=?", (plan.book_id, source_id))
            for move_id in plan.move_ids:
                self.connection.execute("DELETE FROM book_moves WHERE book_id=? AND move_id=?", (plan.book_id, move_id))
            for position_id in plan.position_ids:
                self.connection.execute("DELETE FROM book_positions WHERE book_id=? AND position_id=?", (plan.book_id, position_id))
                self.connection.execute("DELETE FROM positions WHERE position_id=? AND NOT EXISTS (SELECT 1 FROM book_positions WHERE position_id=?) AND NOT EXISTS (SELECT 1 FROM books WHERE root_position_id=?)", (position_id, position_id, position_id))
            self._touch(plan.book_id)

    def save_source(self, book_id, position_id, move_id, details, source_ref_id=None):
        self.require_writable()
        with self.connection:
            if move_id is not None and not self.connection.execute("SELECT 1 FROM book_moves WHERE book_id=? AND move_id=? AND from_position_id=?", (book_id, move_id, position_id)).fetchone():
                raise ValueError("Source must refer to this book's move at this position.")
            if source_ref_id is None:
                cursor = self.connection.execute("INSERT INTO source_references(book_id,position_id,move_id,title,author,edition,chapter,page,private_note) VALUES(?,?,?,?,?,?,?,?,?)",
                                                (book_id, position_id, move_id, *asdict(details).values()))
                source_ref_id = cursor.lastrowid
            else:
                if not self.connection.execute("UPDATE source_references SET title=?,author=?,edition=?,chapter=?,page=?,private_note=? WHERE source_ref_id=? AND book_id=? AND position_id=? AND move_id IS ?",
                    (*asdict(details).values(), source_ref_id, book_id, position_id, move_id)).rowcount:
                    raise ValueError("Source reference not found at this location.")
            self._touch(book_id)
        return source_ref_id

    def delete_source(self, book_id, source_ref_id):
        self.require_writable()
        with self.connection:
            if not self.connection.execute("DELETE FROM source_references WHERE book_id=? AND source_ref_id=?", (book_id, source_ref_id)).rowcount:
                raise ValueError("Source reference not found.")
            self._touch(book_id)

