# Game Review tactical moments

Game Review reads stored discoveries. It does not run analyzers, request engine
positions, backfill opportunities, or write candidate/coverage/training data.
Its SQLite connection uses `mode=ro` and `PRAGMA query_only=ON`.

## Shared read path

`TacticQuery` (`tactic_query.py`) owns candidate visibility and game filtering.
`GameReviewRepository` supplies real games and canonical moves.
`TacticReadService` (`tactic_presentation.py`) passes candidates through the
shared FeedbackContext builder and deterministic Feedback Generator, returning
immutable `TacticalMoment` values with a `FeedbackResult`.
`TacticalMomentsPanel` consumes those results and selection callbacks;
it has no database or analyzer dependencies.

Candidate Viewer also uses `TacticQuery` for its existing fork/mate selection.
Keep visibility changes in the shared query rather than copying SQL into UI
widgets. `game_ids(..., within=...)` allows future consumers to intersect a
tactic filter with an independently selected scope.

## Visibility

- Ordinary missed-tactic types require `candidate_status='candidate'`.
- Mate accepts `candidate` and historical `confirmed` rows, but only the
  primary candidate of an active `candidate` episode. An EXISTS query avoids
  displaying the same candidate twice when multiple episode records refer to it.
- Rejected coverage hides the corresponding move/type candidate.
- Ambiguous duplicate canonical move/type rows are hidden without mutation.
- Historical candidates are not hidden merely because their analyzer version
  is old. This read path does not reconcile them.

The five current labels and mate's episode policy live in `TACTIC_POLICIES`.
Future `missed_*` types automatically receive ordinary active-row visibility,
a humanized label, and a filter option. Add a policy entry only when a label
or visibility exception is required; no Game Review tactic branch is needed.

## Presentation and replay

The [Feedback Generator](FEEDBACK_GENERATOR.md) owns wording. When a valid
TacticalOpportunity exists, the title derives from its primary
outcome. Supported/verified motifs are displayed as motifs; `context_only`
attributions are explicitly separate. Secondary and positional presentation
levels are muted, with positional list entries marked as notes.

Legacy or invalid optional opportunity metadata uses canonical tactic type,
played move, solution move, and stored proof. It never triggers metadata repair.
Proof is collapsed until Show Line is selected. It has a dedicated visible area;
Hide Line removes that area from layout. Selection always resets it to hidden.

Every click reloads the active candidate through
`TacticReadService.moment_for_candidate(game_id, candidate_id)`, rebuilding its
context and FeedbackResult. `TacticalMomentsPanel.render_feedback_result()` is
the single renderer for selection, clearing and proof toggling. It replaces all
optional text, motifs, attribution, relationships, notes and proof; absent fields
are cleared. Motifs have a separate visible label above the scrollable details.
The selected result owns presentation level; list-row snapshots do not supply it.

The board shows one legal canonical recommendation arrow, using the existing
board widget. It disappears on ordinary navigation, game/filter changes or a
selection without a valid suggested move. No ghost pieces are implemented.

`decision_step()` resolves the selected canonical `move_id` within the loaded
game and checks `fen_before`. Game Review sets its existing `current_step` to
that index. Actual-game orientation and navigation retain this replay state. Navigating
away in game mode clears the selected detail. Projected playback uses a separate
line state, described below.

The optional `on_train_candidate(candidate_id)` callback is the future training
integration boundary. Without a supplied callback, Train this is absent. V1's
normal launcher supplies none, so reviewing cannot record training attempts.

## Stored-line display and playback

`line_playback.py` supplies immutable `LinePlaybackState` and
`format_proof_line_rows(StoredLine)`. They depend only on stored-line data and
chess rules, never Tk, an engine, analyzers or persistence. The formatter uses
validated position FENs for full-move numbers and turns, retaining original SAN
spelling. `merlin_ui/proof_line_table.py` renders Move / White / Black columns,
with one row per full move. A black-first line leaves its first White cell empty.

