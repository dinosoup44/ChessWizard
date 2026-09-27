# Opening Intelligence Application V1

Opening knowledge answers whether authored positions/moves exist in a selected
book. Engine quality answers whether a move is good chess. These are separate
contracts. Outside-book is never automatically a mistake, inaccuracy or bad move;
a future engine-best move may also be outside-book. Weights are author preferences.

## Shared services

- `opening_book_reader.read_books/read_book`: read-only coherent authoring snapshots.
  V1 books use model defaults for unnamed moves; reading never upgrades a file.
- `OpeningBookLookup`: validates the saved graph, indexes active root-reachable
  positions/moves, and exposes position identity, available moves, preference,
  variation contexts and provenance. Frozen snapshots are reused across a batch.
- `assess_game`: pure legal actual-move replay to typed OpeningGameAssessment and
  OpeningMoveAssessment. Stored FEN continuity is checked during that same replay.
- `OpeningIntelligenceService`: database-local, read-only individual/batch application,
  streaming iteration and `get_games_for_opening`. Each explicit batch uses one
  SQLite read transaction, deduplicates requested IDs and reports failures separately.
- `matches_opening`, `variation_distribution`, `get_deviations`: portable query and
  aggregation helpers for Explorer and future lessons.
- `OpeningReviewSession`: one in-memory assessment for the selected Review game.
  It rereads the selected book snapshot on refresh, rebuilds on changed content,
  and keys reuse by book content plus visible game/move inputs. Explicit Refresh
  forces a fresh stored-game assessment. No results are persisted.

The core has no Tkinter or engine dependency. Managed calls use the canonical
library UUID plus its local book ID/version/revision/content identity. Direct
unmanaged file lookup retains a normalized source-locator hash; it must not be
mistaken for managed identity. Game identity includes database/source namespace,
exact move sequence, initial position, move IDs and user color.

## Membership, deviations and counts

Known positions are **active root-reachable** canonical positions. Inactive moves
and theory disconnected from active root paths do not count. Position identity,
weights, preferred flags, SAN and Polyglot semantics remain the existing contracts.

At a known position, an actual move absent from active alternatives is a deviation.
A known leaf with no alternatives is `continuation_not_authored`: authored coverage
ended. It is still a first deviation under this definition, not a chess judgment.
Unknown positions are `position_not_in_book`; absent alternatives at a known
non-leaf are `move_not_authored`. A legal matched move is `in_book`.

Each row retains neutral actor color. User/opponent deviation is derived only when
user color is known; otherwise it remains unknown. First deviation is the first
such missing move anywhere in the game, including a root departure. It is not
redefined later when a game re-enters. Every later known-position deviation is
also retained, so queries can distinguish any user/opponent deviation from first.

Raw facts include total actual plies, matched moves, unmatched moves (including
unknown intervals), moves with authored alternatives, known-position visits,
user/opponent matched moves and maximum consecutive matched plies. Known positions
count **visits**, including initial/final positions, not distinct graph nodes.
The last known visit immediately before first deviation is separate from the
last known visit anywhere in the game. No Opening Accuracy score is produced.
The UI's `in-book / total actual plies` is a count pair with an explicit denominator,
not an engine score or unexplained adherence percentage.

## Meaningful book entry

The default `OpeningMatchPolicy.min_consecutive_plies=4` requires at least four
consecutive active authored moves anywhere in the game. The standard root alone,
a single shared move or only two French plies do not qualify. A book with fewer
than four connected authored plies may yield no meaningful matches. This conservative
policy is explicit and caller-configurable, with its own result identity. It can
miss shallow or isolated late-position knowledge; raw position matches remain
available even when `entered_book` is false. No ECO or un-authored name is inferred.

## Variation paths and transpositions

A variation is identified by its authored named move anchor, not its string alone.
Root-following actual moves extend the observed path with traversed named anchors:
The French > Nc3 branches > Winawer Variation > Advance structure, for example.
A short unnamed trunk stays recognizable without inventing a variation name.
Repeated visits to the same named anchor do not manufacture deeper hierarchy.

Standalone position lookup returns possible authored named paths. It does not
choose the first path through a transposition. When actual moves follow a known
path, that played context takes precedence. After an unknown interval, re-entry
uses possible contexts at the reached position. If those include a named prefix
actually supported earlier, compatible paths are retained. Otherwise all candidates
remain; ambiguity is explicit. Position-derived context is distinguished from a
fully observed path. The deepest name is absent when ambiguity/incompleteness
prevents a unique answer.

