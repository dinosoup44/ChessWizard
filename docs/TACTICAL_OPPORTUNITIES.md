# Shared tactical opportunities

## Decision and architecture

An **outcome** explains why an opportunity matters (win a knight, avoid mate,
save material). A **motif** explains a mechanism (check, relative pin, skewer).
One opportunity can have several motifs, with at most one primary motif.
Neither geometry alone nor material gained later proves motif causation.

The implementation follows the existing flat module/dataclass/repository pattern:

| Module | Responsibility |
| --- | --- |
| `tactical_opportunities.py` | Pure structured values, validation, versioned JSON codec. |
| `analysis_results.py` | Existing `HeavyResult`, extended with optional `opportunity`. |
| `tactical_opportunity_repository.py` | Generic metadata preparation and candidate read view. |
| `heavy_repository.py` | Existing authorized, atomic, ID-preserving candidate/coverage write. |

No new package hierarchy, analyzer branches, engine access, UI wiring, or separate
writer is needed. Calculation produces values; engine evidence comes from the
shared position service; persistence remains the repository's responsibility.
`board_analysis` continues to describe board facts, not tactical meaning.
The Pattern Engine can eventually consume these public values and board facts
independently, without coupling to Pin V1 or another specialist's implementation.

## Lean storage decision

Inspection of the live schema confirmed `tactic_candidates.metadata_json` already
exists. Store a versioned document under its reserved `tactical_opportunity` key.
**No SQL schema migration or historical backfill is necessary.** A separate table
and motif child rows would add joins and migration paths without a current query
requirement. A future measured cross-candidate query need can justify an index or
projection; do not add one speculatively.

Store durable conclusions and selected proof evidence. Recompute inexpensive
attack maps, mobility, square control, and ray geometry from FEN through
`board_analysis`. Do not copy engine cache payloads into opportunities. Small
cache ID/profile references can live in the evidence metadata.

Canonical evidence remains in its existing location:

| Evidence | Source |
| --- | --- |
| Played UCI | `moves.uci_played` |
| Tactical UCI/SAN | `tactic_candidates.solution_move_uci` / `solution_move_san` |
| Proof SAN line | `tactic_candidates.solution_line` |
| Candidate identity/status/version | Existing candidate columns |
| Original position | `moves.fen_before` |
| All other opportunity conclusions | Versioned metadata document |

`ProofEvidence` can carry played UCI, tactical UCI, and SAN line in memory. The
repository checks supplied values against canonical evidence, omits these three
fields from metadata, and hydrates them on read. Missing values mean use the
canonical values. No duplicated source of truth is introduced. Material balance
at proof boundaries may be stored as durable proof evidence, not per-move maps.

## Contract

`TacticalOpportunity` contains:

- `primary_outcome: TacticalOutcome(kind, target_piece=None)`. Suggested kinds:
  `win_pawn`, `win_piece`, `win_exchange`, `win_queen`, `force_mate`, `avoid_mate`,
  `save_material`, `force_favorable_exchange`, `gain_attack`, `positional_pressure`.
- `motifs: tuple[TacticalMotif, ...]`: stable kind, primary flag, attribution,
  and rationale. Suggested kinds include fork, check, relative/absolute pin,
  skewer, xray, double_attack, discovered_attack, deflection, removal_of_defender,
  overloaded_defender, sacrifice, and rook_pressure.
- `payoff_timing`: `unknown`, `immediate`, `delayed`, or `positional`.
- `proof: ProofEvidence`: optional canonical moves/line, best defense UCI,
  proof window and scope, material values/profile, evaluations before/played/
  tactic/settlement, best-defense check, settlement and relationship observations,
  and retained material gain.
- `presentation: TacticalPresentation`: level, optional title and explanation.
- `relationships`: optional selected `LineRelationship` records.
- `metadata`: small JSON evidence extensions; not arbitrary engine/board dumps.

Kinds for outcomes, motifs, and relationships are open snake_case codes. New
specialists can add kinds without editing the shared model or crawler. Timing,
presentation, and attribution use enums because their consumer semantics are
stable. Consumers must handle unknown kind codes without inventing a meaning.
Dataclasses are frozen; metadata is a JSON dictionary, so callers should treat
it as read-only. Serialization returns detached values.

### Timing and proof

The proof window counts **further user moves after the tactical move**, not plies
or full moves. Immediate usually means the next user move realizes the payoff;
delayed can cover preparation over multiple turns. Positional describes pressure
without an asserted immediate material win. Timing is a conclusion supplied by
the specialist, not automatically inferred from line length.

All numeric evidence has explicit `score_pov` (`white` or `black`). Material
numbers are centipawn-valued balance/gain, not engine scores; record the material
value profile. `Evaluation` holds centipawns OR signed mate distance, never both.
Unknown values are `None`, not zero or false. A stored material gain or a positive
root evaluation does not by itself establish a settled endpoint.

`best_defense_checked=True` records checking the selected best reply; it does not
mean exhaustive defense enumeration. Use `scope` to state the actual depth,
window, and defensive verification. `settled_position_reached` is independent.
The model validates shape and consistency, not chess truth or analyzer policy.
Specialists remain responsible for legal lines, proof adequacy, and thresholds.

