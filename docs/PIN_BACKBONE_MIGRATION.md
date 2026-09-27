# Pin V2 backbone adoption: read-only checkpoint

Pin V2 is the second opt-in backbone consumer, after Fork V3.1. The production
crawler still uses `pin_adapter_v2` and the unchanged analyzer version `2`.
`candidate_verification_registry.pin_backbone_verifier()` creates an explicit
candidate-only verifier; it does not mutate either discovery registry.

## Entry points and responsibilities

- `pin_backbone.replay_single_position(row, lookup)` reproduces the existing
  position calculation using recorded one-PV evidence. It returns the identical
  HeavyResult plus separate provenance and SettlementEvidence.
- `pin_backbone.analyze_existing_candidate(row, line_service, profile)` uses the
  stored solution move. `analyze_candidate_position` accepts an explicit curated
  move. Neither entry point enumerates historical positions or persists proposals.
- `AnalysisBackbone` owns approval, required-move supplementation, evidence
  memoization, shared escalation, Scale and provenance. CandidateLineService and
  its caller-supplied repositories own exact requests and storage.
- `RecordedPositionReplay` legally normalizes recorded one-PV evidence into
  CandidateLineSet, gates it and records Scale. Its `recorded_single_pv_v1`
  namespace explicitly records unknown Threads/Hash/restrictions/MultiPV.
  It NEVER aliases legacy rows to new raw-engine cache identities or writes them.
- `approved_bounded_proof.verify_approved_bounded_line` composes the existing
  per-ply proof with validated approved entry moves. Entry plies consume the
  original payoff window. Shared SettlementEvidence replays every resulting proof
  and checks the capture/material ledger.
- Pin keeps geometry, absolute/relative identities, related retained value,
  attribution, ownership, acceptance thresholds and outcome/presentation.
  `analyze_pins_v2` is the one interpretation implementation for both paths.
  Its optional choices/proof/policy dependencies replace no default behavior.

## Settings mapping

| Existing V2 setting | Shared/typed mapping | Unchanged value or meaning |
| --- | --- | --- |
| `tactic_quick_v1` | Recorded replay request; new evidence uses shared Quick AnalysisProfile | depth 10, one line |
| `tactic_verify_v1` | Recorded replay request; new evidence uses `profile.escalation.verification` | depth 18, one line |
| New breadth | Normal AnalysisProfile | depth 12, three lines, Threads 1, Hash 64 MiB |
| `PROOF_WINDOW` | `PinPolicy.proof`, matched by breadth and escalation proof settings | 4 user moves + following defense, up to 4 settlement plies, 2 quiet actual and fresh lookahead plies |
| Quick gain/drop | `PinPolicy.quick_min_gain_cp/quick_max_drop_cp` | 120/300 cp |
| Deep gain/drop | `PinPolicy.verify_min_gain_cp/verify_max_drop_cp` | 150/200 cp |
| Total and related material floor | `PinPolicy.min_retained_material_cp` | 100 cp for both |
| Final player evaluation floor | `PinPolicy.min_final_eval_cp` | -100 cp |
| Proof mode | `PinPolicy.proof_mode` | fresh evaluation each ply; no endpoint-PV substitution |
| Escalation budgets | `profile.escalation` | 3 branches, 2 entry levels, 24 distinct requests |
| Ambiguity/ownership | shared escalation policy + Pin interpretation | protect unresolved; defer mate ownership |

All settings use Settings/SettingDefinition and AnalysisProfile. Quick and verify
profiles are shared models, not a second engine configuration format. Pin gain
thresholds compare against the played move and are NOT substitutes for the shared
Quality Gate. PinPolicy is included in interpretation/result currentness, never
raw engine cache identity. Gate/Scale settings likewise do not duplicate raw searches.
The future Admin Console can expose these schemas without importing Tkinter.
Changing V2 proof depth/window or interpretation policy requires a separate policy
review; this checkpoint validates the frozen settings above.

