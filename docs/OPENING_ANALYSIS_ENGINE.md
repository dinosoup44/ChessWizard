# Opening Analysis Engine V1

This is a portable data/service foundation. It does not add an Opening Analysis screen, Lessons, engine generation, an automatic Collection or persisted metrics. Book membership and engine quality remain separate facts. An out-of-book move can be engine-best.

## Layers and entry points

| Layer | Responsibility |
| --- | --- |
| `opening_repertoire.py` | Typed White / Black / Both-reference intent in existing book metadata. |
| `opening_analysis_models.py` | Immutable game, matching-set, deviation, gap and summary contracts. |
| `opening_analysis_repository.py` | Read recorded game/source/owner metadata and resolve a bounded explicit scope or owner history. |
| `opening_analysis_service.py` | Resolve a fresh selected book; coordinate one read-only game snapshot. |
| Existing Opening Intelligence | Validate legal actual-game replay; active rooted membership, meaningful entry, named paths and re-entry. |
| `opening_accuracy_evidence.py` | Shared join using the existing Move Quality repository, also used by `OpeningAccuracyService`. |
| `opening_analysis.py` | Compose user adherence and all known-position departures from those facts. |
| `opening_analysis_statistics.py` | Pure aggregation; no SQL, chess engine, coaching conclusions or frontend imports. |
| `opening_analysis_query.py` / `opening_analysis_accessors.py` | Explorer/Professor consumption of one computed result, without repeating database work. |

```python
from opening_analysis_service import OpeningAnalysisService
from opening_analysis_accessors import get_games_for_opening_book
from opening_analysis_query import OpeningAnalysisQuery

service = OpeningAnalysisService(database_path)
result = service.analyze_opening_book(library_id, book_id, game_ids=None, user_id=1)
games = get_games_for_opening_book(result, OpeningAnalysisQuery(user_deviated=True))
```

`analyze_lookup(lookup, game_ids=None, user_id=...)` supports a frozen book snapshot, read-only external content or an isolated validation copy. Its match policy must agree with the service. No constructor runs game analysis. The default history excludes development-source games. Explicit scopes preserve order, deduplicate positive IDs and report missing/invalid games separately. An empty explicit scope stays empty.

Ownership comes from stored `games.user_id` / `user_color`, never player-name guessing. One unambiguous owner can be inferred from the selected scope. Multiple owners require a supplied user ID. Wrong-owner and development games are excluded; unknown colors cannot earn user-side statistics. No schema/bootstrap path is called by analysis.

## Explicit repertoire side

The compatible existing `books.metadata_json` object stores `repertoire_side` as `white`, `black` or `both`. `RepertoireSide`, `BookDetails.repertoire_side` and `OpeningBook.repertoire_side` expose typed values. Both/reference includes both recorded user colors, scoring only the actual user in each game.

Absent metadata remains **unspecified**, not inferred from the opening name or silently set to Both. The new service requests an explicit choice before analysis. Existing Game Review behavior is unchanged. No production library is configured by this task.

`OpeningBookService.set_repertoire_side(book_id, side)` is an explicit authoring API through the existing repository, preserving other metadata and stable book/move IDs. A same-value call is a no-op. Normal repository revision/currentness updates apply; no table, column, migration or parallel settings file is added. Existing export/import/clone copies retain this metadata. A future Studio control can call the service without embedding logic in Tkinter.

## Matching and transient scope

Use the existing meaningful-entry rule: four consecutive active authored plies by default. Sharing the initial position or a shorter trunk is insufficient. Root-reachable, active branches only; disabling a branch excludes its disconnected positions. After meaningful matching, filter the stored user's side against explicit book intent.

`OpeningMatchingSet` retains the requested IDs, successful IDs, pre-side meaningful count, explicit exclusions/errors, database namespace, owner, repertoire side and full `BookProvenance`. Detailed games carry source/source-game IDs, dates, players, result, color, longest matching run, final known variation and complete legal replay facts. Book provenance includes library/book/version/revision plus content, membership, labels, preferences and matching policy.

This is a **transient analysis set**. A future Save as Collection command may pass its IDs to the existing Collections service after an explicit user action. Computing or filtering the set never creates a Collection.

## Adherence and departures

For each matching game, count all user decisions from known selected-book positions:

`adherence = 100 * active_in_book_user_moves / known_position_user_opportunities`

Return both integers and percentage; no denominator means no percentage. Opponent moves and unknown decision positions contribute neither numerator nor denominator. Active non-preferred alternatives count fully; weights and preferred flags are author facts, not scores. A known authored leaf is an opportunity with `continuation_not_authored`, preserving the existing Opening Intelligence contract; it identifies an unrepresented continuation, not a mistake.

