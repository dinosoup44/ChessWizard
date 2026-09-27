# Missed Pin V1

V1's screener, scout, and analyzer versions are each `1`; its candidate payload
`detector_version` is `1`. This document preserves its conservative definition
and original preview checkpoint. Subsequent 500-game heavy validation produced
two candidates (1835/1836) and 3,363 no-hits without changing existing IDs.
The current registry selects the separate [V2 specialist](MISSED_PIN_V2.md);
V1 calculation and adapter code remain intact as the baseline.

## Implementation boundaries

| Module | Responsibility |
| --- | --- |
| `pin_geometry.py` | Pin-specific target/value policy, structured `Pin`/`PinMove` records, legal pinning alternatives, static screener. Uses shared `ray_contacts`; no custom ray traversal. |
| `pin_scout.py` | Shared light-evidence comparison and canonical scout config. |
| `analyze_pins.py` | One supplied position, injected evaluator, structured `HeavyResult`; no database connection or independent scan. |
| `pin_adapter.py` | Passes `positions.position` from the shared service to the calculator. |
| `analysis_registry.py` | Registers the four stage/version/config interfaces. |
| Existing repository/coverage | Stores results using existing canonical-ID and version-aware rules; no pin-specific persistence. |

`board_analysis` supplies ray contacts, capture-square handling, and material
accounting with injected values. It does not define pins or tactical thresholds.
`analysis_results.HeavyResult` is the neutral shared result contract (the former
import from `heavy_adapters` remains compatible). No tactic-specific logic was
added to the crawler, planner, engine service, or repository.

## Exact V1 geometry

Consider each legal alternative to the move actually played. The resulting
moved piece must be a bishop, rook, or queen. Along one of its movement rays,
the **first two occupied squares** must contain enemy pieces:

```text
newly positioned slider -> intervening non-king enemy piece -> enemy target
```

The target must be a king (absolute pin) or strictly more valuable than the
intervening piece (relative pin). Values are pawn 100, knight/bishop 300, rook
500, queen 900. King targets are handled explicitly, not by a material value.
For material accounting kings have value zero.

Friendly blockers and any intervening occupancy prevent a direct relationship
to a more distant target. A nearer pair can qualify independently if it satisfies
the same rule. Equal-value relative targets do not qualify. The moving slider
must create a new pinned-piece/behind-target relationship; simply relocating
along its already existing identical pin is excluded.

An absolute pin restricts legal moves that expose the king; it does **not** mean
the blocker has no legal moves. A rook/pawn/slider can sometimes move along the
pin line or capture the pinner. A relative pin permits legal moves away that
expose the higher-value target. In either case, pinned pieces still geometrically
attack squares. Attack counts or an undefended piece alone never prove a win.

## Screener and scout

The static screener retains any eligible new direct pin, without evaluation,
capture, attacker-safety, or defender-count requirements. Sliding promotions
are included. Invalid inputs pass through to validation/error rather than being
stored as static misses. The screen is safe relative to this bounded V1
definition; it does not promise recall for every positional/discovered pin.

The scout reuses `ScoutEvidence.for_player` on before/played positions with
the shared `tactic_scout_v1` profile: Stockfish 18, 10,000 nodes, Threads 1,
Hash 64. It retains a position if shallow best-before minus played evaluation
is **at least 80 cp**. Mate-score ambiguity also proceeds to the specialist.
It does not evaluate every pinning move or claim that the shallow loss came
from a pin. This broad gate deliberately retains unrelated mistakes for the
heavy specialist to reject. Shallow misses can still be false negatives.

`pin_scout_config()` records the profile, engine identity/options, threshold,
comparison rule, mate-retention flag, and geometry identity as canonical JSON.
It has separate identity from the fork scout, even with the same loss threshold.

## Heavy proof rules

All evaluations use the same player's perspective before and after moves.
Compare every relevant pinning alternative rather than assuming the engine's
best move is a pin. No arbitrary top-N cap is applied to eligible alternatives.

1. Depth-10 quick evaluations: pinning move must improve on played by **120 cp**
   or more and fall no more than **300 cp** below best-before. These match the
   existing Fork V2 quick conventions.
2. Depth-18 before, played, and pin-position evaluations: pin must improve on
   played by **150 cp** or more and be within **200 cp** of best-before, again
   matching Fork V2 verification conventions. V1 declines mate-score lines.
3. Parse a legal depth-18 best-response continuation from the pin position:
   opponent replies, then the player immediately captures either the pinned
   piece **while the same pin remains active**, or the exposed higher-value
   target with the original pinner after a relative-pin blocker moves away.
   The opponent must not have captured the pinner. Quiet positional gains and
   unrelated captures do not satisfy proof.
4. Analyze the post-capture position at depth 18 and play its first legal best
   defensive reply. Require **at least 100 cp of retained material** both relative
   to the starting board and relative to the board just after the pinning move.
   This rejects simple recaptures, unprofitable sacrifices, and initial-capture
   gains that have no subsequent pin-related gain.
