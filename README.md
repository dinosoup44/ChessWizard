# ChessWizard: Chess Analysis

**Merlin, your guide through your chess history.**

ChessWizard is a local-first chess study application. Import your own games, review
positions and stored evaluations, inspect tactical opportunities, train from saved
candidates, and build an opening repertoire you can edit and keep.

## What you can do

- **Game Review:** replay actual moves, explore stored proof lines, and inspect an
  evaluation timeline and move-quality feedback when compatible evidence is available.
- **Tactical analysis:** explicitly analyze selected games through shared screening,
  engine evidence, specialist proof and ID-preserving storage. Supported analysis
  includes fork, mate, pin, skewer and X-ray families; coverage and confidence vary.
- **Training:** practice stored tactical candidates with separate attempt history.
- **Opening Studio:** author openings and variations, import/export libraries, and
  request Stockfish lines on demand. Saving new theory remains an explicit action.
- **Opening Review:** compare your games with a selected opening, inspect departures
  and gaps, and send the currently displayed position to Studio.
- **Default openings:** start with 96 editable opening families derived from pinned
  CC0 Lichess data. These are reference maps, not engine recommendations or exhaustive theory.

Your game database, editable libraries, settings, caches and themes live locally.
Core study does not require a cloud account. Username imports contact the chosen
provider; PGN import and review of already stored evidence can work offline.
ChessWizard does not automatically upload your chess history.

## Principles

- **Truth above all else.**
- **Correct first. Clever second. Fun third.**
- Local first; free and open.
- The user owns their chess history.
- No mandatory cloud dependency for core use.
- Prefer explicit evidence and uncertainty to unsupported chess claims.

## Status and platform

The centralized application label remains **1.0.0-beta**. The V1.5 installer and
plugin foundation is under release validation; **1.5.0 has not been released**.
New feature work is frozen while install, repair, upgrade, uninstall and plugin
lifecycle acceptance are completed. Synthetic upgrade-test versions are not releases.
Windows 10/11 x64 is the target; other desktop platforms and mobile remain unvalidated.

The public suite uses self-contained synthetic fixtures; private historical audits
remain local. See [public-source boundaries](docs/PUBLIC_SOURCE.md).
For the consumer workflow see [installation](docs/INSTALLATION.md),
[first run](docs/FIRST_RUN.md), [Plugin Manager](docs/PLUGIN_MANAGER.md), and
[plugin development](docs/PLUGIN_DEVELOPMENT.md). Clean-machine, human UI/DPI and
unsigned-download acceptance must pass before an owner-approved public release.

## Run from source (Windows PowerShell)

Use CPython **3.14.7 x64 with Tcl/Tk** for the currently tested environment. From the
checkout directory (for example `C:\Projects\ChessWizard`):

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
$env:CHESSWIZARD_DATA_DIR = Join-Path $env:LOCALAPPDATA 'ChessWizard-Dev'
.\.venv\Scripts\python.exe -B run_chesswizard.py
```

Use a separate development profile to avoid touching your everyday data. First launch
creates an empty game database and installs the default opening library in that profile.
It does not import games or launch analysis. See [development setup](docs/DEVELOPMENT.md)
for the supported Stockfish 18 path and CPU requirements. No engine binary is in the
public source repository.

## Tests and API documentation

```powershell
.\.venv\Scripts\python.exe -B tools\run_tests.py
.\.venv\Scripts\python.exe -B tools\check_public_copy.py
.\.venv\Scripts\python.exe -B tools\check_pydoc.py
.\.venv\Scripts\python.exe -B tools\build_pydoc.py
Start-Process .\build\pydoc\index.html
```

The documentation scripts use an explicit module index and block runtime side effects
while importing/rendering it. Generated HTML stays in ignored `build/pydoc/`.
The public-copy checker runs collection and the complete copied suite without owner
fixtures, reports or profiles. Optional private historical audits remain outside public
source. Both suite boundaries are documented in the development guide.

## Learn and contribute

[Architecture](docs/ARCHITECTURE.md) Â· [API overview](docs/API_OVERVIEW.md) Â·
[Contributing](CONTRIBUTING.md) Â· [Development](docs/DEVELOPMENT.md) Â·
[Roadmap](ROADMAP.md) Â· [Security and privacy](SECURITY.md)

[Opening Studio](docs/OPENING_BOOK_STUDIO.md) Â·
[Opening Review](docs/GAME_REVIEW_OPENING_WORKSPACE.md) Â·
[Default opening provenance](docs/DEFAULT_OPENING_LIBRARY.md)

## Screenshots

Privacy-reviewed screenshots will be added here. Screenshots of personal games,
account names, paths or review notes are not publication assets by default.

## License

ChessWizard code is **GPL-3.0-or-later**; see [LICENSE](LICENSE) and [COPYING.md](COPYING.md).
The owner-provided project icon is separately dedicated under CC0-1.0; see
[icon provenance and permission](packaging/windows/assets/README.md).
Third-party data, libraries and other artwork retain their own terms. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [source distribution notes](source_info/SOURCE.md).
A source commit is not permission to redistribute an unreviewed binary, theme or icon.
