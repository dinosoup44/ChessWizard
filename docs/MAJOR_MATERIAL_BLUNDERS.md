# Major Material Blunder Checker V1

Status: **FROZEN after successful audit + human review — ROBUST / VALIDATED FOR CONTROLLED USE** (2026-09-10). Not globally Trusted. Calculation remains portable and report-only: no production admission, crawler, ranking or persistence activation. Human Review displays frozen audit cases; it does not run the checker. There is no engine request path. The checker consumes supplied moves and shared evidence rather than independently discovering tactics.

## Interface

`check_major_material_blunder(before, played_move, after, continuation, *, move_id=None, target_square=None, material_values=MaterialValues(), policy=MaterialBlunderPolicy(), eval_before=None, eval_after=None, provenance=())` returns the immutable `MajorMaterialBlunderResult`.

Before/after accept FEN or standard/Chess960 `chess.Board`. Played move and continuation use UCI. After must exactly match the legally replayed played move (including counters and rights). A supplied board is copied; its history is preserved. Target square, if specified, always refers to the BEFORE position. Otherwise the immediate captured major piece is selected. All supplied moves must be legal; nulls, mismatched positions and oversized windows return `error`, never a partial positive result.

The typed result carries classification/reason, proposed piece class, player/color/move identity, stable original target and capturer identities, TargetFate, before/after AttackState, actual-side RelevantRecapture and all legal recovery options, complete MaterialTransition/RangeEvidence, terminal state, optional cached evaluations, avoidance witness, uncertain checking/promotion moves, completeness, provenance, policy identity and factual explanation strings. Classification is independent of tactic-candidate/coverage statuses. Piece class is not admission: an unresolved queen exchange may still identify its target as `hung_queen`.

## Modules and dependencies

- `major_material_blunder_models.py`: frozen public results and local typed policy.
- `major_material_blunder_evidence.py`: direct-exposure witness and recovery queries over LegalReplay.
- `major_material_blunders.py`: bounded classification decisions.
- `reports/build_major_material_blunder_report.py`: separately owned SELECT-only fixture extraction and report export.

Shared Position/Range Evidence owns replay, original identities, capture legality, en passant, promotions, castling, material accounting and terminal facts. The checker does not calculate replacement attack maps or material ledgers. Existing Critical Moment `EvaluationEvidence` is reused as an optional fact contract. No toolkit, analyzer, engine, UI, schema or global-settings code changed.

## Exact free-loss standard

Supported captured types are queen, rook, bishop and knight: `hung_queen`, `hung_rook`, `hung_minor_piece`.

Confirmation requires all of:

1. The target belongs to the player making the actual move and is captured legally on the immediate opponent reply (replay ply 2). Being attacked or surviving the window is insufficient. Delayed capture is unresolved when a target is explicitly tracked.
2. Whole-window net loss is at least the smaller configured bishop/knight value. The target's own value minus credited recovery must also meet that minimum. Other losses cannot inflate this target's importance.
3. Recovery is at most one configured pawn by default. Credit begins BEFORE the actual move, including its captures. Queen-for-queen and rook-for-rook exchanges do not confirm; rook-for-bishop at 200 cp is outside this minimum. Larger positive-net exchanges remain unresolved, not accepted as free losses.
4. No supplied promotion or multiple major-piece loss complicates the attribution. Promotion value changes are included in the ledger, not treated as additional free pieces.
5. All legal immediate captures are inspected, including recovery elsewhere, rather than just recapturing the capturer. Unplayed substantial recovery is unresolved. A cutoff capture with a legal recapture remains unsettled even when the cutoff material sum balances.
6. Every represented player turn after the opponent capture is checked for legal checks/promotions and further major recovery. Any such forcing possibility is unresolved; it is not searched, assumed effective or assumed harmless. The player response must be supplied. An endpoint check remains unresolved. Player mate or terminal draw in the supplied line precludes a free-loss claim; opponent mate remains unresolved under this material-only contract.
7. A different legal, nonchecking, nonpromotion move from BEFORE the move demonstrates direct avoidability: the same target survives, has no geometric attacker, and no other friendly major piece is immediately legally capturable. The witness is replayed through the toolkit without changing the side to move. No witness means unresolved (`prior_loss_not_excluded`), not proof that the piece was doomed.

Default window: at most four continuation plies after the actual move (five total). No silent truncation and no additional engine/proof tree. The result certifies only this bounded direct-loss standard. It does NOT prove long-term survival under the alternative, absence of distant quiet compensation, a forced continuation, or a forced game outcome. Recorded moves are observations, not best-defense proof. This limitation must remain visible to future consumers.

## Causality and uncertainty

Exposure labels are factual relationships: moved target into capture, abandoned geometric defender, ignored existing direct threat, or opened capture line. A before-position enemy capture is off-turn: its legality stays unknown. Only the actual opponent-turn after-position establishes legal capture. Defender labels do not by themselves prove a legal recapture existed. A direct-escape witness is required in addition to every exposure label.

`confirmed`: all bounded direct-loss requirements met.

`not_blunder`: this narrow test is not met (survival, no immediate major capture, recovered material, sub-minor net difference, terminal compensation). It is not a judgment that the move was good. A call without an explicit target does not search for delayed losses.

