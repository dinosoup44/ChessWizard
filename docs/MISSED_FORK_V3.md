# Fork V3: targeted existing-candidate verification

Fork V3 verifies the **stored fork move of an existing active Fork V2 candidate**.
It never discovers new fork moves or scans positions without fork candidates.
The normal crawler remains on Fork V2; its screener/scout behavior and versions
are unchanged. V3 is explicitly registered in `CANDIDATE_VERIFIERS`, not enabled
as a historical discovery run. V2 candidate/coverage rows remain protected until
a separately authorized reconciliation.

## Layers

```text
existing_candidates (candidate-ID selection)
 -> candidate_verification registry/orchestrator
 -> analyze_forks_v3 calculator (fixed stored move)
 -> shared position/cache service
 -> shared bounded proof + target settlement
 -> HeavyResult + TacticalOpportunity
 -> preview report OR separately authorized reconciliation repository
```

The calculator receives a record and `analyze_fen(fen, profile)` callback. It
does not own an engine, database connection, crawl or persistence operation.
`tactical_target_proof.py` tracks moving participant identities and exchange costs;
other specialists may reuse it without importing Fork code.

## Geometry, realizable targets and payoff

- `geometric_targets`: enemy non-pawn pieces/king geometrically attacked by the
  stored fork piece immediately after the stored move. Defender squares are
  geometric observations, not proof that a defender can legally recapture.
- `captured_geometric_targets`: tracked targets captured by the original attacker
  within the proof's payoff window, including captures whose value later vanishes.
- `realizable_targets`: those captures when the complete move sequence retains
  positive accounted material and passes the final evaluation rule. This describes the
  observed bounded best-defense continuation, not every alternative branch.
- `realized_payoff`: initial material, material after the fork, after the tactical
  sequence, settled material, net change and a conservative fork-attributable value.

An uncaptured target is **not verified realizable in this line**, not proven
impossible to win by every alternative. King/check geometry can help compel a
reply but a king is never credited as captured material. A captured target is not
automatically a clean piece win: exchanges and counter-captures must be charged.

Original target and attacker identities follow their moves, including castling
rooks. Only the original attacker's target captures receive fork credit. Every
own loss is charged through settlement. Capturing an unrelated piece does not
finance fork attribution, except recovering the exchange cost specifically tied
to that counter-capturer. A target that counter-captures cannot be credited twice.
Initial material captured by the fork move is reported separately. If a verified
target exchange retains that initial capture but produces no additional related
gain, the candidate can remain as an outcome-first secondary opportunity with
**fork context_only**. It must not be described as a clean target win. Without a
verified target exchange, the initial capture alone does not validate the fork.

This conservative attribution does not prove every defensive/positional use of
a fork. A candidate with no retained related material is a proposed rejection,
not a claim that its move is universally bad. No such proposal is applied live.

## Counterplay and bounded settlement

V3 plays the stored move, asks the shared service for the opponent's best reply,
then re-evaluates each ply for both players. There is no requirement that the
opponent move a fork target: checks, zwischenzugs, threats to the attacker and
counter-captures elsewhere follow the same best-response path.

The initial policy uses the existing `tactic_verify_v1` depth-18 profile and
`ProofWindow`: four additional user moves, the following defense, and up to four
extra settlement plies. Stability requires two quiet actual plies, no check and
two quiet best-PV lookahead plies at a freshly evaluated endpoint. This is bounded
engine evidence, not an exhaustive or mathematical proof.

Unsettled, missing-continuation and mate-valued evidence is **ambiguous/retryable**.
It must not automatically reject or rewrite existing rows. The preview reports
this limitation rather than inventing a settled payoff.

Material values: P100/N300/B300/R500/Q900/K0, in the player's perspective.
Require at least 100 cp retained over the original position and at least 100 cp
from the initial capture plus conservatively accounted target exchanges. The
strict follow-up fork-attributed value is stored separately and must itself be
at least 100 cp to label the fork supported; otherwise it remains context_only.
Unrelated later captures do not count toward this acceptance floor.
Final and after-fork evaluation must both be at least -100 cp.
Then one of the following is sufficient:

