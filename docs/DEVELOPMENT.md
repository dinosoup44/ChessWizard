# Development on Windows

Run commands below in **Windows PowerShell** from a checkout such as
`C:\Projects\ChessWizard`. No absolute owner-machine path is required.

## Python and dependencies

The verified environment is CPython **3.14.7 AMD64**, Tcl/Tk **9.0.4**, on Windows 10/11
x64. Install the standard Python distribution with Tk, and verify your interpreter:

```powershell
py -3.14 --version
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -c "import chess, PIL, tkinter; print(chess.__version__, PIL.__version__, tkinter.TkVersion)"
```

`requirements.txt` is the canonical source install file. It pins chess 1.11.2,
python-chess 1.999 (compatibility meta-package), Pillow 12.3.0 and the existing Requests
stack used by legacy import tools. Current core imports need chess and Pillow; preserving
the source requirements also supports those older tools. Do not replace the dependency
system casually. The pins do not provide download hashes or a bit-identical build guarantee.
Unit tests and pydoc use the standard library; pytest is not required.

Optional binary build dependencies are separately pinned in
`packaging/windows/requirements-build.lock.txt`. PyInstaller 6.22.3 and Inno Setup
6.7.3 are build tools, not source-run requirements. Packaging and publication require
their own current audits and owner approval.

## Isolate writable data

```powershell
$env:CHESSWIZARD_DATA_DIR = Join-Path $env:LOCALAPPDATA 'ChessWizard-Dev'
.\.venv\Scripts\python.exe -B run_chesswizard.py
```

The override must be absolute. Choose a new directory for development. Never copy a
maintainer's DB into it. Supported first launch creates the clean schema and a writable
managed copy of the shipped default openings. Without an override, normal user data
is under `%LOCALAPPDATA%\ChessWizard`; a legacy source-adjacent DB can still be selected
when no existing user DB is found. See [FIRST_RUN.md](FIRST_RUN.md).

Do not run `database.py`, cleanup scripts, migrations, seed scripts or old standalone
analyzer launchers as setup commands. Their presence is compatibility/history, not a
supported daily workflow. The application uses the central registry/planner and shared
services. Launching Review does not itself authorize background analysis.

## Stockfish

No executable is proposed for the public Git source tree. Obtain the **Stockfish 18
Windows x86-64 AVX2** archive from the [pinned official release](https://github.com/official-stockfish/Stockfish/releases/tag/sf_18).
Extract it to the existing relative layout, so the executable is:

```text
Engines/Stockfish/stockfish-windows-x86-64-avx2/stockfish/stockfish-windows-x86-64-avx2.exe
```

The inspected binary SHA256 is:
`c86215fa1977d53b82ed854540a4c7b025be4cd042276c85ba3de53fb9118911`.
Verify the downloaded file with `Get-FileHash -Algorithm SHA256 <path>` before using it.
This build requires AVX2; do not run it on unsupported CPUs. Alternative builds require
explicit configuration/evidence-currentness review; there is no documented general
engine-path environment override in this version. Do not silently substitute a newer
engine. Importing modules, pydoc, library authoring and most tests do not need Stockfish.
Analyze Games and on-demand engine lines do require it.

`engine_cache.STOCKFISH_PATH` is the shared configured relative path; Admin reports
presence and offers an explicit bounded UCI handshake. No download automation or engine
run is part of documentation setup. Retain GPL/NNUE notices when redistributing an
engine; binary releases require separately reviewed matching source inputs.

## Tests

```powershell
# Complete available suite: public contracts plus local historical audits, if present
.\.venv\Scripts\python.exe -B tools\run_tests.py
# Focus one module or check collection only
.\.venv\Scripts\python.exe -B tools\run_tests.py --pattern test_opening_book.py
.\.venv\Scripts\python.exe -B tools\run_tests.py --collect-only
# Rehearse the entire public suite without any private files
.\.venv\Scripts\python.exe -B tools\check_public_copy.py
```

The runner uses `discover -s tests` because some existing tests import siblings by
top-level name. GUI tests need Tk and a Windows desktop session; their windows are
positioned offscreen. Every run selects a temporary user profile and prevents actual
Stockfish launches. The optional real-engine acceptance test remains disabled during
ordinary testing. Direct standard-library unittest discovery is also supported.

Public tests use synthetic fixtures and reusable `tests/support/` helpers. Exact
historical audit assertions are retained in ignored `tests/local_history/`; local
normal discovery includes them. A public checkout needs no private reports, review
sets or owner-derived evidence. Do not replace missing data with silent test skips.
The public-copy checker records collection and full-suite results separately and uses
the same installed dependencies, not a new virtual environment. See [PUBLIC_SOURCE.md](PUBLIC_SOURCE.md).

## API documentation

```powershell
.\.venv\Scripts\python.exe -B tools\check_pydoc.py
.\.venv\Scripts\python.exe -B tools\build_pydoc.py
Start-Process .\build\pydoc\index.html
# Inspect one API directly; only use known safe reusable modules
.\.venv\Scripts\python.exe -B -m pydoc opening_studio_handoff
```

`tools/public_api.json` defines the intended index. The checked worker is bounded to
90 seconds and denies network, subprocess/engine creation, SQLite connections, GUI
imports and writes. It is a guard against accidental side effects in trusted code,
not a sandbox for hostile plugins. Render success is distinct from full docstring/type
coverage. Generated pages normalize checkout paths and memory-address representations;
no timestamps are added. An identical run in the same environment should reproduce bytes.

## Public data and source preview

The four assets under `assets/openings/` and pinned upstream TSV/license/manifest inputs
under `data/default_openings/` are public content. Profile `opening_books/` files are
editable private data. Regenerate defaults offline into a **new** directory:

```powershell
.\.venv\Scripts\python.exe -B -m tools.build_default_openings --output build/default-openings-review
.\.venv\Scripts\python.exe -B -m tools.public_source
```

The public-source tool tests actual Git ignore behavior in a disposable temporary Git
repository; it does not initialize, stage or modify Git state in your checkout. Its
manifest in `build/` is a preview, not an approval or a package. It exits nonzero for
unresolved scan findings. Pattern scans cannot prove absence of secrets; review the
listed files before committing. See the [first publication checklist](FIRST_PUBLIC_RELEASE_CHECKLIST.md).