## Proof and conservative multi-line scope

Only the explicit stored/audited root move is considered. The shared gate can
supplement it with an exact restricted request if Normal top-N omits it. All
approved first opponent replies are retained; later moves follow the freshly
approved verification best line. This is bounded branch evidence, not exhaustive
opponent/player multi-line exploration or new historical discovery.

Stable payoff and Pin causality agreement produce `verified`. Valid but varying
payoffs produce `verified_payoff_changed`, a least-payoff representative proof
and generic “Win material” wording. It does not claim a particular captured piece
across branches that win different pieces. Hit/no-hit or motif/identity conflict,
missing evidence, and unresolved/budget-limited proofs remain `ambiguous`.
Root gate failure is a proposed rejection only. Actual execution failure is
`error`; mate/terminal ownership deferral has `proof_deferred` evidence state.

Scale weights only approved evidence and cannot change candidate truth or select
an optimistic branch. It records root-PV interest, not a claim that raw PV material
has settled. Branch SettlementEvidence stays distinct. Robustness records branch
counts/states, material and evaluation ranges, Pin identities, causality and
relationship survival. Prefix and exact verification requests remain auditable.

Unsettled or disagreeing branches use the shared escalation scheduler and budgets.
V2 already requires depth-18 per-ply evidence: this adoption does not weaken its
first pass to manufacture an improvement on escalation. With the same depth/window,
a complete rerun of the same branch may remain unresolved. Do not increase the
window or cherry-pick a stronger favorable result to force a hit.

## Strict equivalence: 39/39

Read-only live SQLite, query_only enabled, no writable live repository, and a
fallback object that raises on missing evidence. Seven candidate rows (five V2,
two V1; all status candidate and protected from persistence) plus 32 frozen gold
entries reproduced the pre-refactor calculation exactly. Classification, complete
HeavyResult, TacticalOpportunity and generated feedback all match. Every legal
proof/material ledger was normalized through SettlementEvidence.

The five stored V2 opportunities and feedback also match after restoring the
canonical played/tactic/proof fields intentionally omitted from compact metadata.
No classification, opportunity or feedback differences were introduced by the
refactor. Exact new-cache quick/verification root requests were missing for all
seven live positions. This is explicitly recorded: legacy replay is NOT an exact
new-cache hit. No engine searches filled those gaps during equivalence.

## Curated proposal validation

32 frozen gold entries + 7 existing candidates reduce to 33 distinct move/tactic
pairs. Normal admitted 26 and rejected 7 root moves. There were 61 approved reply
branches and 34 bounded escalation attempts. Final proposals: **1 verified,
18 rejected, 14 ambiguous, 0 errors**. No changed-payoff proposal occurred in this
sample; synthetic regressions exercise that state and conservative wording.

The verified proposal is the already-curated delayed `Bg4` case at move ID 183806.
It is not a newly discovered or persisted candidate. Existing V2 IDs 1837 and 1838
receive rejection proposals under new exact evidence; 1839/1840/1841 are ambiguous.
The frozen legacy evidence still reproduces all five stored results. See the full
report for the distinction between new evidence and architectural equivalence.

812 searches generated 812 in-memory cache rows; 305 requests reused cache evidence.
The identical rerun made 1,117 cache hits, zero searches, zero inserts/updates and
identical proposals. Additional final-code replay from saved scratch evidence was
also cache-only. Initial generation plus rerun took 288.65 seconds. No evidence was
promoted into either live cache. The database remained byte-identical (251,191,296
bytes); quick_check was `ok`, foreign_key_check empty.

## Mandatory legacy lessons

1835 remains a protected V1 row. Its live recorded V2 replay is a no-hit with a
“Rook pressure wins a pawn” annotation: rook pressure supported, relative pin
context_only. The frozen gold evidence is also not forced positive. Normal
multi-line is ambiguous. “Missed Pin” must not replace the concrete explanation.

