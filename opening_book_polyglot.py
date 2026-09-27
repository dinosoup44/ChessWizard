"""Deterministic active-graph export; python-chess independently decodes every entry."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
import chess
import chess.polyglot
from opening_book_models import BookSnapshot, MIN_WEIGHT, MAX_WEIGHT, position_identity

ENTRY = struct.Struct(">QHHI")


@dataclass(frozen=True)
class PolyglotReceipt:
    path: str
    entry_count: int
    position_count: int
    byte_count: int
    sha256: str
    book_id: int
    book_version: str
    book_revision: int
    snapshot_identity: str


def polyglot_weight(weight):
    """Identity mapping 1–100; editorial preference, never an engine evaluation."""
    if type(weight) is not int or not MIN_WEIGHT <= weight <= MAX_WEIGHT:
        raise ValueError("Authoring weight must be 1–100.")
    return weight


def encode_move(board, move):
    if move not in board.legal_moves:
        raise ValueError("Cannot export an illegal move.")
    target = move.to_square
    if board.is_castling(move):
        target = chess.square(7 if board.is_kingside_castling(move) else 0, chess.square_rank(move.from_square))
    return target | (move.from_square << 6) | (((move.promotion-1) if move.promotion else 0) << 12)


def export_entries(snapshot):
    reachable = snapshot.reachable()
    positions = {p.position_id:p for p in snapshot.positions}
    keys, entries = {}, {}
    for edge in snapshot.moves:
        if not edge.active or edge.from_position_id not in reachable:
            continue
        position = positions[edge.from_position_id]
        identity = position_identity(position.canonical_fen)
        if identity.polyglot_key != position.polyglot_key:
            raise ValueError("Stored Polyglot key does not match the position.")
        key = int(identity.polyglot_key, 16)
        if key in keys and keys[key] != identity.canonical_fen:
            raise ValueError("Polyglot hash collision between distinct positions.")
        keys[key] = identity.canonical_fen
        board = chess.Board(identity.canonical_fen)
        move = board.parse_uci(edge.move_uci)
        after = board.copy(); after.push(move)
        if position_identity(after).canonical_fen != positions[edge.to_position_id].canonical_fen:
            raise ValueError("Branch destination does not match its legal move.")
        raw = encode_move(board, move)
        if (key, raw) in entries:
            raise ValueError("Duplicate equivalent book entry.")
        entries[key, raw] = (polyglot_weight(edge.weight), 0)
    return tuple((key, move, *entries[key, move]) for key, move in sorted(entries))


def verify_polyglot(path, snapshot):
    """Read through an independent reader, including castling/promotion legality."""
    expected = export_entries(snapshot)
    path = Path(path)
    if path.stat().st_size != len(expected)*ENTRY.size:
        raise ValueError("Polyglot size does not match the snapshot.")
    with chess.polyglot.open_reader(str(path)) as reader:
        actual = tuple((e.key,e.raw_move,e.weight,e.learn) for e in reader)
        if actual != expected:
            raise ValueError("Polyglot entries differ from the authored graph.")
        for position_id in snapshot.reachable():
            edges = snapshot.branches(position_id, active_only=True)
            if not edges:
                continue
            board = chess.Board(snapshot.position(position_id).canonical_fen)
            decoded = {(e.move.uci(),e.weight) for e in reader.find_all(board)}
            if decoded != {(e.move_uci, e.weight) for e in edges}:
                raise ValueError("Decoded legal branches/weights do not match.")
    return expected


def export_polyglot(snapshot, path):
    """Never overwrite an existing file; remove only our incomplete new export on failure."""
    path = Path(path)
    if path.suffix.lower() != ".bin":
        raise ValueError("Choose a .bin export filename.")
    entries = export_entries(snapshot)
    data = b"".join(ENTRY.pack(*entry) for entry in entries)
    with path.open("xb") as stream:
        try:
            stream.write(data)
        except BaseException:
            stream.close()
            path.unlink()
            raise
    try:
        verify_polyglot(path, snapshot)
    except BaseException:
        path.unlink()
        raise
    return PolyglotReceipt(str(path), len(entries),len({e[0] for e in entries}),len(data),
        hashlib.sha256(data).hexdigest(),snapshot.book.book_id,snapshot.book.version,
        snapshot.book.revision,snapshot.identity)



def export_library_polyglot(snapshots: tuple[BookSnapshot, ...], path: str | Path) -> dict:
    """Export a library union without summing weights or fabricating preferences.

    Args:
        snapshots: Validated authored books sharing one logical library.
        path: New companion .bin file outside managed authoring storage.

    Returns:
        Entry count, file size and exact output hash.

    Raises:
        ValueError: Equivalent edges disagree, hashes collide or decoding fails.
        FileExistsError: Destination already exists.
    """
    path = Path(path)
    if path.suffix.lower() != '.bin':
        raise ValueError('Choose a .bin export filename.')
    combined, positions = {}, {}
    for snapshot in snapshots:
        for p in snapshot.positions:
            key = int(p.polyglot_key, 16)
            if key in positions and positions[key] != p.canonical_fen:
                raise ValueError('Polyglot position hash collision.')
            positions[key] = p.canonical_fen
        for key, move, weight, learn in export_entries(snapshot):
            if (key, move) in combined and combined[key, move] != (weight, learn):
                raise ValueError('Conflicting cross-book weights; resolve before union export.')
            combined[key, move] = (weight, learn)
    expected = tuple((key, move, *combined[key, move]) for key, move in sorted(combined))
    data = b''.join(ENTRY.pack(*e) for e in expected)
    with path.open('xb') as stream:
        stream.write(data)
    try:
        with chess.polyglot.open_reader(str(path)) as reader:
            if tuple((e.key,e.raw_move,e.weight,e.learn) for e in reader) != expected:
                raise ValueError('Companion byte verification failed.')
            for key in {e[0] for e in expected}:
                board = chess.Board(positions[key])
                entries = tuple(reader.find_all(board))
                if len(entries) != sum(e[0] == key for e in expected) or any(e.move not in board.legal_moves for e in entries):
                    raise ValueError('Companion legal decoding failed.')
    except BaseException:
        path.unlink()
        raise
    return dict(entries=len(expected), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
