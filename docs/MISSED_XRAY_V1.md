# Missed X-ray V1

X-ray V1 is implemented as `missed_xray`, using screener, scout and analyzer
versions **1**. Its rollout boundary is **implementation, synthetic gold,
regression tests and read-only saved-500 preview**. No historical heavy X-ray
checks or live writes have run. See [validation results](../reports/XRAY_V1_VALIDATION.md).

## Definition and ownership

An alignment is not an opportunity. V1 requires a new direct slider line after
an unplayed legal bishop/rook/queen move, followed by a concrete resolution of
the intervening piece and a retained rear-target payoff along that line.

| Family | Distinguishing mechanism |
| --- | --- |
| Pin | The intervening piece is constrained because moving exposes a more important rear target. |
| Skewer | An attacked/compelled front target resolves, exposing a less important rear target. |
| X-ray | Pressure through a blocker becomes useful when a capture, exchange or forcing blocker move resolves the line. |

The geometry layer excludes front kings, rear kings and more valuable enemy
front pieces, conservatively leaving ordinary absolute pins and skewers to
their specialists. Less valuable enemy blockers can also form relative pins.
For those, V1 requires actual blocker resolution and rear capture; it may attach
`pin: context_only` but does not claim that the pin forced the result.

Rear targets must be opposing minor pieces, rooks or queens. The blocker can be
friendly or hostile, but cannot be a king. Only the first two occupied ray
contacts count. Additional pieces cannot be skipped to manufacture a target.

## Module boundaries

| Module | Responsibility |
| --- | --- |
| `xray_geometry.py` | Target/value policy and pure static screener over shared observations. |
| `xray_scout.py` | Shared scout evidence comparison and canonical configuration identity. |
| `xray_adapter.py` | `xray_adapter(row, positions)` calls calculation with `positions.position`. |
| `analyze_xrays.py` | Single-position calculation, selection and structured `HeavyResult`. |
| `xray_attribution.py` | Supported/context-only policy over blocker-resolution evidence. |
| `xray_opportunities.py` | Outcome, motifs, proof, timing and presentation interpretation. |
| `board_analysis.new_slider_move_lines` | Reusable legal moved-slider geometry; no tactic policy. |
| `tactical_material.py` | Injected evidence session, explicit material policy and structured bounded material assessment. |
| `tactical_line_proof.trace_blocker_resolution` | Generic identity tracking and exchange accounting after blocker resolution. |
| `analysis_registry.py` | Registration only; no X-ray branches in the crawler. |
| `heavy_repository.py` | Generic ID-preserving persistence and optional cross-motif ownership guard. |

The specialist has no SQLite access, engine lifecycle, historical scan or UI
dependency. It does not import Pin or Skewer private functions. Existing Pin,
Skewer, Fork and Mate calculation modules remain unchanged. The new shared
services are additive; existing specialists are not migrated during this task.

## Screener and scout

`xray_screener(row)` enumerates legal moved sliders through
`board_analysis.new_slider_move_lines`, including slider promotions. Played
moves, castling and an identical already-present blocker/rear pair are excluded.
Invalid stored context continues to normal validation/error instead of being
silently classified as a static negative. Screening uses no engine.

The scout compares best-before and played-position evaluations from the same
player's perspective using the shared **10,000-node `tactic_scout_v1`** profile.
It retains losses of at least **80 cp** and mate-valued evidence for specialist
handling. This is an inexpensive queue filter, not proof of an X-ray.

Canonical `scout_config` includes the actual profile/options, 80 cp threshold,
mate retention, comparison identity and `new_direct_slider_xray_v1` geometry.
Existing currentness semantics apply: static negatives depend on screener
version; scout negatives depend on screener/scout/config; heavy results depend
on heavy version under the established coverage rules. Error stays retryable.

## Heavy material and evaluation policy

`analyze_single_move(row, analyze_fen)` composes `EvaluationSession`,
`assess_material_move`, bounded proof, X-ray attribution and opportunity building.
The evidence session memoizes exact `(fen, profile)` requests within the call;
the injected position service supplies the shared persistent cache boundary.

V1 policy is explicit in `MaterialPolicy`:

| Gate | Requirement |
| --- | --- |
| Quick evidence | Depth 10; tactic at least 120 cp better than played and no more than 300 cp below before. |
| Deep evidence | Depth 18; tactic at least 150 cp better than played and no more than 200 cp below before. |
| Material | At least 100 cp retained relative to both the original position and the position just after the tactic. |
| Attribution | At least 100 cp retained X-ray-related material and supported blocker-resolution causality. |
| Final evaluation | At least −100 cp, at least 150 cp above played, and no more than 200 cp below before. |

Material values are P100/N300/B300/R500/Q900/K0. Mate scores are never converted
to cp. Baseline, alternative or proof mate evidence conservatively defers primary
ownership to mate review, with X-ray only a contextual geometry note in details.
The X-ray specialist does not launch a mate analyzer.

Proof uses the existing **four further user moves**, their following defense,
at most **four extra settlement plies**, and two quiet actual plus two quiet
PV lookahead plies. Settlement may continue accounting but cannot turn a late
rear capture into an in-window payoff. Each continuation ply follows the
configured depth-18 best reply. This is bounded engine evidence, not exhaustive
defense enumeration or a mathematical proof.

## Blocker resolution and causal accounting

The shared tracker records, without assigning a tactic:

- Capture of the blocker by the original slider.
- Removal of the blocker by another piece.
- Rear target capturing the blocker, followed by immediate recapture by the
  original slider on the same ray.
- A friendly blocker's capture or checking move that opens the line.
- Quiet blocker movement as an observation, **not** concrete causal support.