1836 remains protected V1. Frozen gold replay preserves “Check and win a rook”:
check and double attack supported, relative pin context_only. Current live legacy
evidence produces a V2 no-hit (also reproduced exactly); Normal is ambiguous.
These different evidence snapshots are reported separately, not silently merged.

## Safety, validation and next migration

335 full-suite tests pass, including existing Fork/Mate/Skewer/X-ray, shared
backbone/gate/escalation/Scale, feedback and UI regressions. Focused tests cover
best-line and Normal modes, delayed/immediate/exchange/recapture/context examples,
shared escalation resolution and budgets, failed root admission, conservative
payoff/causality consensus, schema, deterministic provenance and UI independence.

No schema/candidate/status/coverage/training or live-cache changes. All 942
candidate IDs, 11 training attempts/links, 34,982 coverage rows, 238,599 position
cache rows and 23,389 candidate-line cache rows remain untouched. All code/services
are usable without Tkinter; the UI still consumes shared feedback only.

Ready for continued read-only developer use; **not ready for automatic live
reconciliation or default activation**. First review the new-evidence differences,
branch budgets and intended objective admission policy. Then separately authorize
an explicitly scoped, backed-up migration through generic ID-preserving persistence,
with candidate protection, version/currentness plan and zero-work rerun checks.
Do not reuse version 2 coverage to silently reinterpret existing protected rows.

Skewer/X-ray should follow by analogy: retain their pure motif interpretation;
add an explicit candidate-verifier factory; bind shared profiles/evidence/proof;
prove recorded equivalence first; validate curated exact evidence in scratch;
review differences before any live authorization.

