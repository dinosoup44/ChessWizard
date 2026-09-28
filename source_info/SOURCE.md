# Corresponding source and release identity

For a source checkout, start with [Development](../docs/DEVELOPMENT.md) and
[public-source boundaries](../docs/PUBLIC_SOURCE.md). The entries below record
separate dated binary rehearsals. Earlier unresolved-packager statements are
superseded by the later PyInstaller closure. They do not certify a new package
or authorize publication of the current working directory.


Status: distribution plan, checked 2026-09-15. ChessWizard 1.0.0-beta is not yet a
published or packaged release. No source archive URL is invented here.

## Chosen distribution model

Use GPL-3.0-or-later for ChessWizard and retain third-party licenses. Supply a
matching **source companion alongside every Windows binary release**. Prefer a
same-release download with equivalent free access, not a mutable master branch,
a vague homepage, an unspecified future offer, or a source available only on
request. For an offline transfer, hand over the source companion with the binary.
A private external beta is still distribution to its recipients.

The companion is one immutable snapshot containing application source/build
instructions plus separate pinned dependency source archives and required data.
A public source repository can contain ChessWizard and dependency manifests without
vendoring those implementations, provided the release source companion actually
supplies the corresponding dependencies. License files alone do not satisfy source
obligations. GPL section 6(d) permits equivalent source access; retaining it with
the same release avoids dependence solely on another site's continued availability.
See the full local LICENSE, especially sections 1, 4–6, and
https://www.gnu.org/licenses/gpl-faq.en.html#SourceAndBinaryOnDifferentSites.

## Exact Stockfish identity — established

The local executable was compared byte-for-byte by SHA256 to the official sf_18
AVX2 ZIP. The ZIP digest also matched GitHub's release-asset digest. All 86 local
files matched the official archive; 73 source/documentation files additionally
matched the pinned upstream Git tree (allowing line-ending normalization).
No ChessWizard modification was found in that binary or accompanying source.

- Binary: `stockfish-windows-x86-64-avx2.exe`, 114,007,552 bytes.
- Version / architecture: Stockfish 18, x86-64-avx2, 64-bit AVX2/SSE41/SSSE3/SSE2/POPCNT.
- Compiler reported by the binary: MinGW64 GCC 15.2.0. UCI/compiler/readiness commands
  only; no `go`, bench, analysis or game search was run.
- Binary SHA256: `c86215fa1977d53b82ed854540a4c7b025be4cd042276c85ba3de53fb9118911`.
- Source commit: `cb3d4ee9b47d0c5aae855b12379378ea1439675c` (`sf_18`).
- Official archive: https://github.com/official-stockfish/Stockfish/releases/download/sf_18/stockfish-windows-x86-64-avx2.zip
- Archive SHA256: `6f6c272ebd6ea594377715235c8a7326f75940ef4f4f856f45106028fe6ae900`.
- Pinned source tree: https://github.com/official-stockfish/Stockfish/tree/cb3d4ee9b47d0c5aae855b12379378ea1439675c
- Pinned source archive: https://github.com/official-stockfish/Stockfish/archive/cb3d4ee9b47d0c5aae855b12379378ea1439675c.tar.gz

Choose approach A: retain the corresponding Stockfish source in the **source
companion**, not a second large copy inside the application tree. Include src,
Makefile, required scripts/build workflow, license, authors, and exact network
inputs. The existing official ZIP already includes source, but embeds networks
only in the executable; do not claim its source directory alone is sufficient.
Keep a pinned copy of the upstream build instructions with the source; a bare
source commit is not a substitute for the build recipe/toolchain record.

Networks (CC0-1.0 per the official repository) are:

- `nn-c288c895ea92.nnue`, 108,919,594 bytes; full SHA256
  `c288c895ea924429ea9092e3f36b2b3c1f00f2a3a4c759ff7e57e79e3b43e4a7`,
  verified through the official Git LFS pointer.
- `nn-37f18f62d772.nnue`, 3,519,630 bytes; pinned Git blob
  `b8e0f13311c67bcc2997947ed528ca09419e947f`. Compute/record full SHA256 when acquiring
  the release input; the filename already specifies its SHA256 prefix.

Pinned source URLs are in `stockfish_identity.json`. Both returned HTTP 200 at
commit `010b123b69a46018ab83ac4ce99273b727a542ab`. The Fishtest API returned 403 in this
audit, so the plan also records the official network repository rather than relying
only on that endpoint. No network files or third-party implementations were copied
into ChessWizard modules. Official source availability and identities are established;
assembling and hashing the companion is part of the later approved release operation.

