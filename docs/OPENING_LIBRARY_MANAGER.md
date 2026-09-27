# Opening Library Management — Studio V1.3

## Daily authoring lives in Studio

Use **Tools → Opening Book Studio** to choose, create, edit, rename and delete books.
Its Book dropdown lists managed books automatically. A blank inline New Book draft
is committed by Create Book or the first Save Move. No import/install/publish step
is involved. See [Studio guide](OPENING_BOOK_STUDIO.md).

Tools → Opening Library is advanced management: library hierarchy, enabled/primary
preferences, provenance, clone and library-level sharing/removal. Open in Studio
selects the exact existing book within the unified workspace. It is not required
for normal authoring. Opening an empty legacy library opens the workspace empty
state or its sensible existing-book default; new books use the canonical home.

## Library and book identity

Managed files live in `application_data_directory()/opening_books/`, normally
`%LOCALAPPDATA%/ChessWizard/opening_books/`; `CHESSWIZARD_DATA_DIR` isolates profiles.
One stable library UUID identifies one managed `.cwbook` containing any number of
books. Each book keeps its integer book_id within that library. Display names and
paths are not book identity. Assessment provenance is library UUID + book ID +
version/revision/content hash, consistently across Review and relevance services.

The existing V1 catalog schema is unchanged: its historically named
`installed_books` row represents a library file. `LibraryOptions` reads typed
library naming, per-book enabled choices and primary_book_id from the existing
provenance JSON envelope. The existing unique primary index still limits primary
to one library row; primary_book_id identifies exactly one book in that row.
No second primary concept or authoring lifecycle is introduced.

V1 single-book rows are readable without writes, preserving their original
reference ID and settings. New libraries use UUID:book_id reference tokens; all
public results also expose library_id and the actual authored book_id separately.
New books are discovered from a coherent read of the file, not registered as a
second copy or dependent catalog row. No schema migration or FULL backup was needed
for this implementation. Do not add new per-book side effects to Studio saves.

## Status and matching

| State | Editable | Manually selectable | Automatic matching |
|---|---|---|---|
| Draft | Yes | Yes | No |
| Active | Yes | Yes | When Enabled |
| Archived | Yes, retained | Yes | No |

Enabled is a per-book preference; primary is a single book-level study preference.
A disabled/Draft/Archived primary stays designated but does not automatically match.
Manual choices may inspect any available managed book, including nonmatching books.
They never imply that book moves are objectively best or alter engine Accuracy.

Game Review exposes **Library** then **Book**, each with None. Book choices depend
on the selected library and never depend on automatic relevance. Duplicate library
names receive a short identity suffix where necessary. Empty libraries are visible.
“No enabled Active book automatically matches” means precisely that; it does not
mean the user has no books. Missing/broken managed files are distinguished from an
empty catalog and reported in the manager.

Defaults examine Active + Enabled books using Opening Intelligence's unchanged
four-consecutive-authored-plies rule. Prefer a meaningfully matching primary;
otherwise choose a uniquely strongest (longest authored run, then matched plies)
match. Equal strongest matches remain ambiguous. No matches defaults to None.
There is no probability or opening score. Manual book/library/None selection is
remembered across games for this Review session and wins over defaults. Auto clears
both overrides. Explicit selection states whether a meaningful match exists.

## Live editing

`OpeningBookRepository.library_snapshot()` reads all books in one transaction.
`read_library()` uses a read-only connection; consumers never upgrade files.
Studio commits through the same authoring services as before. Desktop notifications
refresh registered Review/manager views after committed Studio actions. Review also
refreshes on focus, selector opening and normal view reload, with reentrancy guards.
The manager refreshes on focus and notifications. Selected facts continue to verify
book content via OpeningReviewSession. There is no persistent assessment cache.
No re-import or application restart is required between edits and use.

## Existing and external libraries

Existing managed files are not merged or rewritten for V1.3. Their books appear in
Studio's one dropdown, preserving every existing library/book reference. New Studio
books and external imports use one catalog-designated authoring home.

