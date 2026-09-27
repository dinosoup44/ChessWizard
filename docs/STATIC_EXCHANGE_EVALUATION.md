# Static Exchange Evaluation Toolkit V1

Status: **Validated advisory fact provider**, frozen 2026-09-14. Available in the shared core; no analyzer consumer is enabled. No thresholds, persistence, cache identity or UI behavior changed.

## Public API

```python
from board_analysis.static_exchange import (
    evaluate_static_exchange,
    StaticExchangePolicy,
    StaticExchangeResult,
    ExchangeVerdict,
    ExchangeCompleteness,
    ExchangeUncertainty,
)
from analysis_settings import MaterialValues

result = evaluate_static_exchange(
    source,                         # standard chess.Board or FEN
    capture,                        # legal capturing chess.Move or UCI
    material=MaterialValues(),      # existing shared accounting values
    policy=StaticExchangePolicy(max_plies=32),
)
```

Calculation lives in `board_analysis/static_exchange.py`; frozen models and string enums live in `board_analysis/static_exchange_models.py` and are exported through the calculation module. Import this submodule explicitly. It is deliberately not eagerly exported from `board_analysis.__init__`, so existing analyzer imports do not load SEE.

The pure function copies the source board. It has no file, database, Stockfish, analyzer, settings persistence or Tkinter dependency. It works without a frontend. It accepts standard chess only. Unsupported types raise `TypeError`; invalid positions, variants, malformed moves, illegal moves and noncaptures raise `ValueError`. An invalid request is not a neutral exchange or a fabricated empty result.

## What it answers

For a supplied legal capture onto one square, SEE generates successive actual-side legal recaptures on that square, choosing the least configured attacker cost. It estimates the initiating side's material result with optional stopping along that one chain. It can offer a local exchange hypothesis when no continuation has been supplied.

Numbers are **material accounting centipawns**, not engine evaluations. Shared `MaterialValues` supplies all values. King accounting remains zero, but a king is ordered after other attackers. No duplicate value table exists.

## What it cannot prove

SEE never establishes move quality, tactic truth, forced payoff, mate safety, absence of intermezzi or off-square compensation, positional compensation, initiative, king safety, or motif causality. It does not replace LegalReplay, MaterialTransition, TargetFate, AttackerSurvival, RelevantRecapture, AttackState, TerminalState, engine evidence or proof escalation.

Every result permanently exposes:

```python
result.authoritative_for_tactic_truth is False
result.safe_for_hard_rejection is False
```

These frozen fields are excluded from constructor arguments and dataclass replacement. No policy option can enable hard rejection. These are API invariants, not a sandbox against malicious Python reflection.

## Result schema

| Field | Contract |
| --- | --- |
| `source_fen` | Normalized starting FEN |
| `initiating_move`, `target_square`, `initiating_side` | UCI, python-chess square index, and color boolean |
| `captured_piece_type`, `captured_piece_value` | Initial victim's python-chess piece type and configured cp value |
| `exchange_sequence` | Tuple of frozen `ExchangeStep` records for the entire generated chain |
| `participant_piece_types` | Each capturing participant's type followed by the initial victim's type; not persistent repository identities |
| `estimated_net_cp` | Integer local estimate or **None** |
| `provisional_net_cp` | Diagnostic optional-stop ledger only; never a fallback when the estimate is unknown |
| `selected_prefix_plies` | Prefix used for provisional/numerical material, which may be shorter than the generated chain |
| `verdict` | `ExchangeVerdict`: favorable, neutral, unfavorable, unknown |
| `completeness` | `ExchangeCompleteness`: complete_lva_chain_only or incomplete |
| `uncertainty_reasons` | Tuple of typed `ExchangeUncertainty` codes; nonempty exactly when numerical evidence is withheld |
| `legality_notes` | Human-readable recapture-choice, EP and diagnostic notes; use typed reasons for control flow |
| `pin_xray_notes`, `promotion_notes` | Excluded geometric attackers, newly available attackers and promotion accounting |
| `limitations` | Tuple of typed `ExchangeLimitation` scope warnings, present even for numerical results |
| `material_values`, `policy` | Frozen input configurations |
| `provenance` | `static_exchange_v1:legal_lva_optional_stop_v1` |

Each `ExchangeStep` contains its pre-move FEN, UCI/SAN, attacker/victim types, actual victim square, captured value, promotion gain, cumulative material and all legal same-square choices. A generated chain is one model path, not a proved best-defense continuation. Frozen tuples prevent accidental mutation of returned collections.

## Unknown is different from zero

Zero is a neutral numerical estimate. None is unavailable local material evidence, and its verdict is UNKNOWN. The result constructor rejects contradictory combinations of estimate, verdict, completeness and uncertainty reasons.

| Enum member | Stable serialized code | Why numerical evidence is withheld |
| --- | --- | --- |
| `OFF_SQUARE_CHECK_EVASION_REQUIRED` | `unexamined_off_square_check_evasion` | An in-check node has an unexamined off-square legal response |
| `TERMINAL_MATERIAL_NOT_GAME_OUTCOME` | `terminal_material_is_not_game_outcome` | An already terminal source or terminal position on the chain cannot be interpreted by material alone |
| `EXCHANGE_BOUND_EXHAUSTED` | `exchange_cap_reached` | The configured bound is reached with legal recaptures still available |

The serialized codes retain their audit vocabulary. They are evidence reasons, never analysis coverage statuses. No legal initiating capture is an input error, not a fourth numerical outcome. Missing saved capture context must be reported by a caller as not applicable; it must not be converted to zero.

