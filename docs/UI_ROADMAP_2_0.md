# UI roadmap — implementation and acceptance status

Round 1 improves current controls and information layout only. Do not expose dead
menu items or imply any of these future capabilities exists.

- File: Export current FEN, copy full PGN, PGN through current position, Save PGN,
  Export board PNG, Manage Data.
- Game Review: per-move evaluation and Game Explorer/search are implemented below;
  the richer whole-game dashboard remains deferred.
- Training: persistent stats, solve history, motif performance, first-try rate,
  average solve time.
- Data management: Delete Games, Delete Themes and dependency-aware deletion.
  Separate design must specify dependency scan, dry-run, transaction/rollback,
  orphan checks, filesystem cleanup and active-theme repair before implementation.

## Analyzer review notes — preserved for a separate task

- Fork + Pin interaction.
- Fork recommending bishop-for-pawn with immediate recapture concerns.
- Fork proof lines ending before the exchange settles.
- Future Tactical Exposure: "this move allowed a fork."

These notes do not authorize analyzer pass 2 or proof-policy changes. No SEE
consumer, new analyzer, accuracy computation, historical scan or experimental
occurrence write is part of UI polish.

## Next acceptance checkpoint

Owner review of the updated source UI at physical Windows 100%, 125% and 150%
scaling, especially Training and long names/text. If accepted, request a new frozen
rehearsal explicitly. Existing certified binaries predate this source polish.
No automatic packaging, publication or distribution.


## Implemented — Eval Bar + Evaluation Timeline V1

Priority #1 is implemented and its visual polish is the frozen foundation for Accuracy V1. It adds
position evaluation only, uses the existing shared Quick cache identity, and integrates
missing actual positions into explicit Analyze Games runs. Navigation never starts an
engine. Mate/unknown/proof-line states remain distinct. This foundation adds no Game Explorer, Critical Moment ranking, opening analytics
or new analyzer. Accuracy is a separate layer described below. Production
data was not evaluated or changed. See [EVALUATION_UI.md](EVALUATION_UI.md).


## Implemented — Move Quality / Accuracy V1

Source is ready for owner review: compact You/Opponent summary with explicit coverage,
Details with best-move and phase metrics, and per-actual-move numeric evidence in the
Position panel. Stockfish depth-16 quality evidence is separate from the frozen Quick
timeline. No qualitative badges, timeline overlay or tactic admission changes.

The transparent ChessWizard score, mate rules, profile study and 24-case trust audit
are documented in MOVE_QUALITY_ACCURACY.md and reports/MOVE_QUALITY_TRUST_AUDIT.md.
No production games were analyzed. Physical visual approval and a new frozen package
remain separate; opening theory and Critical Moment Engine are deferred. Game Explorer is implemented below.

## Implemented — Game Explorer / Advanced Search V1

Tools → Game Explorer opens a dedicated resizable search window with database-local
Game ID lookup, metadata ranges, active tactic relationships, compatible complete
user accuracy, sortable results and exact-game Review navigation. All Games includes
unscored/untagged games. Search is read-only and performs no engine work. Opening
filters, saved searches, game-history dashboards and new played-tactic activation
remain deferred. Accuracy V1 owner review is accepted for now; its calculations,
Eval Bar/Timeline and registered Fork Pass 2 remain frozen.

Source implementation awaits owner visual acceptance. See GAME_EXPLORER.md and
reports/GAME_EXPLORER_V1.md for semantics, data limitations and measured performance.
No frozen package was rebuilt.

## Implemented — Opening Book Foundation V1

Tools → Opening Studio provides functional manual pending/save authoring,
multiple books and move branches, graph navigation/transposition references,
weights/preferred/active flags, original notes/source metadata, reopen/edit, verified
Polyglot export and single-game read-only membership application. Rich authoring
lives in a separately chosen .cwbook library; production game storage is unchanged.
The source foundation is ready for owner authoring acceptance, with dedicated UI
polish deferred. See OPENING_BOOK_STUDIO.md and reports/OPENING_BOOK_FOUNDATION_V1.md.

Still deferred: PGN branch import, opening identification/ECO, Opening Accuracy,
Game Review opening panel, adherence dashboard/search, multiple-book comparison,
opening training, built-in books and packaging/publication. These future features
must consume the shared graph/application service and keep membership separate
from move-quality truth.


## Implemented — Saved Game Sets / Collections V1 (production migration pending)

Tools → Game Explorer → Collections provides static collection CRUD, descriptions,
member counts, inspection and removal. Explorer adds multi-selection, add/remove
membership actions and an AND-composed Collection filter. Exact single-game Review
handoff remains unchanged. No new permanent Game Review panel was added.