V1 credits the rear only when the original slider captures it along the original
ray, or an exposed rear exchanges that slider and is immediately recaptured.
Rear escape is rejected; the immediate rear-for-blocker exchange is an explicit
exception rather than permission to chase a relocated rear piece. New intervening
pieces must actually leave a clear ray before a direct rear capture is credited.
Moving the attacker off the original ray ends its tracked line identity.

Related gains include the enemy blocker and rear target. All own losses through
settlement are charged, including a friendly blocker or attacking slider.
Unrelated captures do not inflate line gains; their value can offset only the
later loss of that same capturing piece. The final net material gate separately
includes every capture in the proof. Board and move context remain immutable.

Quiet displacement, unproven overload, material won elsewhere, a rear that never
becomes relevant, an unsettled position or weak attribution produces no strong
candidate. V1 does not infer a forced deflection merely because an engine line
contains movement.

## TacticalOpportunity and persistence

The outcome states why the move matters: `win_queen`, `win_rook`, `win_piece`,
`win_exchange` or `force_favorable_exchange`. Motifs explain how. X-ray must be
`supported`; blocker removal and sacrifice receive their own supported rationale
when traced, and relative-pin geometry can be `context_only`.

Payoff on the first further user move is `immediate`; moves two through four are
`delayed`. Clear wins use `strong_callout`; a favorable material exchange uses
`secondary_motif`. Presentation is outcome-first, never an automatic “X-ray!”
headline. No Game Review integration is changed by registration.

The specialist returns candidate payload plus `TacticalOpportunity`; only the
generic repository stores canonical proof fields and versioned metadata. It
preserves canonical IDs and training links and never deletes/reinserts them.

`AnalyzerDefinition.deduplicate_opportunities` is a generic opt-in, enabled only
for X-ray V1. Inside the repository transaction, a proposed new candidate is
deferred if another tactic already owns the same `(move_id, solution_move_uci)`.
The existing candidate and history remain untouched. The new coverage outcome
is `analyzed_no_hit` with `existing_opportunity_owned` and the owner ID/type;
no duplicate label-driven candidate is created. The evidence is retained in
coverage details. This is not automatic cross-tactic motif merging or retroactive
deduplication. Other analyzers keep their prior behavior.

## Gold, preview and limitations

`tests/fixtures/xray_v1_gold.json` contains 20 frozen legal positions/continuations:
eight synthetic candidate contracts, eight no-hit contracts and four geometry
contracts. It covers rook/bishop/queen lines, ranks/files/diagonals, own/enemy
blockers, removal, exchange, constrained-looking blockers, rear escape, unrelated
gain, recapture loss, late payoff, pin/skewer ownership and both colors.
Tests additionally cover promotion/castling safety, immutable inputs, canonical
serialization, ID/training preservation, ownership deferral and error retry.

Synthetic scores exercise contracts; their continuations are **not asserted to
be engine best play**. Six of these synthetic positions were independently
cross-checked through the real shared engine service: all six were no-hit, with
zero errors. Thus this checkpoint has not established an engine-confirmed
positive X-ray or live candidate persistence. No thresholds were adjusted to
force positives.

The read-only saved-500 preview proposed **3,489** heavy checks, above the
predeclared review threshold of **2,552** (twice Skewer's original 1,276). Analysis
stopped at the preview. The wide static queue is consistent with permitting both
friendly and enemy blockers; it does not imply 3,489 valid tactics or authorize
heavy execution. See the report for cache and unchanged-database evidence.

Further limits: moved sliders only; no stationary/discovered-ray search, general
overload solver, purely positional pressure, arbitrary deflection, arbitrary
rear pursuit, king-rear material proof, or material-saving-only classifier.
Battery/support positions qualify only through the explicit traced capture rules.
Quiet/ambiguous cases are deliberate false negatives for V1.

## Existing-evidence preflight checkpoint

`xray_preflight.py` now opts into the generic registry hook between scout planning
and heavy dispatch. It uses `ExistingPositionEvidence` and
`SolutionOwnershipService`; it cannot request an engine fallback. Geometry,
`MaterialPolicy`, scout conditions and heavy proof remain unchanged.

In precedence order, the policy returns:

1. `played_checkmate`: the stored actual played move legally delivered checkmate.
   Stalemates and draws do not qualify.
2. `mate_deferred`: both current quick baseline records exist, with before or
   played evidence mate-valued under the existing material-family deferral.
3. `cached_quick_rejected`: every geometric alternative has compatible current
   quick CP evidence and fails gain >=120 CP or before-to-alternative drop <=300 CP.
4. `already_owned`: every geometric alternative has another canonical owner of
   the identical move/solution pair.
5. `heavy_required`: all remaining positions, including missing evidence and
   mixed partial ownership/partial quick failure.

Provenance includes analyzer/preflight/policy identity, quick profile and engine
configuration, cache keys/IDs and player-POV scores, alternative quick-gate results,
owner IDs/types and missing-evidence reasons. Dispositions are recomputed on every
plan and never saved as coverage. Eventual candidate persistence still rechecks
ownership inside the generic repository's transaction.

The exact saved-500 preview retains the original 3,489 incoming checks, removes
1,276, and leaves **2,213** proposed heavy checks. The earlier 2,210 estimate also
removed three mixed partial-ownership/partial-quick-failure positions; the strict
approved all-alternatives predicates retain those three. No broader filter was
added. Preflight made zero engine searches; the database remained byte-identical.
All eight synthetic positive gold contracts survive. These results do not
establish engine-confirmed positive candidates or authorize a live rollout.
See [the complete validation report](../reports/XRAY_V1_PREFLIGHT_VALIDATION.md).
