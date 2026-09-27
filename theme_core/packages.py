"""Import the Art Tester V1 folder format, optionally transported in a bounded ZIP.

Archive entries are never extracted. Every name, type and byte budget is checked
before the existing manifest/PNG validators admit an immutable managed snapshot.
"""
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile
import zlib
from .assets import reject_links, decode_png, MAX_FILE_BYTES, MAX_THEME_BYTES
from .models import Theme
from .repository import ThemeRepository, LoadedTheme, unique_object, MAX_MANIFEST_BYTES, MAX_PACKAGE_FILES

MAX_ARCHIVE_BYTES = MAX_THEME_BYTES * 2
MAX_ARCHIVE_ENTRIES = MAX_PACKAGE_FILES + 3


def _archive_theme(path: Path) -> LoadedTheme:
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Theme archive is too large")
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ARCHIVE_ENTRIES:
                raise ValueError("Too many files/directories in theme archive")
            files = {}
            directories = set()
            total = 0
            for entry in entries:
                name = entry.orig_filename
                parts = name.rstrip("/").split("/")
                mode = entry.external_attr >> 16
                if (not name or "\\" in name or "\x00" in name or ":" in name
                        or PurePosixPath(name).is_absolute()
                        or any(p in ("", ".", "..") for p in parts)):
                    raise ValueError("Unsafe archive path")
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or entry.external_attr & 0x400:
                    raise ValueError("Linked/special archive entries are forbidden")
                if entry.flag_bits & 1:
                    raise ValueError("Encrypted theme archives are unsupported")
                if name in files or name.rstrip("/") in directories:
                    raise ValueError("Duplicate archive entry")
                if entry.is_dir():
                    if entry.file_size:
                        raise ValueError("Directory entry contains data")
                    directories.add(name.rstrip("/"))
                    continue
                if stat.S_ISDIR(mode):
                    raise ValueError("Invalid archive entry type")
                limit = MAX_MANIFEST_BYTES if parts[-1] == "theme.json" else MAX_FILE_BYTES
                if not (parts[-1] == "theme.json" or parts[-1].endswith(".png")):
                    raise ValueError("Only theme.json and approved PNG assets are allowed")
                total += entry.file_size
                if entry.file_size > limit or total > MAX_THEME_BYTES or len(files) >= MAX_PACKAGE_FILES:
                    raise ValueError("Theme exceeds file-count or size limit")
                with archive.open(entry) as stream:
                    data = stream.read(limit + 1)
                if len(data) != entry.file_size or len(data) > limit:
                    raise ValueError("Invalid archive size")
                files[name] = data
            manifests = [name for name in files if name == "theme.json" or name.count("/") == 1 and name.endswith("/theme.json")]
            if len(manifests) != 1:
                raise ValueError("Archive must contain exactly one theme manifest")
            manifest = manifests[0]
            prefix = manifest.removesuffix("theme.json")
            data = json.loads(files[manifest], object_pairs_hook=unique_object)
            theme = Theme.from_data(data)
            if prefix and prefix != theme.theme_id + "/":
                raise ValueError("Theme folder must match its manifest ID")
            expected = {"theme.json", *theme.pieces.values(), *theme.decorations.values()}
            if set(files) != {prefix + name for name in expected}:
                raise ValueError("Missing or unsupported package files")
            allowed_dirs = {prefix + "pieces", prefix + "board"}
            if prefix:
                allowed_dirs.add(prefix.rstrip("/"))
            if directories - allowed_dirs:
                raise ValueError("Unsupported package directory")
            return LoadedTheme(theme,
                {role: decode_png(files[prefix + name]) for role, name in theme.pieces.items()},
                {role: decode_png(files[prefix + name]) for role, name in theme.decorations.items()})
    except (zipfile.BadZipFile, NotImplementedError, UnicodeError, json.JSONDecodeError, EOFError, zlib.error) as error:
        raise ValueError("Invalid theme archive") from error


def import_theme_package(repository: ThemeRepository, path) -> LoadedTheme:
    """Validate completely before copying canonical assets once into a new saved set."""
    path = Path(path).absolute()
    reject_links(path)
    if path.is_dir():
        loaded = ThemeRepository(path.parent).load(path.name)
    elif path.suffix.lower() == ".zip" and path.is_file():
        loaded = _archive_theme(path)
    else:
        raise ValueError("Choose an Art Tester theme folder or ZIP package")
    theme = loaded.theme
    return repository.save(name=theme.name, author=theme.author, description=theme.description,
                           colors=theme.colors, pieces=loaded.pieces, decorations=loaded.decorations)
