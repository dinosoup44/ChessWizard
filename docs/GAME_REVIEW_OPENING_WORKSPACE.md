# Game Review Opening Workspace

Opening Review uses the same board, actual-game cursor, timeline and Game Review window.
The interaction contract is:

**Summary grids filter → game grids select → Opening Moments navigate the board.**

## Daily workflow

1. Choose **Opening Review** and a managed **Opening**. Matching and stored-fact
   aggregation run on a cancellable background worker with visible progress.
2. In **Deviations**, **Opening Gaps** or **Variations**, click a summary. This only
   fills the middle affected-games grid. It never changes the board or loaded game.
3. Click an affected game. The bottom **Opening Moments** grid now belongs to that
   exact game and the selected summary's occurrences. **Selected game: ID · vs opponent**
   identifies this browsing context. The board and timeline still show the previous game.
4. Click an Opening Moment. This loads its exact game, shows the decision position
   before that move, highlights the played move, updates the timeline and the compact
   game/move banner beside the board. The Opening and current subtab remain selected.
5. The **Games** tab uses the same boundary: its row selects a game and shows all its
   moments; only a moment click navigates. Sorting never navigates.
6. **Show Opening Line** previews a selected moment's preferred or sole authored
   continuation. If several choices lack a preference, a small menu offers them.
   **Previous Move / Next Move** step the displayed actual history or authored line.
   **Return to Game**, or an Actual Game Move click, exits authored playback safely.

The contextual Previous/Next Game controls, generic Open button, summary double-click
navigation and Relevant Line tab are removed. Normal Game Review navigation remains.
There is no miniature Opening Studio or alternate clickable line table in this workspace.
The reusable line-formatting and exploration services remain available to other consumers.

Manual Opening selection, including **No opening / None**, persists across games and
subtabs. Browsing a game never silently replaces the selected Opening. An unrelated game
is shown as a nonmatch, with no invented Opening Moments.

## Exact event identity and combined tags

One real event at one game/ply is one Opening Moment. For example,
**Opponent left opening · Opening gap** is one row with two tags, rather than duplicate
rows. User departure, opponent departure, re-entry, authored preference and compatible
stored quality remain attached to the same immutable move facts. Different plies never
merge, including repeated visits to the same position.

The event key includes immutable game identity, full Opening provenance, game ID, move ID
and ply. It is independent of row ordering and display wording. The move retains exact
position, variation path, available/preferred authored moves and all original provenance.
The affected-games grid groups repeated occurrences into one game row but retains every
visit; the bottom grid filters to those exact plies. Variation and Games selections show
all of the chosen game's moments.

The browser selection and the displayed game are separate. Background results and
programmatic refreshes never navigate. Displayed-board arrows use the displayed game's
assessment, not another game's browsing facts. A user-departure arrow is eligible only
when an authored preferred move exists; it is not a Stockfish recommendation.

## Layout and identity

Deviations, Opening Gaps and Variations have summary / affected games / moments panes.
The top and middle grids share a draggable vertical splitter with an even default split;
each requests six rows and has font-derived minimum space. The outer divider initially
allocates 65% to those grids and 35% to moments. At smaller heights the panes keep their
minimum usable rows; at larger heights they expand naturally. Both dividers retain their
fractions for the session. No new preference or storage system is introduced.

The compact board banner says, for example, **Game 1671 · vs opponent · 5...Bd7 · decision**.
It identifies the displayed game, independently of the Selected game browsing label.
Actual navigation and authored/proof modes update this banner even when the board FEN
is identical across games. Under the timeline, a compact position/evaluation strip stays
visible. **Show position details** expands the existing detailed text; it is collapsed
by default and loses no stored information.

Automatic minima use requested control sizes, not feedback from stale child allocations.
The existing `AutomaticSizeGuard` stops alternating cycles or bursts of more than ten
changes within two seconds, logging one diagnostic until the layout context changes.
Explicit divider dragging is not intercepted. Regression tests cover settled layouts,
manual divider movement and minimums at 100%, 125% and 150%. Test windows stay off-screen.

