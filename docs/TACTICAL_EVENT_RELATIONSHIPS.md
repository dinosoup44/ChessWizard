# Tactical event relationships V1

Status: **inactive portable representation and opt-in legacy adapter**. No analyzer,
production consumer, schema, setting or stored row is changed. No historical
scan, played-tactic detection, puzzle mode or statistics implementation is included.

> Analyzers identify the tactic.
> A separate relationship layer identifies whether the tactic was played,
> missed, played by the opponent, or missed by the opponent.

This is a permanent architecture rule. There must not be parallel permanent
MissedForkAnalyzer and PlayedForkAnalyzer frameworks.

## Inspection findings

| Layer | Current coupling | Future adaptation; not performed here |
|---|---|---|
| Registry | `analysis_registry.ANALYZERS` uses missed_fork/mate/pin/skewer/xray keys and Missed labels. Classes such as AnalyzerDefinition, HeavyResult and CandidateVerificationResult are already generic. | Separate motif selection from occurrence selection; preserve existing dispatch/version identities during transition. |
| Scope | `analysis_crawler` selects `m.is_user_move = 1`. | Explicit actor-side scope for a separately authorized pilot. Never infer perspective from UI selection. |
| Fork | V2 rejects an engine best move equal to the played move and compares gain versus played. `fork_discovery` enumerates unplayed geometry. V3 candidate verification requires missed_fork. V3.1's explicit-move path delegates to `analyze_forks_v3_multiline.analyze_position`, which rejects equality with uci_played. | Reuse Fork geometry, interpretation and proof services. Move the discovery-only exclusion into relationship/orchestration selection before a played pilot; do not disguise the actual move or fabricate fen_after. |
| Pin | `pinning_moves` excludes played_uci; Pin V2 compares quick, verified and settled values against the actual move. | Separate tactical proof from the missed-improvement question under a later explicit contract. Equality cannot simply be forced through improvement thresholds. |
| Skewer | `skewering_moves` excludes the played move; single-move proof and metadata retain missed_skewer identity. | Reuse geometry/proof, with occurrence-neutral selection and explicit evidence roles later. |
| X-ray | `xray_moves` delegates to shared slider enumeration with played_uci excluded. Preflight/ownership and metadata use existing missed identities. | Preserve proof/ownership contracts while later separating relation-aware planning. |
| Mate | Mate V3 deliberately returns no hit if the played move delivered checkmate or kept a forced mate. | A no-hit from missed-mate analysis does not mean no played mate. Reuse mate evidence with a separately scoped relationship classification. |
| Persistence | `tactic_candidates.tactic_type` contains missed_*; the repository's canonical lookup is (move_id, tactic_type). No UNIQUE constraint enforces that pair on the candidate table; duplicate handling is in services. `analysis_coverage` does enforce UNIQUE(move_id, analysis_type). | An additive occurrence representation must account for multiple tactical moves, actor and evidence identity without deleting/rekeying historical candidates. |
| TacticalOpportunity | Motifs, outcomes, attribution, payoff timing and piece-line relationships are already independent. ProofEvidence has played and tactical move fields, but line_san has no actual/counterfactual discriminator. Its `relationships` are board geometry, not event relationships. | Compose the new occurrence beside the existing opportunity. Do not reinterpret its proof as game history or change its schema. |
| Game Review | `TacticQuery` explicitly filters missed_*; filter text says Any missed tactic. TacticalMoment has played/suggested fields and one stored proof line. Feedback fallback says Missed and “you played.” | Future consumers must use explicit kind and perspective; existing presentation remains unchanged. Do not pass new played occurrences through missed-only fallback wording. |
| Review sets | ReviewSetEntry/HumanReviewCase retain tactic_type, color, proposed move and optional original audit classification, not event relationship. | Audit status (confirmed/unresolved/control), human verdict and event relation are three separate axes. Older reason labels must not be used to infer relation. |
| Training | train_mates uses missed_mate episode selection and a solution move. training_history anchors attempts permanently to candidate_id and copies tactic_type. | Future selection can support reinforcement and missed puzzles, while preserving all candidate/training links. No changes now. |

