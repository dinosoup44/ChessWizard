"""Portable editor state shared by desktop widgets and tests/tools."""
from dataclasses import dataclass, field
from .models import Theme, BoardColors, PIECE_ROLES, DECORATION_SLOTS
from .repository import LoadedTheme
from .assets import PngAsset, load_png


@dataclass
class ThemeDraft:
    name: str = ""
    author: str = ""
    description: str = ""
    colors: BoardColors = field(default_factory=BoardColors)
    pieces: dict[str,PngAsset] = field(default_factory=dict)
    decorations: dict[str,PngAsset] = field(default_factory=dict)

    @classmethod
    def from_loaded(cls,loaded):
        t=loaded.theme
        return cls(t.name,t.author,t.description,t.colors,dict(loaded.pieces),dict(loaded.decorations))

    def assign(self,role,path):
        if role not in (*PIECE_ROLES,*DECORATION_SLOTS):raise ValueError("Unknown asset role")
        asset=load_png(path)
        (self.pieces if role in PIECE_ROLES else self.decorations)[role]=asset
        return asset

    def clear(self,role):
        if role not in (*PIECE_ROLES,*DECORATION_SLOTS):raise ValueError("Unknown asset role")
        (self.pieces if role in PIECE_ROLES else self.decorations).pop(role,None)

    @property
    def missing_roles(self):return tuple(role for role in PIECE_ROLES if role not in self.pieces)

    def preview(self):
        theme=Theme("editor-preview","Editor preview",self.colors,
                    {k:f"pieces/{k}.png" for k in self.pieces},
                    {k:f"board/{k}.png" for k in self.decorations})
        return LoadedTheme(theme,self.pieces,self.decorations)

    def save(self,repository):
        return repository.save(name=self.name,author=self.author,description=self.description,
                               colors=self.colors,pieces=self.pieces,decorations=self.decorations)