Opening Analysis adherence covers the **full actual game**, resuming whenever the game returns to known positions. Existing Game Review `OpeningSideMetrics` remains window-bound. These related but different denominators are explicit; this pass does not silently change Review.

Each `OpeningDeviation` records the existing exact per-move book facts, actual full FEN, user/opponent party, first-for-party marker, original variation paths, alternatives/preferences/weights, active replies from the resulting position, available engine quality and whether it belongs to the accuracy window. First user and first opponent departures are independent, including a known-position departure preceding later meaningful entry. All departures remain available, not only the first.

Canonical-position summaries use the **full canonical FEN**, never a Polyglot hash alone. They group visits, actual moves, distinct games and retained variation contexts. Clock differences share authored position facts but engine requests still use the exact played FEN with clocks. Repeated visits count as visits; affected-game counts are distinct. Same variation names at different anchor IDs never collapse.

## Repertoire gaps and re-entry

A `repertoire_gap_candidate` requires the same opponent move from the same known position, no active authored continuation at the actual resulting position, and at least two distinct affected games by default. A known leaf with no continuation also qualifies; repeated visits within one game do not meet the distinct-game requirement. No claim about tactical quality or weakness follows.

`OpeningAnalysisSettings.gap_minimum_games` uses the shared typed setting schema (default 2, range 2-1000, basic). `policy_version` defaults to 1 (advanced). Both affect derived-result currentness, neither changes raw engine identity. No new configuration store or Admin Console UI is introduced.

Unknown intermediate moves never gain retrospective in-book credit. Re-entry records include actual ply, reached canonical position, context and whether the existing accuracy window was still open. Detailed games expose all departures and re-entry count, allowing consumers to distinguish games that left and later returned. Final known variation distribution may differ from the variation inside an already expired scoring window; both are labeled separately.

## Accuracy and descriptive aggregation

See [Opening Accuracy](OPENING_ACCURACY.md) for the unchanged book-derived window and score contract. Only eligible user moves enter the aggregate. Compatible exact depth-16 evidence is read; absent or contradictory evidence is not generated or guessed.

