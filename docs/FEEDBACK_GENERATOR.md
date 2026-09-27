# Feedback Generator V1

## Approved-line proof proposals

Fork V3's read-only multi-line proposals use the generic
`approved_counterplay_branches_v1` realizability scope. The opportunity adapter
renders geometric targets separately from `counterplay_status` and
`counterplay_material_range` facts. Counts and material ranges refer to settled
branches; an unfinished branch is not silently assigned a material result.
`verification_status` describes a root rejection or missing consensus when no
branch summary exists. Wording remains conservative when targets/payoffs disagree.

Only verified consensus may supply a representative retained payoff. An ambiguous
proposal clears the inherited legacy proof rather than presenting it as current
multi-line evidence. Templates consume these shared facts without engine access,
analyzer calls or UI-specific state. The example data-only feedback pack includes
the new template keys. Live candidates and Game Review are unchanged by preview.

```text
stored candidate / verified opportunity
 -> FeedbackContextBuilder + legacy adapter registry
 -> FeedbackContext
 -> FeedbackGenerator + template provider registry
 -> FeedbackResult
 -> Game Review / future training, alerts, reports and other consumers
```

Chess facts, wording and UI rendering have separate owners. The `feedback/`
package imports no engine, board-analysis, database, UI or network service. It
never calculates chess conclusions. Consumers obtain records through their read
service, build a context, then render the result.

```python
from feedback import FeedbackContextBuilder, FeedbackGenerator

context = FeedbackContextBuilder().build(candidate_row)
result = FeedbackGenerator().generate(context, style="concise_review")
print(result.title, result.explanation)
```

## Contracts and source priority

`FeedbackContext` is a frozen dataclass. Optional identity, moves, outcome,
motifs, timing, relationships, confidence and presentation fields stay absent
when unknown. It reuses `TacticalOutcome`, `TacticalMotif`, `ProofEvidence` and
`LineRelationship`; TacticalOpportunity's schema is unchanged. Proof holds
material/evaluation evidence with explicit perspective. JSON snapshots retain
source, legacy and opportunity extension metadata without mutable aliases.

1. A valid TacticalOpportunity owns outcome, motifs/attribution, timing,
   relationships, proof and presentation level. Legacy conclusions do not fill
   its unknown fields, avoiding superseded interpretations.
2. Without one, registered legacy adapters normalize recognized metadata only.
3. Canonical candidate/move columns supply identity, played/solution moves and
   proof. Missing canonical fields can use recognized legacy equivalents.
4. Without richer evidence, return a plain stored recommendation and tactic label.

Canonical move/proof identity remains authoritative. Conflicting or invalid
opportunities fall back with provenance warnings, never replacing canonical data.
Malformed optional metadata does not trigger repairs. Notes remain source data;
they are not interpreted as structured chess facts. No historical backfill occurs.

`FeedbackResult` supplies title, short summary, explanation, outcome/motif labels,
separate context-only labels, played/recommended labels, optional proof summary,
presentation/detail levels, optional teaching/warning notes and provenance.
Proof is separate so UIs can keep it collapsed.

## Deterministic wording

Built-in styles: `concise_review`, `teaching`, `alert`, `summary`. Identical
context/style/provider inputs produce identical results. Templates receive
selected fact values; they do not calculate or replace them.

Modern feedback is outcome-first. Only an explicitly supported/verified primary
motif supplies its stored causal rationale. Supported secondary motifs remain
labels. Context-only motifs are separate; unknown attribution produces no causal
language. An unknown modern outcome gets a neutral title rather than promoting
a contextual motif through the candidate's tactic label. Arbitrary presentation
prose is not blindly reused: outcome, attribution and level drive selection.

For modern candidates with a stored proof, concise wording now prefers the
concrete outcome plus a short canonical SAN continuation over an abstract
analyzer rationale. It does not infer that a particular shown move caused the
payoff; omitted later moves are marked with an ellipsis. Supported rationale is
the fallback when no stored continuation exists. Context-only rules still apply.
FeedbackResult also exposes canonical `proof_line`, `attribution_labels` and
`relationship_labels` for complete, generic UI rendering. Legal replay is handled
by the separate `StoredLine` read model, not by feedback generation.

Teaching adds recorded relationships, timing and numeric evidence. It does not
infer that a pinned piece has no legal moves, a capture is net profit, or a bounded
proof answers every defense. Evaluations retain stage, units and perspective;
fork conversion is not relabeled as settlement. Material and evaluation differ.

## Legacy adapters

Verified target-settlement opportunities may provide `geometric_targets`,
`realizable_targets`, `target_captures` and `realized_payoff` under opportunity
metadata, with `realizable_scope=observed_bounded_best_defense_line_only`.
`feedback/opportunity_facts.py` normalizes these stored facts, including exact
capture SAN/square and signed net/balance centipawn values. The generator labels
attacked pieces separately from captured pieces and settled payoff. It does not
derive them from geometry or replay. A context-only fork stays secondary even
when the stored move retains an initial pawn capture through equal exchanges.

