"""Portable advisory analysis contracts, bound to an exact saved authored position."""
from dataclasses import dataclass
import chess
from analysis_settings import AnalysisProfile
from candidate_lines import CandidateLineSet
from opening_book_models import BookSnapshot, PositionIdentity, position_identity


@dataclass(frozen=True)
class OpeningEngineAnchor:
    """Identify a saved position and the exact highlighted route that reaches it.

    Args:
        library_identity: Canonical managed UUID or explicit external-library namespace.
        book_id: Stable library-local book ID.
        book_identity: Frozen content/revision identity, including author metadata.
        path: Saved move IDs from the book root to the selected position.
        position_id: Selected saved position ID.
        position: Canonical authored position identity.
        fen: Exact replay FEN including clocks for engine-cache identity.
        label: Human-readable book/variation/last-move breadcrumb.
    """
    library_identity: str
    book_id: int
    book_identity: str
    path: tuple[int, ...]
    position_id: int
    position: PositionIdentity
    fen: str
    label: str


@dataclass(frozen=True)
class OpeningEngineAnalysis:
    """Hold engine advice without making any repertoire or tactic conclusion.

    Args:
        anchor: Exact saved authoring position.
        profile: Existing shared typed profile used for raw generation only.
        lines: Validated actual MultiPV evidence.
        analyzed_at: Time this request completed, in UTC.
        cache_hit: Whether exact existing evidence satisfied the request.
        engine_searches: Fresh owned searches, zero on a cache hit or terminal root.
        cache_inserts: Complete new advisory-cache rows, never game/coverage writes.
        elapsed_seconds: Actual elapsed service time.
    """
    anchor: OpeningEngineAnchor
    profile: AnalysisProfile
    lines: CandidateLineSet
    analyzed_at: str
    cache_hit: bool
    engine_searches: int
    cache_inserts: int
    elapsed_seconds: float


def saved_opening_anchor(snapshot: BookSnapshot, library_identity: str,
                         path: tuple[int, ...] = ()) -> OpeningEngineAnchor:
    """Resolve an exact saved route without using a potentially unsaved board preview.

    Args:
        snapshot: Current immutable authored book.
        library_identity: Explicit library namespace.
        path: Saved edge IDs currently highlighted in the book browser.

    Returns:
        Position anchor with legal replay FEN and human breadcrumb.

    Raises:
        ValueError: The library or saved route is missing, illegal or inconsistent.
    """
    if not library_identity:
        raise ValueError('Select a saved library before requesting analysis.')
    position_id = snapshot.book.root_position_id
    board = chess.Board(snapshot.position(position_id).canonical_fen)
    names, last = [snapshot.book.name], 'Book start'
    edges = {edge.move_id: edge for edge in snapshot.moves}
    for edge_id in path:
        edge = edges.get(edge_id)
        if edge is None or edge.from_position_id != position_id:
            raise ValueError('The selected saved book path changed. Select it again.')
        move = board.parse_uci(edge.move_uci)
        if not move or move not in board.legal_moves:
            raise ValueError('The saved path contains an illegal move.')
        last = f"after {board.fullmove_number}{'.' if board.turn else '…'}{board.san(move)}"
        if edge.variation_name:
            names.append(edge.variation_name)
        board.push(move)
        position_id = edge.to_position_id
        if position_identity(board).canonical_fen != snapshot.position(position_id).canonical_fen:
            raise ValueError('The saved path has an inconsistent target position.')
    return OpeningEngineAnchor(library_identity, snapshot.book.book_id, snapshot.identity,
        tuple(path), position_id, position_identity(board), board.fen(), ' > '.join((*names, last)))
