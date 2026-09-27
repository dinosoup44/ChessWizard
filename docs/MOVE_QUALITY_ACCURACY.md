# Move Quality / Accuracy V1

## Meaning and ownership

Position evaluation describes a board. Move quality compares the played choice
against the best reported choice at that decision. Accuracy aggregates those
comparisons. Tactical truth, Training admission, Quality Gate and The Scale remain
separate: no accuracy score creates or changes a tactic.

The module sequence follows the existing evaluation architecture:

- `move_quality_settings`: shared typed settings and raw/result identities.
- `board_analysis.phase`: reusable deterministic board-state phase heuristic.
- `move_quality`: immutable move/loss/game contracts and pure calculations.
- `move_quality_repository`: read-only cache evidence and derived game metrics.
- `move_quality_service`: bounded shared-engine requests, one transaction/request.
- `game_analysis_service`: existing scope/lock/cancel orchestration and worker.
- `move_quality_presentation`: shared numeric text, independent of Tkinter.
- `merlin_ui.accuracy_panel`: summary and details window; no chess calculations.

Core consumers can run without Tkinter. No new table, schema migration, standalone
analysis runner, or derived-summary persistence is introduced.

## Evidence choice and exact reuse

Default V1: **Stockfish 18, depth 16, MultiPV 1, Threads 1, Hash 64 MiB**, no node/time
cap, existing `candidate_lines_v1` request family and generator version 1. See the
24-move research in reports/MOVE_QUALITY_TRUST_AUDIT.md. Depth 10/1, 12/1, 12/3,
16/1 and an 18/1 comparison reference were tested before locking the default.
Depth 16 improved best-move agreement and worst observed finite-loss discrepancy
versus the lighter profiles. The sample is small and depth 18 is not ground truth.

For each actual move, read an unrestricted root line set from its exact fen_before.
If the played move is present in that set, reuse its score. An exact best-move match
therefore needs no second search. Otherwise request the same FEN/profile with
`root_moves=(played_uci,)`. This is a distinct exact raw-cache identity. Restrictions
are intentional, explicit and validated; FEN, engine/options, depth, MultiPV, profile
and generator/version mismatches never silently reuse evidence.

Scores are **root-conditioned continuation evaluations**, both at the same decision
and budget. `before_eval` is the unrestricted best continuation score;
`played_continuation_eval` is the score conditioned on playing the actual move.
There are no fabricated `best_after_eval` or `played_after_eval` child-search values.
Independent child searches can have different horizons, so V1 does not subtract
adjacent depth-10 timeline scores. Stored PVs and request identities retain provenance.

The timeline remains frozen at Quick/depth 10. Its values and visual semantics do
not change. Compatible existing depth-16 candidate-line evidence can be reused;
incompatible Quick/legacy FEN-only caches cannot. MultiPV >1 is supported by the
shared contract and tested; V1's default does not invent a Top-N match from one line.

Only complete exact line sets at the requested depth are accepted. Every stored PV
is legally validated by CandidateLineSet. Full actual-game FEN continuity is checked
before the stage writes anything. FEN-only repetition-history limitations of the
existing cache remain explicit; no new history inference is made.

## Canonical loss and best-move agreement

For finite scores:

```
sign = +1 for White mover, -1 for Black mover
raw_difference_cp = sign * (best_white_cp - played_white_cp)
```

When this is nonnegative, it is `eval_loss_cp`. White +150 -> +70 and Black
-150 -> -70 both lose 80 cp from the mover's perspective. Negative positions are
handled identically: a best defensive move may earn 100 while still losing.

A negative raw difference means the restricted played search beat the purported
unrestricted best. V1 records `inconsistent_estimates`, preserves both scores,
and assigns **no loss or accuracy**. It does not clamp contradictory evidence to
zero or present it as a bonus. Fixed-depth estimates are not a proof of global
optimality; the human audit flags instability across profiles.

Best Move Rate is the exact UCI match fraction among moves with compatible root
best evidence. It is not a near-best tolerance or tactic recommendation agreement.
Its denominator is reported separately from scored-move coverage. Top-N is optional
and only available when the exact requested MultiPV evidence contains N lines.

## ChessWizard's transparent accuracy transform

For a nonnegative integer centipawn loss L:

```
accuracy = 100 / (1 + (L / S)^2)
S = 100 cp by default
```

This smooth bounded transform has zero loss -> 100 and S loss -> 50. It penalizes
small losses gently and substantial losses strongly. The controlled comparison also
tested `100*exp(-L/200)` and `100/(1+L/100)`. The selected curve has a flat slope
at zero (less sensitivity to tiny cp noise) and a simple half-score parameter. It
was not calibrated to another platform, player ratings, or observed game results.

| Loss cp | 0 | 10 | 25 | 50 | 100 | 300 | 1000 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Accuracy | 100 | 99.01 | 94.12 | 80 | 50 | 10 | 0.99 |

This is an explanatory product score, not a win probability, empirical skill measure
or cross-platform equivalent. Display rounding is one decimal; aggregation uses
unrounded values. Unknown, invalid and contradictory estimates never become zero
loss/perfect moves.

