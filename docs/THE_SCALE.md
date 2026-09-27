# The Scale V1

`TheScale.weigh(ApprovedCandidateLineSet)` ranks already-retained lines for human
interest. It does not decide whether a move is sound, classify motifs, change the
Quality Gate verdict, start an engine, or write candidates.

`WeightedCandidateLines` retains the approval result. Each weighted line exposes
its engine rank, `interest_weight`, component values/weights/contributions, cheap
continuation facts and semantic events. Sorting is deterministic: weight descending,
then original rank and UCI. All inputs are immutable domain objects.

## Components and evidence

The initial components include objective strength, distance from best, retained
advantage, observed material gain, forcingness, evaluation trend, settlement,
material-investment interest, mate interest, defensive narrowness, motif relevance,
rarity and a forcing-line-length proxy. Unknown values remain `None`, with zero
contribution; they are not manufactured as proof. Weights, normalizers, material
values and penalties live in `ScaleSettings` and its typed children.

The final weight is the configured baseline plus visible contributions and penalties,
clamped to 0–100. It is an initial configurable ranking, not a calibrated probability.
Negative evaluation trend and long quiet lines lower interest. A lower engine rank
can outrank the best move for interest after passing the Quality Gate.

`inspect_continuation` uses shared `board_analysis` primitives to replay the legal
PV, count material and measure checks/captures/promotions. It never reruns a motif
analyzer. Observable events include underpromotion, signed mate evidence, and a
queen/rook/minor **material investment** in the supplied PV. Directly recovered
equal exchanges do not count as investments.

An investment is not automatically a verified sacrifice. The event states what was
observed and does not infer intent, causality, forcedness or sacrifice confidence.
Likewise, endpoint material in a root PV does not prove that exchanges have settled.

## Continuation quality

`ContinuationQuality` carries evaluation start/peak/end/trend, material start/end/
gain/low, forcing density, continuation length, mate pressure, payoff/settlement,
defensive narrowing and continued acceptability.

Ordinary MultiPV provides a root evaluation and a PV, not fresh evaluations at each
ply. Therefore evaluation end/trend, settlement and defensive narrowing remain
unknown unless a caller supplies `ContinuationEvidence`. Evidence must match the
exact line identity and engine request, include a source, and use ordered compatible
evaluation samples. A sample before the PV endpoint does not become an invented
endpoint evaluation/trend. Material and forcing facts can be recomputed cheaply.

The number of returned/approved MultiPV lines does not prove only-move defense.
An explicit defense classifier must provide that evidence. The Scale never inserts
Fork/Pin/Skewer/X-ray geometry rules to make its score more interesting.

## Event extension contract

A future trusted classifier can provide an object with:

```python
provider_id: str
version: str
events(line: CandidateLine, facts: ContinuationQuality) -> tuple[SemanticEvent, ...]
```

`SemanticEvent` has an ID, component, bounded strength, source and concise evidence.
Providers run only for retained lines. They cannot introduce a new root move;
their identities and emitted evidence participate in composed result currentness.
Events affecting the same component use the maximum strength, avoiding duplicate
credit. Contributed events may affect sacrifice interest, motif relevance, rarity
or defensive narrowness; they cannot override objective engine/proof components.
Provider code is explicitly injected by application code, never dynamically
loaded from a theme/config/community pack.

A future verified queen-sacrifice event can give an already-acceptable line high
interest. A rejected sacrifice never reaches a provider or The Scale. V1's curated
real mate position demonstrates a longer mating queen investment outranking the
immediate mate for interest; engine rank and mate distance remain visible.

## Interest is not confidence

- Engine score: estimated objective chess result.
- Quality Gate: objective admission decision under a named policy.
- Interest weight: how useful this continuation may be to inspect.
- Tactic confidence: certainty of a specialist's motif classification.

A high-interest line with no identified tactic is valid. A high-confidence fork
may have low interest. No conversion between these quantities is implemented.
Feedback/Game Review/Training adoption remains a separate task; existing behavior
is unchanged.

Fork V3's opt-in preview records root and child-response Scale components after
their Quality Gate decisions. Branch consensus is independent of interest
weights; all approved first replies/responses enter proof, even if another has
higher interest. A high weight cannot settle an unfinished exchange, discard a
disagreeing defense or turn a rejected root move into a fork. These weights are
read-only diagnostic evidence. Proposed feedback uses conservative proof facts;
the desktop Game Review is unchanged.

## Escalation remains proof-driven

[Proof escalation](PROOF_ESCALATION.md) accepts explicit unresolved/disagreement
reasons, not interest weights. Fork V3.1 records Scale results for approved Normal
root/response alternatives, but does not use them to select an optimistic branch,
resurrect rejected Qxb7, trigger deeper searches or settle disagreement. Changing
Scale weights changes interpretation currentness while retaining compatible raw
engine evidence. No Admin Console or Game Review change is part of this adoption.

## Public backbone boundary

The [backbone](ANALYSIS_BACKBONE.md) calls Scale only with `ApprovedCandidateLineSet`.
`WeightedCandidateLine.unknown_components` explicitly lists unmeasured components;
`WeightedCandidateLines.evidence_provenance` identifies FEN, raw request, approval
and Scale policy. Existing public type names and numerical weights remain stable.

Interest, objective score and tactic confidence are separate concepts. The
backbone's result-currentness includes supplied continuation facts and actual
Scale evidence/provider outputs, while raw cache identity remains generator-only.
A raw PV is not settled proof; use exact compatible `ContinuationEvidence` and
keep distinct normalized `SettlementEvidence` for bounded proof records.

## Pin consumer

Pin records interest weights only after shared gate admission. Candidate truth
comes from bounded settlement and Pin attribution across accepted continuations.
Scale cannot rescue rejected/ambiguous geometry or choose the best-looking payoff.
Changed-payoff consensus chooses the smallest verified related payoff and generic
material wording, independent of interest weights. Root-PV interest does not
pretend to contain normalized branch settlement: those evidence objects remain
separate and unknown Scale components stay unknown.

Pin proof-mode and threshold identity affects result currentness; Scale settings
also affect result currentness without changing the underlying raw request key.
See [the Pin checkpoint](PIN_BACKBONE_MIGRATION.md) for the cache-only and curated
validation and frontend-independent settings contract.