Stockfish source headers grant GPL v3 or later. Retain GPL text and AUTHORS.
Its NNUE README also acknowledges Leela training data; preserve that upstream
acknowledgement. The training corpus itself is not being distributed here. The
compiler's standard runtime/system-library treatment does not require shipping
a compiler installation; preserve any applicable toolchain notices in a rebuilt
engine distribution. Do not silently substitute another engine binary.

## python-chess and Pillow

The implementation imported as `chess` is distribution **chess 1.11.2**, licensed
GPL-3.0-or-later. Installed **python-chess 1.999** only depends on chess and is not
needed in the minimal runtime. Include the unmodified exact chess source archive
and any actual local modifications in the source companion; do not rely on a
broad `chess>=1` dependency or a future PyPI version.

- chess sdist: https://files.pythonhosted.org/packages/93/09/7d04d7581ae3bb8b598017941781bceb7959dd1b13e3ebf7b6a2cd843bc9/chess-1.11.2.tar.gz
- SHA256: `a8b43e5678fdb3000695bdaa573117ad683761e5ca38e591c4826eba6d25bb39`.
- Pillow sdist: https://files.pythonhosted.org/packages/1c/3d/bb7fca845737cf9d7dbde16ed1843984665ff2e0a518f5db43e77ec540b9/pillow-12.3.0.tar.gz
- SHA256: `3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce`.

Archive hashes were read from version-specific PyPI metadata, not verified by
executing or installing source. At release, verify downloaded bytes and match the
shipped modules. Preserve the Pillow wheel-build dependency versions/recipes and
corresponding native library source archives for the extensions actually collected.
All third-party copyrights and licenses remain intact. Keep source archives as
separate release inputs; no third-party implementation was vendored by this task.

## Python and its native/data inputs

The installed interpreter is CPython **3.14.7**, build tag `v3.14.7:823f032`, AMD64.
Installation metadata identifies:

- https://www.python.org/ftp/python/3.14.7/python-3.14.7-amd64.zip
- Archive SHA256 `ac1a727a71738e11de80b76e975f9b8a258aea6412bfc31696b929d59c6aafd0`
  (installation metadata, not a fresh archive download verification).
- Source: https://www.python.org/ftp/python/3.14.7/Python-3.14.7.tar.xz
- Windows external dependencies: https://github.com/python/cpython/blob/v3.14.7/PCbuild/get_externals.bat

Keep the full PSF/history license, Windows additional conditions and incorporated
notices, not just a PSF paragraph. Preserve Tcl/Tk licenses embedded in the actual
DLLs and the extra Python native notices. Supply the corresponding interpreter
and required dependency sources conservatively rather than silently assuming the
whole bundled interpreter is exempt as a System Library.

The embedded Tcl Public Suffix List is MPL-2.0. Extract its **exact** uncompressed
source data from the selected tcl90.dll into the source companion, retaining its
header, and verify `tcl_psl_identity.json`. Do not replace it with today's online
list and call that corresponding source. No fresh external list is needed.
Tcl/Tk logos are upstream runtime resources, covered by retained notices.

The final packaging manifest must identify which stdlib/Pillow native extensions,
DLLs and associated data it collects. Complete their exact source/archive hashes
and retained notices before distribution. In particular, retain the applicable
Microsoft runtime conditions without imposing them on GPL-covered application code.

## Packager — unresolved selection

No active-project spec, pyproject/build config, installed PyInstaller, or other
selected packager was found. The separate Art Tester build does not establish
ChessWizard's packaging mechanism. No tool was installed or changed in this task.

If PyInstaller is chosen later, pin its exact version, bootloader inputs and build
configuration. Official 6.22.3 documentation currently says unmodified generated
applications need not include its own license/credit; bundled dependency licenses
still govern. Modified/redistributed packager code has separate obligations. This
conditional research is not a claim that 6.22.3 is selected or tested here.

## Binary versus source contents

Windows binary package: application, required runtime modules/DLLs/data, one exact
Stockfish executable, safe default code rendering and empty-schema bootstrap,
LICENSE, COPYING.md, README_RELEASE.md, THIRD_PARTY_NOTICES.md, reviewed licenses,
and source_info with real release source identity/access instructions.

Source companion: the exact application/shared-service/GUI/schema source used by
the binary; actual packager spec/hooks and reproducible build/install instructions;
reviewed runtime lock/wheel hashes; all required corresponding dependency sources,
Stockfish build inputs and network data; applicable notices; source manifest and
checksum. Preserve the source needed to build/modify the shipped work, even if a
module's name starts `analyze_`. Do not execute legacy launchers to gather it.

