"""Explicit, bounded full-profile deletion, separate from ordinary servicing."""
import hashlib
import json
import os
from pathlib import Path
from servicing_inventory import file_hash
from servicing_paths import checked_path, tree_files, validate_roots
from servicing_transaction import probe_replaceable

CONFIRMATION = "REMOVE ALL LOCAL CHESSWIZARD DATA"


def removal_preview(app: Path, profile: Path, fixture: Path | None = None) -> dict:
    """Enumerate the entire recognized managed profile without following links.

    Args:
        app: Separate application directory.
        profile: Canonical managed profile, or marked disposable fixture.
        fixture: Optional explicit temporary fixture marker.

    Returns:
        Exact file names, sizes, hashes, and a confirmation identity.

    Raises:
        ValueError: The root is custom, unsafe, linked, or ambiguous.
        OSError: Content cannot be enumerated completely.
    """
    _, profile = validate_roots(app, profile, fixture)
    custom = os.environ.get("CHESSWIZARD_DATA_DIR")
    if custom and checked_path(Path(custom)) != profile:
        raise ValueError("Custom ChessWizard data location detected. Keep data and review that location manually.")
    files = [{"path": p.relative_to(profile).as_posix(), "size": p.stat().st_size, "sha256": file_hash(p)} for p in tree_files(profile)]
    identity = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {"profile": str(profile), "files": files, "bytes": sum(f['size'] for f in files), "identity": identity}


def remove_profile(app: Path, profile: Path, expected_identity: str, confirmation: str,
                   fixture: Path | None = None) -> dict:
    """Delete only the explicitly confirmed, unchanged managed profile contents.

    Args:
        app: Separate application root.
        profile: Recognized managed profile root.
        expected_identity: Digest of the previously displayed deletion inventory.
        confirmation: Required explicit destructive confirmation phrase.
        fixture: Optional temporary fixture marker.

    Returns:
        Removed file/byte counts.

    Raises:
        ValueError: Consent is absent or the enumerated content changed.
        OSError: Deletion fails; partial irreversible removal must be reported.
    """
    if confirmation != CONFIRMATION:
        raise ValueError("Full removal requires explicit confirmation")
    preview = removal_preview(app, profile, fixture)
    if preview['identity'] != expected_identity:
        raise ValueError("Profile changed after confirmation; review its contents again")
    # Enumerate and validate every directory before deleting anything. Never rmtree.
    directories = []
    for folder, children, _ in os.walk(profile, followlinks=False):
        directories.extend(checked_path(Path(folder) / child) for child in children)
    for item in preview['files']:
        probe_replaceable(checked_path(profile / item['path']))
    for item in preview['files']:
        checked_path(profile / item['path']).unlink()
    for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        checked_path(directory).rmdir()
    if profile.exists():
        checked_path(profile).rmdir()
    return {"removed_files": len(preview['files']), "removed_bytes": preview['bytes']}
