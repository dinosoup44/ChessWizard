# Opening Book Foundation V1

ChessWizard's rich **.cwbook authoring library** is the source of truth. Polyglot
.bin is an intentionally lossy generated interchange artifact. No production game
schema, analysis cache, candidate, coverage or accuracy change is required.

## Isolation and components

A library is a separate managed SQLite file. Studio startup creates no file;
new drafts use an in-memory authoring repository. The first confirmed save lazily
creates the canonical home through exclusive creation, refusing existing paths.
Authoring open verifies application_id 0x4357424B, user_version 1 or 2, integrity, foreign
keys and expected table names before opening for edits. A game database fails
this inspection. Only explicitly opening a V1 authoring library performs the additive
V2 migration; there is no production-game bootstrap or background library scan.

- opening_book_models: frozen details/snapshot/result inputs, position identity.
- opening_book_schema: authoring-only schema and identity constants.
- opening_book_repository: explicit transactional persistence and stable edge IDs.
- opening_book_service: legal authoring and finite graph/browser projection.
- opening_book_deletion: pure, snapshot-bound graph deletion preview.
- opening_book_navigation: typed branch paths, finite projection and bounded active-line stepping.
- opening_book_session: pending/save contract and path-based back/forward state.
- opening_book_polyglot: deterministic export plus independent reader verification.
- opening_book_application: pure membership/replay and read-only stored-game adapter.
- merlin_ui/opening_book_studio and opening_book_dialogs: desktop controls only.

The core has no Tkinter or engine dependency. Mobile/review/training consumers can
reuse it without moving chess/business logic out of widgets. No persistent applied
book evidence is needed in V1: derive it from a selected immutable snapshot.

## Authoring schema

| Table | Key facts |
| --- | --- |
| books | book_id, root_position_id, name, description, version, draft/active/archived status, monotonic revision, metadata_json, creation/update timestamps |
| positions | position_id, unique canonical FEN, Polyglot key as 16-character hexadecimal text, side to move |
| book_positions | (book_id, position_id), position note, metadata_json |
| book_moves | stable move_id; book/from/to references; UCI and SAN; 1–100 weight; preferred/active flags; move note, instructional note, metadata_json, variation_name, variation_description; unique (book, source, UCI) |
| source_references | book/position and optional move attachment; title, author, edition/year, chapter, page, original private note |

Positions are shared across books; **position commentary is book-scoped**, preventing
one repertoire's notes from silently overwriting another's. Metadata is JSON data
only, with object roots and no NaN; tags/provenance can live there without a speculative
tag subsystem. Version is an editable author label; revision increments transactionally
for edits. Snapshot SHA256 includes complete rich content/revision for reproducible
derived results. This is not a version-control system or a historical snapshot store.

Move saves upsert the same book/from/UCI key and keep the existing ID. A partial
unique index permits only one preferred branch per book position. Selecting a new
preferred move clears the previous flag in the same transaction. Inactive cannot
also be preferred. Weight and preferred are independent editorial concepts.

Deletion has two explicit modes. Move-only retains detached descendants; subtree
mode computes the selected destination's closure and protects all external entry
points and their continuation. This includes references from disconnected stored
theory, inactive moves and the root. It removes only the remaining unshared
book-scoped content. Globally shared positions survive whenever another book uses
them. No general garbage collector or unrelated pruning runs.

`DeletionPlan` contains exact move/position/source IDs, note counts and a snapshot
identity. The repository takes an immediate transaction, recomputes and compares
the plan, and either applies it atomically or refuses a stale confirmation. Errors
roll back. The UI only renders/chooses the plan; it owns no graph deletion rules.
Lookup/export follow active root-reachable moves only.

## V1.1 variation metadata and additive migration