Re-entry is counted on the move whose **after-position** changes from unknown to
known, after a previous known visit. An initial unknown-to-known transition before
any known visit is entry, not re-entry. A missing move that lands directly on a
known position breaks the authored move run and resets context, but creates no
unknown-position interval and therefore no re-entry count. Missing moves are never
retroactively upgraded to book theory.

`variation_before/after`, `followed_variations`, and `final_variation` retain context
separately. Final variation means the **last known context**, even if the game later
leaves the book; per-move after-position evidence remains authoritative for the
current board. Variation-name search considers contexts on matched actual moves; a position-only
re-entry without a matched move still exposes context in the assessment, but is
not a followed-variation search match. Query defaults exclude ambiguous variation matches. Callers may
explicitly include possible contexts without treating them as certain labels.

Context enumeration is bounded by max_variation_contexts=64 per position and
max_named_depth=32. Saturation marks inferred context incomplete rather than
inventing certainty. These bounds affect policy identity. Exact played membership
and an explicitly observed named path remain usable. Assessment `complete` means
legal replay completed; `variation_context_complete` separately exposes contextual
limits. Invalid stored games produce typed failures, not completed assessments.

## Identity and invalidation

| Identity | Meaning / changes |
| --- | --- |
| membership_identity | Active reachable graph, root and canonical move relationships; graph edits can change membership/deviation |
| label_identity | Book name and authored variation labels/descriptions; naming edits change displayed paths, not membership |
| preference_identity | Move weights and preferred flags; edits change authored preference facts |
| content_identity | Full selected-book snapshot including revision, notes and sources; complete provenance/currentness |
| policy_identity | Meaningful-entry rule and context bounds |
| library/book/version + contract_version | Explicit source selection and interpretation version |
| game_identity | Exact game sequence, IDs, source namespace, initial board and user color |

`changes_from` explains changed identity categories; `is_current` checks provenance
and, when supplied, current game identity. A naming-only edit preserves membership
identity but invalidates the complete assessment's label/currentness. No persistent
cache is added: batch callers hold one indexed book; Review holds only its selected
assessment in memory. Review refresh checks source content, not file timestamps,
so same-version edits and SQLite WAL changes cannot silently reuse old book truth.

Current performance does not justify schema/index/cache duplication of FENs or
PGNs. Future persisted summaries must use these identities and report staleness;
they may reuse membership for naming-only changes while regenerating labels.

## Explorer and future Professor hooks

`GameSearchService.search_openings(lookup, criteria, opening_query=...)` composes
existing metadata/collection filters with opening assessment of the resulting exact
game IDs. `OpeningQuery` supports entered status, exact authored variation name,
any user/opponent deviation, and explicit possible-context inclusion. Existing
Explorer SQL and UI are unchanged; this is the shared integration foundation.
Batch failures remain visible separately from nonmatching games.

Future Professor/Lessons can call get_games_for_opening, assess_games or iter_games,
then variation_distribution and get_deviations. Streaming avoids retaining full
per-move results for every historical game. No lesson builder, dashboard or
persistent opening tables are introduced. Future Opening Accuracy can combine
these book facts with separately versioned engine evidence, retaining both truths.

## Owner validation in Game Review

Use the **Library → Book** selectors to choose a managed reference (or None).
The bottom **Opening → Summary** pane shows the opening facts; **Facts…**
opens the detailed view. Tools → Opening Library manages references and defaults.
Both presentations follow game and actual-move navigation,
showing authored variation, current move membership/weight, first deviation,
preferred move there, known-position counts and re-entries. Refresh reloads current
book/game facts. Proof-line mode explicitly labels the summary as actual-game-only.
No stored proof variation is mistaken for the played game. No V3 player-summary
area or final Opening Intelligence UI is built.

Opening Book Studio V1.2 and all authoring behavior remain frozen. Owner files are
read-only. Validation used original fixture books/games and a consistent isolated
copy of the owner's French book. See the application report for real-game scope,
performance, full test results and production safety hashes.


## Opening Book Management + Active Reference V1

