# Opening Accuracy V1

Opening Accuracy measures engine move quality inside a selected authored opening window. Opening Adherence measures repertoire membership. An out-of-book move can score 100; an in-book move can lose evaluation. Preferred flags and authored weights never become engine scores.

## Opening window

Use the existing meaningful-match policy: four consecutive active authored plies by default. The window starts at the first move of the first qualifying run, not at the fourth confirming move. A game with no qualifying run is not applicable for that book; merely sharing the starting position is insufficient.

Walk actual game moves from that start. Each reached known selected-book position renews the window. Include at most four actual plies after the last known position, or stop at game end. Thus a known position after ply 5 allows plies 6–9. Re-entry within the bound renews it; a later isolated transposition cannot reopen an expired window. Long authored lines can extend beyond ten moves. There is no fixed first-ten-moves fallback.

`OpeningPhase` records start/end ply, last known ply and end reason. `OpeningAccuracySettings.continuation_plies` is shared typed settings metadata (default 4, range 2–20, basic; affects result currentness, not raw engine identity). `policy_version` versions this contract. Settings can be supplied to the service; this pass adds no Admin Console control or separate configuration store. The quality property delegates to authoritative `MoveQualitySettings`, not a parallel opening formula/profile.

## Scores and denominators

Only the user's moves enter user metrics. White and Black have separate typed metrics; an unknown user color receives no guessed user score.

The new Opening Analysis Engine first requires explicit book `repertoire_side` (White/Black/Both-reference) and meaningful matching games on the stored user's intended side. Missing legacy metadata requires configuration; no name-based inference or owner-book edit is performed. Both/reference admits either known user color but scores only that user per game. Existing Game Review selection behavior is preserved.

In the existing Game Review accuracy result, Opening Adherence is `100 × in-book user moves / user moves made from known selected-book positions`, within the opening window. Display numerator and denominator. Active non-preferred moves count as in book. Moves from unknown positions do not enter either count. A known leaf with no authored continuation follows existing Opening Intelligence semantics: it is a book opportunity with `continuation_not_authored` departure, not proof that the actual move is bad.

After an opponent departure, user moves can still receive engine scores within the window, but unknown decision positions do not penalize adherence. Re-entry resumes opportunities at the next move from the reached known position; the transposing move itself retains its original decision-position classification.

Opening Accuracy reuses `move_quality.aggregate`: arithmetic mean of available compatible per-move Accuracy V1 scores. Finite cp scores use the unchanged `100 / (1 + (loss_cp / 100)^2)` formula. Three scored moves of 100, 100 and approximately 0.99 average approximately 67.0, not zero. Missing or contradictory evidence is excluded from the numeric mean and remains explicit in coverage; it is never treated as perfect.

Show scored/total user moves and complete/partial/not-analyzed/unresolved status. `no_moves` applies to an empty side. Average and median cp loss use finite cp results only; best-move rate carries its own available-root-evidence denominator. Mate transitions retain the frozen Move Quality rules and do not receive fabricated cp losses. A result can have engine evidence yet remain unscored because restricted/root estimates contradict.

Only exact compatible Stockfish 18, depth 16, one-line requests are read, with the existing engine options, FEN, legal PV and restricted played-move identity checks. Eval Timeline depth-10 evidence cannot substitute. This layer never generates missing evidence or fills a cache.

## Shared APIs and results

`OpeningAccuracyService(database_path, library=None, settings=...)` resolves a fresh managed book snapshot and joins game facts/quality in one read-only game-DB transaction:

```python
service.get_opening_accuracy(game_id, library_id, book_id)
service.get_opening_accuracy_for_games(library_id, book_id, game_ids)
service.get_variation_accuracy_summary(library_id, book_id, game_ids)
service.get_opening_deviation_quality(library_id, book_id, game_ids)
```

Game IDs are explicit, positive and deduplicated. Batch failures are returned separately from successful not-applicable games. Draft books work when explicitly selected; automatic reference-selection policy is unchanged.

`OpeningMoveQuality` composes existing `OpeningMoveAssessment` and `MoveQuality`, retaining actual IDs, actor/party, position, membership, preferences/weights, variation, book provenance, engine evidence identities, accuracy and loss without flattening or copying those contracts. `OpeningGameAccuracy` adds the window, side metrics and currentness identities. Its first user deviation carries both repertoire and numeric engine facts.

`VariationAccuracy` groups by book provenance, phase/quality identity and full authored path/anchor IDs at the last known position inside the window. Later excluded re-entry cannot rename the window. Ambiguous and unnamed contexts remain explicit. Statistics pool user moves across games, not averages of game averages. Counts expose games, complete games, unknown-user games, scored/total moves and adherence numerator/denominator. They are descriptive statistics, not coaching conclusions.

Deviation summaries return all scoped user/opponent deviations with position and provenance for future repeated-position grouping. Professor, Lessons, mobile and dashboards can consume these portable models; no lesson generation is implemented.

`OpeningAccuracyQuery` and `matches_opening_accuracy` provide future Explorer filters for score/adherence ranges, authored variation, user deviation and minimum cp loss at a user deviation. Complete results are required by default. Including partial results requires `require_complete=False`; absent numbers still cannot satisfy numeric bounds. No Explorer controls or persisted indexes are added.

## Game Review

