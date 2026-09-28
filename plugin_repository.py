"""Atomic plugin-only storage, immutable receipts, and path-contained ownership."""
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import sys
import tempfile
from plugin_locking import file_lease
from plugin_models import InstalledPlugin, PluginLimits, PluginState
from plugin_state import PluginStateError, decode_json, receipt_from_data, state_from_data, state_payload, valid_id

_RESERVED = re.compile(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?")


def checked_path(root: Path, relative: str = "") -> Path:
    """Resolve an owned path without traversing links or accepting Windows aliases.

    Args:
        root: Absolute managed directory.
        relative: Forward-slash relative child, or empty for the root.

    Returns:
        Absolute contained path, without following reparse points.

    Raises:
        ValueError: Traversal, alternate streams, reserved names, or links are present.
    """
    if Path(relative).is_absolute() or PureWindowsPath(relative).drive or "\\" in relative or ":" in relative:
        raise ValueError("Unsafe managed relative path")
    parts = relative.split("/") if relative else []
    if any(not part or part in (".", "..") or part.endswith((" ", ".")) or _RESERVED.fullmatch(part)
           or any(ord(c) < 32 for c in part) for part in parts):
        raise ValueError("Unsafe managed path component")
    absolute = root.absolute()
    current = absolute
    for parent in (*absolute.parents, absolute):
        if parent.is_symlink() or parent.is_junction():
            raise ValueError("Managed paths must not traverse links")
    for part in parts:
        current /= part
        if current.is_symlink() or current.is_junction():
            raise ValueError("Managed paths must not traverse links")
    if not current.resolve().is_relative_to(absolute.resolve()):
        raise ValueError("Managed path escapes its root")
    return current


def inventory(root: Path, limits: PluginLimits | None = None) -> dict[str, str]:
    """Hash a bounded regular-file tree without following links.

    Args:
        root: Installation or synthetic validation tree.
        limits: Optional installation inventory bounds.

    Returns:
        Deterministically sorted relative file hashes.

    Raises:
        ValueError: A link, nonregular file, case collision, or exceeded bound is found.
    """
    checked_path(root)
    result, folded, size = {}, set(), 0
    if not root.exists():
        return result
    for folder, directories, files in os.walk(root, followlinks=False):
        for name in (*directories, *files):
            relative = (Path(folder) / name).relative_to(root).as_posix()
            path = checked_path(root, relative)
            if relative.casefold() in folded:
                raise ValueError("Case-colliding installation entries")
            folded.add(relative.casefold())
            if limits and len(folded) > limits.max_files + 8:
                raise ValueError("Installation tree exceeds entry bounds")
            if name in files:
                if not path.is_file():
                    raise ValueError("Nonregular installation file")
                size += path.stat().st_size
                if limits and (len(result) >= limits.max_files + 8 or size > limits.max_expanded_bytes):
                    raise ValueError("Installation inventory exceeds bounds")
                value = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1048576), b""):
                        value.update(block)
                result[relative] = value.hexdigest()
    return dict(sorted(result.items()))


def atomic_bytes(path: Path, payload: bytes) -> bool:
    """Replace a contained data file atomically, preserving exact no-op writes.

    Args:
        path: Checked repository-owned destination.
        payload: Validated finite bytes.

    Returns:
        Whether the destination changed.

    Raises:
        OSError: Durable replacement fails; the prior file remains available.
        ValueError: A destination link is encountered.
    """
    checked_path(path.parent, path.name)
    if path.exists() and path.read_bytes() == payload:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".atomic-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        checked_path(path.parent, path.name)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    return True