1. Both improve on the played move by at least 150 cp.
2. Both remain at least +300 cp, preserving a clearly winning position.
3. Neither loses more than 150 cp from best-before, preserving an acceptable position.

There is no engine-rank-one requirement and no new candidate-move search. Baseline
best-before, played, after-fork and settled evaluations are stored independently.
Mate evidence is deferred instead of converted to an invented centipawn value.

## Read-only preview

```powershell
.\.venv\Scripts\python.exe preview_candidate_verification.py --analysis missed_fork
```

The command has **no apply option**. It opens the live SQLite database with
`mode=ro` and `query_only`, creates/verifies a safety backup, records candidate IDs,
statuses, fork coverage, training links, counts and hash, and selects active V2
rows only. Rejected rows, newer/unknown versions and ambiguous canonical IDs stay
protected. Only joined moves with existing fork candidates are loaded.

`DryRunPositionAnalysisService` reuses live cache entries. Misses go to temporary
**in-memory SQLite**, never the live cache. Scratch IDs are not durable references.
Counts include actual live hits, temporary hits and engine searches. This preview
does not persist new engine evidence for a future apply run.

Artifacts: `fork_v3_before.json`, `fork_v3_results.jsonl`, `fork_v3_progress.json`,
`fork_v3_preview.json`, `fork_v3_manual_qxb7.json` in `reports/`.

During V3 development the computed proof and its interpretation are separate.
`reports/finalize_fork_v3_preview.py` replays the saved proof legally, checks material
totals and applies the final `interpret_proof`/feedback code with **zero engine or
database access**. Use `fork_v3_final_preview.json` and `fork_v3_final_results.jsonl`
as the final candidate proposals; the initial stream retains the computation audit.
This separation allows payoff interpretation to be corrected without repeating
expensive searches. Ambiguous engine proofs remain ambiguous.

## Reconciliation boundary

`candidate_reconciliation_repository.reconcile_candidate` is a generic, fixture-
tested service. It has no live CLI in this task. A future authorized run must
rerun tests, make a fresh verified backup, re-read the approved IDs/statuses/coverage
and validate current evidence before invoking it.

It starts a transaction, checks the allowed candidate IDs, expected snapshot,
canonical uniqueness, status/version and coverage ownership, then updates the
existing candidate in place. It never inserts/deletes candidates. Rejections retain
the solution, ID, metadata and training anchor, recording a reconciliation reason.
Errors are protected without writes. Same-version reruns do not churn timestamps.
Existing screening/scout metadata is retained; new coverage, if needed, uses zero
stage versions rather than falsely claiming fresh screening/scouting. Training
tables are excluded from the write authorizer. Opportunity metadata merges through
the existing codec, preserving unrelated historical evidence.

## Manual Qxb7 case

Candidate 1828, game 3197, move 17 White:
`r2r2k1/1pp3pp/2nbpn2/p1P5/3P1B2/1QNb4/PP3PPP/R4RK1 w - - 4 17`.
Stored move `Qxb7`; old line `Qxb7 Bxf4 Qxc6`.

The audit enumerates legal opponent replies **only at this supplied decision**,
evaluating each child with ordinary single-PV depth-18 requests. This diagnostic
ranking is not native MultiPV and does not discover additional fork candidates.
It compares Bxf1/Bxf4, best user responses, immediate target captures/recaptures,
and bounded settlement. Reply rankings from independent child searches can differ
from the cached root PV; preserve both and report uncertainty rather than hiding it.
The gold/regression tests use this FEN; production calculation has no position rule.

## Opt-in approved-line verification

The sections above describe the retained single-line V3 path. The separate
`multiline_fork_verifier(profile)` registry factory selects
`analyze_forks_v3_multiline.analyze_existing_candidate`. Normal discovery and the
default candidate verifier remain unchanged. The new read-only command is:

```powershell
.\.venv\Scripts\python.exe preview_candidate_lines_verification.py --analysis missed_fork --profile normal
```

It selects existing active V2 fork candidate IDs only, protects rejected/development/
version-exception rows, opens the live database read-only, and stores new engine
evidence in an in-memory candidate-line repository. There is no apply flag.

