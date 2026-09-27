"""Managed, additive theme snapshots. No database or active-app settings access."""
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
import json
import re
import uuid
from .models import Theme, BoardColors, PIECE_ROLES, DECORATION_SLOTS, valid_id
from .assets import PngAsset, load_png, decode_png, reject_links, MAX_THEME_BYTES

MAX_MANIFEST_BYTES = 65536
MAX_PACKAGE_FILES = 22


def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:
            raise ValueError(f"Duplicate manifest field/role: {key}")
        result[key]=value
    return result


@dataclass(frozen=True)
class LoadedTheme:
    theme: Theme
    pieces: Mapping[str,PngAsset]
    decorations: Mapping[str,PngAsset]

    def __post_init__(self):
        object.__setattr__(self,"pieces",MappingProxyType(dict(self.pieces)))
        object.__setattr__(self,"decorations",MappingProxyType(dict(self.decorations)))


class ThemeRepository:
    def __init__(self, root):
        self.root=Path(root).absolute()
        reject_links(self.root)

    def _folder(self, theme_id):
        folder=self.root/valid_id(theme_id)
        reject_links(folder)
        folder.resolve().relative_to(self.root.resolve())
        return folder

    def managed_directory(self, theme_id):
        """Resolve a validated direct theme child; callers must validate its package before mutation."""
        return self._folder(theme_id)

    def _manifest(self, folder):
        path=folder/"theme.json"
        reject_links(path)
        with path.open("rb") as stream:
            data=stream.read(MAX_MANIFEST_BYTES+1)
        if len(data)>MAX_MANIFEST_BYTES:
            raise ValueError("Theme manifest is too large")
        try:
            theme=Theme.from_data(json.loads(data,object_pairs_hook=unique_object))
        except (UnicodeError,json.JSONDecodeError) as error:
            raise ValueError("Invalid theme JSON") from error
        if theme.theme_id!=folder.name:
            raise ValueError("Theme ID does not match its managed directory")
        return theme

    def list_themes(self):
        """List manifest labels; full package validation still runs before selection."""
        reject_links(self.root)
        if not self.root.exists(): return ()
        result=[]
        for folder in sorted(self.root.iterdir()):
            if folder.name.startswith(".") or not folder.is_dir(): continue
            try:
                result.append(self._manifest(self._folder(folder.name)))
            except (ValueError,OSError):
                continue
        return tuple(result)

    def load(self, theme_id) -> LoadedTheme:
        folder=self._folder(theme_id)
        theme=self._manifest(folder)
        expected={"theme.json",*theme.pieces.values(),*theme.decorations.values()}
        found=set(); total=0
        for path in folder.rglob("*"):
            reject_links(path)
            relative=path.relative_to(folder).as_posix()
            if path.is_dir():
                if relative not in ("pieces","board"): raise ValueError("Unexpected theme directory")
                continue
            if not path.is_file() or relative not in expected:
                raise ValueError("Unexpected/unsupported file in theme package")
            found.add(relative);total+=path.stat().st_size
            if len(found)>MAX_PACKAGE_FILES or total>MAX_THEME_BYTES:
                raise ValueError("Theme exceeds file-count or size limit")
        if found!=expected: raise ValueError("A referenced theme asset is missing")
        return LoadedTheme(theme,{k:load_png(folder/v) for k,v in theme.pieces.items()},
                           {k:load_png(folder/v) for k,v in theme.decorations.items()})

    def save(self, *, name, colors, pieces, decorations, author="", description="") -> LoadedTheme:
        """Save a new immutable set; previous sets are never overwritten or deleted."""
        if set(pieces)-set(PIECE_ROLES) or set(decorations)-set(DECORATION_SLOTS):
            raise ValueError("Unknown asset role")
        safe_pieces={k:decode_png(v.data) for k,v in pieces.items()}
        safe_decorations={k:decode_png(v.data) for k,v in decorations.items()}
        if sum(len(v.data) for v in (*safe_pieces.values(),*safe_decorations.values()))>MAX_THEME_BYTES-MAX_MANIFEST_BYTES:
            raise ValueError("Theme exceeds the 64 MiB size limit")
        slug=re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-")[:48] or "theme"
        theme_id=slug+"-"+uuid.uuid4().hex[:12]
        theme=Theme(theme_id,name.strip(),colors,{k:f"pieces/{k}.png" for k in pieces},
                    {k:f"board/{k}.png" for k in decorations},author,description)
        reject_links(self.root);self.root.mkdir(parents=True,exist_ok=True)
        pending=self.root/(".pending-"+uuid.uuid4().hex)
        target=self._folder(theme_id)
        pending.resolve().relative_to(self.root.resolve());target.resolve().relative_to(self.root.resolve())
        pending.mkdir()
        for directory,assets in (("pieces",safe_pieces),("board",safe_decorations)):
            (pending/directory).mkdir()
            for role,asset in assets.items():
                (pending/directory/f"{role}.png").write_bytes(asset.data)
        (pending/"theme.json").write_text(json.dumps(theme.to_data(),indent=2),encoding="utf8")
        reject_links(self.root)
        pending.rename(target)
        return LoadedTheme(theme,safe_pieces,safe_decorations)
