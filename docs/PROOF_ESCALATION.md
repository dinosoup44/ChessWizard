# Shared proof escalation

`ProofEscalationService` obtains bounded stronger evidence for an exact approved
branch. It owns request budgets and delegates all engine/cache work to the injected
`CandidateLineService`. It does not identify tactics, select database rows, interpret
material ownership, reconcile candidates or import a frontend.

## Breadth and verification

Normal breadth remains three lines at depth 12. The opt-in `normal_escalation`
profile retains that generator and adds `ProofEscalationPolicy`. Its verification
generator requests one line at depth 18, with the request-family identity
`candidate_lines_verify_v1`. This is a shared preset, not a Fork constant.

The initial policy keeps up to two approved entry plies fixed. Stronger evidence
starts at that exact child position. `candidate_line_settlement` legally replays
the deeper PV and requests fresh evidence when the PV ends or a settlement endpoint
needs checking. It does **not** attribute the anchor evaluation to each intervening
position. A stable endpoint requires a fresh evaluation, two quiet actual plies,
no check, and two quiet fresh-PV lookahead plies. Captures, checks and promotions
reset the quiet counter. Scores retain explicit POV and separate mate ownership.

This deliberately differs from Normal's fresh three-line search at every proof
ply. It is bounded deeper continuation evidence, not an exhaustive minimax tree,
and not a claim that every alternative throughout the PV passed a separate gate.
The deeper root choice passes the shared gate; subsequent PV moves are engine
continuation evidence. Fork reports this proof scope explicitly. A future policy
requiring per-ply deep alternatives needs its own measured cost and regressions.

## Contract

1. Construct one service per candidate with the shared line service and profile.
2. Supply `ProofEscalationRequest`: position after the tactical move, player color,
   approved reason, observed proof state, root-admission result and optional tuple
   of `ApprovedPrefixMove` values.
3. Each prefix value carries its complete `ApprovedCandidateLineSet`. The move must
   belong to it, its FEN must match the branch position, and the move must be legal.
4. Call `escalate(request, piece_values)`. Material values belong to the caller's
   established accounting policy; no motif rules live in this service.
5. Interpret the structured result in the specialist. Preserve unresolved evidence
   and compare **all** approved branches, including branches that were not escalated.
6. Record `audit()` along with original branch evidence and final interpretation.
   Persistence, if later authorized, remains a separate repository operation.

`ProofEscalationResult` statuses are `not_needed`, `complete`, `unresolved`,
`incomplete`, `budget_exhausted`, `deferred` and `error`. Complete means bounded settlement,
not that a tactic was proved. `proof`, request identities and verification profile
identity accompany the result when available. A missing/invalid evidence payload
is incomplete; actual engine/runtime failures return structured execution-error results.

## Triggers and protection

Approved triggers are `proof_unsettled`, `material_unsettled`,
`counter_capture_unresolved`, `missing_evidence` and `payoff_disagreement`.
A settled branch does not escalate under an unsettled trigger. Settled consensus,
a stable no-hit, a disabled policy, a failed root gate, and Scale interest do not
trigger deeper work. Root boundary re-admission is not enabled in this policy.

Mate/draw evidence and critical prefixes are deferred. Missing evidence, exhausted
budgets and remaining disagreement cannot produce a definite rejection or optimistic
hit. A stronger recheck that fails to settle invalidates the earlier branch's
settled certainty, while retaining the original audit. No recursion is enabled.

## Settings and limits

All controls use the `AnalysisProfile` loader/schema intended for a future Admin
Console. No UI has been added.

| Setting under `escalation` | Initial value | Meaning |
| --- | --- | --- |
| `enabled` | false in existing profiles | Explicit adoption only |
| `verification.candidate_line_count` | 1 | Depth evidence, separate from breadth N |
| `verification.engine.depth` | 18 | Shared verification budget |
| `verification.engine.threads` / `hash_mb` | 1 / 64 | Exact engine options |
| `proof.user_moves` | 4 | Payoff window, followed by opponent defense |
| `proof.settlement_plies` | 8 | Extra linear settlement plies; 17 total maximum |
| `proof.quiet_plies` | 2 | Actual and lookahead stability requirement |
| `max_escalated_branches_per_candidate` | 3 | No unbounded branch fan-out |
| `max_child_depth_levels` | 2 | Approved entry plies to the deep anchor, not PV length |
| `max_requests_per_candidate` | 24 | Distinct verification requests, including cache hits |
| `ambiguity_policy` | protect_unresolved | No forced certainty |
| `root_admission_policy` | preserve_breadth_gate | No rejected-root rescue |
| `mate_policy` | defer | Preserve ownership boundary |