Managed references now consume these facts through `OpeningReferenceService`. Managed assessments use the installation UUID as their library identity consistently in both relevance and Game Review; unmanaged file callers retain the path-derived locator identity. Enabled installations participate in meaningful matching; relevant primary, sole match, ambiguity and explicit None are separate outcomes. See [Opening Library Manager](OPENING_LIBRARY_MANAGER.md). No scores or game writes were added.


## Opening Library Live Integration V1.1

Managed provenance now uses the canonical library UUID plus local book ID, version,
revision and content identity across relevance and Review. The two-stage Library →
Book picker lists all managed books independently of relevance. Active + Enabled
controls defaults; Draft/Archived/disabled books remain manually inspectable.
A relevant primary wins; otherwise a unique strongest authored run/matched-ply
pair wins, with equal strengths ambiguous. The underlying four-consecutive-plies
knowledge rule and all raw opening facts are unchanged. Studio saves, focus and
selector opening refresh the same canonical content without re-import.
See [Opening Library Manager](OPENING_LIBRARY_MANAGER.md).


## Managed application API

`ManagedOpeningIntelligenceService(database_path, library=None, policy=...)` is
read-only. The optional library service permits isolated profiles. Each call resolves
a fresh canonical book snapshot, then delegates to the existing indexed lookup and
legal replay; one batch uses one coherent game read transaction and one frozen book.
No status changes, imports, migrations, engine searches or assessment writes occur.

```python
from opening_intelligence_managed import ManagedOpeningIntelligenceService
from opening_intelligence_models import OpeningQuery

opening = ManagedOpeningIntelligenceService(database_path)
assessment = opening.assess_game_against_book(game_id, library_id, book_id)
batch = opening.assess_games_against_book(game_ids, library_id, book_id)
matching = opening.get_games_for_opening_book(library_id, book_id, game_ids)
reentered = opening.get_games_for_opening_book(
    library_id, book_id, game_ids, query=OpeningQuery(reentered_book=True))
variations = opening.variation_distribution(library_id, book_id, game_ids)
deviations = opening.get_deviations(library_id, book_id, game_ids)
```

Omitting `game_ids` from `get_games_for_opening_book` intentionally discovers all
real games. Other batch methods require an explicit scope. Find-games returns only
meaningful matches; generic `OpeningIntelligenceService.get_games_for_opening`
retains the broader entered/nonentered query API. Every batch/summary retains typed
failures separately; errors are never quietly counted as nonmatches.

Variation distribution streams successful assessments and counts the final known
context of meaningful matches, retaining `Unnamed trunk` and `Ambiguous` buckets.
Deviation summaries return **all known-position departures in the explicit scope**,
including unmatched games and exhausted authored leaves. For meaningful-entry-only
statistics, first obtain matching game IDs. Every returned move now carries immutable
book provenance, so rows remain attributable outside their parent assessment.
`deviation_relation=None` means unknown ownership for a deviation, not an inferred
player. Neutral actor color remains available. Summary output includes assessed-game
counts and failures. No percentage or Opening Accuracy metric is produced.

`OpeningQuery.reentered_book` is an optional boolean Explorer/Professor hook; `None`
does not filter. Library/book choice is supplied by the selected lookup or managed
API, rather than duplicated as a text-name filter. Existing variation/ownership
filters compose with this predicate.

Draft/Archived/disabled references can be manually assessed. Active + Enabled
controls automatic defaults only. Fresh managed calls and Review content refreshes
invalidate naming, graph and preference edits through the existing separate identity
hashes. No durable assessment cache is justified for this first application pass.

The bottom Opening Summary displays authored context, current actual-move state,
first deviation/available preferred move and raw whole-game counts. Unknown regions
retain the selected book name but do not invent a current variation. Proof playback
is labeled as separate actual-game evidence; None clears all inline content. Detailed
weights, alternatives, last known position and re-entry moves remain in Facts/results.

Future Professor and Opening Accuracy clients can call these portable APIs without
Tkinter. Engine quality remains separately obtained evidence, never inferred from
book membership or weights. See the current application report for measured cost
and the limitations of the owner's short French book.


## Game Review Opening UX V1

Manual Library/Book selection now lasts for the entire open Game Review session,
across game changes. Explicit No book also persists. Auto clears that manual intent
and permits meaningful-match defaults again. No selection preference is written to
the game database or retained after closing Review. An unrelated game keeps the
selected book and reports no meaningful match; it never silently switches books.