Opening Review displays pooled/user metrics separately from authored adherence and
numeric evidence coverage. Summary rows filter affected games, game rows select that
exact game's Opening Moments, and only a moment click navigates the board/timeline.
Moment quality comes from the selected game's existing immutable result. It never
borrows another displayed game's evidence or scores an authored line projection.

Manual Opening selection persists across games. No Opening clears Opening Accuracy
and adherence while general Accuracy remains available. Relevant Line has been removed;
Opening Moments retains authored choices and stored accuracy/loss, and the displayed
board has a compact identity/evaluation strip with expandable position details. No
formulas, matching windows, evidence semantics or persisted data change.

## Provenance and invalidation

Every game result retains library UUID, book ID/name/version/revision, content/membership/label/preference hashes, match policy, game identity and quality/window policy identities. Per-move quality retains raw request/result identities. A new service call loads a fresh book snapshot; existing live-book refresh events rebuild Review output. There is no persistent opening-summary cache to go stale.

| Change | Numeric/context effect |
| --- | --- |
| Naming only | Engine scores and adherence unchanged; authored labels/group names refresh. |
| Weight | Engine scores unchanged; preference metadata refreshes. |
| Preferred move | Membership usually unchanged; recommendation metadata refreshes. |
| Active move graph | Recompute window, membership, deviations and aggregates. |
| Game moves/user color | Recompute join, side ownership and metrics. |
| Window or quality policy | Result identity changes; exact raw engine evidence remains reusable when its request is unchanged. |
| Missing compatible evidence becomes available | Recompute numeric coverage; no inferred score before it exists. |

No schema changes, production writes or duplicated engine evidence. The public
[score and denominator contract](#scores-and-denominators) explains trust limits:
missing evidence is not a perfect score, and repertoire membership is not engine
quality. Owner-derived timing and trust-audit receipts remain private. Owner review
is the next step.


## Opening Analysis foundation extension

`opening_accuracy_evidence.assess_opening_evidence` now serves both the existing OpeningAccuracyService and the new portable OpeningAnalysisService. It reads exact existing requests using the original full played FEN, validates shared settings, and delegates to the unchanged phase/derivation/Move Quality code. No alternative score formula or engine profile exists.

Opening Analysis uses **full-game known-position adherence**, including later re-entry; its numeric Opening Accuracy continues to use the bounded window described above. A user departure outside that window can carry existing move-quality facts for inspection, but is not added to opening-score totals. The legacy Review adherence remains window-bound. Consumers must label these denominators rather than substitute one for the other.

The primary aggregate is the arithmetic mean over scored eligible **user moves**, with every scored decision receiving equal weight. Variation summaries also expose explicitly separate mean/median game scores. For games with `[100, 100]` and `[100, 100, 50]`, pooled accuracy is 90, while mean game accuracy is 91.667. This is standard arithmetic pooling, not a copied proprietary chess formula; median is a complementary descriptive statistic. [NIST definition of mean and median](https://www.itl.nist.gov/div898/handbook/eda/section3/eda351.htm).

`OpeningAccuracySummary` exposes `evaluated_moves / total_moves`, coverage percentage, missing-evidence and complete-but-unresolved counts. A partial mean can coexist with 100% raw evidence availability when contradictory root/conditioned estimates are unscored. Numeric Explorer accuracy filters require complete scores by default; new OpeningAnalysisQuery callers may explicitly include partial values with `require_complete_accuracy=False`. A plain repertoire matching-set query needs no engine scores.

Full-game variation distribution and opening-window variation accuracy retain separate contexts, preventing late transpositions from renaming an expired scoring window. Nested paths and equal-name/different-anchor identities are retained. Departure groups expose frequencies, distinct affected games, cp mean/median, raw accuracy values, authored preference and engine best separately. No harmless/damaging labels are derived.

See [Opening Analysis Engine](OPENING_ANALYSIS_ENGINE.md) and its
[accuracy and aggregation contract](OPENING_ANALYSIS_ENGINE.md#accuracy-and-descriptive-aggregation).
The 27-case owner-derived trust sample and real-data receipts are private. The new foundation does not change Game Review or add a final analysis screen. Earlier UI/audit sections above describe existing behavior, not newly shipped UI in this pass.


## Game Review Opening Workspace V2

Opening Review displays pooled user Opening Accuracy separately from authored adherence. Scored/eligible, missing and unresolved counts remain explicit; per-game incomplete scores are marked partial. Opponent gaps never penalize user adherence, and active nonpreferred moves remain in book. The existing formula and opening window are unchanged. See [workspace guide](GAME_REVIEW_OPENING_WORKSPACE.md).

## Opening Review display terminology

The UI uses **Opening Adherence**, **Opening Side**, **Opening Move** and **Opening Gaps**.
Internal book/repertoire field names and identities are retained. Accuracy arithmetic,
eligibility, missing/unresolved evidence and denominators are unchanged.

Affected-game drilldown shows stored Opening Accuracy and actual departure loss when
available. A combined **Opponent left opening · Opening gap** event is one moment at
one game/ply, with the same quality and provenance retained. Different plies remain
separate. Deduplication changes presentation only, not score eligibility, denominators,
matching or gap frequency. A departure or coverage gap is not automatically a mistake.
The [workspace guide](GAME_REVIEW_OPENING_WORKSPACE.md) documents exact event selection,
Studio handoff and the displayed-game banner.