Owner protection rule: saved games cannot be deleted, ignored-and-deleted or reset
until removed from every collection/set. Collection deletion retains the games.
Fresh and pre-extension migration rehearsals pass; production remains untouched.
Owner review can use the isolated fixture pending an approved backup/migration.

Dynamic saved searches, manual ordering, per-member notes, export, dashboards and
opening-study integration remain future work. Opening Studio owner usability
polish is separate and its source/model were not modified here.

## Implemented — Expanded tactic relationship foundation V1 (isolated rehearsal)

Five motif families now share typed exact-root relationship assessment, with
provider-owned truth, explicit ownership and immutable occurrence planning.
Explorer consumes this shared core; Training remains unchanged. Isolated fixtures
validate played/missed by user/opponent, including collection filters. Real stored
accepted evidence currently supplies missed-user opportunities only. Existing
played-Fork geometry controls remain distinct from verified payoff/admission.

Owner review and a separate approved production mapping step remain pending:
64 desktop mappings proposed; project mappings unchanged. This is not historical
played/opponent discovery or activation of new analyzers. Opening Studio,
Collections production migration and Critical Moment Engine are outside this task.
See TACTIC_RELATIONSHIPS.md and reports/TACTIC_RELATIONSHIP_EXPANSION_V1.md.


## Implemented — Opening Studio usability V1.1

Optional variation names/descriptions follow the existing move graph. Compact
trunks, nested named branches, direct click navigation, explicit editing/pending
states and breadcrumbs make short repertoires practical. Graph-aware deletion
previews preserve shared theory. Terminal information panes and stronger shared
tabs improve legibility. Explicit-open additive `.cwbook` upgrades preserve all
existing content. The isolated French fixture is ready for a second owner test.
Game Review now shows one concise side-specific evaluation label, without changing
its canonical number, accuracy or analysis.

## V3 idea — compact Game Review player summaries (roadmap only)

Explore the space beside player names for opening name, overall accuracy,
best-move rate and opening accuracy. Example concept:

- You: 87.4 | Best 42% | Opening 91
- Opponent: 81.2 | Best 36% | Opening 84
- Opening: French Defense — Advance Variation

These are illustrative display ideas, not implemented metrics or opening
identification. Reuse shared evidence/services, show coverage and unknown values,
and keep book membership separate from move-quality truth. No V3 player-summary,
ECO, Opening Accuracy or Opening Intelligence UI is implemented in this pass.


## Implemented — Opening Studio V1.2 branch navigation

Branch Browser is the primary surface: named headers activate lines, individual
moves navigate on one click, and local ← / → controls stop at explicit branch
boundaries. Book start clears active state. Exact incoming paths survive
transpositions. Saved Moves and competing history/follow controls are removed.
Viewing leaves the editor collapsed; Edit Move opens Save Changes/Cancel, and board
previews open Save Move/Cancel Move. Raw JSON lives only in an explicit Advanced
move-metadata dialog. No schema or engine behavior changes. The French fixture is
ready for a third owner authoring test; no package was rebuilt.

Future structured authoring fields may include Tags, Difficulty, Category and
Study priority. They should use validated shared metadata contracts and replace
routine need for raw JSON. They are roadmap only, alongside the previously noted
V3 Game Review player summaries; no new opening analytics are implemented here.


## Implemented — Opening Intelligence Application V1

Reusable read-only authored-book lookup and game/batch assessment now expose named
variation paths, book weights/preferences, first and later deviations, re-entry,
raw coverage counts and conservative meaningful entry. Explorer has service-level
query composition. A small Opening book facts window in Game Review is sufficient
for owner validation; Studio V1.2 remains unchanged. No persistent cache/schema,
engine work or final UI polish. Opening Accuracy, ECO, Professor/Lessons and the
V3 player-name summary remain deferred; they must consume the shared facts without
conflating book knowledge with move quality.


## Opening Book Management + Active Reference V1

Opening Book Management V1 adds Tools → Opening Library and a compact Game Review reference selector. Import/export/clone/enable/primary/removal are available; owner visual review is pending. Opening Accuracy, community services and lessons remain future work. See [Opening Library Manager](OPENING_LIBRARY_MANAGER.md).


## Opening Library Live Integration V1.1

Studio → New library/New book now writes directly into My ChessWizard Library.
Game Review exposes Library → Book choices, manual overrides and factual defaults;
saved branches appear without re-import/restart. Tools → Opening Library displays
the hierarchy and edits the canonical book. External adoption is explicit and
original-preserving. V1.1 is ready for owner acceptance after the reported tests;
Opening Accuracy, Lessons and publishing remain outside this pass.


