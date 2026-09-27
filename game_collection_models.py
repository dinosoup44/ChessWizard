"""Immutable organization metadata, independent of chess analysis and desktop UI."""
from dataclasses import dataclass

NAME_LIMIT = 120
DESCRIPTION_LIMIT = 4000


@dataclass(frozen=True)
class CollectionDetails:
    name: str
    description: str = ""

    def __post_init__(self):
        for field, limit in (("name", NAME_LIMIT), ("description", DESCRIPTION_LIMIT)):
            value = getattr(self, field)
            if not isinstance(value, str) or len(value.strip()) > limit or "\x00" in value:
                raise ValueError(f"{field.capitalize()} must be text of at most {limit} characters.")
            object.__setattr__(self, field, value.strip())
        if not self.name:
            raise ValueError("Enter a collection name.")


@dataclass(frozen=True)
class GameCollection:
    collection_id: int
    name: str
    description: str
    created_at: str
    updated_at: str
    member_count: int


@dataclass(frozen=True)
class GameCollectionMember:
    collection_id: int
    game_id: int
    added_at: str
    played_at: str | None
    white: str | None
    black: str | None
    result: str | None


def valid_id(value: int) -> int:
    """Reject coerced identifiers before any metadata write."""
    if type(value) is not int or value <= 0:
        raise ValueError("Select a valid collection or game ID.")
    return value
