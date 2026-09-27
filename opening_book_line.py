"""Pure whole-line authoring plans; existing authored metadata is never rewritten."""
from dataclasses import dataclass
import chess
from opening_book_models import BookSnapshot, MoveDetails, PositionIdentity, position_identity, text


@dataclass(frozen=True)
class BookLineStep:
    """Describe one legal ply and whether it needs a new edge.

    Args:
        source: Canonical decision position.
        target: Canonical resulting position.
        uci: Legal move text.
        san: Human notation at that position.
        existing_move_id: Stable existing ID, or None for a planned new edge.
        create: True only on the first occurrence of a missing edge.
        details: Neutral new-edge metadata; never applied to an existing edge.
    """
    source: PositionIdentity
    target: PositionIdentity
    uci: str
    san: str
    existing_move_id: int | None
    create: bool
    details: MoveDetails


@dataclass(frozen=True)
class BookLinePlan:
    """Preview one atomic additive authoring action against frozen book contents.

    Args:
        book_id: Target book ID.
        book_identity: Exact snapshot identity required at commit.
        anchor_position_id: Saved insertion position.
        fen: Original selected-route FEN.
        moves: Entire chosen continuation, with no automatic truncation.
        variation_name: Optional user name applied to the first new edge only.
        provenance_json: Compact authoring origin attached to that first new edge.
        steps: Legal replay and merge decisions for every ply.
        existing_prefix: Number of initial plies already present before this action.
    """
    book_id: int
    book_identity: str
    anchor_position_id: int
    fen: str
    moves: tuple[str, ...]
    variation_name: str
    provenance_json: str
    steps: tuple[BookLineStep, ...]
    existing_prefix: int

    @property
    def new_edges(self) -> int:
        """Count unique inserts rather than double-counting cycles.

        Returns:
            Number of new authored move edges.
        """
        return sum(step.create for step in self.steps)


def plan_book_line(snapshot: BookSnapshot, anchor_position_id: int, fen: str,
                   moves: tuple[str, ...], *, variation_name: str = '',
                   provenance_json: str = '{}') -> BookLinePlan:
    """Preview a full legal continuation, reusing positions and existing move IDs.

    Args:
        snapshot: Current authored book.
        anchor_position_id: Exact saved insertion point.
        fen: Legal route-specific FEN for that point.
        moves: Selected complete continuation in UCI.
        variation_name: User-entered name for the first missing edge; blank stays unnamed.
        provenance_json: Optional authoring metadata for the first new edge only.

    Returns:
        Immutable collision-aware plan suitable for confirmation and atomic persistence.

    Raises:
        ValueError: Anchor, move, metadata or inactive overlapping edge is unsuitable.
    """
    text(variation_name, 'Variation name')
    name = variation_name.strip()
    MoveDetails(metadata_json=provenance_json)
    board = chess.Board(fen)
    if not board.is_valid() or not moves:
        raise ValueError('Choose a nonempty legal line at a saved position.')
    position = next((p for p in snapshot.positions if p.position_id == anchor_position_id), None)
    if position is None or position.canonical_fen != position_identity(board).canonical_fen:
        raise ValueError('The analysis anchor is not this saved book position.')
    positions = {p.position_id:p.canonical_fen for p in snapshot.positions}
    existing = {(positions[m.from_position_id], m.move_uci):m for m in snapshot.moves}
    planned, steps, prefix, named = set(), [], 0, False
    for index, uci in enumerate(moves):
        source = position_identity(board)
        move = board.parse_uci(uci)
        if not move or move not in board.legal_moves:
            raise ValueError('The engine continuation contains an illegal or null move.')
        san = board.san(move)
        board.push(move)
        target = position_identity(board)
        key = (source.canonical_fen, uci)
        edge = existing.get(key)
        if edge and not edge.active:
            raise ValueError(f'{san} already exists as an inactive move. Enable it explicitly before adding this line.')
        if edge and positions[edge.to_position_id] != target.canonical_fen:
            raise ValueError('Existing theory has an inconsistent target position.')
        create = edge is None and key not in planned
        details = MoveDetails(variation_name=name if create and not named else '',
                              metadata_json=provenance_json if create and not named else '{}')
        if edge and prefix == index:
            prefix += 1
        if create:
            named = True
            planned.add(key)
        steps.append(BookLineStep(source, target, uci, san, edge.move_id if edge else None, create, details))
    return BookLinePlan(snapshot.book.book_id, snapshot.identity, anchor_position_id, fen,
        tuple(moves), name, provenance_json, tuple(steps), prefix)
