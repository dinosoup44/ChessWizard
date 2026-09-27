"""Read-only audit game filters, independent of chess analysis and desktop UI."""
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping, TypeVar


BUILTIN_REVIEW_SETS = Path(__file__).parent / "review_data" / "builtin_review_sets.json"
Game = TypeVar("Game", bound=Mapping)


@dataclass(frozen=True)
class ReviewSetEntry:
    game_id: int
    reason_code: str
    reason_label: str
    source_artifact: str
    case_key: str
    move_id: int | None = None
    candidate_id: int | None = None
    move_number: int | None = None
    color: str | None = None
    proposed_move: str | None = None
    review_note: str = ""
    tactic_type: str | None = None
    reason_explanation: str = ""
    audit_metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        if not isinstance(self.audit_metadata, tuple) or not all(
            isinstance(pair, tuple) and len(pair) == 2 and all(isinstance(v, str) for v in pair)
            for pair in self.audit_metadata
        ):
            raise ValueError("Audit metadata must be immutable text pairs")


@dataclass(frozen=True)
class ReviewSet:
    id: str
    label: str
    description: str
    entries: tuple[ReviewSetEntry, ...] = ()
    audit_only: bool = False

    def entries_for_game(self, game_id: int) -> tuple[ReviewSetEntry, ...]:
        return tuple(entry for entry in self.entries if entry.game_id == game_id)

    def filter_games(self, games: list[Game]) -> list[Game]:
        """Narrow an existing ordered game query without changing tactic visibility."""
        if self.id == "all_games":
            return list(games)
        allowed = {entry.game_id for entry in self.entries}
        return [game for game in games if game["game_id"] in allowed]

    def game_label(self, game: Mapping) -> str:
        if self.id == "all_games":
            return f"{game['game_id']} · {game['white_username']} vs {game['black_username']}"
        reasons = tuple(dict.fromkeys(entry.reason_label for entry in self.entries_for_game(game["game_id"])))
        summary = reasons[0] if reasons else "audit review"
        if len(reasons) > 1:
            summary += f" (+{len(reasons) - 1} reasons)"
        return f"Game {game['game_id']} — {summary}"


ALL_GAMES = ReviewSet("all_games", "All Games", "Normal Game Review browsing.")


def load_review_sets(path: Path | None = None) -> tuple[ReviewSet, ...]:
    """Optional QA catalogs extend All Games; absence never requires private data."""
    path = BUILTIN_REVIEW_SETS if path is None else Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return (ALL_GAMES,)
    if data["schema_version"] != 1:
        raise ValueError("Unsupported review-set schema")
    sets = [ALL_GAMES]
    for item in data["sets"]:
        sets.append(ReviewSet(item["id"], item["label"], item["description"],
                              tuple(ReviewSetEntry(**{**entry, "audit_metadata": tuple(tuple(pair) for pair in entry.get("audit_metadata", ()))})
                                    for entry in item["entries"]), audit_only=item.get("audit_only", False)))
    if len({item.id for item in sets}) != len(sets) or len({item.label for item in sets}) != len(sets):
        raise ValueError("Review-set IDs and labels must be unique")
    return tuple(sets)
