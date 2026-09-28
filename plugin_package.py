"""Validate restricted pure-Python wheels before the standard PyPA installation."""
import configparser
import email
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile
from installer import install
from installer.destinations import SchemeDictionaryDestination
from installer.sources import WheelFile
from plugin_models import PluginLimits


def install_wheel(wheel: Path, site: Path, limits: PluginLimits) -> None:
    """Install one checked wheel without importing code or resolving dependencies.

    Args:
        wheel: Local independently built wheel.
        site: New, core-controlled staging directory.
        limits: Finite archive limits.

    Raises:
        ValueError: The archive violates the restricted plugin package contract.
    """
    if wheel.suffix != ".whl" or wheel.stat().st_size > limits.max_wheel_bytes:
        raise ValueError("Expected a bounded local wheel")
    with zipfile.ZipFile(wheel) as archive:
        entries = archive.infolist()
        if len(entries) > limits.max_files or sum(x.file_size for x in entries) > limits.max_expanded_bytes:
            raise ValueError("Wheel exceeds inventory limits")
        names = set()
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (path.is_absolute() or "\\" in entry.filename or ":" in entry.filename
                    or ".." in path.parts or not path.parts
                    or entry.filename.rstrip("/") != path.as_posix()
                    or len(entry.filename) > 512 or any(ord(c) < 32 for c in entry.filename)
                    or any(not p or p.endswith((" ", ".")) for p in path.parts)):
                raise ValueError("Unsafe wheel path")
            if any(re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", p) for p in path.parts):
                raise ValueError("Reserved Windows wheel path")
            mode = stat.S_IFMT(entry.external_attr >> 16)
            if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or entry.flag_bits & 1:
                raise ValueError("Linked, special, or encrypted wheel entry")
            folded = entry.filename.rstrip("/").casefold()
            if folded in names:
                raise ValueError("Duplicate/case-colliding wheel path")
            names.add(folded)
        file_names = {e.filename.casefold() for e in entries if not e.is_dir()}
        if any(parent.as_posix().casefold() in file_names for e in entries for parent in PurePosixPath(e.filename).parents if str(parent) != "."):
            raise ValueError("Wheel file/directory path conflict")
        info_roots = {PurePosixPath(e.filename).parts[0] for e in entries
                      if PurePosixPath(e.filename).parts[0].endswith(".dist-info")}
        if len(info_roots) != 1:
            raise ValueError("Exactly one distribution is required")
        info = info_roots.pop()
        wheel_metadata = email.message_from_bytes(archive.read(info + "/WHEEL"))
        if (wheel_metadata.get("Root-Is-Purelib") != "true"
                or wheel_metadata.get_all("Tag") != ["py3-none-any"]
                or wheel_metadata.get("Wheel-Version") != "1.0"):
            raise ValueError("Only Wheel 1.0 pure-Python py3-none-any is supported")
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        parser.read_string(archive.read(info + "/entry_points.txt").decode())
        if parser.sections() != ["chesswizard.plugins"] or len(parser["chesswizard.plugins"]) != 1:
            raise ValueError("Only one plugin entry point; no executable scripts")
        point = next(iter(parser["chesswizard.plugins"].values())).strip()
        if not re.fullmatch(r"chesswizard_plugin_[a-z0-9_]+:[a-zA-Z_]\w*", point):
            raise ValueError("Unsupported plugin module layout")
        package = point.split(":")[0]
        if package == "chesswizard_plugin_api":
            raise ValueError("Plugin cannot replace host SDK")
        for entry in entries:
            parts = PurePosixPath(entry.filename).parts
            if parts[0] not in (info, package):
                raise ValueError("Wheel contains unrelated top-level code/data")
            if parts[0] == package and not entry.is_dir() and PurePosixPath(entry.filename).suffix not in {".py", ".json"}:
                raise ValueError("Plugin package allows Python and static JSON only")
        if package + "/__init__.py" not in archive.namelist():
            raise ValueError("Plugin must be a regular package")
    with WheelFile.open(wheel) as source:
        source.validate_record(validate_contents=True)
        destination = SchemeDictionaryDestination(
            {key: str(site) for key in ("purelib", "platlib", "headers", "scripts", "data")},
            interpreter=sys.executable, script_kind="win-amd64", bytecode_optimization_levels=(),
        )
        install(source, destination, additional_metadata={"INSTALLER": b"ChessWizard plugin host\n"})