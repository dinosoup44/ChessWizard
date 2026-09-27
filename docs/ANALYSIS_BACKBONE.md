# Multi-line analysis backbone V1

`AnalysisBackbone` is the candidate-scoped composition contract. It reuses the
existing line, gate, proof and Scale services; it is not a crawler, motif detector,
engine launcher, persistence repository or automatic proof scheduler.

```text
Games / selected FEN
  -> CandidateLineService / exact engine cache
  -> CandidateLineSet
  -> Quality Gate -> ApprovedCandidateLineSet
  -> specialist selects relevant approved branches
  -> shared bounded proof / selective Proof Escalation
  -> continuation and settlement evidence
  -> The Scale (human interest only)
  -> specialist interpretation / CandidateVerificationResult
  -> TacticalOpportunity -> Feedback Generator
  -> Game Review / Training / future frontends
```

Interpretation and Scale may consume the same proof evidence independently. Their
order must not let an interest score determine motif truth. Fork preserves its
existing response-Scale evaluation order and computes root interest after proof;
all weighted inputs have already passed the gate. No Game Review behavior changes.

The Pattern Engine is a sibling consumer of shared board/history facts, not a
prerequisite or private implementation dependency of analyzers. The Admin Console
will be a configuration/diagnostics frontend. Mobile will be another frontend
using the same chess core; there is no Tkinter in this backbone.

## One reusable workflow

```python
backbone = AnalysisBackbone(line_service, profile,
                            verification_service=verification_service)
admission = backbone.admit(fen, required_move_uci)  # existing-move verification
# Or: approved = backbone.request(fen)             # ordinary breadth
approved = admission.approved

# Specialist checks admission and geometry, then lazily selects relevant branches.
for branch_key, result in backbone.escalation.escalate_selected(
        selected_requests(), piece_values):
    interpret_branch(branch_key, result)  # motif-specific, no SQL or engine process

weighted = backbone.weigh(approved, compatible_continuation_evidence)
provenance = backbone.provenance(analyzer_id, analyzer_version,
                                interpretation_policy=versioned_policy)
```

Construction performs no I/O. Each explicit request uses the existing shared
service/cache; storage permissions belong to its injected repositories. One
backbone instance owns one candidate's verification budget. Never reset that
budget by constructing a new service per branch. `request` returns incomplete
approval as data; the older `evidence` callback adapter may raise
`IncompleteLineEvidence` for legacy proof callbacks.

`admit` preserves native versus supplemented rank. A required move missing from
MultiPV gets the existing exact restricted request and shared comparison gate;
missing from top-N does not mean rejected. Restrictions never collide with an
unrestricted raw request.

The specialist owns geometry, branch relevance/order, what payoff proves its
motif, target consensus, causality/attribution and ownership. It submits a lazy
sequence of `(branch_key, ProofEscalationRequest)` pairs. The shared service owns
dispatch, exact requests and limits. Laziness lets the specialist stop selecting
after consensus without pre-scheduling every branch. There is no generic
Fork/Pin/X-ray branch inside the backbone.

`LineAnalysisService` remains a compatible lightweight generation/gate/Scale
wrapper and now delegates those stages to the same backbone. Its stable public
result and previous currentness semantics are retained.

## Public contracts and distinctions

| Contract | Responsibility |
| --- | --- |
| `CandidateLineSet` / `CandidateLine` / `LineScore` | Immutable exact raw request evidence, unique roots, legal PVs, explicit POV/mate ownership |
| `QualityDecision` | Objective decision for one observed move |
| `ApprovedCandidateLineSet` | Gate result: retained lines plus every decision; no new redundant `QualityGateResult` type |
| `RequiredMoveAdmission` | Native/supplemented rank and required move's gate result |
| `ProofEscalationRequest` / `ProofEscalationResult` | Exact approved branch and bounded deeper-evidence disposition |
| `BoundedProof` / `ProofStep` | Solver output and per-ply material/capture ledger |
| `SettlementEvidence` | Validated replay of a bounded proof, final evaluation, profile/request provenance and observed material change |
| `ContinuationEvidence` | Optional evidence attached to the exact line identity used by Scale; not an arbitrary proof-to-PV coercion |
| `ContinuationQuality` | Cheap facts from a legal raw PV; settlement/end evaluation stay unknown unless compatible evidence is supplied |
| `WeightedCandidateLines` / `WeightedCandidateLine` | Scale result, visible components, unknown components and provenance; no redundant `ScaleResult` rename |
| `CandidateVerificationResult` | Analyzer proposal: explicit ambiguity separate from operational error |
| `TacticalOpportunity` | Generic outcome, motifs/attribution, proof, timing and presentation |
| `FeedbackResult` | Frontend-neutral wording built by Feedback Generator |