Show Line enters `navigation_mode = merlin_line` at ply 0, the decision FEN.
The existing Move back / Move forward buttons now traverse the stored legal
positions. Start resets the projected line. Bounds safely no-op. The current
move cell is marked subtly; no cell is marked at ply 0. The header explicitly
identifies Merlin-line mode. There is no separate set of line navigation buttons.

The actual-game cursor and move records are never advanced by projected playback.
Hide Line removes the table, clears projected state and restores the actual-game
step saved on entry. The same buttons resume game navigation. Selecting another
tactic, game or filter cancels playback. Invalid, missing or null-move proofs
cannot enter playback; an invalid stored line is displayed with an explicit
unavailable message, and actual-game navigation remains usable. No partial proof
is presented as a playable line. Stored proof text and database rows are unchanged.

At the decision position the canonical legal green recommendation arrow remains
visible (including normal selected-tactic review). It disappears when advancing
into the projected line and returns on reset. Tactical target annotations only
use explicit stored participants, not inferred geometry; only recorded enemy
pieces present at the decision FEN are marked. During line playback, recorded
targets remain only while their original participants stay on those squares.
Moved/captured targets clear; stepping backward recomputes from the displayed
proof prefix. Moving away and back does not revive a target annotation.

## Semantic board roles

The production ChessBoard supports shared style keys and canvas roles:

- `last_move`: soft yellow outline, lowest highlight layer.
- `tactical_target`: soft red/orange stippled fill with a matching outline.
  Last-move borders are suppressed on target squares before drawing.
- `selected_square`: soft blue outline above the target fill.
- `merlin_recommendation`: green arrow; `suggestion_arrow` remains a fallback
  for existing style dictionaries.

Targets cannot be erased by last-move rendering. Selection uses an outline so
its overlap with a target is readable. Piece rendering and hit testing are
unchanged. `set_tactical_targets()` accepts chess-square IDs; position changes
and `clear_overlays()` remove old targets; Game Review then reapplies the targets
valid for the displayed proof prefix. Theme manifests are unchanged; shared
style keys leave room for future semantic theme customization. No ghost pieces,
translucent piece previews, multiple-line selector, Explore or Compare mode is
included. Future line selection can supply another immutable StoredLine to the
same formatter/player.

## Validation

Run `python -m unittest discover -s tests`. The integration tests cover shared
visibility, legacy and opportunity presentation, future tactic discovery,
filters, Candidate Viewer selection, actual Tk selection events, exact FEN
jumps, orientation/highlighting/navigation, and read-only enforcement.

