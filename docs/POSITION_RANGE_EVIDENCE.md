# Position / Range Evidence Toolkit V1

The `position_range_evidence` package provides deterministic chess facts. It does
not evaluate positions, assign motif ownership, identify compensation, validate a
tactic, or decide semantic settlement. It has no engine, cache, database, analyzer,
or UI dependency. Material values come from shared `analysis_settings.MaterialValues`
unless the caller supplies a complete configured value mapping.

## Public entry points

```python
import chess
from position_range_evidence import analyze_position, analyze_range, LegalReplay

position = analyze_position(chess.STARTING_FEN, squares=["e2", "e4"])
evidence = analyze_range(
    chess.STARTING_FEN,
    ["e2e4", "d7d5", "e4d5"],
    track_squares=["d7"],
    material_snapshots=True,
)

# Reuse the same replay for targeted intermediate queries.
replay = LegalReplay(chess.STARTING_FEN, ["e2e4", "d7d5", "e4d5", "d8d5"])
target_id = replay.identity_at_start("d7")
facts = replay.evidence(track_squares=["d7"])
target = facts.get_piece_fate(target_id)
intermediate = replay.position_evidence(ply=3, squares=["d5"])
possibilities = replay.relevant_recaptures(ply=3, track_squares=["d7"])
```

`LegalReplay` accepts a FEN or a `chess.Board`, an iterable of UCI moves, optional
canonical `moves_san` (same length), `piece_values`, and `history_complete`.
`analyze_range` adds selected original `track_squares`, optional material snapshots,
and an explicit `recapture_lookback_plies` (default: the immediately preceding ply).
`analyze_position` performs no range replay and computes attacks only for requested
squares. Standalone `terminal_state(board, history_complete=...)` returns the same
rule contract. No evaluation argument exists.

Squares, piece types, and colors in results use python-chess integer/bool values.
Input square names are also accepted. Event plies start at **1**; intermediate
`ply=0` is the source, `ply=N` is after N moves. Results are frozen/slotted dataclasses
with tuple collections. No custom serialization/cache format is introduced.
`dataclasses.asdict` gives deterministic data in construction order.

## Legal replay and identity

Every initially present piece receives `PieceIdentity(initial_square,
initial_piece_type, color)`. Initial squares distinguish identical pieces. IDs
are local to this replay's starting position, not persistent/global piece IDs.
All initial pieces are tracked internally, so captures identify their capturer
and victim even when callers did not request those pieces' endpoint attack facts.

* Movement changes location, never identity. A replacement on an old square has
  its own original identity; a captured identity never returns.
* Promotion preserves the pawn identity and records the new type and configured
  material delta. `final_piece_type` means the last observed type even if captured.
  A piece already promoted before the supplied start is identified by its type at
  that start; the toolkit does not reconstruct its missing earlier history.
* En passant removes the pawn from its **actual victim square**, which differs
  from the move destination. Both squares are recorded.
* Castling moves both king and rook identities. Standard chess and Chess960 are
  supported, including overlapping source/destination squares and stationary
  castlers. Sources are removed together before destinations are assigned.
  Move count means participation in a move: a stationary Chess960 castler counts
  once; it does not claim a change of square.

Invalid starting boards and other chess variants are rejected. Illegal moves,
null moves, SAN length errors, and incorrect canonical SAN raise `IllegalRangeError`
with a 1-based ply where available. No partial range result is returned. A supplied
board is copied with its move stack; returned `board_at` boards are independent.

Replay means **board-legal moves**. It does not adjudicate whether a player actually
claimed a draw or stop a supplied continuation at a claim/automatic-draw boundary.
Endpoint rules are reported separately. Consumers wanting game termination as a
range constraint must apply that policy themselves. Historical board move stacks
and FEN counters are caller-supplied evidence, not independently authenticated game
records.

## The six helpers

