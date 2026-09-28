"""Inventory a frozen onedir against exact PyInstaller inputs; fail on unknown owners."""
import argparse
import ast
from collections import Counter
import hashlib
import json
import marshal
from pathlib import Path
import re
import struct
import sys
import types
import zipfile
from tools.license_audit import safe_file

from tools.package_privacy import (PRIVATE_PARTS, PrivacyPolicy, content_findings,
    load_privacy_policy, validate_package_path)

FORBIDDEN_MODULES = {"pip", "requests", "urllib3", "certifi", "idna", "charset_normalizer", "setuptools", "pytest", "pefile", "altgraph", "tests"}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_member(name: str, privacy: PrivacyPolicy = PrivacyPolicy()) -> None:
    """Reject private package paths, allowing only the named public default book.

    Args:
        name: Relative frozen-package member.
        privacy: Additional local identifiers forbidden in member names.

    Raises:
        ValueError: The member is private or an unapproved authored library.
    """
    validate_package_path(name, privacy)


def owner(source: Path, root: Path, base: Path, environment: Path) -> tuple[str, str]:
    """Classify exact provenance without inferring unknown native dependencies.

    Args:
        source: Actual packaging input path.
        root: Application source root.
        base: CPython runtime root.
        environment: Pinned build environment root.

    Returns:
        Component owner and applicable license description.

    Raises:
        ValueError: The dependency or source location is unreviewed.
    """
    source = Path(source).resolve()
    site = environment / "Lib/site-packages"
    if source.is_relative_to(site):
        dependency = source.relative_to(site).parts[0]
        if dependency == "PIL":
            return "Pillow 12.3.0", "MIT-CMU and bundled native notices"
        if dependency == "chess":
            return "chess 1.11.2", "GPL-3.0-or-later"
        if dependency in {"installer", "installer-0.7.0.dist-info"}:
            return "installer 0.7.0", "MIT"
        if dependency in {"packaging", "packaging-26.3.dist-info"}:
            return "packaging 26.3", "Apache-2.0 OR BSD-2-Clause"
        if dependency == "PyInstaller":
            relative = source.relative_to(site / dependency).as_posix()
            apache = relative.startswith(("hooks/rthooks/", "fake-modules/"))
            return "PyInstaller 6.22.3 runtime", "Apache-2.0" if apache else "GPL-2.0-or-later WITH Bootloader-exception"
        raise ValueError("Unreviewed dependency: " + dependency)
    if source.is_relative_to(base):
        if source.name.lower().startswith("vcruntime"):
            return "Microsoft VC runtime (CPython distribution)", "Microsoft redistributable terms in Python LICENSE"
        if source.name in {"tcl90.dll", "tcl9tk90.dll", "libtommath.dll", "zlib1.dll"}:
            return "CPython Tcl/Tk 9.0.4 runtime", "Tcl/Tk BSD-style; LibTomMath Unlicense; zlib; embedded MPL-2.0 data"
        return "CPython 3.14.7 runtime", "PSF-2.0 and incorporated software notices"
    if source.is_relative_to(root / "Engines"):
        return "Stockfish 18 AVX2", "GPL-3.0-or-later; embedded NNUE CC0-1.0"
    if source.is_relative_to(root / 'assets/openings'):
        if source.name in {'ChessWizard Default Openings.cwbook','ChessWizard Default Openings.bin','COPYING.txt','manifest.json'}:
            return 'Lichess chess-openings / ChessWizard curated opening data', 'CC0-1.0 source data and provenance'
        raise ValueError('Unreviewed opening content: ' + source.name)
    if source.is_relative_to(root):
        if source.name == "base_library.zip":
            return "CPython standard library archive", "PSF-2.0 and incorporated software notices"
        if source.name in {"ChessWizard.exe", "ChessWizardPluginHost.exe", "ChessWizardServicing.exe"}:
            return "ChessWizard frozen container", "GPL-3.0-or-later plus separately inventoried runtime components"
        return "ChessWizard / reviewed notices and resources", "GPL-3.0-or-later; third-party texts retain their declared terms"
    raise ValueError("Unreviewed input origin: " + str(source))


def code_strings(code):
    if isinstance(code, types.CodeType):
        yield ("source_filename", code.co_filename)
        for value in code.co_consts:
            yield from code_strings(value)
    elif isinstance(code, str):
        yield ("constant", code)
    elif isinstance(code, (tuple, list, frozenset)):
        for value in code:
            yield from code_strings(value)


