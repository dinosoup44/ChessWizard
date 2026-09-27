# Contributing to ChessWizard

Welcome. Small, well-explained changes are useful, including reproducible bug reports,
clearer documentation and tests for edge cases.

**Truth above all else.**

**Prefer safe incremental changes over broad sweeping rewrites.**

## Get started

Follow [DEVELOPMENT.md](docs/DEVELOPMENT.md) to install the pinned dependencies and use
an isolated profile. Read [API_OVERVIEW.md](docs/API_OVERVIEW.md) before adding a service.
A new frontend should be able to use important chess/business logic without Tkinter.

Create a branch for one focused change. Explain the concrete problem, the resulting
behavior and what you tested in the pull request. Do not include unrelated formatting,
new dependency systems or large refactors. Discuss analyzer policy changes before
implementing them. Maintainers review before merging; release approval is separate.

## Evidence and analyzer contracts

Keep calculation, engine access and persistence separate. Specialists accept a specific
position and return structured results. The crawler owns orchestration; shared engine
services own exact request/cache identity; repositories preserve candidate IDs and
training links. Reuse board/proof primitives instead of duplicating another feature's
private logic. See [Adding analyzers](docs/ADDING_ANALYZERS.md).

A motif's geometry is not proof of a payoff. Preserve legal PV replay, attribution,
settlement, relevant defense/recapture evidence, version/profile identity and incomplete
states. Never turn uncertainty or interruption into a verified or rejected tactic.
Presentation/Scale cannot override proof or admission rules. Document policy changes;
do not silently add chess claims or tune thresholds just to make a fixture pass.

## Tests

Use deterministic synthetic positions and temporary databases/libraries. Add a regression
that demonstrates the contract or edge case, then run relevant tests and the full suite:

```powershell
.\.venv\Scripts\python.exe -B tools\run_tests.py --pattern test_opening_book.py
.\.venv\Scripts\python.exe -B tools\run_tests.py
.\.venv\Scripts\python.exe -B tools\check_public_copy.py
.\.venv\Scripts\python.exe -B tools\check_pydoc.py
.\.venv\Scripts\python.exe -B tools\build_pydoc.py
```

Public contracts and fixtures must remain self-contained. Reusable test support belongs
in `tests/support/`. Exact private historical audits belong in ignored `tests/local_history/`
and run additionally in the normal local suite. Never import that directory or private
reports from public tests. Preserve historical assertions locally and add synthetic
equivalents for reusable behavior; do not hide dependency failures with conditional skips.

GUI tests need a Windows desktop session with Tk. No routine test may require a production
database or live account. Real-engine acceptance is explicitly opt-in and must use a
temporary profile. Keep network responses and engine evidence controlled in unit tests.

## Python documentation

For every new or materially modified public/reusable class, function, method or service:
use explicit type annotations and an immediate triple-quoted PEP 257 docstring in
Google style. Include a concise description, `Args:` for parameters, `Returns:` for
returned values, and `Raises:` for expected exceptions callers must handle.
Comments explain why; code explains what. Private/trivial helpers may stay concise.
Do not mass-edit untouched modules just to reformat their documentation.

Update the subsystem guide and `tools/public_api.json` when adding a public API. The
index intentionally excludes launchers and dangerous historical scripts. Validate with
`tools/check_pydoc.py`; generate browsable HTML with `tools/build_pydoc.py` and open
`build/pydoc/index.html`. A passing render does not certify type/docstring completeness;
review the API contract as well.

## Privacy, provenance and assets

Never commit a personal database, editable opening library, settings, reviews, account
identifiers, credentials or unreviewed logs/screenshots. Inspect every staged file.
The exact four `assets/openings/` runtime defaults are public reproducible content;
a similarly named file under your profile is your editable private copy.

New source data/assets need a verifiable upstream URL, license, version/commit and hashes.
Do not assume public access implies redistribution permission. Theme packs are data and
allowlisted assets only, with traversal/symlink/size validation; no scripts or plugins.
Do not publish the application icon until its public reuse terms are explicitly settled.

Source contributions use the existing GPL-3.0-or-later project terms. Preserve third-party
notices. No contributor agreement or copyright transfer is invented by this guide.