| Contract | Factual meaning |
|---|---|
| `MaterialTransition` | Before/after/delta by color, positive captured/lost value totals, separate promotion deltas, ordered capture/promotion events, configured values, optional initial-plus-per-ply snapshots. |
| `TargetFate` | Original identity, current square or capture ply/capturer, participation count, promotion history, last type, alive/moved/promoted properties, endpoint attacks and terminal/check context. |
| `AttackerSurvival` | First mover's `TargetFate`, actual destination after first move, whether it moved again, and legal capture possibilities involving it. Survival/loss is not success/failure. |
| `RelevantRecapture` | A king-safe `LegalCapture` plus explicit relations to attacker, selected targets, recent capture squares, or exchange participants. It predicts no best move. |
| `AttackState` | Geometric attackers/defenders and counts, legal capture sources/count, pinned geometric sources, both colors' selected-square control, legal captures by/against the piece, actual side's check state. |
| `TerminalState` | Rules-only terminal/claim/history state; it never consumes an engine mate score. |

Material values are nonnegative integers for all six piece types. King value comes
from the supplied mapping (shared default zero). For each color:

`total delta = promotion delta - lost material`

Captured-by-side is the opponent's lost material. Captured promoted pieces use
their type **at capture**, not their initial pawn value. An underpromotion can
have a different delta under a custom value configuration. Castling never captures
or changes material. Snapshots are optional; callers need not rebuild every prefix
to obtain a material timeline.

`MoveEvent` embeds optional `CaptureEvent`, `PromotionEvent`, and `CheckEvent`, plus
`PieceIdentityTransition` entries. SAN and checkers are computed from the legal
board. Captured-piece transitions have `to_square=None`. This small ledger supports
factual tracing without an event framework or semantic labels.

### Attacks and recaptures

The toolkit reuses `board_analysis.attackers`, `piece_safety`, `legal_mobility`,
and `capture_square`. It does not duplicate rays, pin detection, or legality.
Other `board_analysis` line/geometry helpers remain available to consumers.

Geometric defense includes pinned defenders. It is not proof of a safe recapture.
A friendly occupied square cannot have a legal friendly capture, so the toolkit
reports **geometric defenders**, not an invented legal-defense move set. King-safe
captures are available only for the **actual side to move**; the toolkit never
flips `board.turn`.

* `legal_attackers=None` / `legal_capture_available=None` means not evaluated
  because the potential capturing side is not to move, or the selected square
  is empty. This is different from an evaluated empty tuple (no legal capture).
* Kings are never legally capturable: their legal capture tuple is empty while
  geometric attacks and `is_checked_king` report check correctly.
* For an empty selected square, `attacked`/`defended` are `None`; white/black control
  sources still describe geometric control.
* `legal_capture_squares` are victim squares for captures **by** the selected piece.
  Each capture also contains its destination. EP legal sources may therefore differ
  from geometric sources attacking the victim's occupied square.

Relevant captures carry one or more stable relation strings: `captures_attacker`,
`captures_target`, `onto_recent_capture_square`, `by_attacker`,
`by_exchange_participant`. Recent capture scope is explicit in plies. For EP it
includes the victim square and landing square. Exchange participants start with
selected targets and the first mover, adding parties to actual captures involving
that set as the ledger advances. This is factual involvement, **not causal motif
attribution**. A caller can query a different endpoint or recency window without
rerunning the legal move sequence. Possibilities include side, UCI/SAN, original
capturer/victim, victim type/value/square, destination, EP, and legality.

### Terminal and history semantics

| State | Automatic endpoint? | Evidence |
|---|---|---|
| `checkmate` | Yes | Check plus zero legal moves; winner is opposite side to move. |
| `stalemate` | Yes | Not in check plus zero legal moves. |
| `insufficient_material` | Yes | python-chess material rule. |
| `other_draw` | Yes | Supported automatic 75-move or fivefold-repetition rule; reason is explicit. |
| `fifty_move_claimable` | No | Claim possible now or with an eligible next move; trusted halfmove clock. |
| `repetition_claimable` | No | Supplied history proves a claim now or with an eligible next move. |
| `nonterminal` | No | No supported terminal/claim condition; repetition history asserted/inferred complete. |
| `unknown_history_dependent` | No | No known ending/claim, but missing earlier repetition history prevents a definitive negative. |

Checkmate/stalemate/insufficient-material/75-move endings take precedence over claims.
When both claims are available, the state is `fifty_move_claimable`; separate claim
fields preserve repetition evidence. A positive repetition can be proved from a
partial stack. A negative is `None` unless history is complete. Fivefold repetition
is automatic; threefold claimability does not mean the game ended.