class PluginRepository:
    """Own plugin receipts and intent under an explicit profile, never chess tables.

    Args:
        profile: Absolute user-data root outside application installation/source.
        limits: Bounded storage policy.
    """

    def __init__(self, profile: Path, limits: PluginLimits | None = None) -> None:
        """Select storage without creating files.

        Args:
            profile: Explicit absolute profile path.
            limits: Optional storage limits.

        Raises:
            ValueError: Storage overlaps application files or uses an unsafe root.
        """
        if not profile.is_absolute() or profile == Path(profile.anchor):
            raise ValueError("An explicit non-root absolute plugin profile is required")
        self.root = checked_path(profile, "plugins")
        core = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        if self.root.is_relative_to(core) or core.is_relative_to(self.root):
            raise ValueError("Plugin storage must not overlap core installation/source")
        self.limits = limits or PluginLimits()

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Hold only a short state transaction; a crash releases the kernel lock.

        Yields:
            None while state may be changed.

        Raises:
            RuntimeError: Another transaction exceeds the bounded wait.
        """
        with file_lease(checked_path(self.root, "state.lock"), self.limits.lock_timeout_seconds):
            yield

    @contextmanager
    def invocation(self, installation_id: str, timeout: float = 0.0) -> Iterator[None]:
        """Lease one installation independently of the state transaction lock.

        Args:
            installation_id: Owned installation identity.
            timeout: Bounded wait used by cancellation/removal.

        Yields:
            None while the installation cannot be removed.

        Raises:
            RuntimeError: Another invocation still holds the lease.
        """
        path = checked_path(self.root, f"leases/{valid_id(installation_id)}.lock")
        with file_lease(path, timeout):
            yield

    def read(self) -> PluginState:
        """Read validated state without resetting malformed data or writing files.

        Returns:
            Typed state, empty when no state has been published.

        Raises:
            PluginStateError: Existing state needs explicit recovery.
        """
        path = checked_path(self.root, "state.json")
        if not path.exists():
            return PluginState()
        if path.stat().st_size > self.limits.max_state_bytes:
            raise PluginStateError("Plugin state exceeds byte limit")
        return state_from_data(decode_json(path.read_bytes()), self.limits)

    def save(self, state: PluginState) -> bool:
        """Atomically save valid changed state while the caller holds exclusive().

        Args:
            state: Complete typed plugin state.

        Returns:
            Whether bytes changed.

        Raises:
            PluginStateError: State violates the typed contract.
            OSError: Atomic persistence fails.
        """
        return atomic_bytes(checked_path(self.root, "state.json"), state_payload(state, self.limits))

    def location(self, installation_id: str, *, staged: bool = False) -> Path:
        """Locate an opaque installation without accepting a caller-provided path.

        Args:
            installation_id: Core-generated UUID hex.
            staged: Whether the unpublished staging location is required.

        Returns:
            Checked site-packages directory.
        """
        area = "staging" if staged else "installations"
        return checked_path(self.root, f"{area}/{valid_id(installation_id)}/site-packages")

    def write_receipt(self, receipt: InstalledPlugin) -> None:
        """Write an immutable staged ownership receipt before publication.

        Args:
            receipt: Validated installation identity and inventory.

        Raises:
            ValueError: Receipt identity is invalid or conflicts with existing bytes.
        """
        data = asdict(receipt)
        receipt_from_data(data, self.limits)
        path = self.location(receipt.installation_id, staged=True).parent / "receipt.json"
        payload = (json.dumps(data, sort_keys=True, indent=2) + "\n").encode()
        if path.exists() and path.read_bytes() != payload:
            raise ValueError("Immutable receipt already exists")
        atomic_bytes(path, payload)

    def verify(self, receipt: InstalledPlugin) -> Path:
        """Verify owned receipt, exact retained artifact, and installed file bytes.

        Args:
            receipt: Indexed immutable receipt.

        Returns:
            Checked installation site.

        Raises:
            ValueError: Receipt or artifact/files changed, disappeared, or became linked.
        """
        site = self.location(receipt.installation_id)
        self.verify_ownership(receipt)
        artifact = checked_path(site.parent, "artifact.whl")
        if artifact.stat().st_size > self.limits.max_wheel_bytes or hashlib.sha256(artifact.read_bytes()).hexdigest() != receipt.artifact_sha256:
            raise ValueError("Plugin artifact changed; explicit replacement/trust review required")
        if inventory(site, self.limits) != receipt.inventory:
            raise ValueError("Plugin files changed; explicit reinstall/trust review required")
        return site

    def verify_ownership(self, receipt: InstalledPlugin) -> Path:
        """Prove a selected deletion target has its exact immutable core receipt.

        Args:
            receipt: Indexed published or retired installation.

        Returns:
            Proven owned directory.

        Raises:
            ValueError: Identity, path, or ownership receipt does not match.
        """
        directory = self.location(receipt.installation_id).parent
        path = checked_path(directory, "receipt.json")
        if path.stat().st_size > self.limits.max_state_bytes:
            raise ValueError("Ownership receipt exceeds bounds")
        if receipt_from_data(decode_json(path.read_bytes()), self.limits) != receipt:
            raise ValueError("Installation receipt identity failure")
        return directory

    def delete_installation(self, receipt: InstalledPlugin) -> None:
        """Remove one receipt-proven directory after unpublication and worker shutdown.

        Args:
            receipt: Retired core-owned installation.

        Raises:
            ValueError: Ownership or containment cannot be proven.
            OSError: Cleanup fails; callers retain the disabled retired receipt.
        """
        directory = self.verify_ownership(receipt)
        inventory(directory)
        checked_path(self.root, directory.relative_to(self.root).as_posix())
        shutil.rmtree(directory)

    def recovery_findings(self, state: PluginState) -> tuple[str, ...]:
        """Describe interrupted/unindexed directories without deleting or executing them.

        Args:
            state: Validated current state.

        Returns:
            Bounded deterministic core-authored recovery descriptions.
        """
        findings = []
        for area in ("staging", "installations"):
            base = checked_path(self.root, area)
            if not base.exists():
                continue
            for path in sorted(base.iterdir()):
                if len(findings) >= self.limits.max_installations:
                    findings.append("Additional recovery items require manual review")
                    return tuple(findings)
                if area == "staging" or path.name not in state.installations and path.name not in state.retired:
                    findings.append(f"Unpublished {area} entry retained for review")
        for transaction in state.transactions.values():
            if transaction.phase not in ("published",):
                findings.append("Incomplete installation transaction retained for review")
        if state.retired:
            findings.append("Disabled retired installations await explicit cleanup")
        return tuple(findings[:self.limits.max_installations])
