"""Pure graph-aware deletion previews, independent of UI and persistence."""
from dataclasses import dataclass
from opening_book_models import BookSnapshot


@dataclass(frozen=True)
class DeletionPlan:
    book_id: int
    snapshot_identity: str
    selected_move_id: int
    subtree: bool
    label: str
    move_ids: tuple[int, ...]
    position_ids: tuple[int, ...]
    source_ids: tuple[int, ...]
    note_count: int
    shared_position_count: int

    @property
    def downstream_move_count(self) -> int:
        return len(self.move_ids) - 1

    def summary(self) -> str:
        continuation = ("Only unshared continuation is removed." if self.subtree else
                        "Downstream theory stays stored; disconnected theory is excluded from export.")
        return (f'Delete "{self.label}"?\n\n1 selected move\n'
                f'{self.downstream_move_count} downstream moves\n{self.note_count} notes/descriptions\n'
                f'{len(self.source_ids)} source references\n\n'
                f'{self.shared_position_count} shared positions preserved.\n{continuation}')


def deletion_plan(snapshot: BookSnapshot, move_id: int, *, subtree: bool = False) -> DeletionPlan:
    """Preserve every external entry into a subtree, including disconnected theory.

    Root reachability alone is insufficient: a stored but disconnected branch can
    still own a transposition. All incoming references protect their continuation.
    """
    selected = next((m for m in snapshot.moves if m.move_id == move_id), None)
    if selected is None:
        raise ValueError("Move no longer exists.")
    outgoing = {}
    for move in snapshot.moves:
        outgoing.setdefault(move.from_position_id, []).append(move)

    def descendants(seeds):
        seen, pending = set(), list(seeds)
        while pending:
            position = pending.pop()
            if position in seen:
                continue
            seen.add(position)
            pending.extend(m.to_position_id for m in outgoing.get(position, ()) if m.move_id != move_id)
        return seen

    candidates = descendants((selected.to_position_id,))
    entries = {snapshot.book.root_position_id}
    entries.update(m.to_position_id for m in snapshot.moves
                   if m.move_id != move_id and m.from_position_id not in candidates)
    shared = candidates & descendants(entries)
    positions = candidates - shared if subtree else set()
    moves = {move_id} | {m.move_id for m in snapshot.moves if m.from_position_id in positions}
    sources = {s.source_ref_id for s in snapshot.sources if s.move_id in moves or s.position_id in positions}
    notes = sum(bool(value) for m in snapshot.moves if m.move_id in moves
                for value in (m.move_note, m.instructional_note, m.variation_description))
    notes += sum(bool(p.position_note) for p in snapshot.positions if p.position_id in positions)
    return DeletionPlan(snapshot.book.book_id, snapshot.identity, move_id, subtree,
                        selected.variation_name or selected.san, tuple(sorted(moves)),
                        tuple(sorted(positions)), tuple(sorted(sources)), notes, len(shared))