A historical saved-500 audit also checked read-only behavior against stored games.
Its per-game receipts are private; the [public test workflow](DEVELOPMENT.md#tests)
uses self-contained fixtures and requires no owner database.


## Built-in human review sets

The Review Set selector is a read-only trust-testing aid. All Games preserves
normal browsing. Human Review — Questionable contains flagged cases from the
final first/second-500 Fork audit shortlists. Human Review — Verified is a curated
positive-control sample; Human Review — Selective-12 Changes contains shortlisted
new acceptances, rejections and deferrals. These labels describe audit results,
not new production analyzer truth.

Review sets narrow the game list; the existing tactic filter intersects that
list without being reset. Games retain normal ordering and appear once, even
when several audit cases/reasons belong to the same game. The dropdown shows a
short reason and the number of additional reasons. An empty intersection clears
the game/details and reports that no games are available; it never falls back
to All Games. Switching back restores ordinary game labels and browsing.

`game_review_sets.py` contains immutable, UI-independent metadata and filtering.
The UI reads only `review_data/builtin_review_sets.json`. Regenerate that fixture
with `python reports/build_game_review_sets.py` after deliberate shortlist
updates. This report-only tool reads the two final manual-review JSON artifacts,
records their SHA256 hashes, preserves case keys/move IDs/reasons/provenance, and
performs no chess analysis or database access. Unknown source categories fail
rather than silently being omitted. Five duplicate case selections across
categories remain as separate reason entries; the game dropdown is unique.

Current sets: Questionable has 17 games / 25 distinct cases / 30 reason entries;
Verified and Selective-12 Changes each have 6 games / 6 cases. Across all sets,
27 distinct cases are represented. Only six have matching visible stored
candidates (four in Questionable). The other 21 are audit-only/hidden proposals:
their actual moves are reachable through normal game navigation, but no Tactical
Moment or playable proof is fabricated. Game 3115's visible move-24 fork is not
the shortlisted move-11 incomplete case. Games 320 and 486 have no stored active
tactics despite their scratch-audit acceptance labels. The exact historical case
index is private and is not bundled with public source. The
[human-review identity contract](HUMAN_ANALYZER_REVIEWS.md) explains how stored
candidates and audit-only targets remain separate. Existing stored candidates
always retain their original details.

User-created sets, editing, sharing and collection persistence are future 2.0
work. No schema, candidate, coverage, training, cache or analyzer-policy changes
are part of this feature.


## Human QA feedback

Tools > Human Review / QA opens a dedicated window that saves an explicit
verdict and optional note to `reviews/human_analyzer_review.jsonl`, outside the
chess database. Selecting a stored candidate reloads its current saved review;
Save Review updates that candidate without navigating. Save drafts before
changing targets. Audit-only cases can be selected in the QA target dropdown
with stable audit IDs and null candidate IDs. Selecting a QA target does not
change the board or make a scratch proof playable. These judgments never affect
analyzer truth or training.

See [Human analyzer reviews](HUMAN_ANALYZER_REVIEWS.md) for identities, atomic
storage, malformed-file handling and the read-only summary command. An existing
Game Review session can continue normally; restart after finishing to load the
new controls.


## Human-facing audit language and context boundary

Built-in reason codes remain stable, while `review_reason_labels.py` supplies
human labels and explanations to the normalized fixture. Examples: "Mate may be
the main story here", "This move passed the engine-quality check", and "Current
proof differs from the older saved proof". A passed quality check is not a
verified tactic. Unknown codes receive a neutral review label and retain their
original code. Existing saved notes/reasons are not rewritten; new saves also
retain `review_reason_codes`. Audit identities and candidate IDs are unchanged.

Audit-only targets (including games 2771 and 2737) already support verdicts and
notes. A missing real move uses an explicitly labeled game-level QA anchor,
never an invented chess move. No new logger migration is needed.

Critical Moment Context V1 is **report-only**. It neither adds another UI panel
nor filters/ranks production moments. The
[context contract](CRITICAL_MOMENT_CONTEXT.md) documents available facts and
conservative gates. The 27 historical human-review notes remain private and are
not evidence supplied by the public distribution.
Tactic truth, The Scale and presentation importance remain separate. A real
material gain does not imply a winning final position; low importance does not
make a motif false. No Opening/Tempo/time-pressure analyzer or automatic
critical-moment aggregation is included.


## Major Material Blunders human-review set

The built-in **Major Material Blunders** set contains exactly the historical CSV shortlist: 19 audit-only cases (8 confirmed, 7 unresolved, 4 controls). `reports/build_game_review_sets.py` invokes the data-only importer in `reports/build_material_blunder_review_set.py`. CSV defines membership and ordering; the matching shortlist JSON supplies target and checker metadata. Separate false-negative spot-check entries are not imported. Existing review sets are preserved. Rebuild only after an approved artifact change.

Entries have real positive game/move IDs and null candidate IDs; no proposed tactic or synthetic position is supplied. Their stable case key is namespaced by the audit source and move. Classification, target, recorded decision FEN, checker reason and line remain generic audit metadata, carried into the existing human-review provenance fields and saved in the separate QA JSONL only when the user clicks Save Review. Changing wording does not change case identity.

Selecting an audit case uses the shared exact-move resolver and jumps to its stored `fen_before`, clears any stored tactical-line playback, and keeps the existing verdict/note controls. A sole selected audit target also positions the board when its game loads. Missing anchors are clearly labeled; mismatched stored FENs do not jump. Normal move navigation does not discard the active QA draft. No blunder-specific branch or calculation was added to Tkinter, and no ranking, detector, engine, candidate or coverage behavior changes.

To use it, open Tools > Human Review / QA, choose **Major Material Blunders** in Review Set, leave the tactic filter at **All games** to see the whole shortlist, then choose a game and its Human Review audit target. An already open Game Review window loads the updated built-ins after reopening.


## Future played/missed relationships (not active in Game Review)

[Tactical event relationships V1](TACTICAL_EVENT_RELATIONSHIPS.md) introduces a
portable occurrence contract beside tactic truth. Future filters should separate
Played/Missed, Me/Opponent using explicit perspective, and motif. Actual game
continuations and alternate proof lines have different roles, even when their
root moves match. A hypothetical proof must never be presented as game history.

The current missed-only query, FeedbackResult wording, StoredLine playback and
training paths are unchanged. Do not route played events into their missed-only
fallback labels. Original audit status, human verdict, and occurrence relation
remain independent concepts; no relation is inferred from the review-set label.
No played-tactic filter, puzzle mode or statistics feature is activated here.

## Played Fork assessment review set

Open Tools > Human Review / QA and choose Review Set **Played Forks**, then a game and its audit case in Human Review.
The exact ten packaged assessments are independent of candidate rows. Selection
jumps before the actual played root and preserves user-side orientation. The
panel shows PLAYED FORK, Geometry, Move admission, Best-defense proof and Recorded
outcome, followed by the existing assessment description. Details exposes targets,
recorded captures and explicitly separated actual/proof lines. Proof lines are
read-only text here; normal Move navigation remains actual game history.

This review tests motif correctness, factual recorded consequence, wording and
importance, not forced-payoff certification. Existing verdict controls and logger
are reused. No production Played/Missed filters, fake candidates, engine searches
or puzzle changes were introduced. Launch from the project root with
`.\.venv\Scripts\python.exe -B run_game_review.py`.

## UI polish round 1

Permanent actions live in File (Import Games, Exit), View (Show Last Move,
Appearance; Game Review where applicable) and Tools (Analyze Games, Training,
Human Review / QA, Admin Console). Both Game Review launch paths expose Training
and reuse one child window with the same database/profile/theme. The bottom utility
buttons/check box are removed. Move/game navigation remains next to the game panel.

White remains the first named player, Black second; only the winning player's
name is bold. Draws bold neither. Raw result is retained and redundant Your Color
text removed. User-oriented board rotation is unchanged.

Actual Game Moves displays one numbered row with separately clickable White/Black
SAN cells. Each cell navigates to the position AFTER that half-move, even for a
black-first partial game. The current actual half-move is highlighted and follows
Previous/Next. Merlin proof playback remains separate and retains the actual-game
return position. Clicking actual history exits proof playback.

The board's lower information surface shows only stored/current facts: turn, last
actual move, selected moment, played/recommended move and available target squares.
Empty filters and unselected positions clear prior moment information. No scores,
accuracy, new chess calculations or engine requests are introduced.

View > Show Last Move toggles only that board layer, leaving tactical targets,
selection and arrows intact. The explicit user toggle persists through the shared
ApplicationSettings repository; reads never create settings. Its setting has no
raw-cache or analysis-currentness impact. Training has a separate hidden default.

### Training context and controls

Training uses Previous/Next Puzzle, Show/Hide Last Move, Show/Hide Game Line, Hint,
Reveal Solution and Open in Game Review. Start Puzzle explicitly starts the existing
attempt workflow; opening Training alone still creates no attempt. Review Mode
and proof stepping retain the existing behavior. Legal-move visibility is a menu
preference in standalone Training; contextual controls replace the checkbox strip.

Previous actual move, actual game continuation, and Merlin solution are separate
reveals. The first two start hidden for each puzzle, as does solution text. Last
Move never moves the puzzle board and never mislabels a proof reply as game history.
The shared read-only game_context helper obtains this context through the existing
repository. Open in Game Review selects the source game's exact fen_before decision
step, clearing incompatible filters. No candidate/analysis identity changes.

The information panel scrolls and wraps; action buttons use a two-column layout
with full-width long actions, while the square board shrinks with the window.
Simulated Tk scaling checks do not replace physical Windows 100/125/150% acceptance.

## Round 1.1: permanent history and separate QA

Right panel = whole-game information/history. Bottom panel = current-position
information. The compact, scrollable actual move list stays below game metadata
and above Tactical Moments; browsing history never requires a tab switch.
The actual move-list highlight represents the last actual move applied to the
board. Start clears it. Selecting a tactical decision highlights the preceding
actual move, while clicking a White/Black SAN cell navigates after that half-move.

Merlin Line is explicitly labeled as a separate board mode. It leaves history
unchanged and clears the actual-history highlight until Hide Line restores the
actual position/highlight. The header omits Before move and ply-counter prose;
bottom context retains turn, last actual move, selected moment and recommendation.

QA controls and Review Set selection live only in Tools > Human Review / QA.
Closing QA restores All Games while retaining the current actual replay step.
Tactical details have a bounded scrollable viewport, leaving history and
navigation visible on small windows. Physical Windows DPI approval remains an
owner acceptance step beyond simulated Tk geometry checks.


## Position evaluation bar and actual-game timeline

Game Review now renders the shared exact-profile PositionEvaluation read model.
The bar shows White POV, explicit mate or unknown; the Position panel includes user
perspective. Actual move navigation and graph clicks share one actual-step state.
Merlin Line playback suppresses the bar score and keeps the graph at the actual anchor.
No evaluation search runs from Review. The permanent move list, result/winner display,
Tactical Moments and separate Human Review QA window are retained. Details and owner
acceptance boundaries: [EVALUATION_UI.md](EVALUATION_UI.md).


## Owner-review evaluation and resizable history

Actual Game Moves now occupies 40% of the available right-side content by default.
Drag the horizontal divider between it and Tactical Moments to resize the two panes.
The existing application settings remember explicit adjustments; font-based minima
and a scaled window minimum keep both panes usable. Scrollbars, actual move cells,
Tactical Moments selection and Show/Hide Line retain their existing handlers.

The evaluation timeline uses independent centered White/Black bars, explicit partial
coverage, honest missing-data gaps, and a clean zero-data message. Exact scores and
mate labels remain separate from visual clamping. See EVALUATION_UI.md for cache,
selection, scaling and preference contracts.


## Opening Book Management + Active Reference V1

The compact Opening Book selector owns the active authored reference; Facts renders that same selection and clears on None/removal. Matching defaults use meaningful theory, not the root. Session-only explicit choices do not alter engine Accuracy, tactic selection, proof playback or stored results. See [Opening Library Manager](OPENING_LIBRARY_MANAGER.md).


## Game Review Opening UX V1

Opening exploration is a separate navigation state from actual replay and Merlin
proof playback. It preserves the actual move anchor, suppresses tactic overlays
and labels any user-only repertoire arrow as Book move. Starting a tactical moment
or proof clears book exploration. Any Actual Game Moves click restores real-game
navigation; Game mode restores its timeline/context. The right-side move/tactic
splitter is unchanged. See [Opening UX](OPENING_INTELLIGENCE.md#game-review-opening-ux-v1)
for the complete navigation contract.


## Opening Accuracy V1

Opening → Summary now shows user Opening Accuracy, scored/total moves, Book Adherence with its own denominator, first user deviation, average cp loss and best-move rate. Branch View adds evidence for the selected actual move only; book exploration never relabels it as analysis of an authored line. Manual book selection persists; No Book clears opening metrics without clearing general Accuracy. Rendering uses shared pure projection over loaded Move Quality, with no engine or persistence path. See [Opening Accuracy](OPENING_ACCURACY.md).


## Game Review Opening Workspace V2

The right side now contains Game Review and Opening Review tabs over one board/game. The old bottom Opening tab and Library dropdown are removed. Tactic proof controls retain their existing behavior; authored opening playback has a separate bounded cursor and actual decision anchor. Actual Game Moves always exits either projection. Opening selection renders only Book arrows for user deviations, without changing tactic annotations/policy. See [workspace guide](GAME_REVIEW_OPENING_WORKSPACE.md).
