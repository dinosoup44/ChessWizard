# Missed Pin V2

## Baseline and module boundaries

Pin V1 remains intact in `analyze_pins.py` and `pin_adapter.py`; see
[MISSED_PIN_V1.md](MISSED_PIN_V1.md). Its immediate-capture proof is a conservative
regression baseline. V2 lives in `analyze_pins_v2.py`, with `pin_adapter_v2.py`
registered under the existing canonical `missed_pin` analysis type.

| Module | Responsibility |
| --- | --- |
| `pin_geometry.py`, `pin_scout.py` | Unchanged static selection and light scout. |
| `tactical_proof.py` | Generic bounded, re-evaluated best line and settlement observations. |
| `pin_attribution.py` | Pin-specific causal accounting over the verified line. |
| `pin_opportunities.py` | Outcome-first shared TacticalOpportunity construction. |
| `analyze_pins_v2.py` | Single-position calculation and score gates. |
| `pin_adapter_v2.py` | Injection of the shared position service. |
| Existing heavy repository | Generic opportunity serialization and ID-preserving persistence. |

No board/engine/database lifecycle belongs to the calculator. Shared
`board_analysis` functions provide geometry, mobility, piece safety, capture
squares, and material accounting. Shared position services supply engine evidence.
The central crawler and registry retain orchestration; there are no pin-specific
crawler or persistence branches.

## Explicit proof policy

Heavy analyzer version **2** uses `bounded_best_line_v1`:

1. Retain V1 quick depth-10 thresholds: at least 120 cp improvement over played,
   at most 300 cp below best-before.
2. Retain depth-18 thresholds: at least 150 cp improvement over played, at most
   200 cp below best-before.
3. Follow up to **four further user moves after the pin move**, plus the following
   defense: nine plies after the pin. Re-evaluate at every ply through the cache
   service and use the selected best move; do not merely replay a root PV and
   assume all subsequent defensive replies remain best.
4. Inspect the entire payoff window even when the first capture is immediate.
   A later recapture can invalidate an early material snapshot.
5. Extend at most **four additional plies for settlement**. Gains first appearing
   in this extension do not establish an in-window tactical payoff.
6. A sufficiently stable endpoint requires two quiet actual plies, no current
   check, and two quiet PV lookahead plies at the freshly evaluated endpoint.
   Captures, checks, promotions, and check evasions reset the quiet count.
7. Require at least 100 cp material retained both versus before the tactic and
   versus just after it, plus at least 100 cp attributable material. Preserve
   V1's final evaluation floor of -100 cp and its +150/-200 cp comparisons.

The policy is bounded best-line engine verification, **not exhaustive defense
enumeration or a mathematical proof**. A stable endpoint is an operational
criterion, not a claim that the entire game is tactically settled forever.
Missing continuations, an unsettled endpoint, terminal draws, and mate-valued
proof lines cannot become material candidates. Malformed/illegal evidence raises
and the dispatcher returns retryable `error`.

## Causality and pinner exchanges

Track the original attacker, pinned piece, and rear target through legal moves.
Eligible payoff captures within the four-user-move window are:

- The original pinned participant while the relationship is active.
- The original rear target exposed to capture by the original pinner from its
  original pinning square or an advance along that same original ray.
- Immediate recapture of the pinned/rear participant that just captured the
  pinner. Pinner survival is not an unconditional requirement.

Supported pin attribution requires an actual absolute restriction, a concrete
relative-pin escape concession, or the demonstrated rear-target exposure.
A relative escape concession means a legal quiet move by the pinned participant
would expose the higher-value rear target to a legal pinner capture which still
wins material after any immediate legal recapture. This is a local supporting
observation; it is not a counterfactual engine proof against every defense.

Only related captures fund the attributable gain. All own-piece losses count,
except an unrelated earlier capture can offset the later loss of that **same
capturing piece**. This permits neutral preparations such as `Bxh3 gxh3` while
preventing an unrelated gain by another surviving piece from subsidizing a
pin-related sacrifice. A profitable `Rf6 Qxf6+ Qxf6+` exchange is accounted for
as a full exchange, not rejected upon the rook's capture.

An immediate check-led capture of the attacked pin participant can instead have
`check` as its supported primary motif, `double_attack` supported, and pin as
`context_only`. This is an explicit outcome-first category, not a claim that the
pin caused a checking double attack. Other unsupported incidental pin geometry
does not produce a strong pin callout.

Movement constraint is recorded as fully constrained, partially constrained, or
not established. Never translate this automatically into “cannot move.” The
relationship-survival flag means it survived at the relevant payoff capture;
capturing the pinned piece naturally ends the geometric relationship afterward.

## Outcomes, timing, and notes

Candidates carry the shared [TacticalOpportunity](TACTICAL_OPPORTUNITIES.md):
outcome, per-motif attribution, immediate/delayed payoff, proof window and
evaluations, best-defense/settlement observations, and selected line participants.
The presentation is outcome first, for example “Win a knight” or “Force a
favorable exchange,” rather than forcing the title “Missed Pin.”

Quiet stable relationships with no material payoff can appear as `positional_note`
annotations in no-hit details. Rook-pressure pawn wins with only incidental pin
geometry can appear as `secondary_motif` annotations. Neither is automatically
a candidate or a training puzzle. No Game Review UI integration is included.

The two V1 candidates illustrate the distinction: 1835's b2 pawn can advance on
the file, so its pin attribution is contextual; 1836 is naturally explained as a
checking double attack winning a knight. Their live candidate rows are untouched.

## Mate ownership

