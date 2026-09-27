# Critical Moment Context V1 contracts

This is an experimental report-only interpretation service. It never changes
analyzer truth, The Scale, candidates, proofs, coverage, caches or training.
No production importance filter, scheduler or new analyzer is activated.

`interpret_context(MomentEvidence, ContextPolicy)` returns immutable
`CriticalMomentContext`: source identity, primary/supporting context, importance,
factual evidence, explanation key, source/provenance, completeness, early-game
flag, actual-played eval swing, final proof evaluation label and policy identity.
Callers must supply verified/complete proof assertions from trusted stored
sources. Reviewer verdicts and note text are not inputs to interpretation.

## Conservative gates

- `tactical_opportunity`: explicitly supplied stored/audit verification. No new
  motif decision is made. A provisional audit context does not replace a
  production candidate's existing status.
- `major_material_blunder`: concrete recorded immediate major-piece capture,
  legal AttackState, captured TargetFate, large net MaterialTransition loss,
  recorded reply window and no legal immediate recapture of the capturer. This
  is an observed loss context; longer compensation/best defense are unassessed.
- `low_importance_tactical_geometry`: verified tactic, complete supplied proof,
  early fullmove, nonnegative minimal retained payoff, and explicit absence of
  a stronger proven outcome. Unknown proof/larger payoff prevents downranking.
- `defensive_resource`: complete proof explicitly supports mate prevention or
  preservation of a playable position. Checks alone do not qualify.
- `forced_simplification`: complete proof explicitly establishes forcedness;
  simply counting queen exchanges is insufficient.
- `drawish_endgame_context`: all supplied final evaluations within the near-equal
  band, low total material and rook/pawn-only structure. Not a theoretical draw.
- `unresolved_complex_position`: default when evidence cannot support a more
  specific interpretation. This does not declare that the game was messy or
  played under time pressure.

Proven mate receives critical importance. A proven terminal draw receives normal
importance, with no winning-position claim. Material payoff and final evaluation
remain separate. Incomplete context's default normal band is not an instruction
to prioritize it in production.

## Experimental configuration

`ContextPolicy` follows shared `Settings` metadata/schema/identity conventions.
Current report defaults: early fullmove <=10; minimal retained payoff 0 cp;
major observed loss >=300 cp; high retained payoff >=500 cp; near-equal band
+/-100 cp; evaluation winning threshold 300 cp; low total material <=2600 cp;
actual-capture observation window 3 plies. Queen loss with at least 500 cp net
loss is critical. These named, configurable defaults are examples for testing,
not thresholds inferred from the 27 reviews or written to global profiles.
Their identity affects context interpretation only, never raw engine searches.

## Evaluation evidence

A score has one cp value or an explicit player-relative mate result, plus FEN,
request identity and provenance. Missing evidence is `None`, never zero cp.
Comparable before/after scores expose player delta, sign crossing,
winning-to-nonwinning, losing-to-recoverable and mate appeared/disappeared.
Mate scores are never converted into invented centipawn numbers.

The report reads existing `engine_position_cache` entries at exact FENs, using
matching stored identities for `tactic_verify_v1`. It found five compatible
before/after pairs; other rows remain unknown for this source/profile. It does
not substitute arbitrary multi-line cache rows or mix depths/profiles. Request
options not present in the historical schema are not reconstructed. Saved
branch-final player evaluations are separately reported with their audit
provenance and ranges; they are not mistaken for actual-game eval swings.

## Reproducibility and safety

The report adapter reads `reports/critical_moment_review_snapshot.jsonl`, an exact
local snapshot of the 27 reviews, and preserves every note verbatim in JSON and
Markdown. It replays existing proof strings using StoredLine/LegalReplay and
checks material totals. No fresh evidence is generated. The source review log
is never rewritten. Run `python reports/build_critical_moment_context_report.py`
to rebuild the structured validation from the frozen inputs and read-only DB.
The Markdown report also contains human commentary on unsupported concepts;
it is not a rule input.

Portable core depends on shared settings/toolkit only. SQLite access is in a
separate read-only repository; UI changes are limited to human-readable audit
labels. Future aggregation, opening ownership, tempo, time pressure, positional
initiative, a full blunder taxonomy, custom game sets, Extend Merlin Line and
ghost pieces require separate tasks.