Request limits include cache hits so a warmed cache cannot change the proof budget
or classification. Exact duplicate requests are memoized within a candidate. A
request-limit failure may have partial evidence but does not claim a completed
proof. Branch limits bound attempts independently of request counts.

Schema entries expose IDs, labels, types, defaults, ranges/options, descriptions,
basic/advanced level and cache/currentness flags. Existing flag names
`affects_cache_identity` / `affects_analysis_currentness` have explicit aliases
`affects_raw_cache_identity` / `affects_result_currentness`. Engine settings affect
raw requests; escalation limits and gate/Scale/proof interpretation affect only
result-currentness. Existing disabled profiles retain their prior currentness hash.

## Cache and safety

The exact key remains `(FEN, engine_identity)`. Generator version, engine/version,
request family, line count, budgets, Threads/Hash and normalized root restrictions
participate. Depth-18 verification cannot consume depth-12 breadth rows as if they
were equivalent. Gate/Scale/policy changes reuse compatible raw evidence.

The caller chooses read-only, scratch or explicitly authorized insert-once live
cache stores. No schema migration happens on service construction. The preview
uses the existing repository with `insert_only_authorizer`, a verified SQLite
backup, per-candidate cache commits, full protected-table fingerprints, old-cache
row comparisons and integrity checks. Candidates, coverage, training, games,
moves and `engine_position_cache` cannot be written through this connection.

## Fork V3.1 adoption

`escalating_fork_verifier` is an explicit candidate-only registry factory. Default
Fork V2 discovery, default single-line V3 verification and all other analyzers stay
unchanged. V3.1 accepts only the same eligible existing Fork candidates.

The small optional `ForkBranchContext` review hook follows Normal's existing branch
proofs. V3.1 keeps original branches, prioritizes unresolved branches, then rechecks
settled disagreement if necessary and budget allows. `interpret_proof` retains the
existing Fork target identity, exchange/recapture accounting and material floors.
The representative result is conservative; no approved branch is dropped to obtain
agreement. Scale is computed separately and cannot choose a favorable proof.

`CandidateVerificationResult.state == "ambiguous"` explicitly distinguishes chess
uncertainty from `error`. This candidate-only model is not a new coverage status
and is not wired to a live reconciliation path. Earlier HeavyResult-based callers
retain their compatibility behavior.

