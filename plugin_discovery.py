"""Static PyPA entry-point inspection inside one bounded metadata helper."""
from importlib import metadata
import hashlib
import json
from pathlib import Path
import re
import sys
import threading
from packaging.utils import canonicalize_name
from packaging.version import Version
from plugin_compatibility import assess_compatibility, current_versions
from plugin_models import CompatibilityCode, HostVersions, PluginDescriptor, PluginLimits
from plugin_repository import checked_path, inventory
from plugin_state import decode_json

GROUP = "chesswizard.plugins"
CAPABILITY = "material_inventory"
_METADATA_LOCK = threading.Lock()
_MANIFEST_BYTES = 16384


def discover(site: Path, host: HostVersions | None = None) -> PluginDescriptor:
    """Inspect one isolated installation using the standard metadata entry-point API.

    Run this API in the bounded metadata helper, not a frontend thread. The
    temporary metadata search path never invokes entry_point.load().

    Args:
        site: One validated managed site-packages directory.
        host: Optional explicit versions for compatibility assessment.

    Returns:
        Typed distribution descriptor including static compatibility.

    Raises:
        ValueError: Distribution association, manifest, or metadata is malformed.
        OSError: An installation file cannot be read.
    """
    inventory(site, PluginLimits())
    distributions = list(metadata.distributions(path=[str(site)]))
    if len(distributions) != 1:
        raise ValueError("Exactly one distribution is required per managed installation")
    with _METADATA_LOCK:
        previous = sys.path[:]
        try:
            sys.path[:] = [str(site)]
            points = list(metadata.entry_points(group=GROUP))
        finally:
            sys.path[:] = previous
    if len(points) != 1:
        raise ValueError("Exactly one chesswizard.plugins entry point is required")
    point = points[0]
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{2,100}", point.name):
        raise ValueError("Invalid stable plugin ID")
    if not re.fullmatch(r"chesswizard_plugin_[a-z0-9_]+:[a-zA-Z_]\w*", point.value):
        raise ValueError("V1 requires a regular chesswizard_plugin_* package and factory")
    package = point.module
    if package == "chesswizard_plugin_api":
        raise ValueError("Plugins may not replace the public SDK")
    dist = point.dist
    if dist is None or Path(dist.locate_file("")).resolve() != site.resolve():
        raise ValueError("Entry point has no matching managed distribution")
    associated = distributions[0]
    if (dist.metadata.get("Name"), dist.version) != (associated.metadata.get("Name"), associated.version):
        raise ValueError("Entry point distribution association mismatch")
    names = {str(path).replace("\\", "/") for path in (dist.files or [])}
    manifest_name = f"{package}/chesswizard-plugin.json"
    if manifest_name not in names or f"{package}/__init__.py" not in names:
        raise ValueError("Plugin manifest and package must belong to the distribution")
    manifest_path = checked_path(site, manifest_name)
    if manifest_path.stat().st_size > _MANIFEST_BYTES:
        raise ValueError("Plugin manifest is too large")
    raw = manifest_path.read_bytes()
    manifest = decode_json(raw)
    required = {"schema_version", "plugin_id", "display_name", "minimum_app_version", "api_version", "type", "capabilities"}
    if not isinstance(manifest, dict) or set(manifest) != required or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValueError("Unsupported plugin manifest")
    if manifest["plugin_id"] != point.name or manifest["type"] != "position_facts":
        raise ValueError("Manifest identity/type does not match the contract")
    if manifest["capabilities"] != [CAPABILITY]:
        raise ValueError("Unsupported plugin capabilities")
    for field in ("display_name", "minimum_app_version", "api_version"):
        if not isinstance(manifest[field], str) or not 1 <= len(manifest[field]) <= 160 or any(ord(c) < 32 for c in manifest[field]):
            raise ValueError("Invalid manifest text")
    author = dist.metadata.get("Author") or dist.metadata.get("Author-email", "")
    license_name = dist.metadata.get("License-Expression") or dist.metadata.get("License", "")
    distribution_name = dist.metadata.get("Name", "")
    if any(not value or len(value) > 512 or any(ord(c) < 32 for c in value) for value in (author, license_name, distribution_name)):
        raise ValueError("Bounded plugin distribution, author, and license metadata are required")
    Version(dist.version)
    python_spec = dist.metadata.get("Requires-Python", "")
    code, reason = assess_compatibility(manifest["api_version"], manifest["minimum_app_version"], python_spec,
                                         tuple(dist.requires or ()), host or current_versions())
    return PluginDescriptor(point.name, manifest["display_name"], dist.version, author, license_name,
                            point.value, manifest["minimum_app_version"], manifest["api_version"],
                            code == CompatibilityCode.COMPATIBLE, reason, canonicalize_name(distribution_name),
                            python_spec, hashlib.sha256(raw).hexdigest(), code)
