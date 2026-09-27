"""Bounded data-only .cwbook inspection and clean single-book serialization.

Imported SQLite DDL is never executed. Only validated authoring rows are copied
into our schema; free pages, extra objects and unrelated books cannot hitchhike.
"""
from contextlib import closing
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import chess
from theme_core.assets import reject_links
from opening_book_schema import APPLICATION_ID, SCHEMA, SCHEMA_VERSION
from opening_book_repository import OpeningBookRepository
from opening_book_models import (BookSnapshot, BookDetails, MoveDetails, SourceDetails,
                                 position_identity, text, json_metadata)

MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_ROWS = 100_000
MAX_BOOKS = 100
MAX_TEXT_BYTES = 65_536
MAX_SQL_STEPS = 20_000_000
TABLES = ('positions', 'books', 'book_positions', 'book_moves', 'source_references')


@dataclass(frozen=True)
class BookImportPreview:
    filename: str
    file_sha256: str
    schema_version: int
    books: tuple[BookSnapshot, ...]


def semantic_identity(snapshot: BookSnapshot) -> str:
    """Ignore SQLite row IDs/revision clocks; retain all authored content and metadata."""
    positions = {p.position_id: p.canonical_fen for p in snapshot.positions}
    moves = {m.move_id: (positions[m.from_position_id], m.move_uci) for m in snapshot.moves}
    book = asdict(snapshot.book)
    for key in ('book_id','revision','created_at','updated_at','root_position_id'):
        book.pop(key)
    book['root'] = positions[snapshot.book.root_position_id]
    book['metadata_json']=json.loads(book['metadata_json'])
    def clean(row, excluded):
        return {k:(json.loads(v) if k=='metadata_json' else v) for k,v in asdict(row).items() if k not in excluded}
    payload = dict(book=book,
        positions=[clean(p, ('position_id',)) for p in snapshot.positions],
        moves=[dict(clean(m, ('move_id','book_id','from_position_id','to_position_id')),
                    source=positions[m.from_position_id],target=positions[m.to_position_id]) for m in snapshot.moves],
        sources=[dict(clean(s, ('source_ref_id','book_id','position_id','move_id')),
                      position=positions[s.position_id],move=moves.get(s.move_id)) for s in snapshot.sources])
    for key in ('positions','moves','sources'):
        payload[key].sort(key=lambda row: json.dumps(row,sort_keys=True))
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def validate_snapshot(snapshot: BookSnapshot) -> None:
    """Validate portable graph fields, references and optional entry metadata.

    Args:
        snapshot: Authored library book being read or serialized.

    Raises:
        ValueError: Content, legality, references or entry anchors are inconsistent.
    """
    from opening_entry import OpeningEntryContract
    OpeningEntryContract.from_snapshot(snapshot)
    book = snapshot.book
    BookDetails(**{k:getattr(book,k) for k in BookDetails.__dataclass_fields__})
    if book.revision < 1:
        raise ValueError('Invalid book revision.')
    positions = {p.position_id:p for p in snapshot.positions}
    if book.root_position_id not in positions:
        raise ValueError('Missing book root.')
    for p in snapshot.positions:
        if position_identity(p.canonical_fen) != position_identity_fields(p):
            raise ValueError('Invalid canonical position identity.')
        text(p.position_note,'Position note'); json_metadata(p.metadata_json)
    preferred, edges = set(), set()
    for m in snapshot.moves:
        MoveDetails(**{k:getattr(m,k) for k in MoveDetails.__dataclass_fields__})
        if m.book_id != book.book_id or m.from_position_id not in positions or m.to_position_id not in positions:
            raise ValueError('Move references a different book or missing position.')
        board=chess.Board(positions[m.from_position_id].canonical_fen)
        move=board.parse_uci(m.move_uci)
        if not move or move not in board.legal_moves or board.san(move)!=m.san:
            raise ValueError('Invalid move or SAN.')
        board.push(move)
        if position_identity(board).canonical_fen != positions[m.to_position_id].canonical_fen:
            raise ValueError('Invalid branch/transposition target.')
        if (m.from_position_id,m.move_uci) in edges:
            raise ValueError('Duplicate branch.')
        edges.add((m.from_position_id,m.move_uci))
        if m.preferred:
            if m.from_position_id in preferred: raise ValueError('Multiple preferred moves.')
            preferred.add(m.from_position_id)
    moves={m.move_id:m for m in snapshot.moves}
    for s in snapshot.sources:
        SourceDetails(**{k:getattr(s,k) for k in SourceDetails.__dataclass_fields__})
        if s.book_id!=book.book_id or s.position_id not in positions:
            raise ValueError('Invalid source reference.')
        if s.move_id is not None and (s.move_id not in moves or moves[s.move_id].from_position_id!=s.position_id):
            raise ValueError('Invalid move source reference.')
    # Disconnected authored remnants are allowed: Studio deliberately retains them.
    # Every edge is nevertheless legal; cycles and shared targets are valid graphs.


def position_identity_fields(position):
    from opening_book_models import PositionIdentity
    return PositionIdentity(position.canonical_fen,position.polyglot_key,position.side_to_move)