## Existing measurements and background work

Opening Analysis owns meaningful entry, explicit Opening Side, scoring windows and
formulas. This UX pass does not alter them:

- Opening Accuracy pools user move scores and labels partial/unresolved evidence.
- Opening Adherence is authored user moves / known-position user opportunities.
  Active nonpreferred alternatives remain in the Opening; opponent departures do not
  lower user adherence.
- Scored/eligible, missing and unresolved counts stay distinct.
- Opening Gaps remain repeated opponent departures without an authored reply, not a
  judgment about move strength. Re-entry retains its existing interpretation.

Game and moment quality comes from that exact game's immutable aggregate. Before an
aggregate is available, the displayed game's existing quality can supply its fallback
summary. Browsing another game never borrows the displayed game's quality.

**Analyzing <Opening>…** reports real matching/stored-evidence and aggregation phases.
**Opening changed — refreshing review…** remains visible after committed edits.
Cancellation and generation IDs reject obsolete worker results. Refresh uses read-only
facts and never requests Stockfish or persists an assessment.

## Exact Studio handoff

**Open in Opening Studio** uses the board currently displayed, independently of
Opening Moment selection or any other browsed game. Once the selected Opening and
displayed game facts are loaded, any valid actual cursor is eligible, including the
starting and final positions. Previous/Next, actual move clicks, moment navigation,
game/opening changes and all four browsing tabs refresh the same enablement check.
A moment displays its decision position **before** the labeled move; press Next to
hand off the position after that move. The action never advances the cursor implicitly.

The handoff captures the current game ID, actual ply, exact position, selected managed
Opening/revision and safely derived variation context. `studio_source_step` validates
the visible board against the loaded game's immutable facts, without storage reads,
engine work or graph traversal. The displayed-game `OpeningReviewSession` supplies
facts; a browsed game's detail panel cannot override them. Loading/stale inputs disable
the action temporarily. Show Opening Line retains its separate moment-specific guard.
Explicit authored-line exploration can still open its exact saved route using its own
validated decision anchor; Return to Game restores the actual cursor. Tactic proof
playback is not treated as actual game history.

The existing handoff planner inspects the actual route through the cursor and finds the
nearest authored ancestor. Only the missing suffix is staged. Exact canonical positions,
including proven transpositions, open the existing saved branch with no proposal or
new content. Canonical matching includes piece placement, turn, castling and relevant
en-passant state; similar-looking boards do not qualify.

Opening Studio or Cancel never writes the Opening. **Create Variation from Game**
previews SAN/merge counts and requires explicit confirmation through the existing
ID-preserving repository.
The proposal is optional: normal Save Move already persists manual authoring. When
its full active route exists, the proposal retires with “Game continuation already
exists in this Opening.” A changed/incomplete route retires as superseded, without
claiming completion; continue with normal Save Move. Redundant creates check the
fresh graph before the old selection anchor and never duplicate authored moves.
Strict revision checks still protect genuinely new atomic inserts. No theory is added
by selecting a grid row. Stockfish Lines remains a separate explicit Studio action.

## Shared contracts and safety

- `opening_workspace.opening_moments`: portable combined-event projection.
- `opening_review_navigation`: exact occurrences and immutable `OpeningGameSelection`;
  `affected_games` groups visits without losing plies or provenance.
- `opening_studio_handoff`: exact immutable context and pure merge planning.
- `OpeningAnalysisService`: cancellable read-only snapshot and unchanged aggregation.
- Desktop adapters own widgets, grid selection and splitters; core facts remain usable
  without Tkinter. No analysis or persistence logic is moved into the UI.

Analyze Games Recent 50/100 still means newest actionable legal games, using existing
readiness/deferred checks before the limit. No analyzer, formula, production schema,
owner Opening, cache, training or candidate changes accompany this pass. No packaging.
The public acceptance contract is the [daily workflow](#daily-workflow) and
[exact event identity](#exact-event-identity-and-combined-tags): drill-down changes
selection without borrowing another game's evidence. Detailed owner-session receipts
remain private.
