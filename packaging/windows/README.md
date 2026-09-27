# Windows onedir rehearsal

Target: CPython 3.14.7 AMD64 on Windows 10/11. The single bundled Stockfish 18
AVX2 engine requires an AVX2-capable x86-64 CPU. No onefile build or publisher step.

Create `build/windows/venv` using that exact Python. Install only the versions
in `requirements-build.lock.txt`; PyInstaller 6.22.3 is build-only. The application
requirements are unchanged. Run from the project root:

```powershell
.venv/Scripts/python.exe -m venv build/windows/venv
build/windows/venv/Scripts/python.exe -m pip install -r packaging/windows/requirements-build.lock.txt
powershell -File packaging/windows/build.ps1 -Smoke -Rehearsal rehearsal-import
.venv/Scripts/python.exe -B packaging/windows/run_smoke.py
build/windows/venv/Scripts/python.exe -B -m tools.package_manifest dist/ChessWizard-1.0.0-beta-rehearsal-import --build-dir build/windows/pyinstaller-rehearsal-import/ChessWizard
.venv/Scripts/python.exe -B -m tools.license_audit --release --package-dir dist/ChessWizard-1.0.0-beta-rehearsal-import
```

`-Smoke` builds a separate validator alongside build intermediates. The runner
copies the complete frozen folder outside the development tree, then places the
validator in that disposable copy to share the **same PYZ and runtime**. The
actual distributable and ZIP contain no validator. Temporary profiles and copies
are removed on completion.
The runner first launches the shipped executable in a new temporary profile,
then drives existing screens through frozen modules, then repeats the shipped
launch. This is functional smoke coverage; human Windows DPI/visual acceptance
remains separate. The final rehearsal additionally runs bounded real engine analysis
on two synthetic positions in disposable profiles; production data is never used.

The spec is an explicit include list for notices, one engine and the few source
resources used by existing Admin introspection. It emits only the first eight
public documentation lines used by Admin, not historical audit narratives.
Default Unicode appearance needs no image or font bundle. Python/Tcl/Tk/Pillow
resources follow their package hooks. Tcl/Tk 9 embeds its libraries in DLL ZIPs.

The build script restricts PATH to the selected Python and Windows system
directories. The spec fails if a collected native input comes from elsewhere.
Do not build using an arbitrary PATH: native DLLs from unrelated applications
can otherwise be picked up. Archive/module inventory rejects unexplained owners
and excluded dependencies. Pin all transitive build versions in the lock file.

No Git metadata is available at this working root. Reproducibility records use
per-input SHA256, spec/lock hashes and an output per-file manifest hash. No
bit-identical independent rebuild is claimed. Source companions follow
`source_info/SOURCE.md`; they exclude user data and are not embedded in the app.

## Post-import rehearsal

`-Rehearsal` selects separate dist, intermediate and metadata directories. The
current default is `rehearsal-import`; choose a new label for a later certification
rather than overwrite preserved output. The prior `rehearsal` folder and receipts
remain historical evidence. Regenerate the manifest before exact-package audit;
never certify a new folder using an older manifest. Current receipts live in
`reports/v1_post_import`, with the current license receipt in `reports/v1_packaging`.

The unshipped validator blocks DNS/socket access and development-tree reads,
checks the Import Games UI through its normal menu and empty-state button, and
exercises cancellation/offline failures. A separate temporary PGN fixture uses the
frozen normalizer/repository and Game Review to check duplicate protection and
newest-first ordering. This does not simulate a successful provider transport.
No fixture interface is added to production; live provider acceptance and new
Import dialog visual acceptance remain owner checks in an isolated profile.

## Final rehearsal with Analyze Games

Run `packaging/windows/build.ps1 -Smoke -Rehearsal rehearsal-final`, then:

```text
.venv/Scripts/python.exe -B packaging/windows/run_smoke.py --distribution dist/ChessWizard-1.0.0-beta-rehearsal-final --build-dir build/windows/pyinstaller-rehearsal-final/ChessWizard --report-dir reports/v1_final_frozen
build/windows/venv/Scripts/python.exe -B -m tools.package_manifest dist/ChessWizard-1.0.0-beta-rehearsal-final --build-dir build/windows/pyinstaller-rehearsal-final/ChessWizard
.venv/Scripts/python.exe -B -m tools.license_audit --release --package-dir dist/ChessWizard-1.0.0-beta-rehearsal-final
```

The unshipped validator supplies deterministic HTTP response bytes to the existing
import transport boundary. It drives the shipped Import and Analyze buttons,
uses the unchanged production registry and bundled Stockfish, then checks Review,
Training, safe Stop/resume and byte-identical zero-work reruns. Only the Windows
asyncio loopback self-pipe during engine startup is exempt from the network block;
external network/DNS and development-tree access remain blocked. Test scheduling
pauses after a completed check to make clicking Stop deterministic. Neither
instrumentation nor fixtures are collected into the distributable.

Prior certified import output and receipts are preserved under the old dist path
and `reports/v1_post_import_certified`; final evidence is in `reports/v1_final_frozen`.
The owner reports live-provider Import acceptance complete. Visual acceptance of
Import and Analyze in this exact frozen build still requires owner confirmation.