`settlement_evidence(...)` accepts a `BoundedProof`, not a raw root line. It checks
legal moves, SAN, FEN/actor continuity, captures including en passant, and material
snapshots. It identifies the exact branch/profile/requests, reports scalar
player-POV endpoint evaluation and retains mate ownership separately. Terminal
proofs do not relabel a preceding evaluation as a fresh endpoint score.

Observed material change is not motif-retained value or sacrifice causality.
Fork's target/exchange accounting remains in its specialist. Cross-branch ranges
and consensus remain aggregate interpretation (`ForkRobustness` for Fork), not
invented scalar settlement facts. A settlement proof may differ from the original
root PV, so there is no automatic conversion to `ContinuationEvidence`; evidence
must match that class's exact line/PV identity.

## State semantics

`EvidenceState` is a shared vocabulary, not a database enum or coverage migration.

| Shared state | Meaning |
| --- | --- |
| `approved` | Normal objective acceptance; still no motif proof |
| `rejected_by_quality_gate` | Selected observed move failed admission |
| `forced_deterioration` | Explicit least-bad retained fallback, visibly critical |
| `incomplete` | Missing/incompatible/partial evidence; cannot reject a tactic |
| `proof_required` | Specialist explicitly identifies proof still needed |
| `proof_stable` | Bounded settlement completed; motif interpretation remains separate |
| `proof_unsettled` | Unfinished proof or exhausted budget; protect uncertainty |
| `proof_deferred` | Mate/terminal/ownership evidence needing appropriate handling |
| `execution_error` | Operational failure, not chess ambiguity |

`approval_state`, `proof_state`, `escalation_state` normalize existing contracts.
A missing move decision means incomplete; use `admit` to obtain a required-move
comparison. A whole complete set always retains its best realistic line, so gate
rejection belongs to a particular move. `not_needed` escalation returns no new
normalized state (`None`): preserve the caller's existing state rather than claim
that settled or rejected work now needs proof.

Analyzer classifications are `verified`, `verified_payoff_changed`, `rejected`,
`ambiguous` (protected) and `error`. `CandidateVerificationResult.classification`
exposes that vocabulary and validates it against its compatible transport state
(`candidate`, `analyzed_no_hit`, `ambiguous`, `error`).

Some older single-line/multiline HeavyResult callers still encode chess ambiguity
as `error` plus `details.classification == ambiguous`. `verification_result(...)`
is an explicit opt-in normalization boundary. Do not silently change heavy
coverage persistence. Fork V3.1 already returns explicit ambiguity; an execution
failure remains error through candidate orchestration. A future legacy migration
should normalize at its candidate-verification boundary, then separately review
persistence compatibility with tests and authorization.

## Breadth, verification and Scale

Breadth defaults remain Normal: 3 lines, depth 12. The opt-in verification profile
uses 1 line, depth 18, four user payoff moves and eight additional settlement plies.
Limits remain three branches, two approved entry plies and 24 distinct requests
per candidate. Exact hits consume the same distinct-request budget as misses.
No recursive fan-out or escalation of every branch is implied.

The shared profile binds verification generator, branch/request limits and proof
window to the candidate session. Individual requests cannot silently change that
profile or reset the budget. To request another verification profile, configure
`profile.escalation` before constructing the candidate's backbone. This is the same
settings path used by presets and a future Admin Console.

