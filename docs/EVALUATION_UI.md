# Position evaluation UI V1

Position evaluation answers who is better in the current position. It is not move
quality, material won, or Accuracy. No best/good/mistake/blunder labels are added.

## Shared contract and ownership

`position_evaluation.py` owns immutable `GamePosition`, `PositionEvaluation` and
shared typed `EvaluationSettings`. Scores use the existing `LineScore` contract:
canonical White POV, integer centipawns or explicit mate distance/owner. Missing
scores remain unknown, never zero. +100 cp favors White; -100 favors Black.
`label('black')` provides the user-relative sign without changing stored evidence.
M3 / -M4 identify White / Black mating; M0 retains an explicit winning color.

`actual_positions` legally replays all stored moves and validates every before/after
FEN before a game is evaluated. Step zero is its actual starting FEN (including
PGN SetUp games); step n follows the nth played half-move. Each point has a source
move ID, exact FEN and chess-move label. Empty games have no invented positions.

Calculation/model, engine generation, cache repository and Tk widgets are separate.
The core has no Tkinter dependencies and can support another frontend. The existing
CandidateLineGenerator, CandidateLineService and CandidateLineRepository provide
engine evidence and persistence. No tactic specialist or coverage semantics change.

## Exact evidence and storage

There is **no migration or new table**. V1 uses `engine_candidate_line_cache`, whose
UNIQUE(fen, engine_identity) key is already deployed. The actual game supplies the
mapping, so no per-ply score table duplicates the same FEN/request.

The default uses the existing shared **Quick** generator: Stockfish 18, depth 10,
MultiPV 1, Threads 1, Hash 64 MiB, no node/time cap or root restrictions, generator
version 1 and `candidate_lines_v1` request family. This reuses an approved low-cost
profile rather than inventing a depth. The running engine name/release is verified
before its result can be stored. The generator normalizes scores to White POV;
this convention is part of its versioned contract. All raw settings, options and
restrictions participate in the existing request identity. UI clamp settings do not.

The legacy `engine_position_cache` lacks persisted Threads/Hash identity, and
`engine_analysis` and tactic before/after scores do not establish one compatible
actual-game timeline. Their scores are not silently relabeled as Quick evidence.
Candidate-line evidence with another depth, MultiPV, profile, version or restriction
is also excluded. Unknown points tell the truth about this boundary.

The repository inserts complete evidence once. Reruns reuse exact requests and do
not update timestamps or duplicate rows. Terminal FENs use legal board facts without
an engine search; a terminal draw is zero, checkmate is explicit mate zero. Existing
FEN-only cache semantics apply: earlier repetition history is not inferred.

The existing format stores one legal PV plus provenance per Quick request. V1 adds
no second PV/payload per timeline point. Exact identical FENs reuse rows; transpositions
with different halfmove/fullmove fields remain different keys. No FEN normalization
or raw-cache cleanup policy changes are made. Future cleanup must respect shared
analysis consumers; it must not delete evidence merely because a timeline is closed.

## Analyze Games

`GameEvaluationService` is a stage within `GameAnalysisService`, not a separate
runner. An explicit Start processes actual positions before registered tactic checks.
Default completion now includes missing position evaluations as well as existing
coverage/mate presentation checks. No evaluation coverage statuses are invented.
Preview/read/navigation never starts an engine. Newly imported games remain unknown
until Analyze Games is explicitly started.

Each bounded request commits only complete evidence. Stop retains completed rows;
resume probes cache and searches missing requests. Incomplete results remain pending,
with an error and no partial cache row. Scope IDs and the existing activity lock are
shared with analyzer orchestration. `evaluation_settings=None` is an explicit core
stage opt-out used by specialist-only tests/tools; desktop Analyze Games enables it.
No legacy standalone launchers are involved.

Progress reports completed/total actual positions for the current game and separate
evaluation cache-hit/search/insert counters. There is no inferred ETA. Profile changes
flow through the shared typed generator/settings model, with a new exact identity.

## Review behavior

The slim bar is next to the board. Black is labeled at the top and White at the
bottom regardless of board orientation; the number is canonical White POV. The
Position panel adds the user's perspective. Numerical cp values retain two decimal
pawn units, matching their stored centipawn precision.