Studio **Import External Books** previews multiple books, versions, authors and
conflicts, imports the selection, and opens the editable result automatically.
Identical content reuses the existing managed reference. Same-name/different
content remains separate. The source never changes. Advanced External Preview is
read-only with one Import action; paths are shown only under Advanced Details.

The manager's advanced whole-library import remains available. It preserves the
original multi-book package as a separate managed file and explicitly confirms
partial overlaps. The lower-level V1 single-book service remains available to tools.
These compatibility paths never relocate existing references.

## Sharing, clone, removal, backups

Export/Share on a library exports all books; on a book exports just that book.
Studio's Export/Share Library writes a new external file and keeps editing the
canonical source. Clean serialization retains shared positions, book boundaries,
notes/sources, variation names, weights/preferred moves, versions and metadata.
No unrelated games or private application data is exported. A book's source/private
notes ARE authoring data and travel with it. `.cwbook` is editable/shareable;
`.bin` remains optional Polyglot interoperability export, unchanged.

Clone keeps the existing independent-copy contract with source provenance and a
new identity. In a multi-book library, Remove archives only the chosen book using
its existing lifecycle and clears its primary designation when explicitly approved.
Other books/IDs are untouched. Removing a single-book library retains the existing
recoverable file archive and provenance receipt. No user games are deleted.

Managed libraries, including archived books, remain protected FULL-backup data.
The existing SQLite snapshot backup/verification integration is unchanged and
rehearsed with multi-book libraries. No FULL backup or retention deletion ran here.
The existing rolling rule remains: only after a new FULL backup is completely
verified, prune the oldest eligible ordinary FULL, preserve milestones/releases,
and record reclaimed space. This task changes no backup or retention code.

## Trust and future consumers

Untrusted files still pass the bounded V1/V2 schema, column/reference constraints,
legal move/position/graph, encoding and size checks. Unknown tables, triggers,
virtual/generated SQL, binary fields, symlinks/reparse traversal and active
external WAL/journals are rejected. JSON, notes, filenames and URLs are inert;
no engine, script, network fetch or external dependency load is performed.
New-library names never become filesystem paths; managed names are generated UUIDs.

Core services/models remain usable without Tkinter. Desktop notifications belong
to the UI only. Opening Accuracy retains managed library/book IDs, version/content
revision and game/variation provenance; V1.3 does not recalculate it.


## Opening Intelligence Application V1 — managed application

Select Library → Book in Game Review, then the bottom Opening tab to inspect the book facts.
Facts… retains detailed alternatives, authored weights and known-position evidence.
Draft books can be assessed manually without changing their status. Active + Enabled
still governs automatic defaults only. Saved Studio changes refresh the block and
facts without import/restart. ManagedOpeningIntelligenceService offers the same
book identity to batch consumers; no author file or game data is modified by assessment.


## Game Review Opening UX V1

Manual Library/Book (including No book) now persists across games for this Review
session. Auto explicitly restores matching defaults. An unrelated game keeps the
selected reference. Live edits retain selection and refresh facts; changed evidence
ends stale book exploration at its real-game anchor. Opening details now live in
the bottom Opening → Summary / Branch View tabs; the right-side selectors remain
compact. No durable setting or database migration was added. See the complete
[Opening UX guide](OPENING_INTELLIGENCE.md#game-review-opening-ux-v1).

## Studio deletion and the canonical authoring home

Catalog provenance now optionally contains `studio_home: true` for the one default
new-book destination and `studio_deleted_books: [book_id, ...]` for confirmed book
removals. These reuse the existing JSON envelope; no schema migration occurs.
Deleted books are omitted from Studio/manager/Review choices and whole-library
exports. Their underlying rows stay intact for recovery and ID reservation. Primary
selection is cleared if that book was primary. Backups retain the catalog and full
managed files, including recoverable graphs. Archived lifecycle is unchanged and
still manually selectable; it is not a substitute for Delete Book.