V2 never converts mate distance to centipawns and does not emit mate/save
candidates. A positive before-position mate is deferred to `missed_mate` ownership.
Other mate-valued roots, including played moves allowing mate, are explicitly
marked for mate/saving-tactic review. This does **not** assert that the current
Mate V3 implements every defensive case or that an alternative pin avoids mate.
Mate-valued alternatives/endpoints are separately rejected/deferred. Dedicated
save/mating attribution would need a separately versioned proof, not an inferred
material result or a duplicate mate candidate.

## Versioning, preview, and rollout

`analyzer_version` is **2**; `screener_version=1`, `scout_version=1`, and scout
configuration are unchanged. Opportunity schema version is independent.

V1 no-hit rows with matching upstream versions become logically stale due only
to the heavy version. Existing candidate/rejected rows remain protected from
automatic refresh and ID churn. The ordinary planner retains its existing
protection of stale heavy no-hits. An explicit saved-10 refresh mode is now
available, separately from candidate reconciliation; see the controlled rollout
section below.

`analysis_planner.preview_heavy_refresh` reports a **proposal only**, separating
version-only stale no-hits from protected canonical candidates and rows requiring
upstream revalidation. It does not turn those rows into an authorized dispatch
queue. Existing negative coverage remains current under its stage-specific rules.

The validation runner has exactly two modes:

```powershell
.\.venv\Scripts\python.exe -m reports.validate_pin_v2 gold
.\.venv\Scripts\python.exe -m reports.validate_pin_v2 preview
```

Gold mode dispatches only the frozen curated positions through the registry and
shared service. The live SQLite connection is read-only/query-only; new engine
evidence goes into an in-memory cache. Preview uses the exact saved 500-game IDs
and static/scout planning only; **it never calls a heavy specialist**. No candidate,
coverage, training, or live cache writes occur in either mode.

## Gold set and limitations

`tests/fixtures/pin_v2_gold.json` freezes 32 pin cases before validation: both V1
candidates, all ten delayed audit leads, all seven quiet pins, all three transient
gains, a profitable pinner exchange, three broken-geometry cases, three unrelated
gain cases, and three mate cases. Two existing fork/mate tests are explicit
regression fixtures. Delayed leads are marked ambiguous, not forced positives.

Saved-line expectations concern the audited move and relationship. A different
valid alternative in the same position is not a failed negative expectation.
If fresh best-line verification supports a formerly quiet/transient line, flag
the changed proof for review rather than silently rewriting the gold expectation.

Known limits include the unchanged direct-slider geometry (no castling or
stationary/discovered pin expansion), unchanged conservative evaluation gates,
single-best-line rather than MultiPV defense verification, the bounded settlement
horizon, and conservative local causal attribution. Repeated strategic pressure
and mate-save mechanisms remain outside strong material candidate creation.

Validation results and exact preview counts are recorded separately in
`reports/PIN_V2_VALIDATION.md` and the accompanying JSON reports.

## Controlled stale no-hit rollout

The central crawler now exposes an explicit, tactic-agnostic operation:

```powershell
.\.venv\Scripts\python.exe analysis_crawler.py --heavy-test-10 --analysis missed_pin --refresh-no-hits-from 1 --report reports/pin_v2_live10.json
```

After separate approval, the same operation supports the exact saved 500 games:

```powershell
.\.venv\Scripts\python.exe analysis_crawler.py --heavy-validation-500 --analysis missed_pin --refresh-no-hits-from 1 --report reports/pin_v2_live500.json
```

Both modes require exactly one selected analyzer and their exact saved IDs;
all-game execution and scope filters remain rejected. The operation selects
only `analyzed_no_hit` rows from the explicit source heavy version whose upstream
screen/scout metadata is current. It performs no screening, scouting, static
negative writes, or scout negative writes. Upstream staleness aborts this operation
instead of silently broadening its work.

`plan_stale_no_hits` protects all canonical candidates, candidate/rejected
coverage, and candidate-linked coverage. `save_heavy_result` rechecks the expected
source no-hit version and canonical-candidate absence inside its transaction.
`expected_no_hit_version` cannot be combined with `reconcile_stale=True`.
The new mode therefore cannot update/backfill V1 candidates 1835/1836.

The crawler records preflight IDs/counts/integrity, creates and verifies a fresh
SQLite backup before writes, then uses registry dispatch and the existing generic
TacticalOpportunity persistence. A no-hit becomes version 2 coverage; a hit creates
a canonical candidate only if none exists. Errors remain retryable. This narrow
source-no-hit mode reports existing errors separately rather than treating them
as completed work or silently expanding its selection to error rows.

An identical rerun skips completed V2 rows without engines or writes. Full original
candidate rows, training tables, and coverage outside the authorized keys are
compared before/after. The live test report is
`reports/PIN_V2_LIVE10_ROLLOUT.md`. The separately approved saved-500 rollout uses
the same protection and persistence path. Neither mode enables candidate
reconciliation or all-games analysis.

## Read-only backbone adoption checkpoint

`pin_backbone` is the opt-in second consumer of AnalysisBackbone. The production
adapter/version and all V2 thresholds remain unchanged. Recorded one-line replay
reproduced seven live positions and all 32 gold entries exactly, including stored
V2 opportunities/feedback after canonical hydration. Normal curated proposals
are separately labeled; they do not reconcile candidate rows.

PinPolicy exposes the original thresholds through the shared settings schema.
Approved-entry proofs preserve the four-user-move/four-settlement-ply clock and
fresh depth-18 evaluation after the explicit entry. See
[the migration checkpoint](PIN_BACKBONE_MIGRATION.md) for settings, the 33-case
proposal audit, 1835/1836 lessons and remaining live-activation requirements.
