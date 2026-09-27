# Reviewed onedir inputs; no project-tree collection.
import ast
import json
import os
import sys
from pathlib import Path

root = Path(SPECPATH).resolve().parents[1]
import re
rehearsal = os.environ.get("CHESSWIZARD_REHEARSAL", "rehearsal")
if not re.fullmatch(r"rehearsal(?:-[a-z0-9]+)*", rehearsal):
    raise ValueError("Invalid rehearsal directory label")
version = next(n.value.value for n in ast.parse((root / "chesswizard_version.py").read_text()).body
               if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in n.targets))
notices = [e["path"] for e in json.loads((root / "licenses/release_files.json").read_text())
           if e["path"] not in {"source_info/runtime_inputs.json", "licenses/provenance.json"}]
# Existing Admin introspection reads these exact resources without running analyzers.
metadata = ["analysis_registry.py", "analysis_settings.py", "application_settings.py",
    "admin_service.py", "admin_models.py", "admin_database.py", "admin_capabilities.py", "admin_engine.py",
    "merlin_ui/admin_console.py", "chesswizard_version.py", "database_schema.py", "database_bootstrap.py", "application_paths.py",
    "major_material_blunders.py", "position_range_evidence/__init__.py", "board_analysis/__init__.py",
    "board_analysis/static_exchange.py", "board_analysis/static_exchange_models.py"]
data = [(str(root / p), str(Path(p).parent)) for p in sorted(set(notices + metadata))]
# Only the public heading/status is consumed; private audit narratives are excluded.
for name in ("MAJOR_MATERIAL_BLUNDERS.md", "POSITION_RANGE_EVIDENCE.md", "BOARD_ANALYSIS.md", "STATIC_EXCHANGE_EVALUATION.md"):
    target = root / "build/windows" / ("metadata-" + rehearsal) / "docs" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join((root / "docs" / name).read_text(encoding="utf-8").splitlines()[:8]) + "\n", encoding="utf-8")
    data.append((str(target), "docs"))
engine = "Engines/Stockfish/stockfish-windows-x86-64-avx2/stockfish/stockfish-windows-x86-64-avx2.exe"
data.append((str(root / engine), str(Path(engine).parent)))
# Public CC0 default content only; editable user libraries are never build inputs.
for name in ("ChessWizard Default Openings.cwbook", "ChessWizard Default Openings.bin", "COPYING.txt", "manifest.json"):
    data.append((str(root / "assets/openings" / name), "assets/openings"))
a = Analysis([str(root / "run_chesswizard.py")], pathex=[str(root)], binaries=[], datas=data,
    hiddenimports=[], hookspath=[], runtime_hooks=[],
    excludes=["requests", "urllib3", "certifi", "charset_normalizer", "idna", "pip", "pytest", "setuptools"],
    noarchive=False)
# Fail closed if native dependency resolution escapes reviewed inputs.
allowed_native_roots = [root / "Engines", Path(sys.base_prefix), Path(sys.prefix)]
for destination, source, kind in a.binaries:
    if not any(Path(source).resolve().is_relative_to(p.resolve()) for p in allowed_native_roots):
        raise RuntimeError("Unreviewed native input: " + destination)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ChessWizard", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False, icon=str(root / "packaging/windows/assets/ChessWizard.ico"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
    name="ChessWizard-" + version + "-" + rehearsal)

# Separate internal test entry; never collected into the distributable folder.
if os.environ.get("CHESSWIZARD_BUILD_SMOKE") == "1":
    smoke = EXE(pyz, a.scripts[:-1], [("frozen_smoke", str(root / "packaging/windows/frozen_smoke.py"), "PYSOURCE")],
        [], exclude_binaries=True, name="ChessWizardSmoke", debug=False, strip=False, upx=False, console=True)