The existing bottom area has **Game / Opening** modes using the shared high-contrast
tabs. Game preserves the evaluation timeline and actual-move context. Opening has
**Summary / Branch View**. Detailed opening content no longer expands the right side;
Library/Book controls, player info, Actual Game Moves, Tactical Moments and their
splitter remain there. Facts… is still available for the full read-only evidence.

Branch View shows the actual line through the last known book position and the next
departure, including unknown intervals before re-entry. A nonmatching game has an
explicit empty state. It does not render the whole repertoire. Saved alternatives
are shown only for the selected actual decision position. A chosen continuation
follows Preferred edges, or a sole active continuation, stopping at an unchosen
branch, leaf or repeated position. This is authored navigation, not engine search.

Italics mean only **an actual move was outside the selected book**. In-book moves,
including active non-preferred alternatives, use normal text. Current actual/book
moves have selection highlighting. Re-entry is marked explicitly; intervening
unknown moves retain their italic styling.

Click an actual user deviation in Branch View to explore its Preferred alternative,
if present. Only this user-owned preferred recommendation receives the shared arrow
style, explicitly labeled **Book move**. Opponent deviations and unknown ownership
never get a book suggestion arrow. Merely playing an active non-preferred move is
not a deviation. The root suggestion disappears when stepping farther down the
book line; no stale arrow is painted over later positions.

**Opening Exploration** keeps an immutable actual-game anchor while displaying the
chosen authored position. The right move list continues highlighting that anchor,
even as book ← / → step within the fixed continuation. Stepping clamps at both
ends and does not jump to a sibling. The actual-game evaluation bar is hidden while
a book board is shown; no game evaluation is presented as evidence for that board.

**Return to Game**, switching to Game mode, or clicking **any Actual Game Move**
restores actual navigation, the real board and its evaluation context. Tactical
selection/proof playback and opening exploration are separate states; entering one
clears the other. Normal actual move controls also leave opening exploration.

Live managed-book saves preserve selection and refresh assessment. A changed book
or game invalidates the exploration snapshot and safely restores the real anchor.
The reusable `OpeningExplorationState` stores game identity, book provenance, actual
anchor, decision FEN, authored steps and variation context outside Tkinter. The
Professor can consume that state later. Opening Accuracy now extends the bottom
Opening mode through its separate shared service; Lessons remain unimplemented.


## Opening Accuracy V1

Book facts remain independent of engine judgment. OpeningAccuracyService now composes them with exact stored Move Quality V1 through a public caller-owned read-snapshot API. It defines a bounded authored opening window, separate user/opponent adherence denominators, numeric deviation evidence and pooled authored-variation statistics. No engine/cache writes or persisted metrics are introduced. See [Opening Accuracy](OPENING_ACCURACY.md) for phase, provenance and invalidation contracts.


## Opening Analysis Engine V1: selected-repertoire facts

The [Opening Analysis Engine](OPENING_ANALYSIS_ENGINE.md) composes these existing facts rather than duplicating move replay or authored membership. It adds explicit book-side metadata, user-history/explicit-scope matching, a transient Collection-ready set, full-game user adherence, canonical-position departure groups, neutral repeated opponent gaps, re-entry facts and descriptive result/source/date/speed context. Names, weights, active/preferred flags and engine strength remain separate.

`repertoire_side` uses existing book metadata (`white`, `black`, `both`); missing legacy intent remains unspecified and requires a choice. No schema or owner library migration occurs. Existing meaningful entry stays four consecutive active authored plies. The original read-only query APIs remain available; the new facade filters by intended user side and uses shared Accuracy V1 evidence. Nested/ambiguous paths and distinct anchor IDs survive grouping. No automatic Collection, final UI, engine generation or Lessons implementation is added.


## Game Review Opening Workspace V2

The primary desktop consumer is now Game Review → Opening Review. Manual book/None selection survives game changes. Pure workspace projections use the existing full-game membership/context facts for deviations, re-entry and relevant-line styling. Book arrows require a user departure and an authored preference. Exact Review-to-Studio anchors preserve the selected book revision, canonical position and route. See [workspace guide](GAME_REVIEW_OPENING_WORKSPACE.md).