A branch may request stronger evidence for unsettled proof/material, unresolved
countercaptures, incomplete evidence or payoff disagreement. Settled consensus,
stable no-hit, failed admission and high interest do not trigger escalation.
See [PROOF_ESCALATION.md](PROOF_ESCALATION.md) for exact predicates and bounded-PV
settlement semantics. There is no root-boundary re-admission policy enabled.

Escalation returns `complete`, `unresolved`, `deferred`, `budget_exhausted`,
`incomplete`, `not_needed` or `error`. Runtime failures now return structured error
results from the escalation service. Fork explicitly propagates that operational
failure to candidate orchestration; it never changes it to an ambiguous branch.
Invalid selection/request construction remains a caller contract error.

Only `ApprovedCandidateLineSet` can enter Scale. Each retained line either passed
the configured objective gate or is an explicit forced-deterioration fallback.
Mate is never converted to CP for tolerance math. Losing CP positions keep the
best realistic line without requiring a positive-score floor; losing-mate policy
and least-bad count are explicit settings.

`WeightedCandidateLine.interest_weight`, `.components` and `.unknown_components`
expose the final interest score and its known/unknown inputs.
`WeightedCandidateLines.evidence_provenance` exposes FEN, raw request, approval
and Scale identities. This score is neither tactic confidence nor an engine
score. Versioned event providers are explicit code dependencies, never dynamic
plugins loaded from community data.

## Settings and currentness

Quick/Normal/Deep and opt-in verification presets use `AnalysisProfile` and the
same loader/schema. `SettingDefinition.to_schema()` returns JSON-compatible
metadata with ID, label, type, current preset default, min/max/options,
description, basic/advanced level, `affects_raw_cache_identity` and
`affects_result_currentness`. Older flag names remain available for compatibility.
No parallel UI configuration or new chess thresholds were introduced.

| Settings family | Representative controls | Raw request identity? |
| --- | --- | --- |
| `generator` | MultiPV count, engine request-family/profile, depth/nodes/time, Threads/Hash, version | Yes |
| `quality_gate` | Absolute/relative tolerance, winning floor, losing-mate policy, deterioration reference policy, fallback count | No |
| `escalation.verification` | Verification profile, count, engine budgets/options | Yes, for verification requests |
| `proof`, `escalation.proof` | Payoff window, settlement extension, quiet plies | No |
| `escalation` limits/policies | Branches, child levels, distinct requests, protected ambiguity | No |
| `scale` | Component/event weights, complexity, quiet and acceptability-loss penalties | No |

The exact raw key remains `(FEN, engine_identity)` from generator settings and
normalized restrictions. Changed depth/count/restriction/engine settings cannot
reuse incompatible evidence. The existing insert-once repository retains IDs and
timestamps; this task adds no schema, cleanup or cache writes.

`AnalysisProvenance` extends proposal currentness with analyzer ID/version,
explicit interpretation/attribution policy, approval evidence and Scale evidence.
External continuation facts and provider outputs therefore affect result
currentness. Gate/Scale/proof policies recompute interpretation using compatible
raw evidence without new searches. Existing profile/raw identities stay intact;
Fork adds `backbone_provenance` rather than rewriting its historical evidence.

## Cache diagnostics and future maintenance

`CandidateLineDiagnosticsService(connection).inspect()` returns the typed
`CandidateLineCacheDiagnostics`. It reports table existence, row count, UTF-8
payload bytes, groups by profile/engine identity, timestamp bounds, duplicate keys,
impossible payload-envelope states and health issues. Allocation/free bytes come
from SQLite page counts and describe the whole database, not just this cache.

Basic inspection scans JSON envelopes; it does not replay each PV.
`inspect(validate_payloads=True)` additionally invokes the existing repository's
full legal/model decoder for every row. The result labels which checks ran.
`checks_passed` is scoped to these checks, not a replacement for quick_check or
foreign_key_check. Missing schema returns `not_installed`; incompatible schema,
bad payloads and duplicates are visible issues. The caller owns any read snapshot.