`COMPLETE_LVA_CHAIN_ONLY` means this deterministic chain finished. It does not mean all legal continuations were searched, all evidence settled, or a tactical proof completed. Repetition history and general game evaluation are outside the contract.

## Legality and deterministic choices

Every recapture is legal on the updated board. Absolute pins exclude only moves made illegal by the pin, not every move by a pinned piece. Relative pins can move legally. King captures into attack are excluded. Geometric attackers and legally movable attackers are distinguished. Newly opened lines are recomputed after each capture. EP removes its actual off-destination victim; promotions charge the capture and the pawn-to-piece increment.

After the mandatory first capture, choose least configured attacker cost, king last. Recapture promotions prefer highest configured value; remaining ties use UCI order. Alternative attackers and promotions remain unsearched. The bound is 32 plies by default and accepts integer values 1–64. No micro-optimization was made. A conservative input-boundary guard preserves a source position already drawn by the 75-move rule before a capture resets its halfmove clock; it reports unknown. All 53 audited capture results remain unchanged.

## Optional stopping — prominent limitation

Optional stopping is **not a legal pass, proof of harmless abandonment, or a guaranteed lower bound**. It compares continuing versus retaining the current material balance along the already generated chain. The first capture is mandatory; no stop option is offered while in check or without an off-square legal move. Even when an off-square move exists, SEE does not account for its consequences or prove it safe.

For example, the five-ply pawn/minor/rook fixture ends at +500 if every capture is played; optional stopping yields +100 because the opponent may decline that continuation. The result retains both the entire generated chain and the selected prefix.

## Correct future consumer usage

GOOD — explicitly handle unknown and record/display only a local estimate:

```python
see = evaluate_static_exchange(board, move)
if see.estimated_net_cp is not None:
    display_local_material_estimate(see.estimated_net_cp)
else:
    display_local_material_unknown(see.uncertainty_reasons)
# Keep the normal analyzer admission, engine and proof decisions independent.
```

A normal pawn trade returns `0` and `ExchangeVerdict.NEUTRAL`. A capture whose check has an off-square evasion returns `None`, `ExchangeVerdict.UNKNOWN`, and a typed reason. Do not use truthiness (`if see.estimated_net_cp`) to distinguish them.

BAD — **prohibited**:

```python
if see.estimated_net_cp < 0:
    reject_tactic()
```

This both mishandles None and grants a local estimate authority it does not possess. Checking for None before rejection would not make that policy acceptable. Also prohibited: verifying a tactic because SEE is positive, using provisional material to bypass unknown, treating completeness as proof stability, or inferring a pin/skewer/fork/X-ray from a material number.

## Dangerous permanent regressions

- Synthetic Nxc5: local +100, but the supplied response Re1# loses immediately.
- Synthetic Qxe5: local -800; Bxd2+ before fxe5 makes the supplied result -1300.
- Synthetic Rxe5: local -400; subsequent off-square Rxb8 makes the supplied line +500.
- Real queen trade, move 163222: local +900 capture, full context 0 after the earlier queen loss.
- Played Fork move 165744: local Nxc6 +900, full branch 0; the existing proof remains rejected.
- Pin candidate 1838: local Bxh3 exchanges are neutral, while the supplied delayed continuation retains +100.
- Skewer 1842: local exchange +200, broader continuation +600.
- X-ray 1847: Rxh2+ needs an off-square response; numerical SEE is withheld despite +400 across the stored line.

These are facts about supplied reference windows, not newly asserted best-play proofs. No analyzer labels were changed. The existing 28-case real set contains no negative-SEE/positive-suffix example; that particular counterexample is retained as a synthetic gold rather than invented as a real case.

## Regression corpus and compatibility

`tests/fixtures/see_synthetic.json` retains all 28 independent synthetic references unchanged. `tests/fixtures/static_exchange_gold.json` freezes the old structured results and all 28 real contexts: 25 applicable captures plus three no-capture cases. Original analyzer status/reason, artifact hashes, source FEN, capture-node offset and full saved lines travel with the real records. Tests need no production DB or research report to execute.

The new calculation matches every pre-existing field for all 53 applicable cases except the intentionally changed provenance tag. Typed reason fields and fixed advisory flags are additive. Original analyzer gold fixtures and expected outputs are untouched.

`see_exchange_prototype.py` is only a compatibility alias module. Its old `see_exchange`, `ExchangePolicy`, `StaticExchangeEvaluation` and `ExchangeStep` names point to the shared API. Research scripts can keep importing those names, but must expect the toolkit provenance and additive result fields. There is exactly one exchange algorithm.

## Validation and maturity

The freeze report records full-suite results, bounded performance and production integrity. Maturity is **Validated** for this advisory local-exchange contract, not Robust across arbitrary chess situations and never an authoritative tactical classifier. New use in an analyzer requires separate approval. Any future consumer settings must remain in shared typed profiles; no setting may promote SEE into a hard filter. This task performs no occurrence migration or analyzer adoption.

See the [regression corpus](#regression-corpus-and-compatibility) and
[limitations](#what-it-cannot-prove) for the public validation boundary. Exact
freeze and feasibility receipts remain private; they do not extend this advisory
contract into tactical proof.

## Authorship

The algorithm was implemented from first principles, with no wiki or engine source copied. Conceptual references remain [ChessProgramming SEE](https://www.chessprogramming.org/Static_Exchange_Evaluation) and [python-chess core documentation](https://python-chess.readthedocs.io/en/latest/core.html). Dependency licensing remains subject to the project's existing distribution requirements.
