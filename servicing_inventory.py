"""Versioned ownership inventory; hashes identify bytes, not publisher trust."""
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from packaging.version import Version
from servicing_paths import relative_file, tree_files

INVENTORY_NAME = "chesswizard-payload.json"
SCHEMA_VERSION = 1
REQUIRED_FILES = frozenset({"ChessWizard.exe", "ChessWizardPluginHost.exe", "ChessWizardServicing.exe", "_internal/LICENSE"})


@dataclass(frozen=True)
class OwnedFile:
    """Describe immutable application ownership.

    Args:
        path: Safe install-relative path.
        sha256: Exact byte digest.
        size: Expected byte count.
        category: Runtime, application, or notice/asset classification.
    """
    path: str
    sha256: str
    size: int
    category: str


@dataclass(frozen=True)
class PayloadInventory:
    """Carry the versioned installed payload contract.

    Args:
        version: Canonical application version or explicit synthetic build version.
        files: Application-owned files; inventory itself is implicitly owned.
        schema_version: Supported inventory schema.
        architecture: Frozen machine architecture.
    """
    version: str
    files: tuple[OwnedFile, ...]
    schema_version: int = SCHEMA_VERSION
    architecture: str = "AMD64"


def file_hash(path: Path) -> str:
    """Hash a file without loading it into memory.

    Args:
        path: File to read.

    Returns:
        SHA256 hexadecimal digest.
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_inventory(path: Path) -> PayloadInventory:
    """Parse a bounded inventory and reject ambiguous or conflicting ownership.

    Args:
        path: Inventory JSON file.

    Returns:
        Validated immutable inventory.

    Raises:
        ValueError: Schema, version, identity, paths, sizes, or required files fail.
        OSError: The inventory is unreadable.
    """
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Inventory exceeds size bound")
    data = json.loads(path.read_text(encoding="utf-8"))
    if set(data) != {"version", "files", "schema_version", "architecture"} or data['schema_version'] != 1 or data['architecture'] != "AMD64":
        raise ValueError("Unsupported payload inventory")
    Version(data['version'])
    records, names = [], set()
    if not 1 <= len(data['files']) <= 20000:
        raise ValueError("Inventory file-count bound")
    for row in data['files']:
        record = OwnedFile(**row)
        relative_file(record.path)
        key = record.path.lower()
        if key in names or key == INVENTORY_NAME or not re.fullmatch(r"[0-9a-f]{64}", record.sha256):
            raise ValueError("Duplicate/invalid ownership identity")
        if type(record.size) is not int or record.size < 0 or record.category not in {"application", "runtime", "notice_asset"}:
            raise ValueError("Invalid inventory attributes")
        names.add(key)
        records.append(record)
    if not {name.lower() for name in REQUIRED_FILES} <= names:
        raise ValueError("Required application artifacts absent")
    if any('/'.join(name.split('/')[:i]) in names for name in names for i in range(1, len(name.split('/')))):
        raise ValueError("File/directory ownership collision")
    return PayloadInventory(data['version'], tuple(records))


def verify_payload(root: Path, inventory: PayloadInventory, exact: bool = False) -> None:
    """Verify expected bytes and optionally reject every unlisted source file.

    Args:
        root: Source staging or installed root.
        inventory: Valid ownership contract.
        exact: Require an exact source set, including the implicit inventory.

    Raises:
        ValueError: A required file, hash, size, or exact file set differs.
    """
    files = tree_files(root)
    if exact and {p.relative_to(root).as_posix() for p in files} != {f.path for f in inventory.files} | {INVENTORY_NAME}:
        raise ValueError("Source payload differs from inventory")
    for record in inventory.files:
        path = root / relative_file(record.path)
        if not path.is_file() or path.stat().st_size != record.size or file_hash(path) != record.sha256:
            raise ValueError("Payload verification failed: " + record.path)


def create_inventory(root: Path, version: str) -> PayloadInventory:
    """Write deterministic ownership for an explicitly supplied build directory.

    Args:
        root: Frozen build payload; never a user profile.
        version: Build's central version or isolated synthetic version.

    Returns:
        Inventory validated against the exact payload.

    Raises:
        ValueError: The build lacks required artifacts or has unsafe paths.
    """
    Version(version)
    records = []
    for path in tree_files(root):
        relative = path.relative_to(root).as_posix()
        if relative == INVENTORY_NAME:
            continue
        category = "runtime" if path.suffix.lower() in {".dll", ".pyd"} else "application" if path.suffix.lower() in {".exe", ".py", ".zip"} else "notice_asset"
        records.append(OwnedFile(relative, file_hash(path), path.stat().st_size, category))
    inventory = PayloadInventory(version, tuple(records))
    target = root / INVENTORY_NAME
    target.write_text(json.dumps(asdict(inventory), sort_keys=True, indent=2) + "\n", encoding="utf-8")
    checked = load_inventory(target)
    verify_payload(root, checked, exact=True)
    return checked