### Causal attribution

Attribution belongs to each motif:

| Value | Meaning |
| --- | --- |
| `unknown` | No causal assessment. |
| `context_only` | Relationship observed; no claim that it caused the outcome. |
| `supported` | Evidence supports a role, with stated limits. |
| `verified` | Specialist's stated causal proof requirements are met. |

Supported and verified require a rationale. They are not numeric confidence and
do not replace the existing candidate confidence. A pin can be context-only while
check is supported. Multiple motifs prevent an incidental geometric relationship
from becoming the entire user-facing explanation.

### Presentation

`strong_callout` highlights a clear actionable opportunity; `secondary_motif`
provides supporting context; `positional_note` describes pressure/restriction.
`unknown` preserves missing legacy classification. Level and primary motif are
independent: an outcome-led callout can include only secondary motifs.
Titles/explanations are ordinary data, not executable templates or UI code.
Game Review has not been wired to these values.

### Line relationships

`LineRelationship` records relationship type, attacker, optional intervening piece,
rear target, optional relevant squares, and optional `(file, rank)` unit direction.
Participants use piece names, white/black color, and algebraic squares in the
position immediately after the tactical move. These selected proof participants
can describe pins, skewers, x-rays, or batteries. Do not populate every candidate
or persist complete board ray/contact maps.

## Specialist and persistence usage

```python
from analysis_results import HeavyResult
from tactical_opportunities import (
    TacticalOpportunity, TacticalOutcome, TacticalMotif, TacticalPresentation,
    ProofEvidence, Evaluation, PayoffTiming, PresentationLevel, Attribution,
)

# After your existing single-position verification has built candidate_payload:
opportunity = TacticalOpportunity(
    primary_outcome=TacticalOutcome("win_piece", "knight"),
    motifs=(
        TacticalMotif("check", primary=True, attribution=Attribution.SUPPORTED,
                      rationale="The check provides the tempo to capture the knight."),
        TacticalMotif("relative_pin", attribution=Attribution.CONTEXT_ONLY),
    ),
    payoff_timing=PayoffTiming.IMMEDIATE,
    proof=ProofEvidence(window_user_moves=1, score_pov="white",
                        evaluation_after_tactic=Evaluation(cp=89),
                        retained_material_gain_cp=300,
                        best_defense_checked=True,
                        scope="depth18_best_reply_not_exhaustive"),
    presentation=TacticalPresentation(PresentationLevel.STRONG_CALLOUT,
                                     "Check and win a knight"),
)
result = HeavyResult("candidate", candidate_payload, details, opportunity=opportunity)
```

The generic heavy repository stores the opportunity in the same transaction as
candidate/coverage. Only candidate results may carry persisted opportunities.
It keeps the canonical `(move_id, tactic_type)` ID, creation/review timestamps,
training links, and unrelated metadata. A malformed or mismatched opportunity
rolls back the transaction. Scope guards and current/protected coverage checks
remain in force; attaching opportunity data does not authorize a rerun or bypass
currentness. No opportunity-only live write/backfill API was introduced.

An ordinary legacy result without an opportunity retains its exact old payload
behavior. If a canonical candidate already has an opportunity, a later result
without one preserves it when analyzer version and canonical proof are unchanged.
A changed version/proof must explicitly supply replacement opportunity evidence;
otherwise the repository refuses to silently erase or misattribute old evidence.
Explicit stale reconciliation can retain historical opportunity evidence on a
rejected candidate; consumers must honor `candidate_status`.

Read without side effects:

```python
from tactical_opportunity_repository import read_candidate_opportunity
view = read_candidate_opportunity(connection, candidate_id)
# Missing candidate: view is None.
# Legacy candidate: view exists; view.opportunity is None.
# Enriched candidate: canonical evidence is hydrated in view.opportunity.proof.
```

The read view also exposes existing solution fields for legacy consumers. It does
not infer a motif/outcome from tactic_type. Invalid structured data and unsupported
schema versions raise explicitly; they are not silently rewritten. Empty/NULL
legacy metadata is accepted. Historical forks, mates, and Pin V1 remain readable.

## Versioning and compatibility

The envelope's `schema_version=1` versions the data contract only. It does not
affect `screener_version`, `scout_version`, `scout_config`, `analyzer_version`, or
coverage currentness. Existing three-positional-argument `HeavyResult` calls are
unchanged. No analyzer produces opportunities automatically, no historical
candidate has been relabeled, and no Pin V1 proof rule has changed.

## Examples and validation

See [TACTICAL_OPPORTUNITY_EXAMPLES.md](TACTICAL_OPPORTUNITY_EXAMPLES.md) and the
machine-readable `reports/tactical_opportunity_examples.json` for candidate 1835,
candidate 1836, a future skewer, and a future delayed pin. These are illustrative
representations, not persisted classifications or newly verified results.

Tests in `tests/test_tactical_opportunities.py` cover model round trips, generic
new-specialist dispatch, unknown legacy values, attribution, timing, presentation,
line metadata, score perspective, canonical deduplication, ID/training/timestamp
preservation, transaction rollback, rerun no-op behavior, and no model I/O or
board mutation. The existing full suite remains the analyzer regression check.