```text
existing candidate -> candidate-verification registry
 -> CandidateLineService -> CandidateLineSet -> shared Quality Gate
 -> ApprovedCandidateLineSet -> Fork proof + shared bounded settlement
 -> conservative branch consensus -> Scale evidence
 -> proposed TacticalOpportunity / feedback
```

`candidate_line_selection.admit_required_move` identifies the stored move in the
root set. If top-N omits it, the shared service makes an explicitly restricted
request with the same generator settings. A temporary comparison set contains
unique top-N moves plus this required move. The shared gate evaluates that set;
omission alone cannot reject a candidate. A supplemented move has no known global
engine rank: its comparison rank is labelled separately. Restricted requests have
distinct exact cache identities; comparison sets themselves are not cached.

If a line reaches Fork V3 through `ApprovedCandidateLineSet`, it has already
satisfied the active Quality Gate or is explicitly marked as a critical least-bad
fallback. Fork does not repeat the single-line objective acceptance policy. It
still uses the established Fork target/exchange accounting and material floors.

The root contains unique user moves. The position after the stored move gets its
own shared line set of opponent replies; each approved reply gets a child set of
player responses. All approved first replies and first responses are compared.
After those two branching plies, each bounded continuation follows the best
approved move at each freshly evaluated ply. This is **not an exhaustive tree of
every approved alternative at every depth**. `ApprovedPositionEvidence` memoizes
shared service results and never supplies a rejected line to proof.

Normal remains three lines, depth 12, four user moves, four settlement plies and
two quiet plies. Gate thresholds, line count, windows and Scale weights come from
the same typed `AnalysisProfile`; a one-line profile uses the same interfaces.
Profile and request identities travel with the proposal. A future Admin Console
must load this shared schema, not introduce Fork-specific controls or defaults.

`fork_robustness.summarize_continuations` reports branch counts, settled counts,
payoff/target consensus, evaluation and material ranges, reply diversity and proof
stability. Any unsettled, incomplete, critical-fallback or conflicting branch
preserves ambiguity. Stable hits require agreement on outcome, attribution,
retained payoff and realizable targets. A conservative representative supplies
the proposed proof; interest weight never selects or overrides the proof result.
Ranges use settled branches only. Missing evidence is distinct from a completed
search whose proof window did not settle.

Feedback reports geometric targets, consensus limits and settled material ranges.
An ambiguous proposal does not inherit an optimistic legacy solution line or
describe one branch's captured piece as a guaranteed win. Nothing is applied to
Game Review or persisted candidates in this task.

See [the validation report](../reports/FORK_V3_MULTILINE_PREVIEW.md) for Qxb7,
classification transitions and storage measurements. The earlier single-line run
used depth 18 and a different objective policy; changes in classification cannot
be attributed to MultiPV alone or treated as measured accuracy improvements.

## V3.1 targeted escalation (candidate-only preview)

`analyze_forks_v31.py` opts into a small public branch-review hook in the existing
multiline verifier. Normal breadth and Fork accounting remain unchanged. Only
unresolved or conflicting branches request stronger evidence through the shared
[proof escalation service](PROOF_ESCALATION.md). Original Normal proofs remain in
the audit alongside escalated proofs and final consensus.

Default limits: three branches, two approved entry plies, 24 distinct verification
requests per candidate, one verification line at depth 18, four user payoff moves
and eight extra settlement plies. Entry moves remain fixed; deeper PV replay gets
fresh endpoint checks. This is bounded continuation evidence, not a deep search
of every alternative at every ply. Limits and windows come from shared settings.

Unsettled/missing/budget-limited/conflicting/mate evidence remains ambiguous and
protected. `CandidateVerificationResult` carries explicit `ambiguous` state; an
engine/runtime failure remains `error`. The opt-in registry factory does not
replace default discovery or enable reconciliation. Qxb7 must remain rejected
under Normal's gate with zero escalation.

`preview_proof_escalation.py --analysis missed_fork
--allow-candidate-line-cache-inserts` selects only the saved existing-candidate
scope, verifies a fresh backup and enforces cache-insert-only SQLite access. It
refuses to overwrite prior preview output. See the
[V3.1 report](../reports/FORK_V31_ESCALATION_PREVIEW.md) for outcome/cost comparison.

## Backbone reference implementation

