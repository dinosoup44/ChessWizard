"""Reusable legal authoring and finite graph browsing; no Tk or engine access."""
from dataclasses import dataclass
import chess
from opening_repertoire import RepertoireSide, with_repertoire_side
from opening_book_models import (BookDetails, MoveDetails, position_identity, standard_board)


@dataclass(frozen=True)
class BrowserEntry:
    path: tuple[int, ...]
    parent_path: tuple[int, ...]
    position_id: int
    label: str
    reference: bool


def branch_browser(snapshot, *, compact=False):
    """Expand each position once; transpositions and cycles remain navigable references."""
    root = snapshot.book.root_position_id
    seen, entries = {root}, []
    board = chess.Board(snapshot.position(root).canonical_fen)
    stack = [((), board, iter(snapshot.branches(root)))]
    while stack:
        parent, board, children = stack[-1]
        edge = next(children, None)
        if edge is None:
            stack.pop()
            continue
        move = board.parse_uci(edge.move_uci)
        label = f"{board.fullmove_number}{'.' if board.turn else '…'} {board.san(move)}"
        label = (f"{edge.variation_name} — {label}" if edge.variation_name else label)
        label += (" ★ preferred" if edge.preferred else "") + ("" if edge.active else " [disabled]")
        path = (*parent, edge.move_id)
        reference = edge.to_position_id in seen
        if reference:
            label += " ↪ shared position"
        entries.append(BrowserEntry(path, parent, edge.to_position_id, label, reference))
        if not reference:
            seen.add(edge.to_position_id)
            after = board.copy()
            after.push(move)
            stack.append((path, after, iter(snapshot.branches(edge.to_position_id))))
    if not compact:
        return tuple(entries)
    # Collapse unnamed single-child runs, but never hide a named navigation anchor.
    children = {}
    for entry in entries:
        children.setdefault(entry.parent_path, []).append(entry)
    by_id = {m.move_id: m for m in snapshot.moves}
    result, pending = [], [(e, ()) for e in reversed(children.get((), ()))]
    while pending:
        entry, parent = pending.pop()
        label = entry.label
        while not entry.reference and not by_id[entry.path[-1]].variation_name:
            following = children.get(entry.path, ())
            if len(following) != 1 or by_id[following[0].path[-1]].variation_name:
                break
            entry = following[0]
            label += " " + entry.label
        result.append(BrowserEntry(entry.path, parent, entry.position_id, label, entry.reference))
        pending.extend((child, entry.path) for child in reversed(children.get(entry.path, ())))
    return tuple(result)


class OpeningBookService:
    def __init__(self, repository):
        self.repository = repository

    def create_book(self, details: BookDetails, root_fen=chess.STARTING_FEN):
        return self.repository.create_book(details, position_identity(root_fen))

    def set_repertoire_side(self, book_id: int, side: RepertoireSide | str) -> None:
        """Set explicit book intent through the existing ID-preserving author repository.

        Args:
            book_id: Library-local book identifier.
            side: White, Black or Both/reference; never inferred from the name.

        Raises:
            ValueError: The side is invalid or the book does not exist.
            sqlite3.Error: The authoring repository cannot write the library.
        """
        book = self.repository.snapshot(book_id).book
        metadata = with_repertoire_side(book.metadata_json, side)
        if metadata == book.metadata_json:
            return
        self.repository.update_book(book_id, BookDetails(book.name, book.description,
            book.version, book.status, metadata))

    def save_move(self, book_id, from_fen, move_uci, details=MoveDetails()):
        board = standard_board(from_fen)
        move = board.parse_uci(move_uci)
        if not move or move not in board.legal_moves:
            raise ValueError("Save a legal chess move, not a null move.")
        identity = position_identity(board)
        snapshot = self.repository.snapshot(book_id)
        position = next((p for p in snapshot.positions if p.canonical_fen == identity.canonical_fen), None)
        if position is None:
            raise ValueError("Position is not part of this book.")
        san = board.san(move)
        board.push(move)
        return self.repository.save_branch(book_id, position.position_id, move.uci(), san,
                                           position_identity(board), details)

    def edit_move(self, book_id, move_id, details):
        snapshot = self.repository.snapshot(book_id)
        edge = next((m for m in snapshot.moves if m.move_id == move_id), None)
        if edge is None:
            raise ValueError("Branch no longer exists.")
        return self.save_move(book_id, snapshot.position(edge.from_position_id).canonical_fen, edge.move_uci, details)


    def preview_deletion(self, book_id, move_id, *, subtree=False):
        from opening_book_deletion import deletion_plan
        return deletion_plan(self.repository.snapshot(book_id), move_id, subtree=subtree)

    def delete(self, plan):
        self.repository.apply_deletion(plan)