The service performs reads only and never changes schema, starts an engine,
renews timestamps, deletes, evicts or vacuums. Cleanup is a future separately
approved maintenance feature with explicit retention, backup and consumer/version
rules. Removing rows and reclaiming SQLite space are different operations. Neither
belongs inside an analyzer. The Admin Console can consume this service later.

## Fork reference and validation

`analyze_forks_v31.py` constructs the backbone and delegates Normal evidence,
required-move admission, Scale, provenance and escalation services to it.
`_selected_requests` retains Fork's existing unresolved-first order and consensus
stop predicate. `review_counterplay` interprets results through the existing
Fork target/recapture accounting; the backbone knows no motifs.

The legacy-compatible optional backbone parameter in the multiline verifier keeps
its existing direct entry point. Default discovery and all other analyzers remain
unchanged. Candidate selection still comes from `existing_candidates`, not a move
crawl. TacticalOpportunity and proposed feedback continue through the existing
shared models/generator; no UI behavior or persistence path changed.

Validation replays all 458 saved results using read-only SQLite and an engine
fallback object that raises if called. It compares every prior detail (apart from
new provenance), candidate payload and TacticalOpportunity, repeats representative
provenance, scans cache health and checks a byte-identical database. The
[Fork reference implementation summary](MISSED_FORK_V3.md#backbone-reference-implementation)
records the equivalence result; detailed local replay receipts remain private.

Pin is now the second read-only adopter; live dispatch remains unchanged. See
[the Pin checkpoint](PIN_BACKBONE_MIGRATION.md).

## Pin as the second opt-in consumer

`pin_backbone` and `pin_backbone_verifier()` demonstrate candidate-only adoption
without changing live dispatch. `approve_recorded` admits normalized historical
evidence in an explicit source namespace; it does not bless it as compatible with
new raw cache requests. Pin uses this for exact recorded-result equivalence.

The optional escalation solver composes the shared per-ply bounded proof with
validated approved entry moves. Fork keeps the original endpoint-PV solver.
Consumers include their proof-mode contract in interpretation provenance. Neither
mode moves motif logic into the backbone. Pin-specific thresholds/attribution
remain separate from the shared gate. See [the Pin checkpoint](PIN_BACKBONE_MIGRATION.md).

## Explicit discovery consumer

The second Fork cohort exercises the same backbone from new-move discovery.
`analysis_discovery` composes a saved scope, an opt-in registry definition, the
existing central planner, scout service, shared breadth/verification services and
ID-preserving repositories. The crawler contains no Fork geometry or proof branch.
Specialists return structured results and own no SQL or engine processes. Default
live analyzer registrations remain unchanged unless a saved experiment opts in.

A single-position calculation does not require a persisted candidate identity.
The existing-candidate wrappers remain strict; new discovery passes an explicit
unplayed move through a shared calculation entry point. Normal three-line evidence,
Quality Gate, bounded targeted escalation and Scale settings are unchanged. Full
branch evidence distinguishes ambiguity from rejection; a storage compatibility
mapping must not turn uncertainty into completed negative proof.

New experiment artifacts record exact settings/source hashes, coverage-aware
cohort provenance, cache references and before/after safety. Fixed-root top-branch
counterfactuals use already-recorded evidence; they neither generate a parallel
candidate set nor prove what a separately configured single-line engine would do.
The original cohort's V3.1 data covers an existing-candidate subset, so it cannot
supply an unbiased full-discovery rate comparison. See
[the second-cohort validation summary](#second-cohort-validation-result--2026-09-08).


## Second-cohort validation result — 2026-09-08

The frozen `normal_escalation` experiment completed on the exact independent
500-game scope: 15,170 user moves, 30,310 plies, zero first-cohort overlap.
The 69 existing Fork candidate/rejected rows were protected. Of the remaining
moves, 7,978 were statically rejected, 4,704 scout-rejected, and 2,419 reached
V3.1. Results: 2 new candidates (1848 and 1849), 2,051 completed no-hits, and
366 retryable ambiguous moves; zero operational errors.

Across 6,952 proposed Fork moves, Quality Gate retained 718 (714 normal and
4 forced-deterioration retentions) and rejected 6,234. Retained native ranks:
289 first, 125 second, 64 third, and 240 explicit comparisons outside top 3.
Both verified proposals were rank 1: one `verified`, one
`verified_payoff_changed`. Proposal totals also include 6,506 rejected and
444 ambiguous. Of those ambiguous proposals, 441 had incomplete/unsettled
proof and only 3 had settled payoff disagreement.

Escalation touched 439 proposals and resolved 163: 162 rejections and one
verified changed-payoff result. It used 2,409 searches (5.487 per escalated
proposal on average; maximum 14). The fixed-root first-Normal-branch diagnostic
agreed in 196 cases and exposed uncertainty in 116; 6,640 had insufficient
comparison evidence, including root-gate rejections. This is not a separate
MultiPV=1 experiment.

Total searches: 55,731 (scout 13,801; breadth 39,521; verification 2,409).
First pass took 99.29 minutes; run/rerun/safety took 102.38 minutes. Database
growth was 227,282,944 bytes, including 54,888,960 additional candidate-line
payload bytes. Complete raw request sets use cache references; approved-line
snapshots still retain some PV content in the audit, so audit/coverage storage
is larger than raw-cache payload growth. No post-run evidence compaction or
policy change was performed.

The exact rerun skipped completed rows and replayed 366 unresolved moves with
zero searches, zero writes, zero timestamp/ID churn, and byte-identical DB.
All 942 old candidates, training (11 attempts), other-tactic/out-of-scope data,
and old cache rows were unchanged. New counts: 944 candidates, 50,083 coverage,
252,400 position-cache rows, 65,349 candidate-line-cache rows. Integrity checks
passed. Read-back legally validated all 107,016 PVs in 41,960 new cache sets,
plus both candidate proofs and material ledgers. Full suite: 360 tests passed.

The original cohort has only a 73-existing-candidate V3.1 review, not a matched
V3.1 new-discovery experiment. Its 6 changed-payoff hits and 52 ambiguities cannot
be treated as comparable discovery rates. A small approved matched review and
an audit separating unsettled proof from the three settled disagreements are
better next experiments than a third broad cohort or immediate threshold tuning.
Default Fork routing and live Pin activation remain unchanged. This section
summarizes the historical validation; exact game IDs, per-position evidence and
machine-readable audit receipts remain private. See the
[public source boundaries](PUBLIC_SOURCE.md) for what is distributed.


## Read-only proof audit boundary (2026-09-08)

The Fork proof audit reused the frozen shared backbone through explicit single-
position calls, with production SQLite opened `mode=ro` plus `query_only=ON`.
Baseline and matched legacy reviews forbade engine fallback. Each independent
experimental dimension read the live cache first and wrote only its own scratch
cache. Exact baselines, matched pairs, isolated profiles, costs and supplemental
sample selection are saved under `reports/fork_proof_completeness_*`.

All 41 baselines matched exactly. The twenty matched pairs showed 80% versus 75%
ambiguity (first versus second cohort), with admission 85% versus 90%. This reduces
one discovery-versus-existing-candidate selection mismatch without establishing
statistical significance. No candidate or result-currentness state was changed.

The audit also found an accounting caveat: a bounded-score rejection occurs after
the engine call but before CandidateLineService increments `engine_searches`.
Its one depth-22 occurrence was explicitly added to the audit's actual-call total:
343 calls including controls/supplement, 342 stored scratch rows. Future engine
accounting should distinguish requests attempted, normalized evidence, and failed
normalization; no shared-service change was made here.

Production DB bytes/hashes, candidates, coverage, training and live caches remained
unchanged. Full tests: 363 passed. The
[Fork proof-completeness summary](MISSED_FORK_V3.md#read-only-proof-completeness-audit-2026-09-08)
records the tested dimensions, costs and conservative recommendation.

## Retained proof and factual endpoint boundary (2026-09-08)

Shared proof/attempt models are in `proof_evidence_state.py`. `TerminalFacts`
reports board-rule outcomes separately from analyzer ownership; terminal evidence
is complete. `ApprovedPositionEvidence.best()` raises the distinct
`TerminalPositionEvidence` for a complete terminal position instead of calling it
incomplete evidence. Consumers should inspect terminal facts before requesting a
best continuation. Fork handles played/candidate terminal outcomes before engine
admission and never claims Mate ownership.

`proof_endpoint_facts.collect_endpoint_facts()` is a pure legal-replay collector:
material transitions, captures, original piece identities, attacker survival,
attack state, legal relevant capture options, recent material and terminal facts.
It does not choose a move, search, persist, admit a motif or declare settlement.
The audit composes it with the existing target-accounting service; geometric
capture credit, conservative related accounting and a net-material residual are
explicitly different quantities. An arithmetic residual is not a proven causal
partition. Endpoint scores must belong to the exact endpoint, not an earlier PV
position. Terminal endpoints do not inherit stale nonterminal evaluations.

Planned boundary:

`raw line → factual endpoint evidence → future semantic settlement → analyzer interpretation`

The 438 endpoint records are sufficient to begin factual Position/Range Evidence
Toolkit V1 contracts. They do not authorize replacing quiet-ply settlement with
material stability or target disappearance. No toolkit-wide settlement decision
or analyzer activation was added. Core helpers remain independent of Tkinter,
SQLite, engine lifecycle and frontend navigation.

Validation: 40 pure-window proposals, five stable controls, 11 resolved no-hits,
82 scratch searches, zero live DB changes, identical cache-only reruns. Default
settings/registration remain unchanged. See the
[proof lifetime and settlement summary](PROOF_ESCALATION.md#proof-lifetime-and-attempt-disposition-2026-09-08-cleanup).

## Selective continuation extension boundary

The backbone still composes shared services; the crawler has no Fork-specific
extension logic. Fork supplies semantic blockers to the generic typed
`SettlementExtensionEligibility` contract. The shared escalation service resumes
a `SettlementContinuation` only after normal 8-ply verification reaches its exact
window boundary. It reuses the root admission, approved obligations, payoff clock
and candidate-scoped branch/request budgets. Other specialists do not call this
extension API, and the shared setting defaults to disabled.

`ProofEscalationService.evidence_approvals()` exposes both normal and extended
approvals for complete backbone provenance. The pure solver knows only chess
continuation state; cache lookup, policy eligibility and tactic interpretation
remain separate modules. No UI or database imports are needed by these core APIs.

The selective path has distinct 8/12 request namespaces plus distinct proof
identities. `SettlementCacheAdapter` can reuse exact compatible legacy evidence as
a provenance-preserving in-memory alias; it never relabels or writes stored rows.
`CandidateLineService.cached_candidate_lines()` is the shared read-only cache
probe and cannot generate evidence on a miss. Breadth identity is unaffected.

The feature is production-ready for an explicitly selected future Fork profile,
but remains disabled pending approval. No historical candidate reconciliation,
coverage update, live cache write or other analyzer migration occurred. Eligibility,
settings and measured replay results are summarized in the
[selective settlement contract](PROOF_ESCALATION.md#selective-settlement-policy-implemented-not-activated).

## Factual position/range layer

The standalone `position_range_evidence` toolkit can supply identity-aware material,
fate, legal-capture, attack, and terminal facts to future backbone consumers. It
reuses `board_analysis` and shared material settings, with no dependency on engine
evidence, Quality Gate, Proof Escalation, or The Scale. It does not reinterpret
`SettlementEvidence` or produce semantic proof/settlement verdicts.

A terminal board fact is distinct from an engine mate prediction. A claimable draw
is distinct from an automatic endpoint. A geometric defender is distinct from a
king-safe recapture. Consumers must preserve these distinctions when combining
facts with multi-line engine evidence. No current analyzer path changes here.
See [Position / Range Evidence](POSITION_RANGE_EVIDENCE.md) for contracts and tests.
