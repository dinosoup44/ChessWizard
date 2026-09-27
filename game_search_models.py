"""Portable, serializable Game Explorer requests and result rows."""
from dataclasses import dataclass
from datetime import date, datetime, timezone
import math

MOTIFS = ("fork", "mate", "pin", "skewer", "xray")
RELATIONSHIPS = ("played_by_perspective", "missed_by_perspective",
                 "played_by_opponent", "missed_by_opponent", "unknown")


@dataclass(frozen=True)
class GameSearchCriteria:
    game_id: int | None = None
    opponent: str = ""
    color: str = ""
    result: str = ""
    source: str = ""
    source_game_id: str = ""
    date_from: str = ""
    date_to: str = ""
    time_control: str = ""
    min_moves: int | None = None
    max_moves: int | None = None
    motifs: tuple[str, ...] = ()
    relationships: tuple[str, ...] = ()
    min_accuracy: float | None = None
    max_accuracy: float | None = None

    collection_id: int | None = None
    uncollected: bool = False

    def __post_init__(self):
        if type(self.uncollected) is not bool or (self.uncollected and self.collection_id is not None):
            raise ValueError("Choose a collection or uncollected games, not both.")
        if self.collection_id is not None and (type(self.collection_id) is not int or self.collection_id <= 0):
            raise ValueError("Collection ID must be a positive integer.")
        for name in ("opponent", "source", "source_game_id", "time_control", "date_from", "date_to"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ValueError(f"{name} must be text.")
            object.__setattr__(self, name, value.strip())
        for name in ("game_id", "min_moves", "max_moves"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < (1 if name == "game_id" else 0)):
                raise ValueError(f"{name.replace('_', ' ').capitalize()} must be a {'positive' if name == 'game_id' else 'nonnegative'} integer.")
        if self.color not in ("", "white", "black") or self.result not in ("", "win", "loss", "draw"):
            raise ValueError("Choose a supported color and result.")
        for name in ("date_from", "date_to"):
            value = getattr(self, name)
            if value and (len(value) != 10 or date.fromisoformat(value).isoformat() != value):
                raise ValueError("Dates must use YYYY-MM-DD.")
        for name, options in (("motifs", MOTIFS), ("relationships", RELATIONSHIPS)):
            values = tuple(dict.fromkeys(getattr(self, name)))
            if any(value not in options for value in values):
                raise ValueError(f"Unsupported {name}.")
            object.__setattr__(self, name, values)
        for name in ("min_accuracy", "max_accuracy"):
            value = getattr(self, name)
            if value is not None and (type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 100):
                raise ValueError("Accuracy must be between 0 and 100.")
        for lower, upper in (("min_moves", "max_moves"), ("min_accuracy", "max_accuracy"), ("date_from", "date_to")):
            a, b = getattr(self, lower), getattr(self, upper)
            if a is not None and b is not None and a != "" and b != "" and a > b:
                raise ValueError("Range minimum must not exceed maximum.")


@dataclass(frozen=True)
class GameSearchRow:
    game_id: int
    played_at: str | None
    white: str | None
    black: str | None
    user_color: str | None
    result: str | None
    move_count: int
    source: str
    source_game_id: str
    time_control: str | None
    accuracy: float | None = None
    tactic_count: int = 0


@dataclass(frozen=True)
class GameSearchResult:
    games: tuple[GameSearchRow, ...]
    total_games: int
    criteria: GameSearchCriteria

    @property
    def summary(self):
        if not self.games and self.criteria.game_id is not None:
            if self.criteria == GameSearchCriteria(game_id=self.criteria.game_id):
                return f"Game ID {self.criteria.game_id} was not found in this database."
            return f"No game matches Game ID {self.criteria.game_id} and the selected filters."
        if not self.games and self.criteria == GameSearchCriteria(collection_id=self.criteria.collection_id) and self.criteria.collection_id is not None:
            return "No games in this collection."
        return f"{len(self.games)} games found · {self.total_games} total"



def sorted_games(rows, column, descending=False):
    """Typed table ordering; unknowns stay last in either direction."""
    if column not in GameSearchRow.__dataclass_fields__:
        raise ValueError("Unknown result column")
    def value(row):
        result = getattr(row, column)
        if column == "played_at" and result:
            try:
                result = datetime.fromisoformat(result[:10].replace(".", "-")+result[10:])
                return result.replace(tzinfo=timezone.utc).timestamp() if result.tzinfo is None else result.timestamp()
            except ValueError:
                return None
        return result.casefold() if isinstance(result, str) else result
    known, unknown = [], []
    for row in rows:
        item = value(row)
        if item is None or item == "":
            unknown.append(row)
        else:
            known.append((item, row.game_id, row))
    return tuple(item[2] for item in sorted(known, key=lambda item: item[:2], reverse=descending))+tuple(unknown)
