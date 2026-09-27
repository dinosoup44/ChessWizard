# Adding an analyzer

## Keep feedback separate from analysis

Store verified outcomes, motif attribution, proof and presentation level in
TacticalOpportunity. The shared `feedback` context builder and generator provide
default outcome-first wording; no tactic-specific Game Review branch is needed.
Do not import feedback/UI into analyzer calculations. Do not invoke analysis or
replay positions from feedback adapters. Missing facts remain unknown.

For legacy metadata, register a trusted adapter returning `LegacyEvidence` and
source-labeled `FeedbackFact` values. Only supported/verified primary motifs may
supply causal explanations; context-only and unknown attribution are not promoted.
New wording/styles belong in template providers, not analyzer thresholds or proof.
Test the resulting context and all relevant styles. The
[Feedback Generator guide](FEEDBACK_GENERATOR.md) documents stable interfaces and
the provisional data-only pack contract. Community packs cannot supply adapters.

## Analyzer contracts

For an upgrade that verifies **existing candidates**, use the separate
`candidate_verification` service/registry rather than running discovery again.
Require a stored candidate ID and tactical move in the calculator contract.
Keep read-only preview and explicit ID-preserving reconciliation distinct.
`tactical_target_proof` supplies identity/exchange accounting; do not infer target
realizability from geometry alone. Preserve ambiguous candidates, deferred mate
evidence, training anchors and unknown/newer detector versions. See
[Fork V3's targeted workflow](MISSED_FORK_V3.md).

Use the contracts and coverage rules in [ARCHITECTURE.md](ARCHITECTURE.md).
Add trusted application code through the registry; community theme packs cannot
supply executable analyzers or dynamic plugins.

For line-tactic examples, compare [Skewer V1](MISSED_SKEWER_V1.md), Pin V2 and
[X-ray V1](MISSED_XRAY_V1.md).
Use shared `board_analysis.direct_slider_lines` for raw attacker/front/rear
contacts and `tactical_line_proof` for identity tracking and exchange accounting
when that contract fits. Keep target-importance and causal-attribution policy in
the specialist; X-ray does not import Skewer's private rules.
The generic tracker is conservative: it credits original-ray captures or a
direct rear-target exchange/recapture, not arbitrary later material gains.

`board_analysis.new_slider_move_lines` enumerates new legal moved-slider contact
pairs without target-value policy. `tactical_line_proof.trace_blocker_resolution`
observes captures, removal, forcing/quiet blocker moves and conservative rear
payoff accounting. `tactical_material` supplies an injected `EvaluationSession`,
explicit `MaterialPolicy` and structured `MaterialAssessment`. These additive
services let a new specialist compose shared work while leaving existing
specialists' calculations and version identities unchanged.

For optional cross-motif ownership protection, set
`deduplicate_opportunities=True` on the registry definition. The generic
repository preserves another candidate for the same move and solution rather
than creating a new label-driven duplicate. It records completed no-hit coverage
with `existing_opportunity_owned`, retaining the evidence and owner reference.
This is not motif merging, a schema migration, or permission to reconcile old
candidates. The default is false for compatibility with existing analyzers.

## 1. Implement calculation and an adapter

Keep calculation, engine access, and database persistence separate. A specialist
calculates one supplied move/position, through an injected evaluator. It must not
open a database, select games, launch an engine, run a legacy launcher, or write
candidate/coverage/training rows.

Compose the public [board-analysis primitives](BOARD_ANALYSIS.md) for geometry,
attack maps, piece safety, line relationships, mobility, and king safety.
Keep tactic-specific target selection, thresholds, and verification in your
specialist. Add generally useful board facts to the shared library with tests
rather than copying another tactic's board logic. Geometric attacks are not
legal captures; structural safety observations are not tactical proof.

The registered adapter has this interface:

```python
from analysis_results import HeavyResult

def new_adapter(row, positions) -> HeavyResult:
    # Implement your public single-position calculator separately.
    result = calculate_one_move(row, positions.position)
    if result.candidate is None:
        return HeavyResult("analyzed_no_hit", details=result.details)
    return HeavyResult("candidate", result.candidate, result.details)
```

This is an interface sketch: `calculate_one_move` and its result type are yours
to implement. A failed calculation must raise or return `HeavyResult("error",
details=...)`; never turn failure or missing evidence into `analyzed_no_hit`.
The dispatcher catches exceptions and stores retryable error outcomes.

`row` provides move/game IDs, move numbers, player color, played SAN/UCI,
before/after FEN, source identifiers, and usernames (full field list in the
architecture checkpoint). `positions.position(fen, profile_name)` returns shared
cached engine evidence. Use registered profiles; do not access service internals.
Scores are White POV. Convert both positions to the same player's POV with
`score_for_color`. Include useful reasons, cache references, and evidence in
JSON-serializable details.

A candidate payload must supply:

```text
candidate_status, confidence, detector_version,
solution_move_uci, solution_move_san, solution_line,
notes, metadata_json
```

`metadata_json` is a JSON string; `detector_version` must match the registry's
`analyzer_version` when converted to a string. Supply a legal solution move,
matching SAN, and a verified solution line. Do not assign `candidate_id` or
persist the payload. The repository finds the canonical `(move_id, tactic_type)`
and preserves its ID. `rejected` is a repository reconciliation outcome, not an
adapter return state.

### Optional tactical meaning

New specialists may also return `HeavyResult(..., opportunity=...)` using the
[shared tactical opportunity contract](TACTICAL_OPPORTUNITIES.md). Populate an
outcome separately from motifs, assess attribution per motif, and state proof
timing/scope and presentation level explicitly. Use unknown/None for unproven
evidence. The generic repository handles serialization in existing metadata and
canonical proof-field reuse; do not write the reserved JSON key in an adapter.
No existing analyzer must be rerun or changed merely to adopt the optional type.

## 2. Supply a screener, scout, and configuration identity

- `screener(row) -> bool`: True continues. False is allowed only for a safe
  static rejection. If no safe screen exists, use `pass_through_screen` and set
  `has_safe_screener=False`.
- `scout(row, evidence) -> ScoutResult`: return `send_to_heavy` and a reason.
  Use `evidence.position(fen)` or `evidence.for_player(row, after=False/True)`.
  A false result becomes `scouted_out`, with no claim of heavy analysis.
- `scout_config() -> str`: return deterministic canonical JSON containing the
  actual profile/evidence identity, engine options, and decision thresholds.
  The current `analysis_scout.scout_config(**thresholds)` helper describes the
  shared 10,000-node scout profile. Do not claim a different budget while still
  using that fixed-profile evidence service. A new budget requires a reusable
  service/profile extension, not direct engine access inside the scout.

## 3. Register the definition

Import your public functions in `analysis_registry.py`, then add an entry:

```python
ANALYZERS["missed_new_tactic"] = AnalyzerDefinition(
    analysis_type="missed_new_tactic",
    label="Missed New Tactic",
    screener_version="0",
    analyzer_version="1",
    has_safe_screener=False,
    screener=pass_through_screen,
    scout=new_scout,
    scout_config=new_scout_config,
    heavy=new_adapter,
    scout_version="1",
)
```

The registry key and `analysis_type` must match and remain stable. Start version
identities explicitly. Bump screener/scout/heavy versions for changes to their
respective logic; configuration changes must change the canonical config string.
Heavy evidence/verification changes must be reflected in analyzer versioning,
not only in cache settings. Reuse profiles or add versioned profiles to
`engine_cache.PROFILES` when distinct evidence is necessary.

No tactic-name branches are needed in the crawler, dispatcher, or repository.
Registration makes an analyzer available to registry-driven planning/dispatch;
it does not authorize a live run. Current heavy validation modes use all
registered definitions in the pinned scope.

`missed_pin` is a concrete example: `pin_geometry.py` supplies static geometry,
`pin_scout.py` supplies the scout/config, `analyze_pins.py` supplies calculation,
and `pin_adapter.py` connects it to the position service. Only registry wiring
is tactic-specific infrastructure. See [MISSED_PIN_V1.md](MISSED_PIN_V1.md).

## 4. Test before a controlled rollout

For bounded material proofs, `tactical_proof.verify_bounded_line` is a reusable
calculator with injected evaluation and material values. It rechecks selected
best replies, enforces a payoff window, and reports bounded settlement. Keep
motif attribution in the specialist (see `pin_attribution.py`); generic material
gain does not establish causation. Reuse the shared TacticalOpportunity contract
and generic repository rather than copying Pin V2 result persistence.

Curated engine validation can use `DryRunPositionAnalysisService` through the
dispatcher's optional `position_service` injection: live-cache reads and scratch
cache misses remain separate. This does not authorize historical runs. See
[MISSED_PIN_V2.md](MISSED_PIN_V2.md) for exact proof limits and ownership.

Use synthetic positions, injected evaluators, and temporary/in-memory databases.
Cover positive detection, no-hit, legal solutions, both colors/score perspective,
failed or missing evidence, cache reuse, and the new scout's rejection boundary.
Exercise integration through `dispatch_heavy` and `save_heavy_result`: canonical
ID reuse, atomic rollback, training-link preservation, scope rejection, current
coverage skip, error retryability, and an unchanged second run. Existing examples
are in `tests/test_heavy_services.py` and `tests/test_negative_coverage.py`.

Run the full suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

For an authorized live rollout, preview and pin a small scope, create a verified
SQLite backup before writes, record the exact queue and candidate IDs/counts,
and use the central crawler. Compare IDs, training history, outside-scope data,
duplicates, cache activity, and integrity checks; rerun to prove idempotency.
Do not use standalone analyzer launchers or clear/delete/reinsert helpers.

Existing current candidate/rejected coverage is independent of scout metadata,
including scout version `0`. Also note the current planner protects stale heavy
rows and canonical candidates rather than automatically refreshing them.
Repository `reconcile_stale=True` is available for explicit controlled handling;
it is not enabled by ordinary registry registration or a version bump.

For a separately authorized **no-hit-only** version refresh, the central crawler
supports `--heavy-test-10 --analysis <one-type> --refresh-no-hits-from <version>`.
After approval to expand, use `--heavy-validation-500` in place of
`--heavy-test-10` to process the exact saved 500-game scope.
This is distinct from candidate reconciliation: the planner selects source-version
no-hits with current upstream metadata, and the repository atomically verifies
their eligibility and absence of a canonical candidate. No screener/scout work
or negative writes are included. Existing candidates remain protected even when
stale; all-game execution and scope filters remain rejected. See the Pin V2 rollout
documentation for a concrete example and audit requirements.

Fork V2/Mate V3, Pin V2 and Skewer V1 have saved-500 rollout evidence. X-ray V1
has synthetic gold validation and a read-only saved-500 preview; existing-evidence
preflight reduces its 3,489-check queue to 2,213, pending heavy-rollout approval.
New specialists need their own controlled validation;
all-games heavy execution is not enabled. Synthetic positive contract fixtures
must be distinguished from engine-confirmed positives in every validation report.

## Optional existing-evidence preflight

Leave `AnalyzerDefinition.preflight_existing_evidence=None` unless a specialist's
safe policy has been independently validated. Currently only X-ray V1 opts in.
Register a public function in the specialist's own `<tactic>_preflight.py`:

```python
def preflight_existing_evidence(row, context):
    # context: PreflightContext(analysis_type, analyzer_version, positions, ownership)
    lookup = context.positions.position(row["fen_before"], "tactic_quick_v1")
    # lookup: ExistingEvidence(available, reason, key, record)
    return PreflightResult("heavy_required", "insufficient_existing_evidence", {
        "analyzer_version": context.analyzer_version,
        "evidence_key": lookup.key,
        "availability": lookup.reason,
    })
```

The generic planner invokes the hook only for pending scout-positive checks.
Use `context.positions.identity(profile)` for profile/config provenance and
`context.ownership.owner(move_id, analysis_type, solution_move_uci)` for another
canonical owner. These services expose no engine fallback or persistence API.
Do not import a write-capable engine service into a preflight policy.

Return `PreflightResult(disposition, reason, provenance)` with JSON-serializable
diagnostics. Supported dispositions are `heavy_required`, `cached_quick_rejected`,
`mate_deferred`, `already_owned`, `played_checkmate`. They describe the current
plan only; never save them as static, scout, or heavy coverage. Missing, stale,
incompatible or unresolved evidence must retain work. Exceptions retain work and
are reported in preflight error counters.

Read current evidence and ownership on each plan; do not cache dispositions.
Record analyzer/policy/profile/config identity, evidence IDs/keys, and missing
reasons. Engine options are not separately encoded in existing cache rows;
the read-only provider accepts the established Threads=1/Hash=64 contract only.
Change profile identity/version when changing its configuration; do not silently
reuse old evidence. The repository must still recheck ownership transactionally.

Test complete rejection, one survivor, incomplete/incompatible evidence, policy
and ownership changes, no fallback, no DB writes, and every positive gold case.
Run the full regression suite and compare an exact saved-scope read-only preview
with its prior queue. Geometry, proof behavior, and other analyzers remain outside
the scope of enabling a preflight hook. See
[the X-ray preflight checkpoint](MISSED_XRAY_V1.md#existing-evidence-preflight-checkpoint).
## Optional candidate-line adoption

New work can opt into the shared [CandidateLineSet pipeline](CANDIDATE_LINES.md).
Do not silently migrate an existing specialist. Use `LineAnalysisService` with an
injected `CandidateLineService`, a typed `AnalysisProfile` and explicit evidence.
Inspect the Quality Gate state, then consume retained/weighted lines. A critical
fallback is an analysis opportunity, not a proved motif; incomplete evidence needs
a retry or explicit review.

Keep calculation, engine access and persistence separate. Prove each motif through
shared proof/board services, return a `TacticalOpportunity`, and use the existing
ID-preserving repository path. Interest weight must never replace tactic confidence.
Add event providers through a stable ID/version and `events(line, facts)` interface,
without importing another analyzer's private implementation.

For fixed-candidate verification, top-N omission does not disprove the stored move.
Alternative defenses are child-position line sets. Fork V3 now provides the first
read-only example in `analyze_forks_v3_multiline.py`, selected by the explicit
`multiline_fork_verifier(profile)` factory. Its adoption does not replace discovery
or the default single-line verifier.

For the next specialist, follow the same structure:

1. Accept a selected record, injected shared line service and typed profile.
2. Use `admit_required_move` for fixed-move verification; preserve native versus
   supplemented comparison rank and incomplete/critical evidence.
3. Consume approved root/child sets through the shared service. Keep tactic proof
   separate from objective acceptance; do not duplicate the gate.
4. Compose shared board/settlement helpers and a small explicit consensus policy.
   Document exactly which plies branch and what remains bounded or unknown.
5. Return structured proposals with profile identity, attribution and conservative
   evidence. Scale ranks interest only; it cannot resolve proof disagreement.
6. Add an opt-in registry factory, contract/gold regressions and candidate-only
   scratch preview before any separately authorized persistence integration.

Use `ApprovedPositionEvidence` where the shared bounded proof callback is suitable;
do not import another specialist's private calculation helpers. Other analyzers
remain on their existing paths until independently approved. A future Admin
Console must consume the same `AnalysisProfile` schema/loader. All of this works
without Tkinter; desktop/mobile frontends consume the same core service.

## Persistent candidate-line cache boundary

The live `engine_candidate_line_cache` table has passed an eight-request cache-only
rollout and a zero-write/search rerun. Its existence does not authorize live
specialist adoption. Fork reconciliation and migration of other analyzers remain
separate tasks. See [the schema and migration procedure](CANDIDATE_LINES.md).

Inject `CandidateLineService` with explicit `CandidateLineRepository` read/write
stores. Do not migrate on construction or import. The caller owns transactions;
cache-only tools can install `insert_only_authorizer` after schema validation.
Exact hits deserialize/legal-validate stored lines; misses insert complete evidence
once. Existing row IDs/timestamps remain stable, and old single-PV rows are not
reinterpreted as MultiPV. Never add tactic-specific SQL or cache keys.

Use the shared generator settings for raw identity, including budgets, engine
options and restrictions. Gate/Scale/proof changes alter result-currentness, not
raw cache identity. A future Admin Console consumes this same profile schema.
Test setting separation, FEN separation, restrictions, legal/SAN roundtrip,
mate ownership, immutable values, unsupported schemas, no timestamp churn and UI
independence. Future cleanup needs a separate explicit retention/backup plan;
cache reads must not acquire hidden persistence side effects.

## Adopting shared proof escalation

Use [PROOF_ESCALATION.md](PROOF_ESCALATION.md) as the shared contract. Supply exact
approved entry moves and a documented unresolved/disagreement reason to one
`ProofEscalationService` per candidate. Inject the shared line service; do not add
engine processes, cache keys, SQL or private imports from another specialist.

Interpret returned bounded evidence with your own established tactic accounting.
Retain every original branch and protect remaining disagreement, incomplete
evidence, budget exhaustion and mate ownership. Scale interest must not trigger
or override proof. Test limits, cache identity/reuse, exact prefix legality,
countercaptures, unresolved cases, failed admission and UI independence.

Use an opt-in registry factory and candidate-only preview before separately
authorized live adoption. Fork V3.1 is the example; Pin/Skewer/X-ray/Mate have not
been migrated. Keep calculation, engine/cache service and ID-preserving
persistence separate so another contributor can follow the same structure.

## Use the consolidated backbone

Start with [ANALYSIS_BACKBONE.md](ANALYSIS_BACKBONE.md) and the Fork V3.1 reference.
Construct one `AnalysisBackbone` per candidate. Request/admit shared breadth, select
approved motif-relevant branches, lazily submit unresolved requests through
`escalate_selected`, interpret evidence, then return structured proposals. Keep
geometry, attribution and payoff consensus in the specialist; do not copy cache,
gate or budget loops. Include analyzer/interpretation policy in `provenance(...)`.

Preserve explicit ambiguity and execution errors. `verification_result(...)` is an
opt-in bridge for legacy HeavyResult ambiguity, not a coverage migration. The
[Pin checkpoint](PIN_BACKBONE_MIGRATION.md) documents the second adapter, direct
settings mappings, admission-policy differences, protected data and regressions.

## Second-adopter example: Pin V2

Compare `pin_backbone.analyze_existing_candidate` and
`candidate_verification_registry.pin_backbone_verifier` with the Fork factory.
Both accept one candidate and injected shared line services. Additive factories
do not activate discovery or persistence. Pin demonstrates that shared plumbing
can preserve a different specialist proof contract: approved entries compose the
existing per-ply verifier instead of copying a proof loop or forcing Fork rules.

Keep original thresholds in typed Settings with SettingDefinition metadata when
they are not equivalent to gate policy. Record their identity separately from raw
engine requests. Use recorded equivalence, then curated scratch evidence; never
alias an old cache row whose request options are unknown. Preserve ambiguity and
outcome-first feedback; return proposals to generic persistence only after live
approval. Follow [the completed Pin checkpoint](PIN_BACKBONE_MIGRATION.md) when
planning Skewer/X-ray adoption.

## Reusing boundary confirmation and consensus contracts

If a specialist has a numeric comparison distinct from the shared Quality Gate,
keep that threshold in typed specialist settings. An explicitly approved
`ThresholdReviewSettings` can compose one `ThresholdReviewService` per candidate
with the injected line service and base verification profile. Call `review_gain`
only for the configured near-boundary interval. `comparison_passed` permits the
specialist's full proof; it is not a verified tactic. Reuse the returned stronger
backbone for subsequent evidence so scores and proof depth remain comparable.
Defer mates and preserve incomplete/budget-limited proof. Never relax the threshold
through Scale, retry until it passes, or put tactic-specific admission in Quality
Gate. This is opt-in policy and requires its own curated regression evidence.

Separate primary causal agreement from optional annotations. Preserve every
branch's motifs and attribution, including context-only evidence. A summary may
select a representative conservative payoff, but secondary motifs on that line
must not be presented as universal consensus. Genuine disagreement about primary
causality or retained payoff remains unresolved. Pin's `pin_consensus` is the
specialist example; do not import its private geometry rules into another analyzer.

Expose policy through the existing setting schema and include it in interpretation
currentness. Reuse raw evidence when only admission/annotation policy changes.
See [Pin migration](PIN_BACKBONE_MIGRATION.md) and
[proof escalation](PROOF_ESCALATION.md). No other analyzer has adopted these changes.

## Preserve evidence across escalation

Use shared `ProofEscalationResult` properties for attempt disposition and evidence
state; do not store a budget denial in a branch's proof state. Retain established
proof when a recheck fails, record the unsuccessful attempt separately, and
propagate operational failures as failures. A stronger unfinished line is evidence
for review, not permission to invent settlement. Use `retained_branches()` when
reading historical overwritten Fork payloads; never rewrite stored candidates as
part of that read adapter.

Inspect terminal board facts before asking for a best continuation. A complete
terminal cache response needs no PV. Mate-valued scores on nonterminal boards are
not terminal boards. Route terminal/mate ownership explicitly; geometric motifs
must not appropriate Mate outcomes.

Reuse `proof_endpoint_facts.collect_endpoint_facts()` for factual legal-replay
audit data rather than embedding board/material logic in a specialist or UI.
Existing target-accounting helpers can supply their documented conservative
ledger. Neither target disappearance, unrelated net gain, nor a legal recapture
list is a complete semantic-settlement proof.

Keep the future boundary clear: raw line → factual endpoint evidence → future
semantic settlement → analyzer interpretation. The first two stages are usable
without Tkinter or persistence. Do not implement the future settlement stage by
quietly making an audit fact an admission predicate. Window/profile changes alter
result currentness while identical raw engine requests retain their cache identity.
See [proof escalation](PROOF_ESCALATION.md) and
[proof lifetime and settlement validation](PROOF_ESCALATION.md#proof-lifetime-and-attempt-disposition-2026-09-08-cleanup).

## Opting into selective settlement

Keep normal proof and optional extension separate. Supply the shared typed
`SettlementExtensionContext` with admitted-root evidence, explicit blocker states
and provenance. Call `settlement_extension_eligibility()` on the actual normal
proof, then `ProofEscalationService.extend_settlement()` only for an eligible
checkpoint produced by that same service. Do not infer eligibility from ambiguity
or reconstruct a fresh unrelated proof. Do not reset branch or request budgets.

The specialist owns causality and ownership decisions. The shared predicate checks
the exact source window and complete evidence. Stable, mate/draw, operational error,
primary budget denial, incomplete evidence or settled disagreement must not become
extension triggers. An eligible result can still reject, remain ambiguous or defer;
no score/interest reward exists for finishing a proof.

The settings schema exposes `escalation.settlement_extension.enabled` (false by
default, basic), `policy_version` (1), `source_settlement_plies` (8) and
`target_settlement_plies` (12), with advanced fixed options for the latter fields.
All affect result currentness. No frontend-specific configuration path was added.
Opt-in specialists use explicit 8/12 verification namespaces, preserving breadth
identity. Legacy raw evidence is reusable only through the exact compatibility
adapter, with source provenance and no cache rewrite.

Use `evidence_approvals()` when assembling provenance so extension evidence cannot
be omitted. The portable `fork_selective_cache.json.gz` fixture supplies 45 real
cases and exact raw evidence; tests run without the production database, engine or
Tkinter. Do not enable this policy for another analyzer merely because its proof
uses the same service; add the analyzer's explicit blocker/ownership contract and
regressions first. See [proof escalation](PROOF_ESCALATION.md).

## Consume shared position/range facts

Before adding local material, identity, or recapture bookkeeping, consult
[`position_range_evidence`](POSITION_RANGE_EVIDENCE.md). `analyze_range` composes
immutable facts; `LegalReplay` reuses the same ledger for endpoint or targeted
intermediate queries. Track original squares, not pieces inferred from endpoint
squares. Use configured material values and distinguish geometric attacks from
actual-side legal captures. Missing repetition history and unavailable capture
queries are explicit unknowns, not negative evidence.

Keep raw facts separate from the specialist's admission, causality, ownership, and
settlement policy. A legal recapture is a possibility, not an engine-selected reply.
This toolkit neither invokes an engine nor persists evidence. Existing adapters
remain unchanged; adopting these facts requires an independently validated change.

### Functional threats and optional exchange presentation

A geometric attack is not an executable capture. Fork specialists can compose
`fork_threats.functional_fork_threats` before admission; do not redefine shared
attack maps. Separately, `exchange_presentation` can produce immutable exchange
detail from an exact supplied continuation. It must not change the short answer,
proof verdict or engine settings. Feed its validated model through FeedbackContext;
frontends render FeedbackResult without calculating chess facts or searching.
See [FORK_PASS_2_CONTRACTS.md](FORK_PASS_2_CONTRACTS.md) before adopting either
contract in another analyzer or a frozen experimental replay path.


## Optional conservative completion contract

An analyzer may opt into durable preflight receipts with `deferred_contract`, a pure
callback returning its exact policy/version/request identity. The existing
`preflight_existing_evidence` must return a complete supported predicate plus full
provenance; the shared typed completion allowlist alone is not write authorization.
The repository rechecks the predicate transactionally before persisting.

Do not add tactic-name branches to the crawler or UI. New stable reasons need an
explicit contract, complete dependency capture and invalidation/cancellation tests.
Unknown/mixed/missing outcomes remain pending. Never repurpose candidate/no-hit/error
coverage for uncertainty. Existing analyzers need not opt in, and heavy result states
are unchanged. See [DEFERRED_ANALYSIS_OUTCOMES.md](DEFERRED_ANALYSIS_OUTCOMES.md).
