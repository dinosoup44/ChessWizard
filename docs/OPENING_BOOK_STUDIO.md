# Opening Studio V1.3

Open **Tools → Opening Studio**. Your books are already available in the
**Book** dropdown. Select an opening and edit it here. You do not need to open a
file, install a book, publish it, or visit Opening Library Manager.

## Create a book

1. Click **New Book**. Studio stays open, resets the board to move zero, and
   focuses a blank **Book title** field.
2. Enter a title, such as **King's Gambit**.
3. Play `e4` on the board or type it and click **Preview move**.
4. Click **Save Move**. Your new book and its first move are saved together.
5. Continue `e5` → Save Move, then `f4` → Save Move.

You can also press Enter in the title field or click **Create Book** to save an
empty book first. New books default to Active, version 0.1. Book IDs are generated
internally. There is no Save Library step. Previewing or abandoning a new book
creates no authoring file; its draft exists only in memory until you save.

## Switch and edit

Choose **The French**, **London**, **Pirc Defense**, or another opening from Book.
Each loads its own saved board root, branches, weights, preferred moves, notes and
sources. If two books share a name, the dropdown distinguishes them using their
existing library names. They remain separate books.

If a preview or edit is unsaved, switching offers **Save / Discard / Cancel**.
Save must succeed before switching; Cancel keeps your exact pending position and
fields. Saved content remains when you switch away and return. Startup chooses a
primary book if present, otherwise an Active book, otherwise the first available
book. It does not create storage simply to show an empty library.

Click a saved move, then **Edit Move**. Change notes, weight or preferred status,
then **Save Changes**. Move identity stays stable. Position note/sources refer to
the displayed position; Move sources refer to the selected move. Opening Details
changes title, description, author, license, version and Draft/Active/Archived
status without replacing the book or its references.

## Navigate, extend and name lines

**Branch Browser** is the main map. Click a named line or any move. Arrows step
within that active line and stop at its ends. **Book start** returns to move zero.
Shared-position markers identify transpositions; the incoming path is preserved.

To create a sibling variation, select the move you want to replace and click
**Add Alternative to This Move**. Studio returns to the position before that move
and tells you whose turn it is. Play your alternative and Save Move. Alternatively,
click any branch point, play a different continuation, then Save Move.

Select a line or a move within it and click **Rename Line**. This also renames
automatic labels such as `Line from 5… O-O` or `Opening trunk`. Clear the name to
restore the automatic label. The existing variation-name field stores this
label; moves, IDs, transpositions and Polyglot entries do not change.

**Delete Move / Variation** retains the existing preview and confirmation flow.
Move-only and subtree removal protect shared continuations. This is separate from
deleting an entire opening book.

## Delete a book

**Delete Book** offers **Export / Share First / Delete / Cancel**. Export First
creates a portable copy and returns you to Studio; it does not automatically delete.
Delete removes that book from normal Studio and Game Review choices. Games are
never deleted, but opening reference links and derived assessments for the removed
book are no longer available.

Deletion is recoverable: the original graph remains in managed storage and backups,
with its ID reserved. Recovery is an advanced catalog operation; V1.3 adds no restore
button. Archived status is different: archived books remain manually selectable.

## Import received books; export for sharing

Use **Import / Export → Import External Books…** for material from elsewhere.
The preview lists titles, versions, authors, identical duplicates and name conflicts.
Select one or more books and Import. They appear in the normal Book dropdown, and
Studio switches directly to an editable selected book.

Identical content reuses the existing book without writes. Different content with
the same friendly title is kept separately; nothing is overwritten. The external
source remains unchanged. An empty external library contains nothing to import.

**Export / Share Book…** writes one selected book to a new portable `.cwbook`.
**Export / Share Current Library…** optionally exports the books in the selected
book's physical library; it does not consolidate legacy files. Your working source
stays in place. Notes, sources, weights, names and metadata travel with `.cwbook`.
Export Polyglot `.bin` contains active moves/weights only.

