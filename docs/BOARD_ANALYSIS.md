# Board-analysis library

Import public primitives from `board_analysis`. This library contains reusable
board facts for specialists and future pattern consumers. It has no engine,
database, UI, or tactic dependencies and does not assign tactical labels or
numerical safety scores.

## Contract

- Inputs are python-chess `Board`, `Square` (0–63), `Color`, `PieceType`, and
  `Move` values. Use legal standard-chess positions for legal-mobility queries.
  Geometric helpers can also inspect partial boards; missing pieces/kings have
  documented empty/None results.
- Calls leave the supplied board, turn, castling/en-passant state, and history
  unchanged. Callers must not mutate a board concurrently with a query.
- Results are tuples or frozen dataclasses containing immutable scalar/tuple
  fields, detached from the board. Square IDs remain integers; format them with
  `chess.square_name` at presentation/serialization boundaries.
- Attack lists and neighborhoods use ascending square-index order. Rays,
  between-squares, blockers, and contacts are ordered from the source outwards.
  Legal moves are returned as sorted UCI strings, retaining promotion choices.

## Public operations

| Function | Result and semantics |
| --- | --- |
| `direction(source, target)` | Unit `(file_step, rank_step)` for distinct rank/file/diagonal endpoints; otherwise `None`. |
| `ray_squares(source, step)` | Squares through the board edge, excluding source. Accepts only one of the eight unit `DIRECTIONS`. |
| `between_squares(source, target)` | Strictly between aligned endpoints. Empty for adjacent, identical, or unaligned endpoints; use `direction` to distinguish them. |
| `neighborhood(square, radius=1)` | Chebyshev-distance neighborhood, excluding center, clipped to the board. Radius must be a nonnegative integer. |
| `attacked_squares(board, source)` | Geometric attacks from the piece at source; empty for an empty source. |
| `attackers(board, target, color)` | Sources of that color attacking target under current occupancy. |
| `attack_map(board, color)` | `AttackMap` with `sources_by_target[square]` and the union `attacked_squares`. |
| `attacked_pieces(board, source, *, target_color=None, piece_types=None)` | Tuple of `PieceRef(square, piece_type, color)` on occupied attacked squares. Default includes both colors/all types. Empty type filter selects nothing. |
| `line_relationship(board, source, target)` | `LineRelationship` with unit `step`, `between`, occupied `blockers`, and `clear`. Clear means distinct aligned endpoints with no intervening piece; endpoint occupancy is not a blocker. |
| `ray_contacts(board, source, step)` | Every occupied square along the ray as `RayContact(piece, intervening)`, including pieces behind blockers. Does not require a slider at source or claim that it attacks through blockers. |
| `piece_safety(board, square)` | `PieceSafety(piece, attackers, defenders, absolutely_pinned, pin_line)`, or `None` for an empty square. `pin_line` is the full rank/file/diagonal of an absolute king pin, empty if unpinned. |
| `legal_mobility(board, source=None)` | `Mobility(color, source, moves_uci, destinations, captures_uci)` plus `move_count`. Legal moves for the actual side to move, optionally from one square. Empty for an empty/enemy source. |
| `capture_square(board, move)` | Square of the captured piece on the pre-move board, or `None`. Caller supplies a legal move. En passant returns the pawn's square, not the move destination. |
| `king_safety(board, color)` | `KingSafety` with king `square`, adjacent `zone`, `checking_pieces`, `attacked_zone`, immediate `pawn_shield`, and `legal_moves_uci`; `None` for a missing king. |
| `material_balance(board, color, piece_values)` | Own minus opposing material using caller-supplied values for every present piece type. Missing values raise `KeyError`. Counts only pieces on the board; not an exchange/safety evaluation. |

Attacks follow python-chess geometric semantics: pinned pieces still attack;
sliders stop at the first blocker but defend a friendly piece there; pawns attack
diagonals, not push squares. Attack maps do not encode en-passant captures.
`PieceSafety.attacked_and_undefended` means it has geometric enemy attackers and
no geometric friendly defenders. It is not a static exchange evaluation or proof
of a hanging piece; pinned attackers/defenders are included.

Material accounting has no default values. A caller can explicitly value kings
at zero for inventory accounting, for example; that convention is not a legal
permission to capture a king. Pin V1 supplies its values from its own policy
module and uses balances only after legal, engine-supported continuations.

Mobility never flips the turn to estimate the other player's legal options.
Promotion alternatives count as distinct moves even when they share a target.
Castling is included. Destinations are the move's encoded `to_square` values;
the library has not been validated for variant-specific/Chess960 interpretation.

For king safety, the zone excludes the king's own square, whose attackers are
listed separately as `checking_pieces`. `pawn_shield` means friendly pawns one
rank forward within that adjacent zone. This is a structural descriptor, not an
assessment of shelter quality. Zone attacks use current occupancy; legal king
moves account for vacating the source and post-move attacks. Do not derive safe
escapes by subtracting `attacked_zone` from `zone`. Legal king moves are `None`
when the requested color is not to move, and an empty tuple when it is to move
but has no legal king move. These moves include castling, not just king steps.

## Composition examples

```python
import chess
from board_analysis import attacked_pieces, line_relationship, piece_safety

# The consumer decides which targets matter; the library has no fork policy.
targets = attacked_pieces(board, source, target_color=not player_color,
                          piece_types={chess.ROOK, chess.QUEEN})
relationship = line_relationship(board, source, target)
safety = piece_safety(board, target)
```

Specialists combine these facts with their own calculation and verification.
The Pattern Engine can consume these same records for pattern predicates or
visual annotations without importing any tactic module or starting an engine.
Do not move tactic thresholds, candidate schemas, or persistence into this library.

## Current adoption and verification

`tactic_screeners.enemy_targets_after_move` and Fork V2's `get_fork_targets`
now use `attacked_pieces`, retaining their existing dictionary schemas, ordering,
piece values, and target policies. Fork V2's `get_capture_square` delegates to
the shared capture helper. Legacy standalone launchers remain retired paths;
this refactor does not make them safe to run.

`tests/test_board_analysis.py` covers alignment/edge geometry, blockers/x-rays,
pawn attacks, pins, legal mobility, both colors of en passant, pinned en passant,
promotion choices, castling, king-ray exposure, missing kings, checkmate,
caller-board immutability, detached results, and fork output compatibility.
All 71 tests in the full suite passed after integration. No live database writes
or heavy-analysis run accompanied this extraction.
