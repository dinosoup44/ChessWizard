# Game Explorer V1

Game Explorer search is a read-only navigation layer over the active user database.
Explicit collection actions separately write organization metadata only. Open
**Tools → Game Explorer**. Search never bootstraps a database, migrates a schema,
starts an engine, writes a cache or changes analysis. Game Review, the registered
Fork Pass 2 path, position evaluation and Accuracy V1 retain their existing rules.

## Available stored facts

The inspected games schema provides game_id, source/source_game_id, played_at,
white_username, black_username, user_color, result, time_control, time_class,
ratings, account/user references, termination, rated, variant and raw PGN. V1 uses
only the metadata listed in the filter/table contracts below. There are no trusted
normalized opening columns; PGN opening tags are not promoted into a new search
classification. Time control is the stored literal value, not a new category.

Moves supplies game_id, ply_number, move_number, color, is_user_move, played SAN/UCI
and FENs. Explorer counts stored plies in SQL; **Moves = ceil(plies / 2)**. A final
White move counts as a move pair started; this is not the last FEN's move counter.
Games without stored moves have count zero.

Tactic candidates hold current legacy status and solutions. Coverage rejection,
canonical uniqueness and mate episode primacy are centralized in TacticQuery.
Occurrence records separately hold actor, kind and motif; evidence revisions are
immutable claims without a universal active/current revision pointer.

Accuracy has no summary table. MoveQualityRepository derives it from exact,
compatible candidate-line cache evidence using the frozen Accuracy V1 settings.
The project database has 3,200 rows including one dev fixture, and 192,987 moves.
Explorer, like Game Review, excludes source=dev: 3,199 real games. The inspected
owner desktop database contains 482 games.

## Filters and unknowns

- Internal Game ID: positive integer, exact and database-local. Only-ID lookup
  uses the games primary key and indexed move counts. Enter submits search and a
  sole result is selected immediately. The Open button or double-click opens it.
- Opponent: case-insensitive literal substring of the other player's username,
  based on stored user_color. SQL wildcard characters are ordinary characters.
  Unknown perspective cannot imply an opponent.
- Your color: White/Black. Result: win/loss from that stored perspective; draw
  follows the explicit draw result even if perspective is unknown.
- Source: exact stored value; choices come from this database. Source game ID:
  literal case-insensitive substring, independent of internal ID.
- Dates: YYYY-MM-DD inputs, inclusive from/to in UTC. Existing dotted dates and
  ISO timestamps are normalized for queries only; source bytes are never changed.
- Time control: exact stored value. Move-count minimum/maximum: inclusive.
- Motifs: Fork, Mate, Pin, Skewer, X-ray. Relationships: played/missed by me,
  played/missed by opponent, unknown. No selection means unrestricted.
- User accuracy: inclusive 0–100 range over **complete user-side** compatible
  Accuracy V1 metrics. Opponent-side incompleteness does not invalidate a complete
  user score. Partial, missing, contradictory or incompatible user evidence is
  Unknown, never zero. Unknown values are excluded by an accuracy range.

Different groups combine with AND. Multiple motifs combine with OR; multiple
relationships combine with OR. **Motif and relationship must match the same
occurrence**, not two unrelated events in the same game.

Unknown metadata stays visible in All Games. Filters requiring it exclude unknown
values; Unknown accuracy remains distinct from an actual 0%. No tactics is a zero
active count, not evidence that historical analysis proved an absence.

## Tactic truth boundary

GameSearchTactics translates current visible legacy candidates through the existing
occurrence_from_legacy_candidate adapter and uses TacticOccurrence.relation. It
never infers "played" from a missed candidate prefix or equal solution/actual move.
The shared active predicate excludes rejected coverage, inactive candidates,
duplicate canonical keys and non-primary mate episode members. Invalid legacy
decision evidence is omitted conservatively. A linked archived occurrence neither
revives a rejected candidate nor duplicates an active candidate in the count.

Standalone stored claims are not automatically verified tactics. The reusable
OccurrenceEvidenceSelection contract accepts **explicit revision IDs selected by
a trusted provider's current policy**, not timestamp-based latest-wins guessing.
The default selection is empty because no live standalone played-tactic provider
is active. A future provider can supply its accepted current revision IDs; search
then validates decision binding and uses the same actor/kind relation contract.
Selection must be recomputed when that provider's evidence/policy changes.

Consequently, the inspected desktop data has missed tactics but no stored played
occurrences; played filters correctly return zero. The project occurrence rows
are legacy archival mappings, not a separate new played-tactic dataset. Isolated
fixtures exercise all five relationships, including explicitly selected standalone
claims. This task does not activate the experimental played-Fork pilot.

## Results and navigation

Columns: Game ID, Date, White, Black, Your Color, Result, Moves, Source, Time
Control, User Accuracy, Tactics. All headings sort, with numeric rather than text
ordering for numbers; unknowns stay last. Dates sort chronologically. Default is
newest first, then descending game ID. Both scrollbars are available; resize the
window for more rows/columns. Game ID is always included as the first column.

The footer shows matching and total real-game counts. An absent only-ID request
says "Game ID 2771 was not found in this database." A combined request says no
match for that ID and its filters, without claiming the ID itself is absent.
There is no cross-database search or ID translation.

