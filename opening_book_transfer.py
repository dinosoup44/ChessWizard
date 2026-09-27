"""Transactional graph copying into an existing library, preserving existing IDs."""
from dataclasses import asdict
from opening_book_models import position_identity
from opening_library_package import validate_snapshot


def append_books(repository, snapshots):
    """Allocate new local IDs; preserve graph sharing, metadata and source ownership.

    The source is immutable. Existing destination rows are never updated; all
    selected books commit together or roll back. No imported SQL is executed.
    """
    repository.require_writable()
    snapshots = tuple(snapshots)
    for snapshot in snapshots:validate_snapshot(snapshot)
    db = repository.connection
    def insert(table, values):
        columns = tuple(values)
        return db.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                          tuple(values.values())).lastrowid
    ids = []
    with db:
        db.execute("BEGIN IMMEDIATE")
        for snapshot in snapshots:
            positions = {p.position_id:repository._position(position_identity(p.canonical_fen)) for p in snapshot.positions}
            book = asdict(snapshot.book); book.pop("book_id")
            book["root_position_id"] = positions[snapshot.book.root_position_id]
            bid = insert("books", book); ids.append(bid)
            for p in snapshot.positions:
                insert("book_positions", dict(book_id=bid, position_id=positions[p.position_id],
                    position_note=p.position_note, metadata_json=p.metadata_json))
            moves = {}
            for m in snapshot.moves:
                row = asdict(m); row.pop("move_id")
                row.update(book_id=bid, from_position_id=positions[m.from_position_id], to_position_id=positions[m.to_position_id])
                moves[m.move_id] = insert("book_moves", row)
            for source in snapshot.sources:
                row = asdict(source); row.pop("source_ref_id")
                row.update(book_id=bid, position_id=positions[source.position_id], move_id=moves.get(source.move_id))
                insert("source_references", row)
    return tuple(ids)