The mandatory Qxb7 regression must fail current Normal root admission without a
verification search. Its separate manual/depth-18 evidence remains auditable but
cannot bypass the configured gate. See the
[Fork V3.1 adoption summary](MISSED_FORK_V3.md#v31-targeted-escalation-candidate-only-preview)
for the frozen bounds; exact preview measurements remain in private audit receipts.

## Reuse and portability

Pin, Skewer and X-ray can adopt the same request/result/service by supplying their
own approved branches and interpreting proof with their established ownership and
settlement helpers. They must define gold regressions, disagreement handling and
an explicit opt-in validation scope first. None has been migrated here.

Models, settings, service, settlement, verification and repositories work without
Tkinter. A desktop/mobile frontend consumes these shared contracts; engine access,
calculation and persistence remain separate layers.

## Consolidated backbone and structured errors

[ANALYSIS_BACKBONE.md](ANALYSIS_BACKBONE.md) is the canonical workflow guide.
`AnalysisBackbone` exposes one candidate-scoped service/profile budget.
`escalate_selected` lazily consumes `(branch_key, request)` pairs so the specialist
can reconsider consensus after each result. It does not choose motifs, reset
budgets per branch or automatically deepen every continuation.

Operational failures now produce `ProofEscalationResult(status="error")`; invalid
request construction remains a caller contract error. Fork propagates operational
failures to candidate orchestration as errors, never as chess ambiguity. Existing
complete/deferred/unsettled/budget/incomplete behavior and all proof thresholds are
unchanged. See the shared `EvidenceState` mapping and legacy result migration
boundary in the backbone guide.

## Pin per-ply composition

ProofEscalationService accepts an optional shared proof solver. The default
endpoint-PV solver and all Fork behavior remain unchanged. Pin injects
`verify_approved_bounded_line`: a validated approved entry prefix followed by
fresh best-line evaluation each ply through the existing tactical proof function.
The prefix is inside the original clock, not extra payoff time. Pin keeps four
user moves, following defense and four settlement plies for both passes.

The same shared scheduler enforces branch/request limits. Partial, conflicting or
budget-limited results remain ambiguous; mate/terminal results remain deferred.
Stable no-hit/positional agreement and failed root admission do not escalate.
Pin's first proof already uses depth 18; this migration does not lower it or extend
the horizon to make escalation look successful. Consumer provenance must include
the solver interpretation contract. See [Pin validation](PIN_BACKBONE_MIGRATION.md).

## One-pass near-threshold confirmation

`threshold_review.ThresholdReviewService` composes the existing shared bounded
requests and verification profile. It owns neither engine lifetime nor cache/DB
persistence. The caller supplies a line service, comparable base profile and typed
`ThresholdReviewSettings`. It requests before/played/tactic evidence at one stronger
depth and returns a structured comparison result. `comparison_passed` is deliberately
not a candidate or proof verdict. Mate evidence defers. Exact raw identities keep
the stronger request separate; margin and trigger policy do not enter raw identity.

Pin's read-only adapter uses a 15 cp margin below its unchanged 150 cp threshold,
depth 22 confirmation and at most 64 distinct requests including subsequent proof
and cache hits. Other engine options must match the base request. The original
proof horizon and all final acceptance conditions remain mandatory. Once escalated,
it does not return to depth-18 proof or repeatedly deepen until accepted. An
incomplete or exhausted comparison/proof stays unresolved. The shared escalation
algorithm and other analyzers are unchanged; this is an opt-in composition rather
than a new automatic global escalation rule.


## Proof-completeness audit findings (2026-09-08)

The read-only Fork audit exposed a distinction consumers must preserve:
**proof evidence state and escalation-attempt disposition are different facts**.
At the time of that audit, Fork review marked a stable branch `budget_exhausted` when the branch cap
prevents a recheck; no new proof accompanies that denial. The audit identified 23
such proposals with stable retained proofs and real payoff disagreement. Reporting
can retain that provenance without admitting the tactic or rewriting production
coverage. That audit documented the behavior; the cleanup below subsequently fixed it.

No sampled/original request hit the 24-request limit or two-prefix-ply child cap;
those bounds are not the present bottleneck. A six-branch experiment peaked at 17
requests. Increasing it completed more branches but resolved no sampled proposal.
The 8→12 verification settlement extension had the best measured cost/resolution
ratio: 3/37 unresolved cases with 21 new searches (3/5 among the explicitly tested
pure-window subset, 7 searches). Depth 22 cost 151 searches for 2 resolutions and
made two resolved controls incomplete. These figures exclude control costs, which
are tabulated separately in the full report.

Actual quiet plies, no check, and fresh quiet lookahead remain required. Stable
material or vanished targets alone were not shown safe as replacement predicates.
Immediate recaptures and continued checking sequences occur in the audited proofs.
Target-fate/local-exchange semantics deserve tests before relaxing settlement.
The six-user-move trial used an isolated research window: production typed settings
still cap four and cannot enable that experiment without a contract extension.
All settings and implementation remain unchanged. See
[the Fork proof-completeness summary](MISSED_FORK_V3.md#read-only-proof-completeness-audit-2026-09-08).

## Proof lifetime and attempt disposition (2026-09-08 cleanup)

The preceding audit described a now-fixed bookkeeping defect. Shared
`proof_evidence_state.py` distinguishes proof evidence from the request to improve
it. `ProofEscalationResult.status` remains compatible with old payloads;
`escalation_attempt_state` exposes `not_needed`, `completed`,
`branch_limit_denied`, `request_limit_denied`, `child_depth_denied`, `deferred`,
or `error`. A completed attempt need not produce stable evidence. Its independent
`evidence_state` is null when no replacement proof was produced.

Canonical proof states are `stable`, `unsettled`, `incomplete`, `terminal`,
`deferred`, and `error`. `BoundedProof.evidence_state` projects the historical solver
strings without changing their serialized shape. Final Fork branch dictionaries
use canonical `proof_state` and retain `legacy_proof_state` when needed.

A denied/failed recheck never overwrites established stable proof. An unfinished
replacement remains in the attempt record; already-unsettled branches update to
its actual endpoint. Stable branches retain their established interpretation.
Operational errors still propagate as errors, without rewriting the retained
branch as an error proof. `retained_branches()` adapts historical overwritten
payloads without mutating them. Consumers must not treat denial as contradiction,
or stable mixed hit/no-hit evidence as common causal payoff.

Terminal board facts are complete without a PV. Played checkmate is explicitly
owned by the played move; candidate checkmate belongs to Mate. A mate score on a
nonterminal board is deferred evidence, not a terminal-board fact.

The predeclared 40-case pure-window experiment resolved 11 no-hits for 82 extra
searches; 29 stayed ambiguous, and five controls were unchanged. Verification
settlement remains **8 in production**. Recommendation awaiting approval: extend
to 12 selectively for pure-window cases. Raw request identity is unchanged by the
settlement window; result-currentness identity changes, and only newly requested
FENs need new evidence. See the
[Fork settlement summary](MISSED_FORK_V3.md#proof-state-cleanup-and-selective-settlement-validation-2026-09-08);
per-case evidence and request receipts remain private.

## Selective settlement policy (implemented, not activated)

`ProofEscalationPolicy.settlement_extension` is shared typed configuration. Its
`enabled` setting defaults to false; source/target settlement are explicitly 8/12.
The old disabled-policy currentness identity is preserved. Enabling the policy
changes result currentness; it does not change Quality Gate, Scale, payoff moves,
engine depths, MultiPV, branch cap or request cap.

`SettlementExtensionEligibility` records eligibility, reasons, blocker states,
source proof state and provenance. It requires admitted root evidence, an actual
unsettled proof at exactly `2 * user_moves + 1 + 8` plies, complete White-POV cp/PV
endpoint evidence, and no terminal board. The specialist must supply operational,
terminal/deferred ownership, primary budget-denial, genuine settled-disagreement,
incomplete-evidence and explicit causality-uncertainty blockers. An ambiguous label
alone never qualifies. Root failure, stable proof or unavailable checkpoint stops
extension.

Fork finishes normal verification before evaluating this predicate. A qualifying
branch resumes its saved `SettlementContinuation`: same approved prefix, prior
steps, remaining PV, quiet count and payoff clock. The checkpoint precedes the
8-ply cap's endpoint-only probe, so that probe does not silently select a different
continuation. There is no fresh candidate search or reset of the branch allowance.
Normal and extended requests share the same 24-request ledger; extensions reuse
an already-counted branch within the cap of three. Denied extension preserves the
old proof. New mate/draw evidence defers ownership, and mixed stable hit/no-hit
branches remain ambiguous. Resolution is not rewarded.

### Explicit cache namespaces

The selective path uses distinct exact engine request namespaces derived from the
existing engine profile: `:settlement=8` and `:settlement=12`. All actual engine
options stay identical. Source and extended proof identities are also distinct.
This refines the earlier unscoped experiment; it does not rebuild that cache.

`SettlementCacheAdapter` first probes the exact scoped row. On a miss, it may read
an exact legacy unscoped request only when FEN, restrictions, complete generator
metadata, MultiPV, depth/nodes/time, Threads/Hash, engine/version and normalization
version match. A read-only alias preserves `source_engine_identity` and original
settings as explicit provenance. The alias is not inserted or written back. It
must not pretend that a longer proof was already complete: it supplies raw engine
evidence only. A scoped 12 row is not silently returned as an 8 row.

If neither exact nor compatible evidence exists, the injected shared line service
handles that new scoped request; no raw process is launched by the specialist.
Breadth identity remains unchanged. The policy flag is result-currentness metadata;
explicit proof-stage namespaces distinguish related verification requests. The
backbone provenance now includes approved evidence from extension stages.

Validation: all 40 sample outcomes reproduced (11 rejected, 29 ambiguous), five
controls unchanged, zero engine searches/writes, 52 extended branches and 78
additional cached verification requests. Maximum candidate request usage was 16/24.
No production profile was enabled. The
[backbone extension boundary](ANALYSIS_BACKBONE.md#selective-continuation-extension-boundary)
documents integration and provenance; detailed replay receipts remain private.

### Settlement summary provenance

`settlement_provenance.branch_settlement_summary` is the canonical branch-to-summary
mapping. It matches the retained branch against recorded escalation proofs, then
uses the actual `ProofWindow` and typed verification profile. A denied or unused
recheck cannot replace the retained branch's provenance. Selective extension keeps
its explicit `selective_settlement_extension` stage and twelve-ply window; normal
verification retains eight plies, and breadth remains a separate source.

The summary's `provenance` contains generator settings (including depth/budget),
engine request identity, profile currentness, proof window/version, policy identity,
stage, and recorded request keys. Selective summaries preserve the recorded request
chain from the original proof through its extension. These keys describe requests;
they do not assert that corresponding physical production-cache rows exist. Exact
legacy cache aliases retain their own raw-source metadata. Missing legacy request
history is marked as unrecorded rather than invented.

`normalized_settlement_summaries` provides nonmutating compatibility for older report
payloads, including mislabeled selective summaries. It changes provenance and its
identities only. Moves, captures, material, scores, state and analyzer classifications
are preserved. Missing verification source proof or conflicting stored settlement
facts raises an error instead of guessing. No engine, persistence, or UI dependency
is introduced by this normalization.

For legacy branches with no outer stage label, `settlement_evidence.provenance`
provides the explicit authoritative source stage recovered from the retained proof.
The compatibility reader does not change historical branch interpretation fields.

Scratch audit replay records incomplete request outcomes separately from valid engine
evidence. See [audit outcome contract](AUDIT_REQUEST_OUTCOMES.md) for exact identity,
cache precedence, interruption semantics and NoEngine reproduction.

