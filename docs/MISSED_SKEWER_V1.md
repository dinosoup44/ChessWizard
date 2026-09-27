# Missed Skewer V1

Skewer V1 detects a concrete material opportunity created by a legal bishop, rook or queen move. An attacked front target must resolve in a way that exposes a rear target or causes a directly related exchange. Alignment alone is not a candidate. The outcome explains why the move matters; the skewer motif explains how it works.

## Modules and contracts

| Layer | Module / interface |
| --- | --- |
| Selection/orchestration | Existing central crawler, scope and planner; registry key `missed_skewer` |
| Static geometry | `skewer_geometry.skewer_screener(row)`; `skewering_moves(board, played_uci)` |
| Scout | `skewer_scout.scout_skewer(row, evidence)` → `ScoutResult` |
| Adapter | `skewer_adapter.skewer_adapter(row, positions)` → `HeavyResult` |
| Calculation | `analyze_skewers.analyze_single_move(row, analyze_fen)` → `HeavyResult` |
| Engine | Existing `PositionAnalysisService.position(fen, profile)` |
| Board facts | `board_analysis` rays, lines, direction, contacts and material helpers |
| Bounded proof | Existing `tactical_proof.verify_bounded_line` |
| Participant tracking/accounting | Shared `tactical_line_proof` |
| Attribution | `skewer_attribution.attribute_skewer` |
| Interpretation | `skewer_opportunities.skewer_opportunity` → `TacticalOpportunity` |
| Persistence | Existing generic `heavy_repository` and opportunity codec |

Calculation has no SQLite access, engine lifecycle, selection loop or persistence. No skewer-specific crawler/database/UI branch was added. Pin V1/V2, fork/mate calculation and existing engine profiles remain unchanged. Registry registration does not authorize live execution.

## Skewer vs pin vs x-ray

A **pin** constrains the intervening piece because moving it exposes a more valuable rear target. A **skewer** attacks the more important front target, whose resolution exposes the rear target. **X-ray** is a line through intervening occupancy and does not itself prove a forced response or payoff.

Shared `board_analysis.SliderLine` records attacker, front, rear and direction. `direct_slider_lines` returns exactly the first two occupied contacts, including friendly contacts, without skipping blockers or assigning tactic/value policy. Pins continue using the same underlying `ray_contacts` API without a behavior migration.

The shared persisted `LineRelationship` uses `intervening_piece` for the skewer's front target and `rear_target` for the rear, with `absolute_skewer` or `relative_skewer` as the relationship type. This is a structural mapping, not pin semantics. Squares describe the position immediately after the tactical move; proof tracking follows identities through moves and captures.

A future X-ray specialist may reuse these facts and generic resolution/accounting helpers, but needs its own pressure, forcing and payoff policy. X-ray V1 is not implemented.

## Static screener

Screener version **1** enumerates legal unplayed moves by bishops, rooks and queens, including slider promotions. It checks the moved piece's new direct rays and excludes an identical already-existing contact pair. It runs no engine and proves no material gain.

- Both contacts must be opponents; the rear cannot be a king.
- A king-front skewer requires a rear minor, rook or queen.
- A relative skewer requires a front queen or rook with strictly greater material value than the rear; the rear may be a pawn.
- A friendly or irrelevant contact is never skipped to reach a better target behind it.
- Invalid input proceeds to validation/error rather than becoming a completed static negative.

Recall is scoped to direct moved-slider geometry. Stationary/discovered attacks, castling rook attacks, king-front/pawn-rear lines and equal-valued contacts are outside V1.

## Scout and versioning

Scout version **1** uses the existing `tactic_scout_v1` profile: 10,000 nodes, one engine thread, 64 MB hash. Its canonical `scout_config` includes engine identity, profile, options, comparison, the **80 cp** missed-gain threshold and `new_direct_slider_skewer_v1` geometry identity.

The scout compares shallow best-before and played-move evaluations from the player's perspective. It retains losses of at least 80 cp and all mate-valued ambiguity for specialist review. This is a cheap position-level proxy, not a classification or a claim that a specific skewer move is best. Actual alternatives are evaluated by the heavy specialist.

Analyzer version is **1**. Existing currentness rules apply unchanged: static negatives depend on the screener; scout negatives also depend on scout/configuration; heavy no-hits additionally depend on analyzer version. Candidate/rejected coverage depends on analyzer version independently of scout version. Error remains retryable. Persistence remains generic and ID preserving.

## Heavy proof and noise control

The calculation receives one canonical move context and an evaluation callback. It returns structured results; generic dispatch converts failures to retryable errors.

| Gate | V1 requirement |
| --- | --- |
| Quick profile | Existing depth-10 `tactic_quick_v1` |
| Quick gain over played / drop from best-before | At least 120 cp / at most 300 cp |
| Verification profile | Existing depth-18 `tactic_verify_v1` |
| Deep gain over played / drop from best-before | At least 150 cp / at most 200 cp |
| Retained total and line-related material | Each at least 100 cp |
| Settled evaluation | At least −100 cp, at least 150 cp above played, at most 200 cp below best-before |