`feedback/adapters.py` owns trusted application adapters:

- Fork: stored targets, realization reply/capture/target, classification. Numeric
  evidence requires the known `fork_v2_post_conversion` schema and player color.
  No net material gain is inferred from a captured piece.
- Mate: canonical solution and line. No distance is guessed from notes, SAN or
  line length. Upstream `TacticQuery` retains episode-primary selection; a pure
  builder does not decide visibility or deduplicate an arbitrary input batch.
- Pin V1: stored piece types/square indices, relation type, explicit player
  evaluations and retained gain. No immobility claim.
- Skewer: legacy `skewer` object with `attacker`, `front`, `rear` piece/square
  records. Current Skewer V1 and X-ray rows use TacticalOpportunity.
- Unknown tactic: canonical fallback until a trusted adapter is registered.

Adapters return `LegacyEvidence` / `FeedbackFact`, not prose or DB writes. They
must not import analyzers or derive facts by replaying positions.

## Game Review and extension points

`TacticReadService -> present_candidate -> FeedbackContextBuilder ->
FeedbackGenerator` supplies `TacticalMoment.feedback`. Existing convenience
fields remain compatible. `TacticalMomentsPanel` renders the result's labels,
explanation and proof summary. Visibility, filters, episodes, move-ID/FEN mapping,
orientation and navigation remain unchanged. Reopen an existing desktop process
to load changed Python modules; this task does not restart a window in use.

- New analyzer: store facts in TacticalOpportunity; default feedback needs no
  UI edit. New vocabulary gets a humanized label until curated wording is added.
- Legacy source: register an adapter in `LegacyAdapterRegistry`, inject it into
  the builder, and test source fields, missing values and conflicts.
- Style: add a data entry using supported summary/evidence modes. A new kind of
  layout may extend the provider contract without analyzer changes.
- Provider: register a trusted `TemplateProvider` in `FeedbackRegistry`; select
  its pack ID. `DataTemplateProvider` copies and validates JSON-shaped data.
- Consumer: accept `FeedbackResult`. Pattern/repertoire contexts may construct
  `FeedbackContext` directly without candidate IDs.

## Provisional packs and security

See [draft schema](FEEDBACK_PACK_V1.schema.json) and
[complete built-in example](feedback_pack_v1_example.json). These are provisional,
not a community installation API. Fields: `schema_version`, `pack_id`, `name`,
plain-text label maps, `templates`, `styles`. Template keys and placeholder sets
must match the V1 contract. Only simple named placeholders are accepted: no
attribute/index access, format specifications, conversions, expressions,
conditions, functions or imports. Styles select summary format, detail level,
evidence and teaching notes. Packs cannot override facts or attribution.

Future external packs must be **data only**, initially an explicit `.json`
allowlist. Never allow `.exe`, `.com`, `.dll`, `.bat`, `.cmd`, `.ps1`, `.py`, `.pyw`,
`.js`, `.vbs`, `.jar`, `.msi`, `.scr`, `.reg`, `.lnk`, scripts or dynamic plugins.
No installer/import UI exists. A future importer must validate every entry, size
and count limits, paths and manifest/schema; reject unknown types, nested archives,
absolute/traversing paths and symlinks. Never execute pack content. Assets/icons
would require an explicitly approved safe asset contract.

Data-only validation cannot prove arbitrary prose is factually faithful. External
wording needs semantic review and fact-fidelity tests before activation. V1 accepts
trusted application providers only; it does not declare untrusted JSON prose safe.

## Future persona distinction

A feedback pack controls wording/presentation of verified facts. A chess persona
or bot profile could describe openings, tactical tendencies, aggression, pawn
structures, sacrifices, time-control behavior or historical style. These are
separate responsibilities. No persona/bot modeling is implemented here.

## Validation and limits

Run `python -m unittest discover -s tests -v`. Tests cover source priority, all
current tactics, attribution, four styles, determinism, missing/conflicting data,
provider/adapter extension, template validation and no engine/DB/network access.
Existing widget tests exercise filters, jumping, proof expansion and episode behavior.

`python reports/build_feedback_examples.py` opens the live DB read-only/query-only,
blocks engine/network calls, checks IDs/counts/hash/integrity and writes reports only.
See [real examples](../reports/FEEDBACK_GENERATOR_EXAMPLES.md).

Limits: no LLM, translation engine, importer, analyzer execution, arbitrary notes
parsing or proof revalidation. Legacy schemas are explicit. Modern feedback can
retain technical wording from a supported stored rationale. Missing historical
facts cannot be recovered by a feedback generator.
