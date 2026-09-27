# Opening Studio 2.5: Stockfish Lines V1

Stockfish advises. The user authors the repertoire. Opening advice is neither a tactic verdict nor Opening Accuracy nor a Polyglot preference weight.

## Using the tab

1. Choose a saved book and position in **Branch Browser**. Save or discard pending moves/edits first.
2. Open **Stockfish Lines** and check **Analysis position**. The breadcrumb identifies the book, named variations and last saved move.
3. Click **Analyze Position**. Nothing runs merely because Studio opens, a book/branch changes, or this tab is selected.
4. Read the returned ranks, moves, **Eval (White)** and numbered SAN continuations. Positive scores favor White; negative scores favor Black. `M3` / `-M4` remain mate distances.
5. Select a line to enter **STOCKFISH PREVIEW**. The arrows step one ply, bounded at either end. The move-pair table follows the cursor and can scroll. **Return to Book Position** restores the authored board. Preview never moves the saved insertion anchor.
6. Select a candidate and choose **Add as Variation…**. Review the destination, complete continuation and reused/new move counts. Optionally enter a variation name, then explicitly confirm **Add Variation**.

The selected whole continuation is added. Existing edges, position IDs, notes, names, sources, weights and preference flags are preserved. New edges use the normal weight **50**, Active, **not Preferred**. A custom name and compact engine provenance attach only to the first new edge; blank names retain the ordinary automatic branch label. Existing names are never overwritten to accommodate a new name.

When a full line already exists, Studio explains this and writes nothing. Shared positions/transpositions and repeated edges are reused. An overlap with an inactive move is blocked: decide explicitly whether to enable that authored move first. Analysis never enables it for you.

The normal author editor is hidden while the advice tab is selected, giving the line table usable space; returning to Branch Browser restores the same author controls. Switching tabs starts no engine request. External read-only preview permits advisory research but disables Add; import it into the managed library to author.

## Profiles and exact raw evidence

These are the existing shared `analysis_settings` presets, unchanged:

| Profile | Depth | Requested MultiPV |
| --- | ---: | ---: |
| Quick | 10 | 1 |
| Normal (default) | 12 | 3 |
| Deep | 16 | 5 |

Stockfish **18**, Threads **1**, Hash **64 MiB**; no node or time cap. Raw request family is `candidate_lines_v1`, generator version 1. The service accepts the shared typed `AnalysisProfile` for future settings consumers; the desktop selector uses the three existing presets. No independent configuration system or analyzer-profile changes were added.

Only actual returned lines are shown. If fewer legal root moves exist, fewer lines are expected. Terminal positions need no search. Missing ranks, incomplete searches, malformed scores/PVs, incompatible identities and unfinished requested depth are rejected rather than shown as complete advice. Legal PV/SAN and unique ranks/root moves reuse `CandidateLineSet` validation.

**Analyze Position** first probes exact compatible game evidence read-only, then the advisory cache. New complete advice uses the existing candidate-line schema/repository in:

`<user data>/cache/opening_lines.sqlite3`

On a normal Windows installation, this is `%LOCALAPPDATA%/ChessWizard/cache/opening_lines.sqlite3`. Tests/tools can inject isolated paths. The database and its directory are created only after an explicit successful request needs an insert. No game DB schema migration is performed. `engine_position_cache`, candidates, coverage, training and occurrences are not written.

Identity uses the full request FEN (including route clocks), engine name/version, depth/nodes/time, Threads/Hash, MultiPV, generator version/family and root restrictions through the shared `request_identity`. Quality Gate/Scale settings do not duplicate raw evidence and are not applied as opening-authoring admission rules.

Cache rows are insert-once. Exact reruns search/write nothing. **Refresh Analysis** bypasses reads and displays fresh session evidence; an already-existing exact cache row is retained unchanged, so a later ordinary request can return the older cached evidence. This is explicit refresh, not in-place cache replacement. **Analyze Deeper** requests the existing Deep profile, keeping the old complete advice visible until the replacement is ready. Incomplete/malformed existing rows are misses, never silently repaired.

The acceptance fixture used 3,700 payload bytes / 12 KiB SQLite for one Normal and one Deep request. Growth varies with PV length; there is no background cleanup or eviction in V1. Future cache maintenance may target the separate advisory file without touching authored books. Compact authoring provenance is self-contained; a saved book does not require its engine cache to remain available.

## Portable contracts and persistence

- `opening_engine_models`: immutable `OpeningEngineAnchor` / `OpeningEngineAnalysis`; `saved_opening_anchor(snapshot, library_identity, path)` legally replays the exact saved route.
- `opening_engine_service.OpeningEngineService.analyze_opening_position(anchor, profile, refresh=False, cancel=None)`: shared candidate-line generation/cache plus the owned cancellable engine. Construction/import performs no search or file creation.
- `opening_engine_presentation`: legal preview and shared score/SAN formatting independent of Tkinter.
- `opening_book_line.plan_book_line`: pure, immutable whole-line merge preview, canonical position reuse and neutral new-edge details.
- `OpeningEngineAuthoringService.preview_add` / `add_engine_line_to_book`: explicit confirmation boundary binding advice, selected rank, current selection and frozen book revision.
- `OpeningBookRepository.apply_line`: one explicit transaction, revalidating the plan under the write lock before inserting only missing edges. Any failure rolls back the whole line. An entirely existing line does not touch revision/timestamps.
- `merlin_ui.opening_engine_panel` / `opening_engine_dialog`: Tk presentation, worker delivery, board projection and explicit author confirmation only.

The anchor includes library identity, local book ID, full content/revision identity, selected saved route/position and exact FEN. Analysis retains the shared profile/raw request identity. Navigation or book changes cancel outstanding work and clear stale advice. Add rechecks selection, library, snapshot and complete evidence before committing; a board preview can never redirect insertion. Changes outside this Studio window also invalidate the frozen plan.

**Stop** sets the owned cancellation event. `LazyScoutEngine` terminates only its worker process and joins its watcher. Worker threads never touch Tk or authoring repositories. Results are delivered on the main thread with a generation token; late/stale/cancelled work cannot replace the current selection. Failed/incomplete/stopped requests leave no partial cache evidence or authored branch. Existing complete advice remains usable after a failed refresh/Stop at the same anchor.

A future repertoire-gap workflow can supply one saved anchor to this service and open Studio there. It must still wait for explicit Analyze and explicit Add. It must not auto-analyze or fill a collection of gaps. Core imports work without Tkinter, supporting another desktop/mobile frontend or The Professor.

## Validation

Automated Tk tests cover navigation, modal content/confirmation and layout bounds at 100/125/150% equivalent Tk scaling. Real Stockfish acceptance used only copied books and isolated caches. Native owner visual review remains required; the Windows interaction tool was unavailable during this pass. Detailed owner-session receipts remain private; use the [public test workflow](DEVELOPMENT.md#tests) for self-contained regressions.