Visual fill is linear and clamps at ±800 cp. The true numeric score is not clamped.
The height is neither material balance nor a win probability. Mate uses an explicit
edge state, not synthetic centipawns. Unknown uses a gray bar with a separate
Not analyzed label, as does the Position panel. Black/White side labels remain
separate from the score/state. The center reference does not imply unknown is zero.

The compact actual-game timeline sits above Position information below the board;
Actual Game Moves and Tactical Moments remain simultaneously accessible. Known
positions render as independent centered bars: White advantage above the visible
0.00 line, Black advantage below, zero as a small central mark. Both directions
use the same ±800 cp clamp. Mate reaches the corresponding edge as a flat rectangle;
mating distance remains in the selected M# text, with no glyph over the endpoint.
The selected numeric score is never clamped. Unknown positions have no
bar, connector, interpolation or fake zero. A selected unknown position gets a
navigation marker below the plot plus Not analyzed text.

Partial coverage explicitly says Partial analysis · known/total positions. Zero
known positions show only coverage and the two-line Analyze Games empty-state
message, with no plot/axis/ticks. Sparse full-move labels (Start, 5, 10, etc.) adapt
to available width. The selected known bar has a cyan outline. Selection uses
canonical actual step indexes. Next/Previous, move-list
clicks and timeline clicks share `_set_step`; tactical selections use their actual
before-position. Empty games clear prior values. Invalid cached points remain unknown
while neighboring valid points survive; an invalid actual sequence is reported as
unavailable. No hidden engine work occurs during navigation.

During Merlin Line playback, the actual timeline stays at its return/decision anchor.
The bar says Proof line and suppresses the actual-position number while the board
shows a counterfactual position. Position information explicitly distinguishes the
proof from actual history. Clicking the timeline exits proof playback and navigates
the actual game. Proof-cache evaluations are not mixed into this graph.

## Footprint, performance and acceptance

The isolated six-ply real game needed seven requests/rows. Payload: 6,413 bytes,
about 916 bytes/position; SQLite growth: 12 KiB including page/index effects.
Rerun: zero searches/writes and identical DB bytes. At ~196k position instances
(193k moves plus starts), the same average suggests ~180 MB of payload and a few
hundred MB including SQLite/index overhead, before exact-FEN reuse. This is an
order-of-magnitude estimate from a small fixture, not a storage guarantee.

Observed timeline load ~5.7 ms; move-step UI update ~13 ms in that fixture. Large-game
or high-DPI performance is a separate owner acceptance concern. The bar and timeline
use existing Tk drawing, no new assets/fonts/dependencies. Automated widget geometry
checks cover 1120×760 and 900×650. Human visual/DPI acceptance and any frozen rebuild
remain separate. No production evaluation backfill runs as part of implementation.

Move Quality / Accuracy V1 now uses separate exact depth-16 root/played continuation
evidence from the same shared cache. It does not subtract adjacent Quick timeline
values or change this position-evaluation contract. See MOVE_QUALITY_ACCURACY.md.
Critical Moment ranking remains separate.


## Owner-review layout and preferences

The right-side content uses a native vertical PanedWindow, with Actual Game Moves
above Tactical Moments. Dragging down enlarges moves; dragging up enlarges tactics.
Moves initially receive 40% of usable split height. Both children expand and retain
their existing scroll/click handling. Font-based pane minima reserve approximately
seven lines for moves and six for tactics. Game Review increases its minimum window
height when scaled headers/controls would otherwise squeeze either pane or the board.

`ApplicationSettings.review_moves_fraction` uses the existing atomic settings.json
repository (default 0.4, range 0.1–0.9). It affects neither raw cache identity nor
analysis currentness. Only a completed divider adjustment saves it, merging fresh
preferences so theme/highlight choices survive. Opening, navigation, mere sash clicks,
and window resizing do not save. Pane minima may override the stored ratio in a small
window; enlarging the window restores the ratio. No new settings subsystem is added.

The isolated owner-review fixture starts at 5/34 exact Quick evaluations. Analyze
Selected Game reuses five unchanged rows, searches/inserts only 29, and reaches
34/34. Its identical rerun searches/writes nothing and preserves the database bytes.
Automated Tk tests cover 100%, 125%, 150% scaling, actual mouse divider events,
scrolling, navigation and preference restoration. Physical Windows DPI and final
appearance remain part of the second owner visual review.
