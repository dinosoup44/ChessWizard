"""Portable branch paths and bounded line stepping; no navigation-history semantics."""
from dataclasses import dataclass
import json
import chess
from opening_book_models import BookSnapshot
from opening_book_session import OpeningBookSession


@dataclass(frozen=True)
class BranchStep:
    path: tuple[int, ...]
    label: str
    shared: bool = False


@dataclass(frozen=True)
class BranchPath:
    anchor: tuple[int, ...]
    parent_path: tuple[int, ...]
    label: str
    steps: tuple[BranchStep, ...]
    closes_cycle: bool = False


def _replay(snapshot, path):
    board = chess.Board(snapshot.position(snapshot.book.root_position_id).canonical_fen)
    position = snapshot.book.root_position_id
    seen = {position}
    moves = {m.move_id: m for m in snapshot.moves}
    repeated = False
    for move_id in path:
        move = moves.get(move_id)
        if move is None or move.from_position_id != position:
            raise ValueError("The saved branch path changed.")
        board.push_uci(move.move_uci)
        position = move.to_position_id
        repeated = position in seen
        seen.add(position)
    return board, position, seen, repeated


def branch_paths(snapshot: BookSnapshot, prefix: tuple[int, ...] = ()) -> tuple[BranchPath, ...]:
    """Group clickable moves without repeating one anchored name along its route.

    Args:
        snapshot: Authored graph with optional position-based opening labels.
        prefix: Exact route whose following branches should be projected.

    Returns:
        Bounded line groups; shared choice points expand once. Legacy books keep
        their explicit edge boundaries, while anchored recognition aliases do not
        create duplicate same-name headings on a single continuation.

    Raises:
        ValueError: The prefix no longer follows legal saved edges.
    """
    prefix = tuple(prefix)
    _, position, _, repeated = _replay(snapshot, prefix)
    if repeated:
        return ()
    outgoing, incoming = {}, {}
    for move in snapshot.moves:
        outgoing.setdefault(move.from_position_id, []).append(move)
        incoming[move.to_position_id] = incoming.get(move.to_position_id, 0) + 1
    anchored = 'opening_entry' in json.loads(snapshot.book.metadata_json)
    by_id = {m.move_id:m for m in snapshot.moves}
    def display_name(move, parent):
        if not anchored or not move.variation_name:
            return move.variation_name
        name = (*json.loads(move.metadata_json).get('opening_named_parents', []), move.variation_name)
        for move_id in reversed(parent):
            earlier = by_id[move_id]
            if earlier.variation_name:
                previous = (*json.loads(earlier.metadata_json).get('opening_named_parents', []), earlier.variation_name)
                return '' if name == previous else move.variation_name
        return move.variation_name
    pending = [(prefix, m) for m in reversed(outgoing.get(position, ()))]
    expanded, result = set(), []
    while pending:
        parent, first = pending.pop()
        board, _, seen, _ = _replay(snapshot, parent)
        path, move, steps, cycle = parent, first, [], False
        while True:
            label = f"{board.fullmove_number}{'.' if board.turn else '…'} {move.san}"
            path = (*path, move.move_id)
            steps.append(BranchStep(path, label, incoming.get(move.to_position_id, 0) > 1))
            board.push_uci(move.move_uci)
            position = move.to_position_id
            cycle = position in seen
            seen.add(position)
            children = outgoing.get(position, ())
            if cycle or len(children) != 1 or display_name(children[0], path):
                break
            move = children[0]
        title = display_name(first, parent) or ("Opening trunk" if not parent and len(outgoing.get(snapshot.book.root_position_id, ())) == 1 else f"Line from {steps[0].label}")
        result.append(BranchPath(steps[0].path, parent, title, tuple(steps), cycle))
        if not cycle and position not in expanded:
            expanded.add(position)
            pending.extend((path, child) for child in reversed(children))
    return tuple(result)