**Advanced → External Preview — Read Only…** is optional inspection. Use its
**Import into My ChessWizard Library** action to switch directly to editable
managed content. Paths and technical IDs are confined to Advanced Library Details.

## Game Review and existing libraries

New books and saved edits appear in Game Review immediately. Active + Enabled
books may auto-match; Draft and Archived remain manually selectable. Book adherence
is separate from engine Accuracy. Ordinary authoring/navigation does not run an engine; the separate Stockfish Lines tab runs only explicit requests.

Existing managed books stay in their original files with the same library/book IDs.
Studio presents all of them in one opening workspace. New books and newly imported
content use one stable managed authoring file. No consolidation or owner-data
migration is required. Advanced **Tools → Opening Library** remains available for
primary/enabled preferences, provenance, clone and library-level management.


## Branch-point guidance during testing week

Select the move you want to replace and choose **Add Alternative to This Move**.
Studio returns to that move's parent and names the exact position. For the line
1.e4 d6 2.d4 Nf6 3.Nc3 g6 4.f4 Bg7, select Bg7: the hint now reads
**Branch point after 4.f4 · Black to move. Play a move on the board to add an alternative.**
Play and save the alternative normally. At a book root, the hint says book start.

**Rename Line** overrides an autogenerated header such as 'Line from 4…c5'.
A blank custom name restores the automatic label. Rename survives reload without
changing move/position IDs, graph relationships or Polyglot export bytes.

The existing V1.3 Book dropdown, inline New Book and managed import/edit workflow
were validated, not replaced. External preview remains an Advanced read-only option;
self-created books require no import/install step. Owner libraries are never test
fixtures. This pass uses temporary libraries only.


## Studio 2.5: optional Stockfish Lines

The tab family is now **Branch Browser / Stockfish Lines / How To**. Saved-position research starts only on Analyze Position, Refresh Analysis or Analyze Deeper. Normal requests three Stockfish 18 lines; Quick one; Deep five. Select a returned line for a separate, bounded board preview, then Return to Book Position. Eval is White POV, separate from book weights and Opening Accuracy.

Add as Variation requires an explicit full-line confirmation at the original saved anchor. Existing theory and metadata are reused unchanged; only missing edges receive normal weight 50 and no Preferred flag. User naming is optional. Switching saved position/book cancels stale work; drafts and unsaved edits cannot start analysis. The normal editor returns when you leave the advice tab.

See [Stockfish Lines guide and contracts](OPENING_STUDIO_STOCKFISH.md) for refresh/cache semantics, cancellation and copy-only acceptance.


## Game Review Opening Workspace V2

Game Review can open Studio at an exact existing route or stage missing played theory from the nearest known position. Staging/Cancel are read-only. Add as Variation requires a full-line preview and explicit confirmation through the same atomic ID-preserving repository used by Stockfish Lines. Legacy single-book catalog identities remain supported. Opening Details now exposes explicit Opening Side (unspecified/white/black/both); existing metadata is preserved and no legacy intent is inferred. See [workspace guide](GAME_REVIEW_OPENING_WORKSPACE.md).

## Opening Review polish terminology and handoff

The window and Tools entry are **Opening Studio**; select an **Opening**, edit
**Opening Details**, and inspect **Opening Side** directly below the selector. Side remains
explicit White, Black, Both/reference, or unspecified; names never imply intent.
The `.cwbook` format, internal APIs, metadata and authoring persistence are unchanged.

Opening Review retains a flat opening selector. Its deviations and Opening Gaps expose
affected games with exact decision navigation. **Open in Opening Studio** carries the
existing game/move, managed opening, revision and saved-route contract. Missing played
continuations are staged; only confirmed **Add as Variation** writes them. After a
committed edit Review says **Opening changed — refreshing review…** and rereads stored
facts in the background. Stockfish Lines still requires an explicit owner request.