Both exclude personal merlin.db, all DB backups/caches/journals, private review
JSONL/cohort metadata, user themes/fonts/settings, audit scratch reports, credentials,
raw venv, desktop shortcuts, private history and machine-specific configuration.
Optional internal QA datasets are not needed to build or run the release. Source
and tests must undergo privacy review; required code cannot simply be omitted to
hide a private hard-coded value. Correct such issues before building, then identify
that matching source snapshot rather than claiming a mismatched redacted snapshot.

No Git repository exists at the active root. For this release, use an immutable
source archive SHA256 and per-file manifest; a future public Git tag may supplement
it. `runtime_inputs.json` pins the currently audited inputs but is not the final
source archive hash or a claim of reproducible bit-for-bit compilation.

Suggested layout once a build is separately authorized:

    ChessWizard/
        ChessWizard.exe
        ... actual collected runtime files ...
        LICENSE
        COPYING.md
        README_RELEASE.md
        THIRD_PARTY_NOTICES.md
        licenses/
        source_info/SOURCE.md
        source_info/release-identity.json

    Same release/download location:
        ChessWizard-1.0.0-beta-source.tar.gz
        SHA256SUMS

No archive, tag, upload, final backup or package is created by this plan. Packaging
selection and collected-file reconciliation are the remaining licensing gate;
manual Windows DPI acceptance is separate. Once the gate is resolved, replace
pre-release status with actual source archive identity and availability before
sending a build to any external tester.

## Onedir rehearsal closure (2026-09-15)

The local rehearsal now uses PyInstaller 6.22.3, CPython 3.14.7 AMD64, chess
1.11.2 and Pillow 12.3.0. The exact build is identified by the per-file frozen
manifest and source-input hashes in the local build reports. Packager/collected
file closure supersedes the earlier pending-packager statements above; it does
not authorize distribution or provide a public source download.

The reproducible configuration is `packaging/windows/ChessWizard.spec`,
`requirements-build.lock.txt` and `build.ps1`. The binary uses one runtime and
one embedded-network Stockfish binary. Notices/source pointers live under
`_internal`; the Stockfish source tree and external network files are separate.

Prepared local Stockfish inputs: source archive at exact commit
cb3d4ee9b47d0c5aae855b12379378ea1439675c, SHA256
b5d3b85e08cdf9189a4753142eb21a4333983d97501531b19e1cd1ac9fc43f35;
small network nn-37f18f62d772.nnue SHA256
37f18f62d772f3107e1d6aaca3898c130c3c86f2ab63e6555fbbca20635a899d.
The previously recorded big-network hash is unchanged. Both networks passed
verification against pinned upstream identities. The exact MPL-covered Tcl
public suffix data is also staged separately with its recorded hash.

Before public release, stage matching application runtime sources (including
schema/bootstrap and shared services), the spec/locked build instructions,
notices and exact dependency source inputs described above. Include build-only
packaging/audit scripts needed to reproduce the build; exclude private reports,
cohort/review data, databases, credentials, settings, themes and build caches.
Use the exact source-input manifest rather than the whole working directory.
Add a final source archive SHA256 and working adjacent download only when an
external release is separately approved. No source archive or upload is created
by this internal rehearsal.


## Current beta installer distribution (2026-09-20)

The current 1.0.0-beta installer is built from the current accepted runtime sources, not a prior rehearsal folder. Its matching `ChessWizard-1.0.0-beta-Corresponding-Source.zip` is staged alongside the tester ZIP. Give the source companion to every tester together with the Windows package. It includes the exact consumed application sources, approved icon sources, locked build instructions and required Stockfish source/networks plus exact Tcl MPL data. The companion contains no user databases or libraries. SHA256SUMS binds the local distribution artifacts. No public download or upload is claimed. The preceding rehearsal entries are historical; the current build receipt identifies the exact artifacts.

## Servicing and plugin source additions

For the Phase 4 build, include `plugin_host.py`, `servicing_host.py`,
`application_lifetime.py`, `servicing_*.py`, `chesswizard_plugin_api/`, and the
runtime plugin service modules identified by **all** `PYZ-*.toc` inputs.
Include the corresponding Inno scripts, inventory/build tools, build lock, and
installation/upgrade instructions. The source-companion assembler reads every
container's PYZ inventory; a desktop-only PYZ list is insufficient.

Pin the additional pure-Python upstream distributions: installer 0.7.0
([upstream](https://github.com/pypa/installer)) and packaging 26.3
([upstream](https://github.com/pypa/packaging)). Retain their complete copied
license texts. Stage matching upstream sources before distributing a changed
binary/source companion; an old beta companion does not cover these additions.
The Phase 4 owner handoff is a local servicing test, not permission to publish.