## Mate-state rules

Mate is kept as typed LineScore with explicit owner, including mate zero. No huge
centipawn sentinel enters arithmetic. From the mover's perspective:

| Best -> played state | Accuracy rule |
| --- | --- |
| Winning mate preserved, same/faster distance | 100 |
| Winning mate preserved, slower | 100 minus 2 per extra mate move, at most 20 |
| Unavoidable losing mate retained | 100 minus 2 per move of shortened resistance, at most 20 |
| Winning mate -> finite score | 40; explicit lost-forced-mate rule |
| Finite score / winning mate -> opponent forced mate | 0 |
| Alleged losing mate -> finite score / own mate | unresolved (`mate_escaped_unresolved`) |
| Finite score -> newly found own mate | unresolved (`mate_found_unresolved`) |
| Missing either score | unknown |

The last two improvements contradict the unrestricted search's obligation, so V1
retains the transition but does not certify an accuracy number. Preserving a forced
loss can score 100 relative to available choices; it does not assert the position
is good. Mate-distance penalties and the lost-mate score are explicit configurable
product conventions, not empirical centipawn conversions. CP averages/medians exclude
mate states and expose their finite-score denominator.

## Phase heuristic

Phase is determined from the board **before** the move, independent of result or
opening names. Sum non-pawn phase weights for both sides: knight/bishop=1, rook=2,
queen=4 (24 initially). At <=8, classify Endgame. Otherwise, >=20 plus at least
four minor pieces on their original squares classifies Opening. The rest is
Middlegame. No fullmove-number-only cutoff, opening book or theory classification
is implied. Returned pieces may produce an opening-like classification again;
this deliberately simple stateless heuristic is documented, not hidden.

## Aggregation and incomplete coverage

`GameQuality` exposes overall, each color, user/opponent and phase aggregates.
Accuracy is the equal-move arithmetic mean of available move accuracies. Each
aggregate includes total/scored moves, best-match count/denominator, average and
median finite cp loss and the finite-loss denominator. No eligible moves means
None, not 0 or 100. Result labels (win/draw/loss) are never used in calculation.

A game is partial whenever scored moves < total moves, including unresolved search
contradictions. Details separate missing evidence from unresolved estimates.
Raw-evidence readiness is a different concern: once exact requests exist, a
contradictory comparison is not queued forever. Further investigation would need
an explicitly chosen new profile, not silently repeated deterministic requests.

## Settings and currentness

MoveQualitySettings composes existing GeneratorSettings/EngineSettings and shared
PhaseSettings, all through the existing typed Settings schema/loader. Labels, types,
defaults, ranges and identity impact are discoverable for future settings/Admin UI.

Raw identity depends only on the existing engine request settings/restrictions.
Result identity also includes policy_version, half_accuracy_loss_cp, mate rules and
phase settings. A scoring/phase change recomputes derived results without new raw
engine searches. There is no parallel JSON configuration, hidden database policy,
new Admin Console UI or profile selector in this task.

## Analyze Games and review

Default GameAnalysisService runs actual-position evaluation, then move-quality
evidence, then the existing registered tactic checks. Scope, locking, worker,
progress/errors and stop/resume remain centralized. A stopped root request commits
before a missing played request is started; resume reuses the root. Games already
complete for tactics/timeline may legitimately need quality evidence. Source-only
specialist/evaluation tests can explicitly opt out with `quality_settings=None`.

Only explicit Start writes complete evidence via CandidateLineService/Repository.
Preview, Game Review load, move clicks, summaries, Details and proof playback never
start an engine or write data. Main Review shows You/Opponent accuracy and coverage;
Details holds color totals, best rates, cp statistics, user phase breakdown and
unresolved/missing counts. The Position panel describes the last selected actual
move and its played/best/loss/accuracy. Start has no invented move quality. During
Merlin proof playback, actual-move quality is suppressed rather than attached to
a counterfactual position. No qualitative move badges or new timeline overlays.

## Cost, growth and acceptance

Two isolated full games (52 and 28 plies) required 94 and 43 new requests/rows;
the second reused one shared root. Runtime was 33.08 and 15.97 seconds on this host
while regression tests also ran. Payload total: 129,815 bytes / 137 rows, ~948 bytes
per row. SQLite growth: 143,360 + 69,632 = 212,992 bytes including indexes/pages.
At 1.71 new requests per ply in this tiny sample, an 80-ply game would be about
137 rows / 130 KB payload before sharing; this is an extrapolation, not a guarantee.

Completed orchestrator reruns had zero searches/writes and byte-identical DBs.
Direct stage cache replays had 94/94 and 44/44 request hits and identical structured
outputs. Existing non-cache tables in those fixtures were unchanged. Production
was only inspected read-only; no backfill, migration or candidate reconciliation.

One full game had 51/52 scored moves because 18...Ke7 produced a -13 cp contradictory
difference. That limitation is visible. The 24-card trust audit flags additional
profile-sensitive moves. Ready for owner review, not a claim of human calibration.
Future Opening Accuracy may consume phase-tagged move evidence, but opening theory,
Game Explorer and Critical Moment ranking remain outside this implementation.