def inventory(root: Path, distribution: Path, *, build: Path | None = None,
              privacy: PrivacyPolicy = PrivacyPolicy()) -> dict:
    """Inventory frozen files with generic privacy rules and optional local identifiers.

    Args:
        root: Source checkout supplying the build inputs.
        distribution: Frozen directory to inspect without modifying it.
        build: Explicit PyInstaller build directory, or the established default.
        privacy: Additional local privacy rules; finding values remain redacted.

    Returns:
        Exact component inventory and privacy finding categories.

    Raises:
        ValueError: An input has unknown provenance or a forbidden package path.
        OSError: Required build inputs cannot be read.
    """
    import pefile
    from PyInstaller.archive.readers import CArchiveReader
    build = Path(build) if build is not None else root / "build/windows/pyinstaller/ChessWizard"
    environment = root / "build/windows/venv"
    base = Path(sys.base_prefix).resolve()
    collected = ast.literal_eval((build / "COLLECT-00.toc").read_text())[0]
    origins = {(name if kind == "EXECUTABLE" else "_internal/" + name).replace("\\", "/"): (source, kind)
               for name, source, kind in collected}
    from servicing_inventory import INVENTORY_NAME, load_inventory, verify_payload
    if (distribution / INVENTORY_NAME).is_file():
        verify_payload(distribution, load_inventory(distribution / INVENTORY_NAME), exact=True)
        origins[INVENTORY_NAME] = (str(distribution / INVENTORY_NAME), "GENERATED_OWNERSHIP")
    containers = [name for name, (_, kind) in origins.items() if kind == "EXECUTABLE"]
    files, findings = [], []
    for path in sorted(distribution.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(distribution).as_posix()
        validate_member(relative, privacy)
        source, kind = origins.pop(relative)
        ownership, license_name = owner(source, root, base, environment)
        data = path.read_bytes()
        pe = data.startswith(b"MZ")
        machine = None
        if pe:
            offset = struct.unpack_from("<I", data, 0x3c)[0]
            assert data[offset:offset+4] == b"PE\0\0"
            machine = hex(struct.unpack_from("<H", data, offset+4)[0])
        entry = dict(path=relative, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
            pe=pe, pe_machine=machine, kind=kind, owner=ownership, license=license_name,
            input_sha256=digest(source), input_matches=digest(source)==hashlib.sha256(data).hexdigest())
        if pe:
            binary = pefile.PE(data=data, fast_load=True)
            binary.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
            entry["imports"] = [item.dll.decode("ascii") for item in getattr(binary, "DIRECTORY_ENTRY_IMPORT", [])]
            binary.close()
        files.append(entry)
        for label in content_findings(data, privacy):
            findings.append(dict(member=relative, marker=label, kind="raw bytes"))
    assert not origins, "Missing collected files"
    pure_inputs = [dict((name, source) for name, source, _ in ast.literal_eval(path.read_text())[1])
                   for path in sorted(build.glob("PYZ-*.toc"))]
    modules, scripts = [], []
    for container in containers:
        archive = CArchiveReader(str(distribution / container))
        pyz = archive.open_embedded_archive("PYZ.pyz")
        matches = [pure for pure in pure_inputs if set(pure) == set(pyz.toc)]
        if len(matches) != 1:
            raise ValueError("Frozen archive has no unique exact PYZ source inventory: " + container)
        pure = matches[0]
        for name, (kind, offset, size) in sorted(pyz.toc.items()):
            if name.split(".")[0] in FORBIDDEN_MODULES:
                raise ValueError("Forbidden embedded dependency: " + name)
            source = pure[name]
            ownership, license_name = owner(source, root, base, environment)
            modules.append(dict(container=container, name=name, compressed_bytes=size,
                owner=ownership, license=license_name, source_sha256=digest(source)))
            for category, value in code_strings(pyz.extract(name)):
                for label in content_findings(value.encode(), privacy):
                    findings.append(dict(member=container+":PYZ:"+name, marker=label, kind=category))
        for name, entry in archive.toc.items():
            if entry[-1] in {"s", "m", "M"}:
                content = archive.extract(name)
                application = name in {"run_chesswizard", "plugin_host", "servicing_host"}
                scripts.append(dict(container=container, name=name, bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
                    owner="ChessWizard" if application else "PyInstaller runtime",
                    license="GPL-3.0-or-later" if application else "Apache-2.0" if name.startswith("pyi_rth_") else "GPL-2.0-or-later WITH Bootloader-exception"))
                for category,value in code_strings(marshal.loads(content)):
                    for label in content_findings(value.encode(), privacy):
                        findings.append(dict(member=container+":EXE:"+name, marker=label, kind=category))
    archives = []
    for path in distribution.rglob("*"):
        if path.is_file() and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                members=[]
                for name in z.namelist():
                    if name.endswith("/"):
                        continue
                    validate_member(name, privacy)
                    data=z.read(name)
                    members.append(dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
                    for label in content_findings(data, privacy):
                        findings.append(dict(member=path.name+"!"+name, marker=label, kind="embedded bytes"))
                archives.append(dict(path=path.relative_to(distribution).as_posix(), members=members))
    return dict(schema_version=1, files=files, embedded_python_modules=modules, boot_scripts=scripts,
        embedded_zip_resources=archives, file_count=len(files), total_bytes=sum(f["bytes"] for f in files),
        privacy_findings=findings, exclusions=sorted(PRIVATE_PARTS | FORBIDDEN_MODULES),
        spec_sha256=digest(root / "packaging/windows/ChessWizard.spec"),
        build_lock_sha256=digest(root / "packaging/windows/requirements-build.lock.txt"))


def main() -> int:
    """Inspect a supplied frozen folder without building or publishing it.

    Returns:
        Zero for a clean privacy inventory, otherwise one.
    """
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("distribution",type=Path)
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--output", type=Path, help="Explicit local audit receipt")
    parser.add_argument("--privacy-config", type=Path, help="Ignored local JSON with additional private literals")
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    result=inventory(root,args.distribution.resolve(),build=args.build_dir,privacy=load_privacy_policy(args.privacy_config))
    path=args.output or root / "reports/v1_package_manifest.json"
    path.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:result[k] for k in ("file_count","total_bytes","privacy_findings")},indent=2))
    print("Manifest SHA256",digest(path))
    return int(bool(result["privacy_findings"]))

if __name__ == "__main__":
    raise SystemExit(main())