The [strict equivalence](#strict-equivalence-3939) and
[curated proposal](#curated-proposal-validation) sections summarize the public
findings. Exact case identities, request receipts and branch/proposal exports remain
private; they are not dependencies of the public test suite.

## Follow-up difference audit: activation recommendation 2

The read-only difference audit summarized below
compares all 33 explicit move/tactic pairs, using current recorded V2 evidence for
the seven live rows and the frozen gold snapshot otherwise. It replays exact saved
requests only. No policy/profile, production source, database, or cache changed.

There are 16 changed candidate/no-hit/ambiguity outputs: A likely correction 1,
B likely policy mismatch 1, C genuinely uncertain 2, D incomplete proof 12,
E presentation-only 0. The other 17 retain their prior candidate/no-hit output.
Seven root-gate failures are separately tabulated because they change admission
or ownership routing without removing a current verified positive. Numeric score
changes alone are not counted as material outcome changes.

### Taxonomy and policy findings

- Root gate: seven failures (four CP-distance decisions, three mate decisions).
  All five live V2 positives pass. No demonstrated accepted Pin is lost solely to
  Normal root admission. V2's played-move improvement/drop tests answer a different
  question from shared objective line admission; do not equate their thresholds.
- 1837 is a likely correction of the **pin-specific** follow-up overclaim: the
  delayed rook gain disappears in the new b5 line and the other defenses cost a
  pawn or trade queens evenly. The root move itself still has a good evaluation.
- 1838 is near-threshold fresh-evidence sensitivity: depth-18 improvement changes
  from 217 to 146 cp, four below the same 150 cp floor. Its root passes and neither
  approved reply reaches proof. This is not a multi-line tactical refutation.
- 1841 has genuine settled causal disagreement: Nd5 verifies +300 related cp,
  while Ne4 settles at +200 total but -200 related cp with context_only attribution.
  The Bb4+ branch is also unsettled. Do not select the optimistic branch.
- 1839 is a **secondary-motif consensus mismatch**, not disagreement about the
  primary Pin. All three initial branches verify the same supported absolute pin
  and retain +400 to +600 related cp. Two exchange the pinner and include sacrifice;
  one keeps it and omits that secondary annotation. Whole-motif equality currently
  declares ambiguity. A detached diagnostic comparison of the common primary Pin
  yields conservative verified_payoff_changed; no override was installed.
- Thirteen cases contain unsettled proof; ten exhaust verification request budget.
  Across 34 escalation attempts, eight complete, eleven remain unsettled and fifteen
  exhaust budget. All 302 escalation service requests duplicate first-pass cached
  evidence at the same depth and horizon. No candidate-level verdict is improved.
  A budget flag is not proof of tactical failure, especially for a previously
  completed stable branch.
- Other differences include four deep-evaluation preemptions before continuation
  proof. Three mate baseline deferrals become root rejection reasons; their
  ownership semantics should remain visible rather than imply generic no-hit proof.

The audit distinguishes recapture/exchange costs, contextual pin geometry, delayed
payoff that no longer settles, annotation differences and absent cache evidence.
There were **zero missing exact requests**; “incomplete” here means bounded chess
proof, not an absent raw-cache row. Every case has root rank/evaluation, gate reason,
geometry, initial/final branch states, escalation, material/evaluation ranges and
an evidence-linked explanation in the report.

### Protected 1835 and 1836

1835: Rab8 is admitted (rank 2, +260 cp, 54 cp from best). b4 is a legal approved
reply. Current recorded V2 calls the historical pawn-capture line rook pressure
with a context-only pin. New lines show -100 to 0 observed cp; two are unsettled,
and the stable Na3 branch has no retained pin payoff. Prefer “Rook pressure on the
b-file; a pawn win is not verified across the approved defenses.” The V1 line is
valid legacy evidence but its primary causal “Missed Pin” description is too strong.

1836: Qd5+ is admitted (rank 1, +101 cp). Check plus attack on the c6 knight remains
the concrete idea. The new line shows +400 observed cp/final +70 cp but is unsettled.
The frozen gold snapshot separately supports “Check and win a rook” through a
different longer line; it must not be silently substituted for the current proof.
The stored V1 immediate knight capture and scope are legitimate legacy evidence,
while primary Pin wording overstates the causal role. Both IDs remain unchanged.

### Value, cost and next decision

Decision value across 33 cases: seven confirmations, one likely pin-overclaim
correction, one genuine causal ambiguity, zero presentation-only changes, and 24
without demonstrated decisive multi-line benefit. The last group includes already
unsettled cases, early gate/evaluation stops and 1839's annotation mismatch; it does
not mean that exposing uncertainty or cheaper rejection has no operational value.
Several confirmations have only one approved defense, so this is not evidence that
multiple replies were needed for every confirmation.

Per replay: 71 Normal breadth requests (33 roots, 12 required-move supplements,
26 reply positions), 78 Quick comparisons, 968 verification requests, total 1,117.
The original run searched 812 times: 68 breadth, 78 Quick, 666 verification; the
remaining 305 were cache hits. Today's audit and identical rerun each used 1,115
scratch-artifact hits and two live hits, with zero misses/searches/writes. Average
33.85 requests/case; worst 71 requests/47 original searches for Qf6 (176849) and
Rab8 (176178). The scratch artifact and live database remain hash-identical.

**Recommendation 2 — ready after small policy/configuration clarification and
separately approved targeted revalidation; not ready to activate today.** Keep Pin
on the equivalence path and keep the shared gate unchanged for previews. Clarify
primary Pin consensus versus optional secondary motifs, redundant same-evidence
escalation/budget handling, and mate/deep-threshold currentness semantics. No
observed positive requires a gate override; do not add Pin-specific hacks or relax
tolerances without evidence. A focused consensus contract revision is warranted;
a new Pin chess definition, Pin V3 or full policy redesign is not supported here.

Four focused characterization regressions cover the newly identified categories.
Full suite: **339 passed**. Production hashes unchanged; database byte-identical,
quick_check ok, foreign_key_check empty, candidates/history/coverage/live caches
preserved. No live activation, other analyzer migration, historical scan or UI change.

## Policy clarification and targeted revalidation — 2026-09-07

This checkpoint supersedes the preceding activation recommendation, while retaining
its historical evidence. **Recommendation 1: ready for separately approved live
activation.** No activation or persistence change was made. This section summarizes
the 33-case revalidation and its policy changes. Per-case branch evidence, exact
request identities and local safety/rerun receipts remain private.

`PinBackbonePolicy` now separates primary causality consensus from secondary motif
variance. Every branch must independently verify the same primary Pin relationship
and attribution. Supported versus context-only primary disagreement remains
ambiguous. `primary_motif_consensus`, `secondary_motif_variance` and
`branch_motif_evidence` retain annotations and their rationales; full branch
opportunities/settlements are preserved. The representative opportunity does not
claim that every secondary motif occurs in every defense. The conservative minimum
related-payoff rule is unchanged. 1839 now verifies across all three settled
branches, with varied related gains of 400–600 cp. 1841 remains ambiguous because
its settled branches genuinely disagree about primary Pin payoff.

`ThresholdReviewService` reuses the shared bounded request/evidence service. The
unchanged 150 cp Pin threshold has a settings-driven 15 cp review margin: evidence
in [135,150) may request one depth-22 confirmation. Before/played/tactic scores must
be comparable, the confirmed improvement must still reach 150 cp, and the existing
Pin proof, material/evaluation limits and horizon must all pass. Subsequent proof
uses the confirmation profile consistently. Missing, unsettled, budget-exhausted
or mate-valued evidence is protected; no threshold discount, repeated search until
passing, or weaker-evidence fallback is allowed. Root Quality Gate and Scale policy
are unchanged. No other analyzer opts into this mechanism.

1838's improvement changed from 146 cp at depth 18 to 156 cp at depth 22; both
approved defenses settle with 100 cp supported absolute-Pin payoff, so it now
verifies as a proposal. Three cases entered review: two passed the score comparison,
one ultimately verified, one remained unsettled and one deferred on mate evidence.
None remained rejected; passing a score comparison alone did not create a candidate.

Final disjoint reporting counts: **3 verified, 15 rejected, 2 ambiguous/deferred,
13 incomplete bounded proofs, 0 errors**. The existing proposal API retains all
15 unresolved cases as `ambiguous`; no coverage status was added. One change was
solely primary/secondary separation (1839). Protected 1835/1836 remain unchanged:
rook pressure / legacy pawn win is clearer for 1835; check/double attack with a
secondary/context pin is clearer for 1836. No stored interpretation was rewritten.

Settings are exported through shared `SettingDefinition` metadata, including ID,
label, default, range/options, description, basic/advanced level and identity impact.
See [the shared Pin settings definitions](../pin_analysis_settings.py).
`pin_backbone.motif_consensus` defaults to `primary_causality` (`all_motifs` is the
explicit old diagnostic policy). `boundary.enabled=true`, `margin_cp=15` (0–100),
`max_requests=64` (3–256, including hits), and `policy_version=1` affect interpretation
currentness only. `boundary.confirmation` is the shared one-line generator with
depth 22, Stockfish 18, Threads 1 / Hash 64; its engine settings affect exact raw
identity. Confirmation must increase depth while matching the base request's
other engine settings. Changing margin or consensus does not duplicate raw evidence.
The typed profile remains suitable for a future Admin Console and contains no UI
imports. Live `PinPolicy`, analyzer version 2 and registry dispatch are unchanged.

First pass: 1,093 cache hits, 40 misses/searches, 40 new scratch rows, 105.91 seconds
including the primary-only cache comparison. Rerun: 1,133 hits, zero searches or
writes/churn, identical results. Six verified branch proofs legally replay with
matching material totals. Full suite: **350 passed**. Database byte-identical;
quick_check ok, foreign_key_check empty; all 942 IDs, 11 training attempts, 34,982
coverage rows and both live caches unchanged. No historical scan, schema change,
other analyzer migration, Game Review change or live activation. Bounded proof is
not exhaustive: future activation must preserve unresolved/protected candidates.