class BranchNavigation:
    """Keep an exact route and snapshot-scoped projections without choosing siblings.

    Args:
        session: Authoring session whose immutable snapshot owns cached paths.
    """
    def __init__(self, session: OpeningBookSession) -> None:
        """Bind one authoring session and its disposable branch projections.

        Args:
            session: Current selected book and route; refreshed snapshots invalidate caches.
        """
        self.session = session
        self.active: BranchPath | None = None
        self.index = 0
        self._snapshot = None
        self._prefixes = {}
        self._branches_key = None
        self._branches_value = ()

    def activate(self, branch: BranchPath, index=0):
        if not 0 <= index < len(branch.steps):
            raise ValueError("Choose a move inside this branch.")
        self.session.go_to(branch.steps[index].path)
        self.active, self.index = branch, index

    def step(self, offset):
        if offset not in (-1, 1):
            raise ValueError("Branch steps are one ply at a time.")
        if self.active is not None:
            target = self.index + offset
            if 0 <= target < len(self.active.steps):
                self.activate(self.active, target)

    def root(self):
        self.session.root()
        self.active, self.index = None, 0

    def _paths(self, prefix: tuple[int, ...] = ()) -> tuple[BranchPath, ...]:
        if self._snapshot is not self.session.snapshot:
            self._snapshot = self.session.snapshot
            self._prefixes = {}
            self._branches_key = None
        if prefix not in self._prefixes:
            self._prefixes[prefix] = branch_paths(self._snapshot, prefix)
        return self._prefixes[prefix]

    def branches(self) -> tuple[BranchPath, ...]:
        """Reuse branch projections only within the same immutable snapshot.

        Returns:
            Exact visible paths, including contextual shared-choice ancestors.
        """
        base = self._paths()
        key = (self.active.anchor, self.active.steps[-1].path) if self.active else ()
        if key == self._branches_key:
            return self._branches_value
        result = list(base)
        if self.active is not None:
            def extend(prefix):
                anchors = {b.anchor for b in result}
                result.extend(b for b in self._paths(prefix) if b.anchor not in anchors)
            # Contextual transpositions still need the selected route's ancestors.
            for depth in range(len(self.active.anchor)):
                path = self.active.anchor[:depth+1]
                if not any(step.path == path for b in result for step in b.steps):
                    extend(path[:-1])
            extend(self.active.steps[-1].path)
        self._branches_key, self._branches_value = key, tuple(result)
        return self._branches_value

    def sync(self) -> None:
        """Rebind active state after an explicit edit/save; never persist UI state."""
        path = self.session.history[:self.session.cursor]
        if not path:
            self.active, self.index = None, 0
            return
        branches = self.branches()
        for branch in branches:
            for index, step in enumerate(branch.steps):
                if step.path == path:
                    self.active, self.index = branch, index
                    return
        # A newly saved path beyond a shared reference remains navigable exactly.
        for depth in range(len(path)-1, -1, -1):
            for branch in self._paths(path[:depth]):
                for index, step in enumerate(branch.steps):
                    if step.path == path:
                        self.active, self.index = branch, index
                        return
        self.active, self.index = None, 0

    def alternative_to_current(self):
        """Return to the selected move's parent without changing the saved graph."""
        path = self.session.history[:self.session.cursor]
        self.session.go_to(path[:-1])
        self.sync()

    def alternative_prompt(self) -> str:
        """Describe the exact current branch point for a frontend's authoring hint.

        Returns:
            Branch position, side to move and the next authoring action.
        """
        path = self.session.history[:self.session.cursor]
        board = self.session.board
        side = "White" if board.turn else "Black"
        if path:
            edge = next(move for move in self.session.snapshot.moves if move.move_id == path[-1])
            number = board.fullmove_number - int(board.turn)
            notation = f"{number}{'…' if board.turn else '.'}{edge.san}"
            point = f"Branch point after {notation}"
        else:
            point = "Branch point at book start"
        return f"{point} · {side} to move. Play a move on the board to add an alternative."

    def status(self) -> str:
        if self.active is None:
            return "Book start — choose a branch or a move"
        step = self.active.steps[self.index]
        return f"{self.active.label} · move {self.index + 1} of {len(self.active.steps)} · after {step.label}"