Shared board_analysis, Position/Range Evidence, tactical proof helpers, the
AnalysisBackbone, Quality Gate and The Scale already have useful reusable
boundaries. Their outputs and policy are untouched. Existing names/keys are
compatibility identifiers, not a mandate to duplicate future analyzers.

## Typed contract

`tactic_occurrences.py` contains frozen `TacticOccurrence`, `OccurrenceKind`,
`TacticColor` and derived `TacticOccurrenceRelation`. Kind is PLAYED, MISSED or
UNKNOWN. Actor and perspective are explicit WHITE/BLACK or absent. “User” is a
frontend label for the perspective side; it is not an implicit global setting.

| Kind | Actor versus explicit perspective | Derived relation |
|---|---|---|
| PLAYED | same side | PLAYED_BY_PERSPECTIVE |
| MISSED | same side | MISSED_BY_PERSPECTIVE |
| PLAYED | other side | PLAYED_BY_OPPONENT |
| MISSED | other side | MISSED_BY_OPPONENT |
| UNKNOWN, or either side absent | unknown | UNKNOWN |

Kind can remain known when perspective is absent. Unknown is never guessed from
move equality, names, a verdict or frontend state. There is no independently
mutable relation field that could disagree with kind/actor/perspective.

Fields identify motif (open snake_case vocabulary without missed_/played_
prefixes), source identity, optional candidate ID, decision position, actual
and tactical UCI moves, two optional line roles, proof-source reference,
original source verdict and immutable provenance. Source identity survives a
change of review perspective. Candidate ID is only an existing reference;
constructing an occurrence never allocates or reconciles it.

This wrapper records a **supplied motif claim**, not a new tactical verdict.
It does not grant admission, mark coverage complete, upgrade attribution or
replace TacticalOpportunity. Use the original proof/verdict separately when
selecting verified events. Move equality alone never proves a tactic.

## Actual versus counterfactual evidence

Both line tuples include their first move and use the same source position:

- PLAYED requires actual_move == tactical_move, an actor, a decision position
  and a nonempty actual_game_line rooted at that move. A one-move historical
  line records only that move; it does not claim the payoff occurred.
- MISSED requires different actual/tactical moves and a nonempty
  counterfactual_line rooted at the tactical move. An optional actual_game_line
  is separately rooted at the actual move.
- Every supplied line must be an immutable, nonempty UCI tuple with the proper
  root. Move-match state is derived, not supplied independently.
- A played root may ALSO have a counterfactual continuation: the actual reply
  may differ from the proof engine's reply. Matching the first move does not
  make the entire PV historical. Keep both roles separate.
- A proof-source reference is not an actual game line. Never fill historical
  continuation from solution_line or ProofEvidence.line_san.

The core enforces structural relationships and UCI shape, not chess legality,
FEN truth, continuation completeness or tactical proof. Callers must provide
correct source/actor data and legally validated evidence. Reuse LegalReplay
for legal/board validation; do not add replacement board logic to this model.
All line tuples supplied to the core are immutable; no engine/DB/Tkinter imports.

## Existing missed-candidate adapter

`tactic_occurrence_adapters.occurrence_from_legacy_candidate(row,
perspective_color=...)` is pure, explicit and **not called by production**.
The supplied row must include canonical candidate/game/move IDs, tactic_type,
candidate_status, fen_before, color, uci_played and solution_move_uci. Perspective
is a required argument, including explicit None when unknown; callers may obtain
it from validated games.user_color, never from “missed” or a widget.

Known legacy fork/pin/skewer/xray/mate codes map through one explicit vocabulary.
The adapter uses shared LegalReplay to validate both supplied root moves and
checks actor color against the decision board. It copies candidate_id and the
source verdict, and creates a candidate:<id> reference without changing the row.
It keeps only the separately labeled one-move actual/counterfactual prefixes.
Stored SAN proof is referenced as candidate:<id>/solution_line, not parsed,
regenerated or copied into game history. Detector version is retained in
provenance; this reference is not a new immutable proof hash/currentness scheme.

The returned OccurrenceAdaptation contains an occurrence or None plus a reason.
Unsupported/missing identities, unknown types, invalid boards/moves, inconsistent
actor, and inactive/unknown source statuses fail closed. candidate and historical
confirmed are accepted source-status vocabulary, not fresh proof. Equal actual
and solution moves on a missed row are contradictory: do not turn that legacy
row into a played event. Missing perspective alone yields UNKNOWN relation while
preserving the known missed kind. No inferred material/evaluation/motif truth.