The primary aggregate pools available **per-move** Accuracy V1 values. It does not average game means. Variation summaries additionally expose the separately labeled unweighted mean and median of scored game means. For two games with scores `[100, 100]` and `[100, 100, 50]`, pooled accuracy is 90; mean game accuracy is 91.667. This denominator choice gives each scored decision equal weight. Arithmetic mean and median use their standard definitions; median offers a complementary less-extreme-sensitive summary, not another chess formula. [NIST measures of location](https://www.itl.nist.gov/div898/handbook/eda/section3/eda351.htm).

Return scored/eligible moves, numeric coverage, missing evidence, complete-but-unresolved moves, complete/scored games, cp-loss means/medians, best-move counts and available-root denominator. Missing scores never become 0 or 100. Mate evidence retains the shared rules without fabricated cp. User-departure evidence can be inspected even outside the accuracy window, but never extends that window's denominator. Opponent quality, when available inside the existing join, is explicitly opponent-owned and excluded from user accuracy.

Variation aggregation preserves full nested anchor paths, ambiguous alternatives and unnamed trunk. Final-context groups do not add one game to every ancestor. Original observed/inferred contexts remain on game facts; aggregate grouping deliberately ignores that observation flag and groups by paths plus completeness. Descriptive result, user-color, source, time-class/control and date breakdowns provide no ranking or lesson. Dates preserve original metadata; the range uses parseable calendar dates without inventing timezones.

## Consumer APIs

All accessors accept the same immutable computed result:

- `get_games_for_opening_book(result, query=...)`
- `get_variation_distribution(result)`
- `get_user_deviation_summary(result)`
- `get_opponent_deviation_summary(result)`
- `get_repertoire_gap_candidates(result)`
- `get_opening_accuracy_summary(result)`
- `get_variation_accuracy_summary(result)`

`OpeningAnalysisQuery` supports exact library/book, observed named variation/anchor, accuracy bounds, adherence bounds, user/opponent departures, gap membership and an explicit minimum user departure loss. Equal-name variations can be distinguished by anchor. Missing numbers never pass numeric bounds. Numeric accuracy bounds require a complete user score by default; `require_complete_accuracy=False` explicitly permits partial means. A plain matching-set query does not discard games merely because they lack scores. No hidden harmless/damaging thresholds or qualitative labels are introduced.

Future UI should expose book side, sample size, both adherence integers, numeric evidence coverage/unresolved counts, known-leaf versus unrepresented-move departure, active alternatives, repeated opponent gaps and direct game/move navigation. Partial aggregates must be labeled. Do not rank variations from this descriptive dataset. Professor can consume position facts and exact game references before any lesson policy exists.

## Safety, currentness and cost

Game access uses SQLite URI `mode=ro`, `query_only=ON` and one transaction; the selected book is a frozen read-only snapshot. No candidate, coverage, training, occurrence, cache or owner-book writes. No engine startup or missing-evidence fallback. Core modules are importable without Tkinter. The result is portable to a future phone/tablet frontend.

Each call reloads selected book content; there is no persistent summary cache. Result identity incorporates matching scope, owner/side, book provenance, interpretation policy, game identity/context and actual numeric/missing evidence. Relevant authoring or evidence changes require a fresh result. Raw engine cache identity remains the shared Move Quality request; interpretation-only settings never create duplicate searches.

Legal full-game validation dominates history discovery. Measurements cover cold-ish whole history, recent subsets, a full matching-set rerun and pure aggregation; they are observations, not a promised latency SLA. No persistent opening index is introduced before results justify one. See [audit and performance](../reports/OPENING_ANALYSIS_ENGINE_V1.md).

## Next analysis-control pass

Documented future meaning: **Recent 50 = newest 50 games with actionable analysis work**, and equivalently Recent 100. Exclude fully complete, valid stable-final-deferred and zero-move/invalid games **before** applying the limit. Invalid/diagnostic counts should remain visible separately. This task changes neither scope selection nor Analyze Games UI/scheduler.


## Optional next consumer: Studio advisory research

Opening Studio now exposes the portable `OpeningEngineService` at one exact saved book anchor. A future gap consumer may open that saved position, then let the user request Stockfish advice and explicitly add one selected continuation. This adds no automatic gap analysis, repertoire repair, final Opening Analysis UI or Lesson workflow. Existing matching, adherence and Opening Accuracy semantics stay unchanged.

Advice has its own labeled White-POV evidence and separate cache write destination, reusing shared raw profiles/identities. It is not authored truth and never changes an existing book without confirmed authoring. See [Studio Stockfish guide](OPENING_STUDIO_STOCKFISH.md).


## Game Review Opening Workspace V2

Game Review now consumes these existing results in its right-side Opening Review workspace. The flat book selector feeds the unchanged explicit-side/meaningful-match service on a cancellable read-only worker. A games grid, transparent metrics, variation/deviation/gap tables and current-game Opening Moments replace the former standalone facts entry point. No Stockfish or persisted assessment is created by browsing. See [workspace guide](GAME_REVIEW_OPENING_WORKSPACE.md).

## Opening Review progress and drilldown

`OpeningAnalysisService.analyze_lookup` and `analyze_opening_book` accept an optional
`progress` observer receiving immutable `OpeningAnalysisProgress` records on the caller's
thread. Real phases/counts describe matching and stored-evidence reads, then aggregation;
there is no estimated percentage. Result identities and arithmetic are unaffected.
The desktop adapter marshals progress through its existing generation-tagged queue and
drops cancelled/stale events. Refresh does not request Stockfish or write results.

`opening_review_navigation` resolves existing grouped deviations to exact game/move
occurrences, preserving repeat visits and canonical-position transpositions. Opening Gaps
are the existing coverage signals, not engine judgments. `affected_games` groups visits
into one selectable game row while retaining every
exact ply in an immutable `OpeningGameSelection`. Summary rows only filter; game rows
only select/filter Opening Moments; only a moment click loads a game/decision. Background
refresh cannot navigate. Games-tab selections follow the same boundary.

`opening_workspace.opening_moments` combines compatible tags at one exact game/ply:
for example, opponent departure plus Opening Gap becomes one row. Its event identity
includes game identity, full Opening provenance and exact move/ply. Different visits do
not merge. The selected game's stored quality stays attached to its own event facts;
it is never borrowed from the displayed board's game. No matching, aggregation,
repetition, scoring or engine-request policy changes are involved.

Opening Review no longer exposes contextual Previous/Next Game, generic Open or Relevant
Line navigation. Explicit Show Opening Line and exact guarded Studio handoff remain.
The board banner identifies the displayed game while a separate label identifies the
browsing selection. Two font-derived splitters organize summary/games/moments, with the
existing resize-loop guard. See the [current workspace guide](GAME_REVIEW_OPENING_WORKSPACE.md).