Total material gain must remain relative to both pre-move and post-tactical-move balances. An unrelated capture made by the initial move cannot alone qualify. Arithmetic values are P100/N300/B300/R500/Q900/K0; king importance is handled separately.

The unchanged shared proof re-evaluates each ply at depth 18, follows the selected best reply, and covers four further user moves after the tactic plus the following defense. It permits at most four extra settlement plies. Settlement requires two quiet actual plies, no check and two quiet best-PV lookahead plies. A payoff beyond four user moves does not qualify merely because it occurs during settlement.

This is bounded best-line evidence, not exhaustive defense enumeration or a mathematical proof. Illegal/missing evidence, unsettled sequences and mate-valued continuations never become strong material-skewer results.

## Front handling, causality and exchanges

A king-front check establishes a forced response. For a relative skewer, `capture_balance_floor` must show a legal capture of the front target with positive material gain after every immediate legal recapture. This is conservative local threat evidence, not full SEE or a counterfactual engine theorem. The engine continuation must still support the payoff.

Shared `trace_line_resolution` follows original attacker/front/rear identities. It records the first front resolution separately from a later front capture. Rear credit requires either the original attacker capturing the exposed rear target on the original ray, or immediate recapture of that rear target after it directly exchanges the attacker on the open ray.

The attacker can capture the front target and continue to the rear. Losing the attacker is not automatic rejection: its loss and all subsequent recaptures are charged through settlement. A front target simply taking the attacker without a proven rear payoff is insufficient. A rear target that escapes and later loses to an unrelated attack is not credited. Moving the original attacker off its ray ends that line identity.

All own losses through settlement are deducted. Unrelated wins cannot finance a skewer claim; they offset only a later loss of the same capturing piece. Front material is credited only when captured by the original attacker, and there must still be a timely rear payoff.

The motif is `supported` only when meaningful threat, resolution, causal payoff and retention gates pass. Otherwise the alignment is context in rejection evidence, with no candidate or positional-skewer annotation. `supported` does not assert exhaustive causal verification.

## Outcome, timing and presentation

The shared opportunity stores outcome, motifs and attribution, timing, proof, presentation and line metadata. Canonical played/tactical moves and proof SAN remain in the existing columns through the generic codec. A captured front queen can determine the outcome instead of the smaller rear target. Net exchange value prevents an unqualified piece-win headline when the attacker is lost.

V1 uses existing open codes: `win_pawn`, `win_piece`, `win_rook`, `win_queen`, `win_exchange`, `force_favorable_exchange`. No enum/schema change was needed. Strong results use outcome-first titles such as **“Check and win the rook”**, a supported `skewer` motif, and `check` for king-front cases. Accounted attacker losses can add a supported sacrifice motif.

`immediate` means payoff on the first further user move after the tactic; `delayed` means moves two through four. Front resolution/capture, related retained gain, attacker loss, payoff move and extra settlement plies are explicit metadata. `relationship_survived` means the tracked attack line was operative at payoff, not that three original pieces remain aligned on the final board.

No Game Review implementation was changed. No positional notes or strong callouts for unrelated gains are created.

## Mate ownership

Mate scores are never converted to cp. Winning pre-position mate evidence defers to `missed_mate`; negative/other mate evidence defers to mate or saving-tactic review. Alternative/continuation mate evidence is recorded as deferred, never a material candidate. Plausible geometry can accompany a deferral as `context_only` for an owning specialist; Skewer V1 does not create mate candidates or claim causal credit for a mating mechanism it has not proved.

## Validation and rollout boundary

`tests/test_skewers.py` covers geometry, both colors, immutable contexts, timing, front captures, exchanges, unrelated gain, recaptures, mate ownership, service injection, opportunity roundtrip, canonical IDs and training links. The full fork/mate/pin suite is the regression boundary.

`tests/fixtures/skewer_v1_gold.json` distinguishes deterministic legal contract lines from real engine claims. `reports/validate_skewer_v1.py` validates those contracts and explicitly selected synthetic engine cross-checks. Ambiguous cases are not required positives. Live data is read-only and cache misses stay in memory. The runner contains no historical crawl.

The authorized historical work is only this existing central-crawler preview:

```powershell
.\.venv\Scripts\python.exe analysis_crawler.py --validation-scope-500 --negative-preview --analysis missed_skewer --report reports/skewer_v1_preview.json
```

It uses exact saved IDs, a read-only live connection and temporary scout cache. No heavy historical checks or live candidate/coverage/cache writes run. The proposed queue must be reviewed before rollout; correctness thresholds must not be weakened to reduce its cost.

See `reports/SKEWER_V1_VALIDATION.md` for results. Live Skewer writes, all-games analysis, X-ray V1 and Pin V1 candidate reconciliation remain outside this task.
