# Sharing ChessWizard books

`.cwbook` is the editable ChessWizard sharing format. `.bin` is an optional
Polyglot export for other compatible chess software; it does not replace authored
notes, variation names or sharing metadata.

1. Create your own library directly in Studio; it is already managed. For an external
   `.cwbook`, use Tools → Opening Library → Import External Book, inspect the books
   and confirm importing the library. Originals remain untouched. Older owner-created
   files use Studio → Add to My ChessWizard Library instead.
2. Optionally edit Author, License and Description under Metadata. Fields may be
   blank. Existing package metadata stays intact; license text is not interpreted.
3. Export / Share to a **new** `.cwbook` file. A selected book exports just that book; selecting a library exports all its books.
   Its notes and source notes are included, so inspect private prose first.
4. Send that `.cwbook` to another user. They inspect it, import, optionally clone
   it into their own repertoire, then enable it or set it primary.

Matching content is recognized even if local row IDs or timestamps differ.
Different editions/content with the same title coexist; V1 never silently replaces
an existing edition. Version strings are labels, not automatically ordered upgrades.
Clone creates a new UUID and records the source identity/version/content hash.
Imported author/provenance metadata is preserved. Local import filename/date/hash
are retained in the installation catalog; they are not silently injected into the
shared author's original metadata. This keeps exact re-exports semantically stable.

Exports use a clean SQLite schema, retaining positions, legal moves/transpositions,
nested branch names, notes/sources, weights/preferred flags and all book metadata.
No game databases, credentials, cache payloads or unrelated libraries are included.
Unknown tables, scripts or binary payload fields cannot be carried along.

Downloaded books are untrusted data. Nothing in a book is executed, imported as
Python, fetched from a URL or used as a destination path. Close authoring before
sharing a committed file; an active WAL/journal is not a portable package.

Installed and removed/archived books are protected user data and included in the
existing FULL backup workflow. See [Opening Library Manager](OPENING_LIBRARY_MANAGER.md)
for storage, selection, safeguards and future community contracts.


V1.1 uses canonical multi-book managed libraries. Exact self-import reuses existing content; partial overlaps require an explicit separate-library choice. See [live workflow](OPENING_LIBRARY_MANAGER.md).