## Opening Intelligence Application V1 — managed application

Opening Intelligence Application V1 now adds a provisional inline Opening block to
the existing Library → Book controls, with detailed Facts retained. Managed batch
application, meaningful matching, variation distribution, deviation and re-entry
query hooks are available without engine calls or production writes. Final visual
polish, Opening Accuracy, Professor/Lessons and persisted Explorer indexes remain
deferred. Owner validation of this application pass is pending.


## Game Review Opening UX V1

Implemented bottom Game/Opening modes and Opening Summary/Branch View using shared
high-contrast tabs. Manual selection persists across games; out-of-book actual moves
are italic; selected moves highlight; user-only authored suggestions are labeled
Book move. Exploration keeps a fixed actual anchor and has Return to Game plus the
always-available actual move-list escape. Owner visual acceptance is pending. Future
Opening Accuracy may extend the bottom Opening surface; Accuracy and Lessons are
not implemented in this pass. See [Opening UX](OPENING_INTELLIGENCE.md#game-review-opening-ux-v1).


## Opening Accuracy V1 — ready for owner review

Opening Summary now separates engine Accuracy from Opening Adherence, including evidence coverage and numeric first-user-deviation facts. Branch View shows the selected actual move's evidence without annotating every row. Accepted session selection/navigation remain intact. Typed variation/deviation/query APIs prepare future Explorer and Professor work; Lessons, new Explorer controls and publishing remain deferred. The preceding milestone descriptions describe their original scope; Opening Accuracy is implemented in this milestone. See the [definition](OPENING_ACCURACY.md) and
[score/coverage limits](OPENING_ACCURACY.md#scores-and-denominators).
Owner-derived trust-audit receipts remain private.

## Opening Studio V1.3 — ready for owner authoring acceptance

The daily workflow is Book dropdown → edit, or New Book → blank inline title and
move zero → Save Move. Save/Discard/Cancel protects switching. Opening Details, Delete
Book, Rename Line and Add Alternative to This Move stay in Studio. External import
previews selected books and lands on editable managed content; export shares a copy.
Physical paths and external preview are Advanced only. Manager is no longer required
for authoring. This supersedes the older New Library/adoption-first UX above.

One logical workspace includes existing files without moving their IDs. New content
uses one canonical managed home. Owner books and game databases are untouched during
development; copy-only rehearsal and automated acceptance precede owner review.
No packaging, analysis or Opening Accuracy calculation is part of this milestone.


## Testing week: analysis responsiveness and Studio guidance

Analyze Games now separates background coverage counting from explicit Start.
Selected Game does not wait for global backlog counting. Real phase/progress counts,
per-database cross-process worker exclusion, prompt engine Stop, atomic-stage rollback,
and confirmed stop-and-exit continuation are implemented. Completed work resumes
through existing coverage/cache identities. Read-only incomplete-work detection
prepares a future startup Resume prompt; automatic analysis and a scheduler remain
deferred pending an owner preference.

Opening Studio V1.3 remains the single authoring screen. Add Alternative now names
the exact branch point/side; custom line-name reload and unchanged Polyglot bytes
are covered. Training stays unchanged, with an interactive grading regression.

Source testing and isolated profiling precede owner acceptance. No packaging,
production reanalysis, new analyzer or weaker proof policy is part of this pass.
See [progress, cancellation and errors](ANALYZE_GAMES.md#progress-cancellation-and-errors)
for the public behavior and safety contract. Owner-history latency measurements
remain private and are not a performance guarantee.


## Testing week: progressive recent-game analysis

Recent 50 is the explicit-analysis default; Recent 100 and All Missing are available.
All Missing validates and processes consecutive 50-game windows instead of waiting for
a global cached-proof count. Batch progress and separate deferred/recoverable/fatal
outcomes are visible. Review receives durable batch results without resetting the
owner's current move or selected proof. Stop retains completed stages and rolls back
the unfinished stage. Import skips empty records with an explicit count.

No production empty-game cleanup, evidence-policy change, scheduler or frozen release
is included. Native owner review of the new scope/progress wording remains a source
acceptance step. See
[progressive batching and recoverable failures](ANALYZE_GAMES.md#progressive-batching-and-recoverable-failures).


## Opening Analysis data foundation — inspect before UI design

Opening Analysis Engine V1 now offers explicit book-side intent, transient matching sets, full-path variation groups, transparent user adherence, first/common user/opponent departures, neutral repeated-gap candidates, re-entry and descriptive context. Existing Accuracy V1 supplies separately labeled user engine scores and partial/unresolved coverage. Pure accessors/query hooks prepare Game Review, Explorer, Save as Collection and The Professor.

No final Opening Analysis screen or Lessons UI is implemented. First review the public
[analysis model](OPENING_ANALYSIS_ENGINE.md) and
[aggregation contract](OPENING_ANALYSIS_ENGINE.md#accuracy-and-descriptive-aggregation).
Owner-derived book results and trust samples remain private. A future design should make side, sample sizes, adherence numerator/denominator, score coverage, known-leaf departures, alternatives and source game/move navigation visible. Do not turn descriptive variation scores into rankings by default. Owner books remain unconfigured/unchanged by this development audit.

## Next analysis-control pass: actionable Recent 50 / Recent 100

Agreed future semantics: **Recent 50 means the newest 50 games that still have actionable analysis work**, not the newest 50 stored games. Recent 100 follows the same rule. Exclude fully complete games, games whose remaining obligations are all valid stable-final defers, and zero-move/invalid games **before applying the limit**. Invalid cases should retain separate diagnostic reporting. Stale deferred contracts become actionable according to existing version/profile/evidence currentness.

This is a documented next-pass change only. The current task does not alter Analyze Games UI, readiness, batching, scope limits, deferred-ledger semantics or scheduling.


## Opening Studio 2.5: explicit Stockfish advice

Implemented **Stockfish Lines** between Branch Browser and How To: saved anchor, Analyze/Stop, existing Quick/Normal/Deep levels, White-POV MultiPV/SAN table, isolated preview arrows/Return, optional deeper/refresh requests and confirmed Add as Variation. Whole-line merge preserves existing theory and author-controlled weights/preferences. The advice tab uses the right pane while author controls remain available on Branch Browser.

Automated acceptance and isolated real-engine checks are summarized in the
[Studio advisory validation](OPENING_STUDIO_STOCKFISH.md#validation). Native owner visual/authoring review is the next acceptance step. No packaging, final Opening Analysis UI, automatic gap repair or Lessons work is included.


## Game Review Opening Workspace V2

Implemented Opening Review V2 in Game Review: flat book choice, explicit repertoire side, stored-fact background metrics, sortable matching games, moments, authored playback, relevant paths, gap drill-down and exact staged Studio handoff. This supersedes the earlier separate-screen/data-only plans above. The actionable Recent 50/100 correction is also implemented. Isolated acceptance and the real French read-only benchmark precede owner visual acceptance. No Lessons, automatic gap repair or packaging is included. See [workspace guide](GAME_REVIEW_OPENING_WORKSPACE.md).

## Opening Review drill-down polish V1 — ready for owner acceptance

This supersedes the previous context-dependent navigation polish. Summary grids only
filter; game grids only select/filter; Opening Moments alone load the chosen game and
navigate its exact decision. Contextual Previous/Next Game, generic Open, summary
double-click navigation and Relevant Line are removed. Normal Game Review navigation,
explicit Show Opening Line and exact Studio staging remain.

One game/ply event combines compatible tags such as opponent departure and Opening Gap.
A separate Selected game label names browsing context; the compact board banner names
the displayed game/move, even across identical positions. Summary and affected games
share a balanced draggable splitter above moments. Position details are collapsed by
default behind a compact evaluation strip. Background progress and the resize safety
guard remain. Matching, scores, analyzers, Recent 50/100 and persistence are unchanged.

See the [workspace guide](GAME_REVIEW_OPENING_WORKSPACE.md) and
[exact event identity contract](GAME_REVIEW_OPENING_WORKSPACE.md#exact-event-identity-and-combined-tags).
Automated isolated acceptance covers repeated deviations, exact game selection,
read-only safety and 100/125/150% layout tests; owner-case receipts remain private. Native owner visual acceptance is next. No packaging.

## Automatic resize safety

Review minimum height is derived from requested fixed controls and padding, never from
subtracting a child allocation that may still belong to the previous resize. The desktop
`AutomaticSizeGuard` stops an alternating size cycle or a burst of more than ten automatic
changes within two seconds. It logs one diagnostic and remains latched until width,
scale or view context changes; it never intercepts manual dragging or saves a preference.
Both the root minimum and Opening Review pane minima use this guard. Stable no-op sizes
do not count. Regression coverage exercises alternating/growing proposals and real layouts
settling at 100/125/150% scaling without triggering the guard. Test windows run offscreen,
and Tk callback errors fail the test runner.