def inspect_package(path, *, allow_empty=False) -> BookImportPreview:
    path=Path(path).absolute()
    if '..' in path.parts or path.suffix.lower()!='.cwbook':
        raise ValueError('Choose a .cwbook file without parent traversal.')
    reject_links(path)
    if not path.is_file() or path.stat().st_size>MAX_PACKAGE_BYTES:
        raise ValueError('Opening packages must be regular files at most 64 MiB.')
    # A portable export is a single committed SQLite file, never an active WAL.
    if any(Path(str(path)+suffix).exists() for suffix in ('-wal','-journal')):
        raise ValueError('Close the authoring file and export a committed .cwbook first.')
    with path.open('rb') as stream: data=stream.read(MAX_PACKAGE_BYTES+1)
    if len(data)>MAX_PACKAGE_BYTES or not data.startswith(b'SQLite format 3\x00'):
        raise ValueError('Not a bounded SQLite opening package.')
    try:
        with closing(sqlite3.connect(':memory:')) as db:
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,MAX_TEXT_BYTES*16)
            db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH,MAX_TEXT_BYTES*2)
            db.deserialize(data)
            db.enable_load_extension(False)
            db.execute('PRAGMA trusted_schema=OFF');db.execute('PRAGMA query_only=ON')
            steps=0
            def budget():
                nonlocal steps
                steps+=1000
                return int(steps>MAX_SQL_STEPS)
            db.set_progress_handler(budget,1000)
            version=db.execute('PRAGMA user_version').fetchone()[0]
            if db.execute('PRAGMA application_id').fetchone()[0]!=APPLICATION_ID or version not in (1,SCHEMA_VERSION):
                raise ValueError('Unsupported opening package/schema.')
            objects=db.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
            if {(kind,name) for kind,name,_ in objects}!={*(('table',t) for t in TABLES),('index','one_preferred_branch')}:
                raise ValueError('Extra tables, views, triggers or executable schema are not allowed.')
            if any('virtual' in sql.lower() or 'generated' in sql.lower() for _,_,sql in objects):
                raise ValueError('Executable/virtual schema is not allowed.')
            with closing(sqlite3.connect(':memory:')) as expected:
                for statement in SCHEMA:expected.execute(statement)
                for table in TABLES:
                    actual_columns=[r[1:] for r in db.execute(f'PRAGMA table_xinfo({table})')]
                    wanted_columns=[r[1:] for r in expected.execute(f'PRAGMA table_xinfo({table})')]
                    if version==1 and table=='book_moves':wanted_columns=wanted_columns[:-2]
                    if actual_columns!=wanted_columns:raise ValueError('Unsupported column constraints.')
                    if db.execute(f'PRAGMA foreign_key_list({table})').fetchall()!=expected.execute(f'PRAGMA foreign_key_list({table})').fetchall():
                        raise ValueError('Missing or changed reference constraints.')
                    cols=[r[:2] for r in actual_columns]
                    want=[r[:2] for r in wanted_columns]
                    if cols!=want:raise ValueError('Unsupported column layout.')
                    count=db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                    if count>(MAX_BOOKS if table=='books' else MAX_ROWS):raise ValueError('Package row limit exceeded.')
                    for row in db.execute(f'SELECT * FROM {table}'):
                        for (name,kind),value in zip(cols,row):
                            if value is None and name=='move_id' and table=='source_references':continue
                            if kind=='INTEGER' and type(value) is not int:raise ValueError('Invalid integer field.')
                            if kind=='TEXT':
                                if not isinstance(value,str) or len(value.encode('utf-8'))>MAX_TEXT_BYTES or '\x00' in value:
                                    raise ValueError('Invalid/bounded UTF-8 text required; binary payloads are forbidden.')
                            if name in ('preferred','active') and value not in (0,1):raise ValueError('Invalid Boolean.')
                            if name.endswith('_id') and value<1:raise ValueError('Invalid row reference.')
            if db.execute('PRAGMA quick_check').fetchall()!=[('ok',)] or db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Opening package integrity failed.')
            repo=OpeningBookRepository(db,path)
            books=tuple(repo.snapshot(b.book_id) for b in repo.books())
            if not books and not allow_empty:raise ValueError('No books in package.')
            for snapshot in books:validate_snapshot(snapshot)
        return BookImportPreview(path.name,hashlib.sha256(data).hexdigest(),version,books)
    except (sqlite3.Error,UnicodeError,TypeError,KeyError,StopIteration,RecursionError) as error:
        raise ValueError('Malformed or unsupported opening package.') from error


def write_package(snapshot: BookSnapshot, destination):
    """Exclusive clean single-book export; authoring IDs and fields are preserved."""
    return write_library_package((snapshot,),destination)


def write_library_package(snapshots, destination):
    """Clean whole-library serialization preserves shared positions and book boundaries."""
    snapshots=tuple(snapshots)
    for snapshot in snapshots:validate_snapshot(snapshot)
    destination=Path(destination).absolute();reject_links(destination)
    if '..' in destination.parts:raise ValueError('Parent traversal is not supported.')
    repo=OpeningBookRepository.create(destination)
    try:
        db=repo.connection
        def insert(table,row):
            columns=tuple(row)
            db.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",tuple(row.values()))
        with db:
            seen={}
            for snapshot in snapshots:
                for p in snapshot.positions:
                    row={k:v for k,v in asdict(p).items() if k not in ('position_note','metadata_json')}
                    if p.position_id in seen:
                        if seen[p.position_id]!=row:raise ValueError('Conflicting library position identity.')
                    else:insert('positions',row);seen[p.position_id]=row
            for snapshot in snapshots:
                insert('books',asdict(snapshot.book))
                for p in snapshot.positions:
                    insert('book_positions',dict(book_id=snapshot.book.book_id,position_id=p.position_id,position_note=p.position_note,metadata_json=p.metadata_json))
                for m in snapshot.moves:insert('book_moves',asdict(m))
                for source in snapshot.sources:insert('source_references',asdict(source))
    except BaseException:
        repo.close();destination.unlink();raise
    else:repo.close()