`unresolved`: incomplete response, delayed capture, uncertain prior inevitability, substantial exchange/promotion, unsettled recovery, possible forcing compensation, terminal loss or attribution ambiguity. Missing engine information remains unknown.

`error`: invalid supplied evidence. Callers must not interpret error as completed negative coverage.

## Settings and cached evaluations

Material values come from shared `MaterialValues` (default pawn 100, minor 300, rook 500, queen 900). There are no duplicated piece-value constants. `MaterialBlunderPolicy` uses the shared Settings/setting/schema convention:

| Setting | Default | Range | Meaning |
|---|---:|---:|---|
| continuation_plies | 4 | 1–4 | Maximum supplied continuation, excluding actual move |
| recovery_pawns | 1 | 0–1 | Maximum compensation in configured pawn units |

Both are advanced, result-currentness settings with no raw-cache impact. Policy identity includes both local policy and shared material settings. They are not installed into global profiles or an Admin Console. Future controls can consume the existing schema without a parallel configuration path.

Optional evaluations use exact before/after FEN and caller-normalized player POV. Only matching request identities yield a numeric delta. Missing scores are None, mate scores remain mate semantics, and no evaluator fallback exists. A cached player mate after the move blocks positive admission. Scores never turn uncertainty into confirmation.

## Fixtures and limits

Synthetic tests confirm quiet queen, rook and minor losses (including rook for pawn), and cover trades, unplayed recovery, pinned illegal capturers, forced mate sacrifice, absent prior escape, surviving target, promotions, en passant, castling identities, multiple attackers, source immutability and legal/material parity.

Six exported positions from four human-reviewed games are frozen in `review_data/major_material_blunder_fixtures.json`; tests replay them without a DB. Full findings: `reports/MAJOR_MATERIAL_BLUNDER_V1.md` and structured `reports/major_material_blunder_validation.json`.

- 2737, White 10.d4: 900 cp net loss, Qe4 direct escape; unresolved because Bf7+ remains unproved. This deliberately favors precision over recall.
- 14, White 9.Qxe7+: queen plus bishop lost, bishop plus knight recovered; 600 cp net. Substantial exchange, unresolved.
- 320, White 11–13: supplied windows include material recovery; not a demonstrated essentially-free major loss.
- 2771, White 30.Rf4: rook for bishop, 200 cp; not a V1 major free loss.

The completed controlled audit and human review below do not establish population precision or recall. Further measurement requires separate approval. Any deeper compensation/inevitability proof must reuse shared proof services under a separately approved task. Do not broaden this module into a new engine, infer strategic mistakes, modify analyzer outcomes, automatically rank moments or create candidates from this V1 result.


## Frozen V1 checkpoint — 2026-09-10

The implementation checkpoint passed **617 tests** at the time of checker delivery.
That historical count is separate from the current public suite; use the
[test workflow](DEVELOPMENT.md#tests) to validate the checkout being reviewed.
No checker code, thresholds, settlement window or acceptance policy changed in
the status-clarity task.

- Read-only historical audit: 150 games (2651–2800), 4,470 user positions,
  8 confirmed, 238 unresolved, 4,224 not_blunder, zero errors.
- The 19-case human shortlist contained 8 confirmations, 7 unresolved cases and
  4 negative controls. All **8/8 original confirmations received PASS**.
- Both WRONG MOTIF reviews were equal-exchange negative controls already marked
  not_blunder. INVESTIGATE was unresolved. No detector false positive or false
  negative was established; this does not establish recall or global precision.
- Unresolved cases remain conservative. Stored judgments stay unchanged.
  No production activation or additional cohort is authorized by this freeze.

These aggregates summarize the historical audit and 19-case reconciliation;
per-game receipts and human notes remain private. See the
[review-status contract](HUMAN_ANALYZER_REVIEWS.md#original-audit-status-separate-from-human-verdict)
for the distinction between a checker result and a human verdict.

### Discovered Attack Analyzer — future candidate

Human review of game **2666 / move 163398 (31.Kh2)** identified the preceding
**30...Rc1+**, actual tactical move ID **163397**. The rook moves c4→c1 and checks
king g1 while uncovering bishop b3's attack on queen e6 along b3–c4–d5–e6.
The recorded payoff is 31.Kh2 Bxe6. The other legal check evasion, Qe1, permits
Rxe1+. This is a discovered attack with direct rook check, not a discovered check.

Keep this concrete example on the future analyzer design map, separate from the
material checker. It is not an active analyzer, candidate or V1 scope expansion.
The earliest avoidable error is not established by this bounded observation.

### Recommended next design-map item (requires approval)

**Mate-Enabling Blunder Checker V1 — design contract and frozen fixtures only.**
Define a separate factual contract for a played move allowing an immediate legal
mate, with explicit prior-position/causality and uncertainty requirements. It
must reuse shared evidence and remain separate from material-loss classification
and Critical Moment ranking. No implementation, scan or activation is part of
this checkpoint. Discovered Attack Analyzer remains a subsequent independent
candidate; neither item is started automatically.
