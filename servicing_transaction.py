"""Application-only preflight, rollback snapshot, and bounded stale-file cleanup."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import platform
import shutil
from packaging.version import Version
from servicing_inventory import INVENTORY_NAME, file_hash, load_inventory, verify_payload
from servicing_paths import checked_path, relative_file, tree_files, validate_roots

DISK_RESERVE_BYTES = 32 * 1024 * 1024
PLAN_NAME = "transaction.json"


def probe_replaceable(path: Path) -> None:
    """Check existing owned bytes for locks without modifying them.

    Args:
        path: Existing file to be replaced or removed.

    Raises:
        OSError: A lock or access restriction prevents safe replacement.
    """
    if getattr(path.stat(), "st_file_attributes", 0) & 1:
        raise OSError("Read-only owned file requires explicit permission repair: " + path.name)
    if os.name != "nt":
        with path.open("rb"):
            return
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = api.CreateFileW(str(path), 0x80010000, 0, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError("Close ChessWizard and other programs using this owned file: " + path.name)
    api.CloseHandle(handle)


def prepare(source: Path, app: Path, profile: Path, transaction: Path,
            fixture: Path | None = None, available_bytes: int | None = None) -> dict:
    """Verify inputs and snapshot application files before Inno mutates anything.

    Args:
        source: Extracted exact installer payload.
        app: Managed installation root.
        profile: Separate managed profile; never read or copied here.
        transaction: New private temporary rollback directory.
        fixture: Optional disposable-root marker for tests.
        available_bytes: Explicit free-space probe result for deterministic tests.

    Returns:
        Serializable preflight/rollback plan.

    Raises:
        ValueError: Ownership, version, architecture, or path validation fails.
        OSError: Insufficient space, locked files, or snapshot failure.
    """
    app, profile = validate_roots(app, profile, fixture)
    source, transaction = checked_path(source), checked_path(transaction)
    if platform.machine().upper() not in {"AMD64", "X86_64"}:
        raise ValueError("This installer requires an AMD64 Windows machine")
    for left, right in ((source, app), (transaction, app), (transaction, profile), (source, profile)):
        if left == right or left in right.parents or right in left.parents:
            raise ValueError("Staging, rollback, app and profile roots must not overlap")
    if transaction.exists():
        raise ValueError("Rollback directory must be new")
    incoming = load_inventory(source / INVENTORY_NAME)
    verify_payload(source, incoming, exact=True)
    present = tree_files(app)
    previous_path = app / INVENTORY_NAME
    previous = load_inventory(previous_path) if previous_path.is_file() else None
    incoming_names = {f.path.lower() for f in incoming.files} | {INVENTORY_NAME}
    if previous is None and any(p.relative_to(app).as_posix().lower() in incoming_names or p.name.lower().startswith("unins") for p in present):
        raise ValueError("Existing application has no valid ownership inventory. Uninstall it preserving user data, then install again.")
    if previous and Version(previous.version) > Version(incoming.version):
        raise ValueError("Downgrade refused. Repair with the installed version or use a newer installer.")
    old = {f.path for f in previous.files} | {INVENTORY_NAME} if previous else set()
    new = {f.path for f in incoming.files} | {INVENTORY_NAME}
    observed = {}
    for name in sorted(old | new):
        target = checked_path(app / relative_file(name))
        if target.exists():
            if not target.is_file() or name not in old:
                raise ValueError("Unknown file collides with incoming ownership: " + name)
            probe_replaceable(target)
            observed[name] = {"sha256": file_hash(target), "size": target.stat().st_size}
    required = sum(f.size for f in incoming.files) + sum(f['size'] for f in observed.values()) + DISK_RESERVE_BYTES
    existing_parent = next(p for p in (app, *app.parents) if p.exists())
    free = shutil.disk_usage(existing_parent).free if available_bytes is None else available_bytes
    rollback_parent = next(p for p in (transaction.parent, *transaction.parents) if p.exists())
    if free < required or shutil.disk_usage(rollback_parent).free < required:
        raise OSError("Insufficient disk space for payload and application-only rollback snapshot")
    transaction.mkdir(parents=True)
    for name, record in observed.items():
        destination = transaction / "previous" / relative_file(name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(app / relative_file(name), destination)
        if file_hash(destination) != record['sha256']:
            raise ValueError("Application changed while preparing rollback snapshot")
    plan = {"schema_version": 1, "app": str(app), "profile": str(profile), "fixture": str(fixture) if fixture else None,
            "version": incoming.version, "previous_version": previous.version if previous else None,
            "new_files": sorted(new), "stale_files": sorted(old - new), "previous_files": observed,
            "state": "prepared", "required_free_bytes": required, "incoming_inventory_sha256": file_hash(source / INVENTORY_NAME)}
    (transaction / PLAN_NAME).write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return plan


def _plan(transaction: Path) -> dict:
    checked_path(transaction)
    data = json.loads((transaction / PLAN_NAME).read_text(encoding="utf-8"))
    validate_roots(Path(data['app']), Path(data['profile']), Path(data['fixture']) if data['fixture'] else None)
    for name in [*data['new_files'], *data['stale_files'], *data['previous_files']]:
        relative_file(name)
    return data


def validate_and_prune(transaction: Path) -> dict:
    """Verify installed bytes before finalization, then remove only stale ownership.

    Args:
        transaction: Prepared application-only snapshot.

    Returns:
        Version and removed-file list for an installer receipt.

    Raises:
        ValueError: Installed bytes or a stale file changed unexpectedly.
        OSError: Stale-file cleanup is blocked.
    """
    data = _plan(transaction)
    app = Path(data['app'])
    if file_hash(app / INVENTORY_NAME) != data['incoming_inventory_sha256']:
        raise ValueError('Installed inventory changed after preflight')
    inventory = load_inventory(app / INVENTORY_NAME)
    if inventory.version != data['version'] or {f.path for f in inventory.files} | {INVENTORY_NAME} != set(data['new_files']):
        raise ValueError("Installed inventory differs from prepared ownership")
    verify_payload(app, inventory)
    removed = []
    for name in data['stale_files']:
        path = checked_path(app / relative_file(name))
        if path.exists():
            if name not in data['previous_files'] or file_hash(path) != data['previous_files'][name]['sha256']:
                raise ValueError("Stale owned file changed during setup; repair required")
            probe_replaceable(path)
            path.unlink()
            removed.append(name)
    data['state'] = 'validated'
    (transaction / PLAN_NAME).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {"version": inventory.version, "removed": removed}


def rollback(transaction: Path) -> dict:
    """Restore snapshotted application bytes after a pre-finalization failure.

    Args:
        transaction: Prepared snapshot retained by the installer until completion.

    Returns:
        Restored version and application file count.

    Raises:
        ValueError: Snapshot validation fails before restoration begins.
        OSError: Restoration fails; the installer must give repair guidance.
    """
    data = _plan(transaction)
    app = Path(data['app'])
    for name, record in data['previous_files'].items():
        saved = checked_path(transaction / "previous" / relative_file(name))
        if file_hash(saved) != record['sha256']:
            raise ValueError("Rollback snapshot failed verification; use repair installer")
    # Unknown files are never enumerated for deletion. Inno owns its registration log.
    for name in data['new_files']:
        target = checked_path(app / relative_file(name))
        if name not in data['previous_files'] and target.is_file():
            target.unlink()
    for name in data['previous_files']:
        target = checked_path(app / relative_file(name))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(transaction / "previous" / relative_file(name), target)
    return {"restored_version": data['previous_version'], "restored_files": len(data['previous_files'])}