5. Analyze that final position at depth 18. Require an evaluation of at least
   **-100 cp**, at least **150 cp above played**, and within **200 cp of best-before**.
   These extra conservative requirements reject material gains that leave an
   obviously losing position or do not retain the tactical advantage.

Among qualifying lines, choose the highest pin-position evaluation, then
retained material, then a deterministic UCI tie-break. Confidence is a fixed
**0.9 heuristic**, not a calibrated probability. Classification is
`wins_pinned_piece` or `blocker_moves_target_lost`.

The candidate records UCI/SAN, the verified four-ply solution line, pin type,
piece identities and squares, played move, player-POV evaluations, evaluation
gain, retained material, final FEN, classification, and explanatory notes.
Coverage details also retain engine evidence/profile references.

This is depth-limited best-response evidence, not an exhaustive all-defense
proof. Empty/short PV evidence yields no hit; malformed or illegal PV evidence,
invalid positions, and engine failures propagate as retryable `error` through
the dispatcher. Failure is never converted into completed negative proof.

## Coverage and identity

Unchanged generic status rules apply: static rejection -> `screened_out`, scout
rejection -> `scouted_out`, verified heavy miss -> `analyzed_no_hit`, verified
hit -> `candidate`, failure -> `error`. `rejected` remains a repository outcome
for separately controlled stale reconciliation, not a specialist return state.
No heavy coverage is claimed by either screening stage.

Canonical `(move_id, tactic_type)` lookup preserves existing IDs and training
references. Current `candidate`/`rejected` coverage remains protected even with
scout version `0`; stale-heavy refresh is not automatically enabled. Fork/mate
definitions, version identities, and currentness rules are unchanged.

## Deliberate limitations

V1 does not detect every positional pin, exploit an already existing unchanged
pin, discover a pin by moving a different blocker, attribute a stationary rook's
pin to castling, recognize equal-value relative targets, or prove a delayed
attack several moves later. Promotions to sliders can qualify; variants and
Chess960 are not validated. It omits mate-based pins and improvements that still
leave the final evaluation below -100 cp. Pins where the king/target escapes the
line before a capture may be missed even if the pin caused that concession.

A verified sequence supports a useful pin-related material callout but cannot
prove unique motif ownership against forks/skewers or all counterfactual defenses.
Pattern recognition and Game Review rendering are future consumers; this task
does not add UI-specific logic or run live heavy proof checks.

## Tests and preview operation

The full suite passed **89 tests** before preview. Pin tests cover absolute and
relative pins, queen/rook targets, bishops/rooks/queens, both colors, blocked rays,
pin mobility versus attacks, promotions/castling, no-value geometry, recapture,
unsustained evaluation, missing/illegal proof, engine failure, input preservation,
canonical ID reuse, retained training links, and persistence idempotency.
Existing fork/mate behavior tests continue to pass unchanged in meaning.

The preview command is read-only, selects only the registered pin definition,
and uses temporary memory storage for new scout evidence:

```powershell
.\.venv\Scripts\python.exe analysis_crawler.py --validation-scope-500 --negative-preview --analysis missed_pin --report reports/missed_pin_preview_500.json
```

The generic CLI permits tactic filters in saved-scope negative previews only;
saved-scope write-mode filter restrictions remain intact. Aggregate preview results
appear in the [saved-500 summary](#saved-500-game-preview-result--september-6-2026);
exact game IDs and per-position receipts are private.
Do not run heavy validation modes yet: those modes dispatch all registered
specialists, including this newly registered pin analyzer. Heavy rollout and
all-games expansion require separate authorization.

## Saved 500-game preview result — September 6, 2026

| Stage | User moves |
| --- | ---: |
| Total in saved games 2701–3200 | 13,679 |
| Already-current `missed_pin` | 0 |
| Static screened out | 4,511 |
| Remaining for scout | 9,168 |
| Scout screened out | 5,810 |
| Proposed heavy queue | 3,358 |
| Errors | 0 |

Elapsed time: **63.91 seconds**. Scout evidence reused **14,088 database hits**
and **1,146 in-memory hits**; **3,102 new scout searches** were stored only in the
temporary database. The stage counts describe proposals, not persisted negatives.
No heavy calculations, negative writes, or candidate/coverage writes ran.

Live candidate count remained **929**, training attempts **11**, and coverage
rows **28,128**. Protected rows and sequences were unchanged, `quick_check` was
`ok`, and the foreign-key check passed. The entire live database SHA-256 matched
before and after. The exact database hash and local integrity receipt remain private.
Existing candidate IDs, fork/mate coverage, and training history remain intact.
The 3,358 proposed checks are unvalidated hypotheses, not confirmed pin hits.
## V2 status

V1 remains the unchanged conservative implementation and test baseline.
The registry now selects the separately versioned [Pin V2 specialist](MISSED_PIN_V2.md).
Existing V1 candidates remain protected until explicitly reconciled; this
registration does not authorize their refresh or a historical heavy rollout.