V3.1 now constructs `AnalysisBackbone` for required-move admission, Normal evidence,
Scale, candidate-scoped escalation and deterministic provenance. Its lazy
`_selected_requests` retains the same motif-specific ordering/consensus decisions;
shared dispatch owns request limits. Target/exchange accounting and thresholds
remain unchanged. `backbone_provenance` is additive proposal metadata.

All 458 saved results were reproduced from exact cached evidence with zero engine
searches and no database writes. Every previous detail, candidate payload and
TacticalOpportunity matched, apart from the newly added provenance. Qxb7 remains
gate-rejected with no escalation. See the
[consolidation report](../reports/ANALYSIS_BACKBONE_V1.md) and
[shared contract](ANALYSIS_BACKBONE.md). No live reconciliation is enabled.

## Explicit V3.1 new-discovery experiment

Default discovery previously remained Fork V2; the V3.1 factory only accepted
existing V2 candidate rows. The additive `analyze_position` entry points now let
an unpersisted legal move use the same breadth, gate, branch proof and escalation.
Existing-candidate entry points retain their guards. No fabricated candidate ID is
used. New discovery has no historical target/defense to compare; absence of a prior
candidate alone no longer labels its payoff “changed.” Admission and causal/payoff
thresholds are unchanged.

`analysis_crawler --discovery-scope reports/fork_second_500_scope.json` explicitly
selects the experiment through `discovery_registry`. Default Fork dispatch and all
other tactics remain unchanged. `fork_discovery` enumerates the static screener's
unplayed geometric Fork moves and explicitly compares moves outside native top 3.
Each proposal uses V3.1. One canonical candidate per user move is stored: choose the
objectively strongest verified move, with UCI as the deterministic tie-break;
retain all other proposals and disagreements in the coverage/report audit. Scale
never selects truth. Existing canonical candidates and training are protected.

Ambiguity remains distinct from operational failure in proposal diagnostics. With
the existing schema it uses retryable `error` coverage, not completed no-hit.
Identical retryable evidence avoids UPSERT/timestamp churn; completed candidate and
no-hit coverage skips normally. Candidate/coverage writes use the generic repository,
while separate shared cache services own evidence. No schema migration or destructive
launcher is involved. `SettlementEvidence` validates the already-computed branch
ledger; it does not introduce a new proof or search. Raw MultiPV evidence is retained
once in exact caches and referenced by the audit.

The second cohort is saved by source/game identity, dates and target coverage,
not inferred from an ID range. It contains 500 real imports dated June 1 through
September 4, 2026, 15,170 user moves and 30,310 plies, with zero original-cohort
overlap. Frozen settings and final experimental findings belong in
[the second-cohort report](../reports/FORK_SECOND_500_MULTILINE_VALIDATION.md).
No live Pin activation, other-analyzer migration or Game Review change is included.


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
Default Fork routing and live Pin activation remain unchanged. See the
[full report](../reports/FORK_SECOND_500_MULTILINE_VALIDATION.md),
[exact scope](../reports/fork_second_500_scope.json), and
[structured summary](../reports/fork_second_500_summary.json).


## Read-only proof-completeness audit (2026-09-08)

The saved second cohort was audited without production writes or policy changes.
41 exact baseline replays matched from cache: the initial 33 unresolved proposals
and four resolved controls, plus a separately declared four-case pure-window
supplement. Twenty matched existing-candidate pairs used the same V3.1 profile;
no candidate was reconciled.

The 444 ambiguous labels conceal several causes. Evidence-aware counts are 232
mate/terminal blockers, 123 settlement-window cases, 60 branch-limit cases, 26
settled disagreements, one critical fallback and two draw deferrals. Twenty
"missing continuation" cases were played checkmates. Twenty-three of the settled
disagreements were obscured by a budget-denied recheck overwriting stable proof
status; their retained evidence was inspected without changing stored verdicts.
All 26 disagreements mix supported Fork payoff with no supported Fork payoff,
so a conservative common outcome is not justified for them.