Completeness is inferred only when the supplied board's root is the canonical
starting position; other roots default to incomplete. Callers may explicitly assert
`history_complete=True/False`. FEN alone cannot recover a repetition history.
`determined_from_position_alone` describes the selected main state, not every
secondary metadata field. Claims/unknown states have `is_terminal=False`.
History queries operate on copies, preserving the caller's stack.

This is not a complete FIDE adjudication system: resignation, time forfeits,
agreed draws, and unavailable history are not invented. A mate-in-N evaluation
on a board with legal moves never becomes `checkmate` through this API.

## Performance and validation

One replay updates the identity ledger in O(N); material timelines use that ledger
in O(N), not repeated prefix replays. Endpoint capture generation is shared across
selected pieces. No whole-board attack map or per-ply terminal/attack scan is eager.
SAN/legal generation and endpoint repetition probes are the main costs. Intermediate
queries copy/pop only the requested position; querying every prefix's full rule
state is intentionally not the fast path. Use the ledger/snapshots for timelines.

Measured on this Windows/Python 3.14.7 environment, 200 deterministic repeats per
range, with material snapshots and 3–4 tracked pieces:

| Plies | Median ms | p95 ms |
|---|---:|---:|
| 1 | 0.619 | 0.958 |
| 8 | 0.835 | 0.978 |
| 20 | 1.021 | 1.207 |
| 80 | 2.914 | 3.369 |

The 1/8/20-ply cases use stored audit `15180:c6d5`, branch 3. The 80-ply case is a
seeded legal standard-game sequence, not a claim about typical human game quality.
These are sanity measurements, not a performance SLA. Reproduce with
`python -B reports/benchmark_position_range_evidence.py`.

Tests cover synthetic standard/Chess960 castling, all promotions, capture-promotion,
EP and EP king exposure, identity replacement, captured promotions, pinned captures,
multiple/no/immediate/x-ray-exposed recaptures, checks, draw/history rules, illegal
input, immutability, and independent legal/material replay of eight seeded ranges.
Sixteen stored audit lines cover moved/captured targets, attacker loss, mixed survival,
ongoing checks, repetition, mate-valued nonterminal boards, castling, promotions,
late captures, and cases formerly discussed as negative related ledgers. Tests use
only their factual boards/lines/material, never their Fork classifications or
causal settlement labels. Controls 1848/1849 are represented by their stored lines.
No engine or production database is needed by the fixtures.

## Architecture and future adoption

Modules: `models.py` (immutable contracts), `replay.py` (legal replay/composition),
`material.py` (configured accounting), `attacks.py` (targeted legality/relations),
`terminal.py` (rules/history), and the explicit package exports in `__init__.py`.
All are usable from mobile, desktop, CLI, and tests without Tkinter.

No analyzer has been migrated, and the older `proof_endpoint_facts` audit collector
remains untouched. No settlement or admission policy changed. Future adoption
should compare factual outputs before changing an analyzer's interpretation.

* Fork: original target fate, attacker survival, recapture possibilities, material.
* Pin: pinned-piece movement, rear-target fate, geometric/legal attack distinction.
* Skewer: front-target movement and rear-target exposure/fate.
* X-ray: blocker movement and shared line primitives around selected positions.
* Sacrifice: material investment/recovery timelines, attacker fate, check/terminal context.
* Critical Moments: material swings, selected-piece danger, checks, rule endings.
* Pattern Engine: the same board attacks/relationships without analyzer dependencies.

The toolkit is ready to supply facts for controlled future semantic-settlement
experiments. It does **not** establish that material is retained, a motif is causal,
a tactic is settled, or a move is good. Engine evidence and semantic interpretation
belong to separate consumer layers and require their own validation/approval.

## Legacy comparison contract (parity audit V1)

A legacy `still_on_original_square` label describes endpoint location. It must not
be normalized to `moved=False`: the same original piece may have moved away and
returned. Compare current square separately from `move_count`/`moved`. Likewise,
compare legacy tracked-square capture availability with the matching subset of
`RelevantRecapture`; extra captures by exchange participants have a wider factual
scope. Legacy `none` for terminal status means no automatic ending, while the
toolkit also reports claimability and missing-history information.

The frozen 55-case / 263-range audit found zero unexplained factual contradictions.
Full taxonomy, independent replay, tests, and limitations:
[parity report](../reports/POSITION_RANGE_EVIDENCE_PARITY_V1.md). No analyzer adoption
or semantic-settlement policy change followed this audit.
