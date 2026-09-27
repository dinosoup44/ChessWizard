"""Versioned theme data and fixed semantic asset roles."""
from dataclasses import dataclass, field, asdict
from types import MappingProxyType
from typing import Mapping
import re

PIECE_ROLES = tuple(f"{color}_{piece}" for color in ("white", "black")
                    for piece in ("king", "queen", "rook", "bishop", "knight", "pawn"))
DECORATION_SLOTS = ("corner_top_left", "corner_top_right", "corner_bottom_left",
                    "corner_bottom_right", "border_top", "border_bottom", "border_left",
                    "border_right", "center_emblem")


def valid_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", value):
        raise ValueError("Invalid theme ID")
    return value


@dataclass(frozen=True)
class BoardColors:
    light_square: str = "#d8c7a6"
    dark_square: str = "#7d6b58"
    frame: str = "#302b35"
    coordinate: str = "#ffffff"

    def __post_init__(self):
        for value in asdict(self).values():
            if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                raise ValueError("Colors must be six-digit hex values, for example #d8c7a6")


def asset_mapping(mapping, roles, directory):
    if not isinstance(mapping, Mapping) or set(mapping)-set(roles):
        raise ValueError("Unknown or invalid asset role")
    for role, path in mapping.items():
        if path != f"{directory}/{role}.png":
            raise ValueError("Asset paths must use the managed role filename; external paths and traversal are forbidden")
    return MappingProxyType(dict(mapping))


@dataclass(frozen=True)
class Theme:
    theme_id: str
    name: str
    colors: BoardColors = field(default_factory=BoardColors)
    pieces: Mapping[str, str] = field(default_factory=dict)
    decorations: Mapping[str, str] = field(default_factory=dict)
    author: str = ""
    description: str = ""
    version: int = 1

    def __post_init__(self):
        valid_id(self.theme_id)
        if type(self.version) is not int or self.version != 1:
            raise ValueError("Unsupported theme version")
        for key, limit in (("name",80),("author",160),("description",2000)):
            value=getattr(self,key)
            if not isinstance(value,str) or len(value)>limit or (key=="name" and not value.strip()):
                raise ValueError(f"Invalid {key}")
        if not isinstance(self.colors,BoardColors):
            raise ValueError("Invalid board colors")
        object.__setattr__(self,"pieces",asset_mapping(self.pieces,PIECE_ROLES,"pieces"))
        object.__setattr__(self,"decorations",asset_mapping(self.decorations,DECORATION_SLOTS,"board"))

    @property
    def missing_roles(self):
        return tuple(role for role in PIECE_ROLES if role not in self.pieces)

    @property
    def complete(self):
        return not self.missing_roles

    def to_data(self):
        return dict(theme_id=self.theme_id,name=self.name,author=self.author,description=self.description,
                    version=self.version,colors=asdict(self.colors),pieces=dict(self.pieces),decorations=dict(self.decorations))

    @classmethod
    def from_data(cls, data):
        if not isinstance(data,dict) or set(data)-{"theme_id","name","author","description","version","colors","pieces","decorations"}:
            raise ValueError("Unknown manifest fields")
        if not isinstance(data.get("colors"),dict) or not {"light_square","dark_square"} <= set(data["colors"]):
            raise ValueError("Light and dark square colors are required")
        try:
            return cls(**{**data,"colors":BoardColors(**data["colors"])})
        except (TypeError,KeyError) as error:
            raise ValueError("Invalid theme manifest") from error
