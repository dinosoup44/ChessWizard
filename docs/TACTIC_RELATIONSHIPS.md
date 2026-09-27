# Tactic relationships V1

The analyzer decides what tactic exists. `tactic_relationships.py` decides who
had the accepted opportunity and whether its initiating move was played. This
portable typed layer has no database, engine, settings or Tkinter dependency.
`TacticRelationshipRepository` supplies active canonical legacy candidates and
read-only reconciliation plans. Game Explorer consumes the same assessor.

## Contract and ownership

`AcceptedTactic` carries provider-owned admission/currentness, an independent
motif, tactical root and exact `DecisionIdentity`. `RecordedDecision` supplies the
stored game move and known user color. The identities must agree on database-local
game/move references, source/source_game_id, ply, FEN and actor. The actor must be
the legal decision side, and both roots must be legal at that FEN. Signed IDs are
persisted references, not missing markers. Unknown identity/color, invalid or
missing moves, unaccepted evidence, inactive truth and mismatches return typed
UNKNOWN with a reason. No evaluator or geometric motif inference occurs here.

Canonical names remain:

| Relationship | Meaning |
| --- | --- |
| played_by_perspective | User's side; actual root equals accepted verified root |
| missed_by_perspective | User's side; actual root differs |
| played_by_opponent | Other side; actual root equals accepted verified root |
| missed_by_opponent | Other side; actual root differs |
| unknown | Evidence or ownership cannot safely establish a relationship |

Changing perspective changes a relationship view, never occurrence UUID or tactic
truth. White and Black are symmetric. Multiple motifs retain distinct identities.
No similar move later in the game, evaluation gain, prefix or terminal board alone
establishes a played/missed event.

## Provider boundary

`verified_root` means an upstream trusted provider supplied accepted tactic truth
at this exact root. The assessor cannot promote geometry, ambiguous proof or
actual material gain into that status. A future provider must perform its own
currentness/acceptance selection before constructing the input.

`legacy_missed` preserves existing active candidate semantics via `TacticQuery`:
status, rejected coverage, canonical duplicate exclusion and primary mate episode
rules are unchanged. It is not a new proof/admission policy. A legacy missed row
whose solution equals its actual move is contradictory: it stays unknown until
independent accepted played-root evidence exists. Legacy type names identify the
motif/provider vocabulary, not sufficient proof of relationship.

Standalone Explorer claims require explicit `OccurrenceEvidenceSelection` revision
IDs selected by a trusted provider. Selected revisions additionally require accepted
(or admitted) admission and verified (or verified_payoff_changed) proof. Selection
never defaults to the newest timestamp. UUID/immutable columns and actual source
anchor/side are checked. Linked archives cannot revive rejected candidates or
count the same legacy claim twice. Unselected archived facets remain historical.
No standalone live discovery provider is enabled by this change.

## Motif semantics

Fork, Mate, Pin, Skewer and X-ray use the same comparison. Pin/Skewer/X-ray payoff
may occur later: only the initiating move must match, not the subsequent proof
line. Recorded history and counterfactual proof retain separate roles.

Mate follows the same exact accepted-root rule. An accepted immediate mating move
that was actually played is played; a different actual move misses that supplied
opportunity. An earlier mating opportunity has its own decision identity. A
terminal checkmate position cannot supply a legal initiating move, so it does not
become a new played occurrence. Existing primary-episode visibility remains in
force for legacy Mate candidates.

## Identity and isolated persistence

The frozen UUID contract is unchanged (`OccurrenceKey` v1 and `NamedOccurrenceKey`
v2). Kind, actor, motif and tactical root belong to identity; perspective does not.
The existing signed -1 developer puzzle retains its named-source UUID and explicit
legacy binding. New signed references need explicit named-source registration;
the planner never applies abs(id), synthesizes a local ID, or invents a sentinel.

`OccurrencePlan` is read-only: insert / unchanged / unknown / conflict. Existing
anchors are immutable. A conflict requires a separate reviewed reconciliation;
there is no automatic update/delete/relink API. The scratch rehearsal uses the
existing generic insert-once occurrence store, inside an explicit transaction,
with SQLite authorization restricting inserts to occurrence tables. It never
writes candidates, coverage, training, caches or reviews. Evidence is a separate
revision; storing an occurrence does not activate standalone search truth.

## Reconciliation proposal and future Training

See `reports/tactic_relationship_expansion/desktop_plan.json` and
`project_plan.json` for every candidate, UUID, source anchor, relationship and
planned action. The desktop proposal reserves a source namespace only in the
report; a separately approved production procedure must persist that lineage.
Before any future write, take an approved verified backup and revalidate the exact
DB/source hashes and active scope. If data changed, regenerate the proposal rather
than applying stale IDs. No production migration/backfill is part of V1 here.

Current rehearsal: desktop 64 new occurrence/evidence/link triples, zero updates;
project 861 existing active mappings unchanged. Archived inactive mappings remain.
The desktop copy grew 88 KiB; reruns had zero writes and identical bytes. No
training/review links change. Explorer's real-game results remain unchanged:
these legacy misses were already projected read-only before mapping.

Future training can consume the relationship view through a separate eligibility
policy. Current real-data missed-user pools are 64 desktop and 860 project;
verified played-user reinforcement pools are zero. These databases overlap and
must not be summed as unique games/opportunities. No new training items or behavior
were introduced. The ten frozen played-Fork assessments still describe geometry
and recorded consequences independently: six rejected proofs, four ambiguous,
zero verified payoff examples.

New providers can use this contract without Tkinter and without modifying any
existing analyzer. No engine searches are needed for relationship determination.