Schema 2 adds `variation_name TEXT NOT NULL DEFAULT ''` and
`variation_description TEXT NOT NULL DEFAULT ''` to `book_moves`. Empty values
represent unnamed branches. These are authoring labels, not chess identity,
engine evidence, preference, or a second source-reference hierarchy. Named
ancestors in the actual navigation path provide nesting; a transposed move shares
its label in each path, just as it shares its move note. Names never change the
move key, position identity, Polyglot payload or game-membership classification.
They do change the rich snapshot/revision, because that snapshot includes metadata.

Open first checks application identity, supported version, tables and integrity
read-only. A write-capable connection then uses one explicit transaction for both
ALTERs and user_version=2, checks column shape/quick_check/foreign keys, and commits.
Failure rolls back; there is no rebuild, ID replacement or game-schema migration.
Schema-2 opens add no data and cause no timestamp churn. Automated validation uses
new fixtures and temporary copies, never the owner's live authoring files.

## Position identity

V1 supports valid **standard chess only**, not Chess960/variants. Identity includes:

1. piece placement and piece colors;
2. side to move;
3. actual castling rights;
4. en-passant square only when a side-to-move pawn can pseudo-legally capture it.

Halfmove/fullmove counters are excluded; canonical FEN uses clocks 0 1. Promotion
history is not an identity field beyond the resulting piece on its square. Actual
session/game boards retain their own clocks; book identity does not adjudicate
repetition/fifty-move draws.

The EP rule uses python-chess X-FEN: an adjacent **pinned** pawn still makes the EP
file relevant to Polyglot even when the capture is illegal. Non-capturable EP is
discarded. Thus d4 Nf6 Nf3 and Nf3 Nf6 d4 merge, while a genuine relevant EP state,
turn or castling-right difference does not.

