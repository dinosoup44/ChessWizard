# Third-party notices — ChessWizard 1.0.0-beta

Checked 2026-09-15 against the actual PyInstaller 6.22.3 onedir rehearsal,
installed files, embedded DLL resources and official upstream metadata. One
executable shares the runtime across four existing screens. Individual copyrights
remain with their authors; complete license texts are in `licenses/`.

## Principal runtime components

| Component / exact observed version | Project and license | Bundled form / notice | Source obligation and planned handling |
|---|---|---|---|
| python-chess implementation: `chess` 1.11.2 | [python-chess](https://github.com/niklasf/python-chess), GPL-3.0-or-later | Python library source or frozen bytecode; `licenses/python-chess/LICENSE.txt` | Matching source and modifications, if any, in the source companion; pinned sdist below |
| Pillow 12.3.0 | [Pillow](https://github.com/python-pillow/Pillow), MIT-CMU plus native terms | Python modules/native extensions; complete `licenses/pillow/LICENSE.txt` | Preserve full notices; include matching source/build inputs in the conservative combined-GPL source companion |
| CPython 3.14.7, AMD64, build `823f032` | [CPython](https://www.python.org/), PSF-2.0 and historical/incorporated terms | Interpreter, required stdlib/native files; `licenses/python/LICENSE.txt` and `INCORPORATED_SOFTWARE.rst.txt` | Retain full notices; pin upstream source/build inputs; no claim that every stdlib DLL must ship |
| Stockfish 18, x86-64 AVX2, MinGW GCC 15.2.0 | [Stockfish sf_18](https://github.com/official-stockfish/Stockfish/releases/tag/sf_18), GPL-3.0-or-later in source headers; GPL v3 text | Separate unmodified executable; `licenses/stockfish/Copying.txt`, AUTHORS, README.md | Exact source, build scripts and networks; see SOURCE.md and stockfish_identity.json |
| Two Stockfish NNUE networks | [official network repository](https://github.com/official-stockfish/networks), CC0-1.0 | Embedded in engine; `licenses/stockfish/CC0-1.0.txt` | Preserve exact named network inputs in source companion; names/hashes below |

Installed `python-chess` 1.999 is a compatibility/meta distribution requiring
`chess`; it is not a second implementation. The imported implementation version
is 1.11.2, and its full GPL text is included. Pin the actual `chess` dependency,
not just the broad meta-package requirement.

## CPython native and incorporated components

These are observed build inputs or native dependencies, not additional pip packages.
Upstream `v3.14.7/PCbuild/get_externals.bat` establishes bundled build versions;
DLL/API observations corroborate the core runtime versions. The collected
native-file inventory includes the components below; system APIs remain supplied
by Windows rather than copied from unrelated installations. Python's two complete notice documents also cover historical
stdlib contributions (including sockets, dtoa, SipHash, asyncio, Unicode and others).

| Component | Version / identity | License and evidence |
|---|---|---|
| Tcl / Tk | 9.0.4 / 9.0.4; Python dependency tags tcl-9.0.4.0, tk-9.0.4.1 | Tcl permissive terms; exact license.terms extracted from installed DLL zip resources |
| LibTomMath | Revision bundled in Tcl dependency tag tcl-9.0.4.0 | Unlicense; `licenses/python/LIBTOMMATH_LICENSE.txt`; retain this pinned source tree rather than inventing a separate version |
| Tcl Public Suffix List | Exact embedded snapshot identified by SHA256 in `source_info/tcl_psl_identity.json` | MPL-2.0; `licenses/python/MPL-2.0.txt`; exact decompressed source data must accompany the source offer |
| OpenSSL | 3.5.7 | Apache-2.0; Python incorporated notices; `_ssl`/`_hashlib` and libssl/libcrypto collection determines shipped use |
| SQLite | 3.50.4; dependency sqlite-3.50.4.0 | Public domain, [SQLite copyright](https://sqlite.org/copyright.html); bundled sqlite3.dll |
| libffi | 3.4.4 | MIT; Python installed LICENSE, if `_ctypes`/libffi collected |
| bzip2 | 1.0.8 | bzip2-1.0.6 family of terms; actual text in Python LICENSE |
| xz / liblzma | 5.2.5 | Public-domain library portions; retain upstream per-file notices in source companion; optional `_lzma` |
| zlib-ng | 2.2.4; runtime compatibility string 1.3.1.zlib-ng | Zlib; `licenses/python/ZLIB_NG_LICENSE.txt`; Tcl/core compression dependency |
| mpdecimal | 4.0.0 | BSD-2-Clause; incorporated notices; optional `_decimal` |
| Expat | 2.8.2 from runtime API | MIT; incorporated notices; pyexpat/_elementtree collection-dependent |
| Zstandard | 1.5.7 upstream build input | BSD-3-Clause option; incorporated notices for Python wrapper, preserve upstream library license if `_zstd` collected |
| Microsoft VC runtime | vcruntime140 / vcruntime140_1 14.51.36247.0 | Microsoft distributable-code conditions in installed Python LICENSE; applies only to those portions, not ChessWizard's GPL code |
| Windows system libraries | Target Windows APIs (kernel/user/GDI/UCRT etc.) | Supplied by Windows; do not copy arbitrary system DLLs into the package |

The installed Python build explicitly carries Windows redistribution conditions.
Retain notices, do not imply Microsoft endorsement, and respect those conditions
for Microsoft portions. Final packaging must record how they are supplied to
recipients; this is not a GPL restriction on ChessWizard. System-library exclusions
from GPL corresponding source do not erase their own redistribution terms.
The upstream interpreter archive identity is recorded in the audit report.

Tcl's embedded Public Suffix List is distinct from the excluded Python `certifi`
and `idna` packages. It remains inside tcl90.dll even though ChessWizard does not
invoke the Tcl cookie-jar feature. Preserve its MPL notice and exact source form.

## Pillow native-library notices

The actual 12.3.0 Windows wheel's combined LICENSE identifies the following.
Preserve that file verbatim, including internal subcomponent/patent notices.
The frozen build contains _imaging, _imagingcms, _imagingmath, _imagingtk,
_avif and _webp. It does not collect _imagingft or _imagingmorph. The table is an
inventory of the intact upstream wheel notice, not a claim that every optional
font component ships. Keeping that upstream combined text intact avoids dropping
subcomponent obligations; no separate unused-library notice has been added.

| Library | Version in installed notice | License / upstream |
|---|---|---|
| Brotli | 1.2.0 | MIT — https://github.com/google/brotli |
| FreeType | 2.14.3 | FTL option selected, compatible with GPLv3 — https://freetype.org |
| HarfBuzz | 14.2.1 | MIT-style Old MIT terms — https://github.com/harfbuzz/harfbuzz |
| Little CMS | 2.19.1 in notice; feature API reports 2.19 | MIT — https://www.littlecms.com |
| libavif | 1.4.2 | BSD-2-Clause plus included subcomponent terms — https://github.com/AOMediaCodec/libavif |
| libjpeg-turbo | 3.1.4.1 | IJG, BSD-3-Clause and Zlib terms — https://libjpeg-turbo.org |
| libpng | 1.6.58 | libpng license text — https://www.libpng.org |
| libwebp | 1.6.0 | BSD-3-Clause — https://chromium.googlesource.com/webm/libwebp |
| OpenJPEG | 2.5.4 | BSD-2-Clause — https://www.openjpeg.org |
| libtiff | 4.7.1 | libtiff permissive terms — https://libtiff.gitlab.io/libtiff |
| xz/liblzma | 5.8.3 | Per-file public-domain/permissive library terms; complete notice retained — https://tukaani.org/xz |
| zlib-ng | 2.3.3 | Zlib — https://github.com/zlib-ng/zlib-ng |

This software is based in part on the work of the Independent JPEG Group.
It includes bzip2 software by Julian R. Seward where the Python bzip2 extension
is bundled. Other required attributions, disclaimers and individual copyright
notices appear verbatim in the complete combined notices.

## Not selected for the four-screen runtime

- pip 26.2.1 (MIT and its vendored licenses): build-only; exclude installer/vendor tree.
- Requests 2.34.2 (Apache-2.0), urllib3 2.7.0 (MIT), idna 3.19 (BSD-3-Clause),
  charset-normalizer 3.5.1 (MIT), certifi 2026.7.22 (MPL-2.0): installed for excluded
  import/development utilities; none appears in the reviewed application import
  closure. If those tools later ship, revise notices and the source plan first.
- python-chess 1.999 meta distribution: not required when chess 1.11.2 is pinned.
- Test fixtures, developer reports, raw venv, package managers and documentation
  build extras do not ship. No NumPy, pytest, PyInstaller or alternative packager
  ships in the application; PyInstaller is installed only in the isolated build environment.

PyInstaller is pinned to 6.22.3 in the isolated build environment. Its build
tooling is excluded, while its bootloader, loader and selected runtime hooks
are present. Their exact license/exception is documented below and copied from
the installed distribution. This does not alter dependency GPL obligations.

## Artwork, fonts and UI resources

ChessWizard bundles no private image theme, artist artwork or custom font. Default
pieces are Unicode characters rendered using installed system fonts; no font file
is redistributed. User-imported themes stay private user assets, not release assets.

CPython's Tk DLL does contain upstream Tcl/Tk logo images and scripts. These are
covered by its embedded terms and explicit image permission, retained in
`licenses/python/TK_IMAGES_README.txt`. They are not private ChessWizard artwork.
No new logo, icon or third-party theme has been approved for bundling.

## Source and scope

The source companion must cover ChessWizard, chess, and the other non-system
components required to reproduce the distributed application, including relevant
native build inputs. Permissive licensing alone is not a reason to omit required
combined-work source. Keep third-party source archives separate, pinned and
unaltered instead of copying implementations into application modules.
See [source_info/SOURCE.md](source_info/SOURCE.md). These files prepare distribution;
they do not assert that a nonexistent binary/source release is already compliant.

## Frozen packager runtime

PyInstaller 6.22.3 (build-only) contributes its unmodified bootloader/loader
under GPL-2.0-or-later with the Bootloader Exception, and runtime hooks plus
`_pyi_rth_utils` under Apache-2.0. Copyright PyInstaller Development Team.
See `licenses/pyinstaller/COPYING.txt` for exact terms, exception and full license texts.
Application and dependency GPL obligations are unchanged. Build-only hooks-contrib,
pefile, altgraph and setuptools are not runtime dependencies. Packaging becomes a
runtime dependency in the plugin/servicing build described below.

## Public source preparation (2026-09-27)

The dated binary inventory above is historical, not a new package certification.
The current source proposal excludes executable engine/runtime/build outputs.
Its code remains GPL-3.0-or-later. The pinned Lichess chess-openings inputs and
four default-opening assets retain their CC0-1.0 source dedication; see
[default provenance](docs/DEFAULT_OPENING_LIBRARY.md) and the exact upstream
COPYING.txt in `data/default_openings/source/`.

The owner confirmed on 2026-09-27 that the application icon was generated by the
owner using ChatGPT for ChessWizard, and explicitly selected **CC0-1.0** for the
preserved PNG and derived ICO. These are owner-provided project artwork, approved
for inclusion in public source. See [provenance and permission](packaging/windows/assets/README.md),
[asset hashes](packaging/windows/assets/provenance.json) and the
[complete CC0 legal text](packaging/windows/assets/LICENSE.txt). The dedication
applies to those two files, to the extent of the owner's copyright/related rights;
it does not relicense code or user themes. System fonts are not redistributed.

Inno Setup's retained terms are in `licenses/inno-setup/LICENSE.txt`; the compiler
is an optional external build dependency. Before any future binary distribution,
re-run the exact package/source/notice audit against that build. Historical notice
hashes and receipts must not be presented as certification of changed inputs.

## Plugin and servicing runtime (Phase 4)

The frozen desktop, `ChessWizardPluginHost`, and `ChessWizardServicing` are
separately inventoried GPL-3.0-or-later ChessWizard application containers.
The public Plugin API V1 SDK is application source under the same license.
No external sample plugin implementation is included in those containers.

- **installer 0.7.0**: MIT, copyright Pradyun Gedam; the existing plugin service
  uses its pure-Python wheel installation library. Exact upstream terms are in
  `licenses/installer/LICENSE`. This does not include pip or resolve arbitrary dependencies.
- **packaging 26.3**: Apache-2.0 OR BSD-2-Clause; used for plugin version/dependency
  compatibility and installer downgrade comparison. Preserve `licenses/packaging/LICENSE`,
  `LICENSE.APACHE`, and `LICENSE.BSD`, including their upstream copyrights.
- **Inno Setup 6.7.3**: unchanged pinned compiler and installer runtime under its
  retained `licenses/inno-setup/LICENSE.txt`. No new servicing dependency is added.

The exact package audit inspects every collected file and every container's PYZ
and boot scripts. Hash inventory is an ownership/integrity record, not a code
signature or a grant of trust. Source companions must include both host entry
points, the SDK, the servicing modules, installer scripts, and the exact reviewed
runtime dependency sources. Existing Stockfish/network, CPython, Tcl/Tk, Pillow,
application GPL, default-opening, and artwork obligations remain in force.
