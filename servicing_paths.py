"""Fail-closed paths for owned payloads and explicitly disposable servicing roots."""
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile

FIXTURE_MARKER = ".chesswizard-servicing-fixture.json"


def checked_path(path: Path) -> Path:
    """Reject traversal and reparse points before resolving an absolute path.

    Args:
        path: Absolute local path to inspect, including existing ancestors.

    Returns:
        Normalized absolute path without following links.

    Raises:
        ValueError: The path is relative, traverses, or contains a reparse point.
    """
    if not path.is_absolute() or ".." in path.parts or str(path).startswith("\\\\"):
        raise ValueError("An absolute local non-traversing path is required")
    for item in [*reversed(path.parents), path]:
        if item.exists() or item.is_symlink():
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Links/junctions/reparse points are not serviceable")
    return path.absolute()


def relative_file(name: str) -> Path:
    """Validate one portable, case-stable payload inventory name.

    Args:
        name: Forward-slash relative file name.

    Returns:
        Safe relative path.

    Raises:
        ValueError: An absolute, traversal, ADS, reserved, or ambiguous name occurs.
    """
    parts = PurePosixPath(name).parts
    forbidden = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}
    if not parts or name != "/".join(parts) or name.startswith("/") or "\\" in name or ":" in name:
        raise ValueError("Unsafe inventory name")
    if any(p in (".", "..") or p.rstrip(" .") != p or p.split(".")[0].upper() in forbidden or any(c in p for c in '<>"|?*') for p in parts):
        raise ValueError("Unsafe inventory component")
    return Path(*parts)


def tree_files(root: Path) -> tuple[Path, ...]:
    """Enumerate regular files without ever traversing a link or junction.

    Args:
        root: Validated directory, which may not yet exist.

    Returns:
        Sorted absolute file paths.

    Raises:
        ValueError: Any path is linked or is not an ordinary file/directory.
        OSError: Enumeration cannot be completed.
    """
    checked_path(root)
    if not root.exists():
        return ()
    if not root.is_dir():
        raise ValueError("Managed tree must be a directory")
    found = []
    def fail(error: OSError) -> None:
        raise error
    for folder, directories, files in os.walk(root, followlinks=False, onerror=fail):
        for name in [*directories, *files]:
            path = checked_path(Path(folder) / name)
            if name in files:
                if not stat.S_ISREG(path.stat().st_mode):
                    raise ValueError("Non-regular file in managed tree")
                found.append(path)
    return tuple(sorted(found))


def canonical_profile() -> Path:
    """Locate the consumer managed profile without consulting custom overrides.

    Returns:
        Per-user managed ChessWizard directory.

    Raises:
        ValueError: Windows user-data storage is unavailable.
    """
    value = os.environ.get("LOCALAPPDATA")
    if not value:
        raise ValueError("LOCALAPPDATA unavailable")
    return checked_path(Path(value) / "ChessWizard")


def validate_roots(app: Path, profile: Path, fixture: Path | None = None) -> tuple[Path, Path]:
    """Admit canonical consumer roots or a marked, bounded temporary fixture.

    Args:
        app: Application destination.
        profile: User-data directory; never an application payload target.
        fixture: Optional explicit disposable marker for isolated test builds.

    Returns:
        Validated application and profile paths.

    Raises:
        ValueError: Roots overlap or are not the recognized managed locations.
    """
    app, profile = checked_path(app), checked_path(profile)
    if app == profile or app in profile.parents or profile in app.parents:
        raise ValueError("Application and profile paths must be separate")
    if fixture is None:
        expected = checked_path(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "ChessWizard")
        if app != expected or profile != canonical_profile():
            raise ValueError("Unsupported custom application/profile path; use the managed installation")
    else:
        marker = checked_path(fixture)
        root = marker.parent
        temporary = checked_path(Path(tempfile.gettempdir()))
        data = json.loads(marker.read_text(encoding="utf-8"))
        if (marker.name != FIXTURE_MARKER or root.parent != temporary or not root.name.startswith("chesswizard-servicing-")
                or data != {"schema_version": 1, "root": str(root), "purpose": "disposable-servicing-test"}
                or app != root / "app" or profile != root / "profile"):
            raise ValueError("Invalid disposable servicing fixture")
    return app, profile