Deduplication uses the complete canonical FEN, not a 64-bit hash alone. Export
checks hash/state consistency and refuses detected collisions. The starting key
is 463b96181691fc9c. These rules are verified against the installed python-chess
implementation and its [official Polyglot source documentation](https://python-chess.readthedocs.io/en/latest/_modules/chess/polyglot.html).

## Graph navigation

A move edge goes from one position to another; siblings need no special mode.
The session retains exact move-path replay, including internal history helpers for
core callers. V1.2 exposes branch stepping rather than those history helpers.
Following a newly selected path replaces the previous path. Pending moves cannot navigate or persist
implicitly: Save or explicit discard is required.

The branch browser iteratively expands each position once. A repeated position
gets a shared-position reference marker, avoiding recursion through cycles. Click
the reference to navigate there; its outgoing moves remain available in Saved
moves here. A cycle is legal graph structure, not an infinite tree.

## Read-only game application

apply_book accepts a snapshot plus a legal move sequence. apply_stored_game reads
one exact local game in mode=ro/query_only with a consistent SQLite snapshot, reuses
the existing actual-position continuity check, and returns typed data. There are
no engine calls or result writes. An empty game without recorded initial-position
evidence is rejected rather than silently assumed to start normally.

For each played move the result includes actor, move number/ply, SAN/UCI, known
position ID, membership, actual weight, preferred move, available branches and one
of: in_book, move_not_authored, continuation_not_authored, position_not_in_book.

A first deviation is the first absent actual move **from a known position**.
A known leaf with no outgoing moves reports continuation_not_authored: the book
ended, not necessarily a repertoire decision worth criticizing. A completely
uncovered start is unknown coverage, with no attributed deviation. Deviating side
is explicit; user/opponent relation requires stored user color. Lookup continues
after leaving theory, so a later transposition can re-enter. First deviation never
changes on re-entry.

in_book_move_count counts matched played edges across all visits. known_position_count
counts known board visits including initial/final positions (not distinct graph
nodes); last_known_position_ply is the number of game plies already played, with 0
meaning the initial board. Provenance includes book ID, version, revision and snapshot
hash. Unknown/nonbook does not mean inaccurate, bad, or an engine loss.

Future ECO identity, review panels, adherence/search, opening training or comparison
should consume this service and explicit snapshot identity. They must not turn
book membership into engine accuracy or alter the existing Accuracy V1 formula.
No opening identification, built-in repertoire, saved searches or new analysis is
activated by this foundation.


## V1.1 presentation contracts

The V1.1 `branch_browser` projection remains available to core callers. V1.2's UI
uses `opening_book_navigation.branch_paths`, `BranchPath`, `BranchStep` and
`BranchNavigation`. Each step carries its exact incoming move-ID path; each branch
has an anchor and a bounded step index. A named child, branching choice or repeated
ancestral position terminates a branch. Preferred/weights never resolve choices.

Projection expands shared choice points once, while retaining unambiguous
continuations on incoming paths. Contextual projection reveals omitted shared
choices under the selected path and reconstructs their visible ancestors. Thus
transpositions remain finite without conflating board identity and path identity.
Navigation state lives in memory only. Book start clears it; explicit saves/edits
rebind it to the updated snapshot. All navigation remains engine-free and write-free.

The UI has Branch Browser and How To only. It delegates activation/stepping to the
portable navigator. Each move has a single-click target; a variation header targets
its first resulting position. Active header and current move are marked separately.
The editor is collapsed in viewing state, explicitly opened for saved edits and
automatically opened for pending authoring. Save Changes/Cancel and Save Move/Cancel
Move represent separate states. Graph deletion still uses the V1.1 snapshot-bound
service. Deleting a selected after-move context first removes the saved move through
that service, then replays the surviving parent path.

Move sources use the selected move's `from_position_id`; position sources use the
currently displayed saved position. This distinction prevents after-move navigation
from attaching provenance to the wrong position. Metadata remains data: normal
book/position edits preserve existing JSON; the move editor exposes validated JSON
only through an explicit Advanced dialog. No schema, identity or export change.

Terminal tree styling reuses `information_panel` colors and clones only the native
field surface needed for dark empty areas on Windows. `MerlinNotebook` retains
native navigation while enforcing at least 3:1 selected/inactive fill contrast
and 4.5:1 text contrast with theme-aware fallbacks. No global theme replacement.

Game Review's concise evaluation label keeps the signed canonical White-POV
number, naming the advantaged side (or Equal). Mate labels use existing winner
semantics, including M0. This is formatting only; evidence and math are unchanged.


## Opening Intelligence Application V1

The authoring model and Studio V1.2 UI remain frozen. The separate read-only reader
loads public repository snapshots without migration. OpeningBookLookup indexes a
selected immutable snapshot; typed legal game replay adds named-path context,
first/later deviations, re-entry and transparent coverage facts. Context/path
identity remains distinct from position identity. Batch application and search
hooks are portable; no engine or production persistence is involved.

See [OPENING_INTELLIGENCE.md](OPENING_INTELLIGENCE.md) for the four-consecutive-ply
meaningful-match rule, uncertainty bounds, naming/preference/membership identities,
Review invalidation and future Professor/Opening Accuracy contracts. The earlier
BookApplication API remains compatible; every stored acceptance fixture was checked
against its per-move membership, first deviation and visit counts.


## Opening Book Management + Active Reference V1

Installed books use separate single-book authoring files and a profile-local catalog. Package inspection/serialization, management, relevance selection and UI are separate layers. Existing Studio and Polyglot contracts are reused unchanged. See [Opening Library Manager](OPENING_LIBRARY_MANAGER.md) and [Sharing](CWBOOK_SHARING.md).


## Opening Library Live Integration V1.1

The managed source of truth is a multi-book .cwbook library identified by a UUID.
Books retain local book IDs and existing lifecycle status. A coherent library
snapshot discovers new books directly; no per-book import/registration step.
V1 catalog rows and IDs remain compatible through typed LibraryOptions in the
existing JSON envelope, without a schema migration. All consumers share canonical
library UUID/book/version/content provenance. Read-only external inspection and
explicit adoption are separate from internal creation.
See [Opening Library Manager](OPENING_LIBRARY_MANAGER.md).


## Opening Intelligence Application V1 — managed application

ManagedOpeningIntelligenceService resolves a canonical library UUID and local book
ID into the existing lookup/replay service. One snapshot per call prevents stale
live edits; structured per-move results carry book provenance even when returned
by deviation queries. Streaming distribution and deviation summaries retain typed
failures. No persisted assessment table or engine dependency was introduced.

## Studio V1.3 workspace contract

`opening_studio_service.OpeningStudioService` presents one logical opening workspace
without reassigning existing library/book identities. It lists all managed books,
resolves friendly duplicate labels, chooses the canonical new-book home, commits
in-memory drafts, and plans/reuses/imports selected external books. These services
import neither Tkinter nor an engine.

The first save of a draft copies its complete graph into the canonical home in one
authoring transaction; title-only confirmation saves an empty shell. The first
Save Move includes that move in the same graph transaction. New books default to
Active/version 0.1. Existing files are read/editable in place, with no automatic
consolidation. `studio_home` lives in the existing catalog JSON and is selected
under the catalog write lock. Startup alone never adds a home or preference file.

`opening_book_transfer.append_books` validates immutable snapshots, allocates new
local IDs and copies all selected graphs transactionally. It reuses destination
positions by canonical FEN but keeps notes scoped by book; remaps move/position/source
references; preserves metadata, clocks, revision and graph sharing; and never
updates existing books. The external source SQL is never executed. Existing service
semantic identities drive duplicate detection; same-name/different-content books
are distinct. Validation/failure rolls back the authoring transaction.

`OpeningLibraryService.delete_book` applies a snapshot-bound removal confirmation
by recording the ID in `studio_deleted_books` in catalog JSON. It clears a removed
primary and leaves the `.cwbook` graph byte-identical. Shared listing APIs exclude
that book, invalidating Review references without game-DB writes. Retained rows
reserve their old IDs and remain recoverable in managed backups. No schema change,
physical consolidation, background pruning or automatic owner migration occurs.

`merlin_ui/opening_studio_workflow.py` owns desktop selection and confirmations;
`opening_studio_dialogs.py` owns the small Save/Discard/Cancel and import previews.
Branch editing still delegates to the existing service/session/navigation modules.
The selected branch's first move already has a stable variation-name field; Rename
Line reuses it, including for generated headers. Clearing it restores the generated
label. Alternative navigation returns to the selected path's parent without graph
changes. All writes still use shared repositories and emit the existing live refresh
notification only after a successful action.


## Advisory research and atomic whole-line authoring (Studio 2.5)

`opening_engine_models`, `opening_engine_service` and `opening_engine_presentation` provide portable advice at an immutable saved library/book/route/revision anchor. Generation uses the shared CandidateLineService/Generator, exact request identity, existing Quick/Normal/Deep profiles and owned cancellation. Existing game evidence is read-only; complete new results use a separate user-data candidate-line cache. Advice applies neither Quality Gate/Scale admission nor analyzer truth.

`opening_book_line.plan_book_line` calculates an insert-only merge plan without SQL. `OpeningEngineAuthoringService` requires explicit confirmation and rechecks saved selection/evidence. `OpeningBookRepository.apply_line` revalidates under one transaction, preserves all existing IDs/metadata, reuses canonical transpositions, and rolls back every inserted edge on error. It deliberately does not call per-move metadata-upserting `save_branch`. Neutral weight/Preferred defaults apply only to new edges; inactive overlaps require a separate author decision. No book schema changes.

Tk owns only controls, background request delivery and board projection. No engine/database authoring logic is embedded in its event handlers. The existing Studio service/session and branch-navigation interfaces remain intact. See [complete advice contract](OPENING_STUDIO_STOCKFISH.md).
