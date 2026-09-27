# ChessWizard Default Opening Library V1

ChessWizard Default Openings is one editable managed library containing 96 opening families. It is an opening map: names, defining positions and useful major branches, with neutral weights. It is not a recommendation engine or a complete theory database.

## Source and reproducibility

The source is the official [Lichess chess-openings repository](https://github.com/lichess-org/chess-openings), pinned to [`c67912be581f0793dbaa776be5ccf111e01f88d9`](https://github.com/lichess-org/chess-openings/tree/c67912be581f0793dbaa776be5ccf111e01f88d9), retrieved 2026-09-27. The upstream data carries the [CC0 dedication](https://github.com/lichess-org/chess-openings/blob/c67912be581f0793dbaa776be5ccf111e01f88d9/COPYING.txt). Exact original bytes, license, README, generator, commit and SHA256 records are retained in `data/default_openings/source/`.

The committed upstream TSV files contain ECO, name and PGN. UCI and legal-en-passant EPD are generated upstream columns, not silently invented source fields. All 3,815 rows were legally parsed; our derived PGN/UCI/EPD matched the pinned upstream `bin/gen.py` output exactly. Malformed rows are reported and fail the build. The existing ChessWizard canonical/Polyglot identity retains its established X-FEN en-passant convention; it is not confused with upstream EPD string formatting.

Offline regeneration, from the project root:

```powershell
.venv/Scripts/python.exe -B -m tools.build_default_openings --output build/default-openings-new
```

The output directory must not exist. The tool verifies pinned hashes, parses all rows, applies `data/default_openings/curation.json`, creates legal canonical graphs, serializes through the existing package repository, independently reads the package, exports and legally decodes the Polyglot union, and writes build/provenance/exclusion/candidate-ranking receipts. IDs, order and authoring timestamps are deterministic; timestamps use the pinned upstream commit date. Repeated builds with the same source, curation and Python/chess/SQLite environment produce identical `.cwbook` and `.bin` bytes. Cross-runtime comparisons should additionally use semantic graph identities.

The four runtime assets are `ChessWizard Default Openings.cwbook`, `ChessWizard Default Openings.bin`, `COPYING.txt` and `manifest.json`. Copy only these reviewed generated outputs into `assets/openings/` for a future approved update; do not copy local game audits or owner libraries. Generated build reports are development artifacts. No download or engine request happens at application startup.

## Selection and pruning

Selection is an explicit semantic/ECO coverage review of 96 useful families and reference systems, not the first 100 names or a claimed statistical top-100 list. Major e4/d4 defenses, open games, flank openings, systems and common gambits are represented. Limited reference sidelines remain useful for recognition. `family_candidates.json` ranks candidates by source breadth, explicitly not playing frequency. The attempted official Lichess master Explorer frequency request returned HTTP 401; no frequency was fabricated and no authentication workaround was attempted. Reliable future frequency evidence can refine the review separately.

The data configuration lists every family and its side. Broad established families receive explicit major-variation allowlists; reviewed nested subvariations have their own allowlists. Generic route bounds are 14 plies, reviewed major-family routes 18, selected subvariations 22. Additional same-name continuations are limited to four plies beyond that name's shortest included route. These are editorial content bounds, not analysis thresholds or per-family quotas. All 2,996 excluded rows retain their precise reason in the build report. No malformed row was accepted.

Family aliases and promotions are explicit: London routes appearing under Queen's Pawn/Indian are grouped into London; related accepted/declined gambit labels are grouped; reviewed comma-bearing family names are normalized. Names are not split blindly. A nested visible parent must have a source-defined position on the legal child route; otherwise the retained label is an honest compound name, without inventing a parent position. The retained data includes 472 distinct named variation paths.

There is no engine-generated theory. Every included move belongs to an official source route. Every edge has weight 50 and `preferred=False`. The companion union keeps equal duplicate weights once; it never sums prevalence or selects a favorite from source ordering. Conflicting weights and Polyglot collisions fail export.

## Entry and transposition contract

The optional, versioned `books.metadata_json.opening_entry` contract stores explicit canonical position FENs. Each selected source endpoint is a confirmed family entry or later re-entry anchor. Setup positions remain in the editable graph so Studio can show and extend the entire route, but they cannot alone establish membership in the selected opening.

There are 819 family/position anchors and 1,387 unique authored positions. Canonical identity includes pieces, turn, castling rights and relevant en passant, excluding clocks. A transposed actual game reaches the same board ID. Recognition never relies solely on a SAN prefix or one shared pawn move. Disabling/deleting the only active route to an anchor makes that unreachable anchor unavailable for entry.

Before an explicit entry:

- `entered_book` is false; no deviation, Opening Gap, adherence decision opportunity or opening-accuracy window is created.
- Lookup still permits pure graph browsing and Studio authoring.

After entry:

- Existing membership, deviation, bounded continuation and gap aggregation rules apply.
- `entry_ply` records the observed activation; the accuracy window begins at the following decision. Numerical Accuracy V1 formulas and engine evidence are unchanged.
- Legacy books without this metadata retain their established consecutive-authored-move entry policy and window semantics.

Pirc starts at its defensible setup (`e4 d6 d4 Nf6 Nc3 g6`) or a retained named endpoint. `1.d4 d6`, `1.e4 d6`, and `1.e4 d6 2.d4 Nf6` alone do not activate it. King's Indian setup-only labels are similarly excluded before sufficient defining development. Generic labels such as King's Pawn Game intentionally have much earlier defining positions; matching those does not imply deep opening knowledge.

Variation labels live on defining destination positions via the existing editable move name and optional `opening_named_parents` metadata. Alternate incoming edges resolve to shared logical named-path IDs. A variation is not active before its board is reached. Repeated same-name recognition endpoints preserve transposition support but do not create repeated same-name Studio headings along one continuation. Branches remain legal clickable moves, and shared graph positions still use the existing bounded browser.

All entry/name metadata participates in content/currentness identities; entry changes affect membership identity. Parent/path label changes affect label identity. There is no game-database migration, durable assessment write or analyzer policy change.

## Side and editability

Clearly Black-authored defenses receive Black (French, Caro-Kann, Pirc, Sicilian and so on). Clearly White-authored attacks/systems receive White (London, Italian, Spanish, English). Broad shared categories or uncertain intent use Both/reference. Side labels are explicit data, not runtime name guesses. They remain editable through Opening Details.

Studio opens the managed copy read/write in `%LOCALAPPDATA%/ChessWizard/opening_books/` (or the existing `CHESSWIZARD_DATA_DIR` override). Add moves, extend branches, rename lines, change notes, add books and export through existing services. Stockfish Lines remains available only when the user requests it. `.cwbook` is authoritative; `.bin` loses family names, hierarchy, entry gates and provenance and should never be used to reconstruct them.

Entry metadata is advanced content metadata in V1. Normal branch/deeper-line editing works immediately. Inventing a completely different family setup may require a separately authored opening or a future explicit anchor editor; the application must not guess new family entry anchors from arbitrary edits.

## First install, updates and rollback

`default_opening_install.seed_default_openings()` is an explicit startup step, independent of Tkinter and the game database. Read/list services never seed. Only a profile without a library catalog or existing loose `.cwbook` files receives an editable copy. The library is the Studio authoring home. A later launch, customized library, existing empty catalog or intentionally removed content does not trigger replacement/reseeding. Future default upgrades must be explicit imports/merges with user preservation; there is no destructive automatic refresh.

The Windows spec includes only the four public runtime assets. The package provenance classifier identifies their CC0 source data; other `.cwbook` package members are rejected. No owner library is a release input. This task prepares inputs only; a later package must receive a new exact-package audit and its own release approval.

The owner-authorized current-profile replacement uses the existing `opening_library_backup.backup_managed_books` workflow first. Its coherent SQLite backups, exact original paths/raw hashes, semantic book identities, quick checks and foreign keys are verified. A separately seeded and inspected replacement directory is staged. The original managed directory is moved intact beside its verified backup outside normal library storage, then the staged directory takes its place. A failed second rename restores the original directory. No recursive deletion is used and no game/profile settings are rewritten. Restore is an explicit operation: close Studio, preserve any newer edits, then select the appropriate archived catalog and book files together.

## Validation artifacts

`reports/DEFAULT_OPENING_LIBRARY_V1.md` records the final installation and safety result. Its `default_opening_library_v1/` evidence folder contains the source/build receipts, all exclusions, twelve-family trust audit, copied-game comparison, backup receipt and test logs. Private copied game rows never enter the runtime asset directory.

The focused tests cover malformed PGN/UCI/EPD, all twelve named family entry/non-entry pairs, French/Pirc/London transpositions, delayed variation activation, parent hierarchy, currentness, disabled anchors, deterministic generation, legal Polyglot decoding, load/save/edit/delete, isolated Studio loading, fresh seeding, customized restart and fail-before-write hash checks. Full-suite and protected-data verification accompany the release report.