## Storage limits and proposed direction

There is **no schema change or serialization migration**. The current candidate
lookup supports one canonical result per move/type and cannot cleanly distinguish
several tactical roots or occurrence kinds. Coverage completeness still describes
existing missed-only analyzers, not all played/missed possibilities. A missed-only
no-hit must never suppress a future played-tactic check.

If persistence is later authorized, prefer an additive occurrence table/view
with its own occurrence ID, move/position reference, motif, actor, occurrence
kind, tactical root, proof/evidence identity and optional legacy candidate_id.
Give actual/counterfactual lines explicit roles. Perspective is normally a query
view over actor, not part of canonical event identity. Uniqueness and coverage
scope must include the approved proof/move obligation; exact SQL is intentionally
not settled here. Preserve candidate IDs and training foreign keys. Do not
rename historical missed_* rows or conflate statuses with event relation.

## Future consumers (not implemented)

- Game Review: filter kind Played/Missed, actor relative to perspective Me/Opponent,
  and motif Fork/Pin/etc independently. UNKNOWN remains explicit. Use relationship
  wording only after source/proof admission; never label a played event Missed.
- Puzzles: select missed only, played only or both. Played events can support
  “You found this in your game” reinforcement, with separately verified puzzle
  solutions and hypothetical defense lines. Do not confuse the recorded reply
  with best-defense proof.
- Strength analysis: count found/missed motifs only over a deliberately defined
  eligible scope with consistent proof/currentness and actor perspective.
  Unknown, unexamined, rejected and unresolved data cannot silently enter either
  denominator. Supporting these questions does not establish coverage or recall.
- Pattern Engine/Critical Moment aggregation: consume the same occurrence and
  factual/proof contracts later. Neither gets new ranking or discovery logic here.

## Fork Played-Tactics Pilot readiness

**Ready as the next separately approved controlled task at the representation
level; the current Fork entry point is not a drop-in played analyzer.**

Before executing that pilot, isolate the unplayed-discovery guard from reusable
single-position Fork proof. Inspect gain-versus-actual and baseline assumptions
without changing tactical truth or bypassing Quality Gate, payoff/causality or
settlement checks. Add equivalence tests for all existing missed outputs and a
separate actual-root contract; do not fabricate a different played move merely
to pass the guard. Keep one Fork specialist/framework.

The pilot should use a tiny exact read-only scope, actual recorded root moves,
explicit perspective, shared services and isolated evidence if separately
approved. Keep recorded continuations distinct from counterfactual proof and
send results to human review as audit cases, not persisted candidates. None of
that selection, analysis or activation is performed by this architecture task.


### Played-Fork pilot checkpoint — 2026-09-11

The next approved task has now separated the guard: legacy `analyze_position`
keeps its unplayed-only check, while `evaluate_fork_move` in the multiline/V3.1
modules uses the same internal proof body for an explicitly selected legal move.
`fork_occurrence_adapter.evaluate_recorded_fork` supplies the actual root and
requires explicit matching user perspective. It returns an in-memory occurrence
only for a supported/verified Fork motif with retained payoff; context-only proof
is retained but does not qualify for the played-Fork shortlist. It writes nothing.

The 150-game cache-only pilot (2701–2850) inspected 4,399 user moves and 203
geometric proposals: **0 verified, 11 rejected, 192 unresolved**. Of the unresolved
cases, 187 lacked exact cached evidence and 5 deferred terminal ownership.
No engine searches or cache writes occurred. This does not establish that no
played Forks occurred; it establishes an evidence gap. No verified Human Review
Played Fork set is ready from this pilot. Any targeted evidence completion needs
separate approval; do not broaden the cohort or relax proof rules.

Complete missed-Fork outputs for 52 recorded/synthetic cases matched before/after.
See [actual versus counterfactual evidence](#actual-versus-counterfactual-evidence)
for source/line roles and [played-Fork assessments](PLAYED_FORK_ASSESSMENTS.md#validation-workflow)
for validation boundaries. Exact cohort and cost receipts remain private. Existing registry/UI/training and persistence
remain unchanged; no PlayedForkAnalyzer framework was introduced.