Open in Game Review uses its existing navigation path, clears hidden QA/tactic
filters and line playback, and starts at the actual initial position. Existing
orientation, moves, tactics, evaluation and accuracy readers remain responsible
for the review. The metadata now explicitly shows Game ID as well as source ID.

## Architecture and performance

- game_search_models: immutable criteria/results and typed sorting.
- game_search_repository: parameterized SQL metadata and shared fact enrichment.
- game_search_tactics: occurrence relationship projection and active visibility.
- game_search_service: explicit path, mode=ro, query_only, consistent read snapshot.
- merlin_ui/game_explorer: controls, worker queue, sortable table and navigation.

No Tk imports or engine generation exist in core search. A mobile frontend can
reuse the service. Criteria round-trip through dataclass/JSON data; saved searches
are deliberately not persisted yet. Workers own their SQLite connection and pass
results to Tk through a queue; sorting is in memory and does not query the database.

Existing indexes suffice: games INTEGER PRIMARY KEY; moves UNIQUE(game_id,
ply_number); candidate lookup/coverage/episode indexes used by TacticQuery; cache
UNIQUE(fen,engine_identity). Exact-ID plans have no full move-table scan. SQL counts
moves, and a bulk indexed root-evidence prefilter avoids loading every game's
moves into Python. Only potentially complete accuracy games reach shared legal
history/evidence validation. Fully scored large databases may cost more to derive;
no persistent summary or speculative index was introduced.

Measured timings and safety receipts are in reports/GAME_EXPLORER_V1.md and
reports/game_explorer_benchmarks.json. The original Explorer foundation did not include migration or saved sets.
The optional Collections V1 extension is described below; opening intelligence,
dashboards and historical analysis remain outside Explorer search.


## Saved Game Sets / Collections V1

Use **Collections…** beside the Collection filter to manage static sets. The filter
offers All Games, Games not in a collection and each saved collection, with counts.
Collection membership is filtered through indexed SQL before tactic/accuracy fact
enrichment, and combines with all existing filters using AND. Result counts and
numeric/date sorting retain their existing behavior. Clear filters returns to All
Games. Renaming a collection retains its selected internal ID.

The result table supports Ctrl/Shift multi-selection. **Add selected to collection…**
adds membership without duplicates; **Remove from collection** removes selected
memberships from the currently displayed collection. Open in Game Review requires
exactly one selected game and retains the existing exact-game handoff.

Games in any collection/set are protected from normal deletion, Delete & Ignore
and full reset. Remove them from every collection first. Deleting a collection
keeps its games. See [GAME_COLLECTIONS.md](GAME_COLLECTIONS.md) for migration,
protection, static-set semantics and the portable service contract.

Existing databases require an explicitly approved additive migration; browsing
and search never perform it. No source/import identity, analysis, accuracy or
opening-book data changes as a result of collection actions.

## Shared relationship assessment V1

Search now uses `TacticRelationshipRepository` / `assess_relationship` for all five
supported motifs and all four ownership/played-missed relationships. Exact decision
identity, side and legal initiating moves are required. Matching a proof's later
continuation is not required. Unknown perspective remains unknown; legacy
missed-prefix equality cannot invent played proof. Standalone selections validate
UUIDs and actual anchors, and require accepted admission plus verified proof.
Provider selection still owns currentness; timestamps never activate archives.

The isolated expansion replay exercised all 25 motif/relationship filter pairs
against each production copy, without duplicate games. Populated synthetic
standalone fixtures exercised all four known relations for every motif, including
collection AND filters and cross-occurrence negative controls. Production has no
accepted played/opponent discovery evidence in the audited active population, so
its existing results remain missed-user only. Collection storage/migration is
unchanged. See TACTIC_RELATIONSHIPS.md and the expansion/owner-review reports.


## Opening Intelligence service foundation

`GameSearchService.search_openings` accepts an indexed selected book, ordinary
GameSearchCriteria and OpeningQuery. It applies existing metadata/collection filters
first, then derives read-only opening facts for that explicit game-ID scope. Queries
can select meaningful book entry, exact authored variation names and user/opponent
deviations; ambiguous variation inclusion is explicit. Returned batches retain
failures separately from no-match results. No opening filters or schema/cache
columns were added to the Explorer UI in this pass. Counts remain book knowledge,
not engine accuracy. See [OPENING_INTELLIGENCE.md](OPENING_INTELLIGENCE.md).


## Opening Intelligence Application V1 — managed application

OpeningQuery now includes an optional reentered_book predicate alongside meaningful
entry, variation and user/opponent deviation. Existing search_openings composes these
with metadata/collection scopes. ManagedOpeningIntelligenceService provides direct
library UUID/book ID selection, find-games, variation distribution and deviation
queries for future filters. Failed games remain explicit; no persisted assessment
index or new Explorer filter UI is introduced in this pass.


## Opening Accuracy query foundation

OpeningAccuracyQuery supplies frontend-neutral accuracy/adherence ranges, authored variation, user-deviation and high-loss-deviation predicates. Complete results are required by default; partial inclusion is explicit. OpeningAccuracyService returns scoped game, variation and deviation summaries with typed failures and provenance for future Explorer/Professor consumers. No new filter UI or database index is introduced. See [Opening Accuracy](OPENING_ACCURACY.md).
