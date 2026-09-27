"""Read-only book membership facts, independent of engine quality and game storage."""
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import chess
from game_review_repository import GameReviewRepository
from position_evaluation import actual_positions
from opening_book_models import OpeningMove, BookSnapshot, position_identity, standard_board
from collections.abc import Sequence


@dataclass(frozen=True)
class BookMoveMembership:
    ply: int
    move_number: int
    actor_color: str
    played_uci: str
    played_san: str
    position_id: int | None
    in_book: bool
    weight: int | None
    preferred_move: str | None
    available_moves: tuple[OpeningMove, ...]
    state: str


@dataclass(frozen=True)
class BookApplication:
    game_id: int | None
    book_id: int
    book_version: str
    book_revision: int
    snapshot_identity: str
    moves: tuple[BookMoveMembership, ...]
    first_deviation_ply: int | None
    deviating_side: str | None
    deviation_relation: str | None
    last_known_position_ply: int | None
    last_known_position_id: int | None
    known_position_count: int
    in_book_move_count: int


def apply_book(snapshot: BookSnapshot, moves_uci: Sequence[str], *,
               initial_fen: str = chess.STARTING_FEN, game_id: int | None = None,
               user_color: str | None = None) -> BookApplication:
    """Project the shared opening replay into the original membership interface.

    Args:
        snapshot: Authored graph, including optional family-entry metadata.
        moves_uci: Legal actual game moves.
        initial_fen: Actual starting board.
        game_id: Optional game identifier.
        user_color: Known player side or None.

    Returns:
        Membership and deviation facts with the same entry rules as Game Review.

    Raises:
        ValueError: Graph, game moves or player-side metadata are invalid.
    """
    from opening_intelligence_lookup import OpeningBookLookup
    from opening_intelligence_application import assess_game
    result = assess_game(OpeningBookLookup(snapshot), moves_uci, initial_fen=initial_fen,
                         game_id=game_id, user_color=user_color)
    rows = tuple(BookMoveMembership(r.ply,r.move_number,r.actor_color,r.played_uci,r.played_san,
        r.position_id,r.played_move_in_book,r.played_weight,
        r.preferred_move.move_uci if r.preferred_move else None,r.available_moves,r.state) for r in result.moves)
    first, last = result.first_deviation, result.last_known_position
    return BookApplication(game_id,snapshot.book.book_id,snapshot.book.version,snapshot.book.revision,
        snapshot.identity,rows,result.first_deviation_ply,first.actor_color if first else None,
        first.deviation_relation if first else None,last.after_ply if last else None,
        last.position_id if last else None,len(result.known_book_positions),result.in_book_moves)


def apply_stored_game(database_path, game_id, snapshot):
    """Read one explicit local game; no bootstrap, schema change or result persistence."""
    if type(game_id) is not int or game_id <= 0:
        raise ValueError("Game ID must be a positive integer.")
    path = Path(database_path).resolve()
    with closing(sqlite3.connect(path.as_uri()+"?mode=ro",uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        game = db.execute("SELECT user_color,variant FROM games WHERE game_id=?", (game_id,)).fetchone()
        if game is None:
            raise ValueError(f"Game ID {game_id} was not found in this database.")
        if game[1] and game[1].lower() not in ("standard", "chess"):
            raise ValueError("Opening Book V1 supports standard chess only.")
        moves = GameReviewRepository(db).moves(game_id)
        if not moves:
            raise ValueError("Game has no stored moves; its initial position is unknown.")
        actual_positions(game_id,moves)
        return apply_book(snapshot,tuple(row["uci_played"] for row in moves),
                          initial_fen=moves[0]["fen_before"],game_id=game_id,user_color=game[0])

