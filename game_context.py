"""Read-only presentation facts shared by review and training frontends."""
from dataclasses import dataclass
from game_review_repository import GameReviewRepository


@dataclass(frozen=True)
class ActualMoveRow:
    number: int
    white: str = ""
    black: str = ""
    white_step: int | None = None
    black_step: int | None = None


def actual_move_rows(moves):
    """Steps are positions AFTER stored half-moves, including black-first imports."""
    rows = []
    for step, move in enumerate(moves, 1):
        if not rows or rows[-1]["number"] != move["move_number"]:
            rows.append(dict(number=move["move_number"]))
        color = move["color"]
        rows[-1][color] = move["san_played"] or move["uci_played"] or "?"
        rows[-1][color+"_step"] = step
    return tuple(ActualMoveRow(**row) for row in rows)


@dataclass(frozen=True)
class TrainingGameContext:
    previous_san: str = ""
    previous_uci: str = ""
    continuation: tuple[ActualMoveRow, ...] = ()


def training_game_context(connection, game_id, move_id):
    moves = GameReviewRepository(connection).moves(game_id)
    index = next((i for i, m in enumerate(moves) if m["move_id"] == move_id), None)
    if index is None:
        return TrainingGameContext()
    previous = moves[index-1] if index else {}
    return TrainingGameContext(previous.get("san_played") or "", previous.get("uci_played") or "",
                               actual_move_rows(moves[index:]))
