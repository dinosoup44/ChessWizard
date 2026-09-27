# Quality Gate V1

`approve_lines(CandidateLineSet, QualityGateSettings, ...)` returns one decision
per input root move and an `ApprovedCandidateLineSet`. It performs no engine calls,
database work, motif detection or interest scoring.

Scores are compared from the player-to-move's perspective, even though cached
scores use White's perspective. Engine rank is preserved for audit; score ordering
selects the best realistic result. Ties preserve engine rank.

## Normal acceptance

For cp alternatives, any configured rule can pass:

- Absolute loss from best is at most 75 cp by default.
- Loss is at most 20% of a **positive** best advantage. This cannot replace the
  absolute tolerance near zero and is not applied to the magnitude of a losing score.
- Alternative remains at least +500 cp, even if far below best.
- Optional acceptable floor, disabled by default.

Thus +800/+550 can both pass; -200/-220 can both pass; +20/-180 fails the weak
alternative. A negative evaluation does not by itself fail the gate.

Winning mates are compared by ownership and distance, with up to three extra moves
allowed by default. Giving up a known mate for cp is rejected unless explicitly
enabled with the winning cp floor. A losing mate cannot pass as a cp alternative.
When every line loses by mate, critical retention keeps the longest resistance;
normal losing-mate acceptance is an explicit optional policy. Mate zero retains
its owner and never enters cp math.

## Best retention and forced deterioration

The best line always remains available when complete usable evidence exists.
This is separate from **normal acceptance**.

An optional `maximum_deterioration_cp` compares every line to an explicitly supplied
reference score. If the reference is 0, the allowed loss is 50 cp, and every line
is -200 or worse, all normal decisions fail. The gate retains the configured top
least-bad lines (two by default), sets `forced_deterioration=true`, and reports the
failed normal reasons. It does not discard the position or call it zugzwang.

If at least one line passes normal policy, only normally approved lines are retained.
If none pass, the configured critical fallback applies. The best line is preserved
in either case. This resolves the otherwise contradictory requirements that the
best always remain available and that an all-normal-fail state be representable.

This flag describes a configured critical-position observation, not a claim that
all legal chess moves were exhaustively proven losing. MultiPV samples only the
requested root alternatives. The reference can also be incomplete or incomparable.

## Evidence failures are separate

Missing/partial line sets, incompatible engine identity, insufficient depth, or a
missing cp reference for the configured deterioration policy return `incomplete`.
They do not fabricate critical fallback or reject chess moves as unsound. Terminal
positions return `terminal` and no lines. Bound engine scores are rejected by the
generator rather than treated as exact evidence.

Each `QualityDecision` exposes normal acceptance, retained status, reason and cp
distance when meaningful. `ApprovedCandidateLineSet` validates membership and
retention invariants. Its currentness identity includes evidence, policy settings
and reference evaluation. Callers must preserve that identity with downstream work.

The Scale consumes this result and cannot add a rejected move. A heavy
specialist must still prove its tactic: passing the gate is objective admission
to analysis, not proof of a motif or an already settled continuation.

## First specialist adoption

Fork V3's opt-in verifier consumes this exact contract: **a retained line has
satisfied the active gate or is explicitly marked as a critical least-bad
fallback**. It has no parallel absolute/relative/winning-floor acceptance rule.
Fork-specific target accounting and material proof remain separate obligations.
Critical or incomplete evidence cannot become high-confidence consensus.

For a fixed stored move absent from top-N, shared required-move admission requests
that move explicitly and reuses this gate on a unique-move comparison set. The
generator profile is unchanged, and missing top-N membership is not rejection.
Child replies are gated from their own side-to-move perspective. Approval at the
root neither guarantees child settlement nor licenses optimistic payoff wording.

## Proof escalation boundary

[Targeted escalation](PROOF_ESCALATION.md) does not rescue a failed root admission.
It consumes explicitly approved branch entries and gates stronger child evidence
through the same policy. The initial policy preserves Normal admission and does
not enable boundary re-admission. Missing evidence and critical/mate ownership
remain protected. Depth evidence may settle counterplay; it cannot replace the
objective gate with a tactic-specific optimistic threshold.

## Backbone handoff contract

The [backbone](ANALYSIS_BACKBONE.md) delegates acceptance here. Every downstream
approved line either passed normal acceptance or is explicitly retained as forced
deterioration. Missing evidence remains incomplete. A selected observed move can
be gate-rejected; a complete set retains its best realistic line. Negative CP
positions need no positive floor, and mate remains separate from CP arithmetic.

`QualityDecision` and `ApprovedCandidateLineSet` already form the public gate
result; no redundant renamed result model is needed. Specialists may reject motif
or payoff, but may not maintain a hidden parallel objective gate.

## Pin adoption and recorded equivalence

Pin uses the same gate for Normal root admission (including a required-move
supplement) and approved reply evidence. Its original 120/150 cp improvements over
the played move and 300/200 cp loss limits remain separate PinPolicy settings;
these are not equivalent to absolute/relative objective line-admission math.

Recorded one-PV replay gates a legally normalized line set in its original source
namespace. Unknown legacy engine options remain explicit; this is not a new-cache
hit or a substitute for missing exact multi-line evidence. Normal proposals can
differ from recorded V2 results and require separate review before live adoption.
No gate rejection in this validation writes coverage or reconciles a candidate.