Across 37 unresolved test cases, settlement 8→12 resolved 3 with 21 new searches;
payoff 4→6 resolved 1 with 86; depth 18→22 resolved 2 with 151; branch cap 3→6
resolved 0 with 60. Every resolution was a rejection. Depth 22 also made two
resolved controls incomplete, including the read-only control for candidate 1849;
this was unfinished deeper proof, not a demonstrated refutation. Stored 1849 is
unchanged. Five pure-window cases yielded 3 rejections with 7 extra searches under
the longer settlement setting. This small purposive sample is not a cohort forecast.

Recommendation 5: validate a targeted settlement extension and clarify evidence/
terminal semantics before any production change. No global depth increase,
conservative-common-payoff admission, or live activation was performed. Full suite:
363 tests passed. See [audit report](../reports/FORK_PROOF_COMPLETENESS_AUDIT.md).

## Proof-state cleanup and selective settlement validation (2026-09-08)

Fork V3.1 now records escalation attempt disposition separately from retained
proof. Branch/request/child-limit denial or failed evidence cannot turn stable
proof into `budget_exhausted`. Genuine stable hit/no-hit disagreement still blocks
verification. Operational engine errors remain errors. Historical payloads remain
readable without rewriting them.

Played checkmate now returns explicit `played_checkmate` with
`played_move_terminal` ownership. Candidate checkmate defers to Mate. Complete
terminal results are not missing continuations; nonterminal mate-valued evidence
is deferred. All 20 historical missing-continuation cases were replayed without
engine requests and confirmed as played checkmates.

Read-only taxonomy of 444 ambiguous proposals: 232 mate/terminal, 123 pure-window,
60 branch-limit, 26 settled disagreements, one critical fallback and two draw
cases. The 23 newly visible disagreements still have no common supported Fork
payoff; no candidate/status changes followed.

A predeclared 40-case diversity sample excluded five prior experiment cases.
Only verification settlement changed 8→12, retaining Normal MultiPV3, depths12/18,
4-user-move payoff, 3-branch and 24-request caps. Results: 11 no-hit rejections,
29 ambiguous, no verified hits, no errors; 82 added searches / 42.76 seconds.
All five controls retained their proof/material/outcome, including 1849. Identical
45-case reruns made no searches or writes. Full suite: 375 passing tests.

Recommendation awaiting approval: keep 8 generally; selectively extend pure-window
cases to 12. The live profile, admission policy, default registration, candidate
IDs, caches and all DB bytes are unchanged. No historical scan or live activation
was performed. Detailed case explanations and future evidence-toolkit limits:
[settlement validation](../reports/FORK_SETTLEMENT_VALIDATION.md).

## Selective 12-ply settlement implementation

The previously recommended selective extension is implemented and **disabled by
default**. Normal verification stays at 8. After all normal branch obligations are
reviewed, Fork supplies explicit blockers to the shared eligibility predicate;
only a complete cp proof that is unresolved at the exact settlement boundary may
continue to 12. Stable proof, terminal/mate ownership, missing evidence, primary
budget denial, existing settled disagreement and explicit causality uncertainty
cannot qualify. The same root, prefix, payoff clock and branch/request budgets are
retained. No threshold, Quality Gate or Scale change was made.

The 40-case cache-only replay reproduced every prior classification: 11 no-hit
rejections, 29 ambiguous/protected, zero verified additions and zero errors. The
five controls retained their classifications, proof lines, material and evaluation;
discovery controls 1848/1849 remain verified/verified_payoff_changed respectively.
Both current saved V3.1 candidate rows were also compared with the policy disabled:
proof/material/evaluation and classifications are unchanged. For 1848, the existing-
candidate comparison already labels the result verified_payoff_changed with the
policy disabled; this is a pre-existing comparison-mode distinction, not a change
in the discovered tactic or candidate data.

Fifty-two eligible branch extensions used 78 additional cached requests; all
requests were satisfied without searches. Maximum candidate usage was 16 of 24
verification requests. The earlier experiment's 82 new searches are historical
cost evidence, not a promise of this policy's cold-cache cost or resolution rate.
The identical replay is deterministic and writes nothing.

Exact 8/12 request namespaces are separate, with a narrow read-only compatibility
adapter for the original unscoped cache. Source identities remain explicit. Full
eligibility, settings, cache semantics and activation recommendation:
[selective policy report](../reports/FORK_SELECTIVE_SETTLEMENT_POLICY.md).
