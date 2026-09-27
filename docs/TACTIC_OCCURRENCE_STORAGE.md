# Tactical occurrence storage contract V1

Status: proposed storage contract and in-memory prototype only. No production
schema, writer, migration, backfill or analyzer activation exists. The implementation
is `tactic_occurrence_storage.py`; the schema and memory prototype live in
`tests/occurrence_storage_prototype.py`. A subsequent temporary-copy rehearsal uses
that exact schema through `tests/occurrence_migration_rehearsal.py`; neither is a
production migration API.

The analyzer supplies tactic truth. The relationship layer compares the tactical
root with the actual game. Storage retains both without putting `missed` inside
motif truth. Persisting an occurrence claim does not mean it passed admission,
proved a payoff, deserves praise, or is suitable for training.

## Current coupling

Inspection of the current production path found:

- `heavy_repository.save_heavy_result` finds a canonical candidate by
  `(move_id, tactic_type)`, protects current candidate/rejected coverage, and
  updates candidates in place. Duplicate canonical candidates raise. This is
  repository enforcement: `tactic_candidates` has no corresponding UNIQUE
  constraint; its type/version index is non-unique.
- `analysis_coverage` has UNIQUE `(move_id, analysis_type)`, analyzer/screen/scout
  currentness and a candidate link. Its completion states describe a search
  obligation, not every event/root/motif found at that decision.
- `tactical_opportunity_repository` encodes the opportunity inside candidate
  `metadata_json`. Canonical root/SAN information is reconstructed from the
  candidate and move. It is a codec, not a separate occurrence writer.
- `tactic_query` explicitly selects `missed_` tactic types, filters candidate and
  coverage rejection states, and handles mate episodes. It cannot become an
  all-occurrences query merely by inserting played rows.
- `training_history` writes permanent `training_attempts.candidate_id` links.
  `tactic_episodes.primary_candidate_id` also depends on candidate identity.
  Existing episodes are not a general Critical Moment model.
- Human reviews use `candidate:<id>` or an opaque `audit:[game,move,case,root]`
  identity in JSONL. Game Review already consumes these compatibility paths.
- `games` identifies imports by `(source, source_game_id)` and local game ID;
  `moves` identifies a decision by `(game_id, ply_number)` and local move ID.
  User color is nullable. These integers alone are not global mobile/import IDs.

Existing `TacticOccurrence`, `TacticOccurrenceRelation` and
`occurrence_from_legacy_candidate` remain the relationship/legacy adapters.
The storage contract reuses their vocabulary and validation; no production caller
has been switched to it.

## Options and recommendation

| Criterion | A: extend candidates | B: one generalized table | C: stable events + evidence + legacy links | D: event journal only |
|---|---|---|---|---|
| Migration risk | High: touches heavily used table | Moderate additive risk | Moderate, additive and independently rehearsable | High replay/projection complexity |
| Backward compatibility | Easy initially, mixed assumptions persist | Preserve legacy reader path | Preserve legacy reader path and exact IDs | Needs compatibility projections |
| Query simplicity | Simple SQL, increasingly overloaded meanings | Simple until evidence multiplies | Small joins; explicit claim vs evidence | Requires projections |
| Played/missed filters | Requires changing many assumptions | Natural | Natural, perspective derived | Natural after projection |
| Training | Risks accidental played puzzle exposure | Legacy mapping still needed | Explicit mapping; training unchanged | Additional identity adapter |
| Analyzer independence | Coupled to candidate lifecycle | Evidence becomes an oversized row | Append revisions without changing identity | Good but more infrastructure |
| Human review | Candidate keys retained, audit links awkward | Separate review links still needed | Opaque old keys linked to event/revision | Must stabilize replay identity |
| Critical Moments | Candidate-centric | Event references possible | Independent grouping of stable references | Event references possible |
| Mobile/core reuse | Legacy DB assumptions persist | Portable contract possible | Portable typed models and repository interface | Portable, excessive V1 complexity |
| Contributor clarity | Familiar names, misleading semantics | Initially simple, mixed lifecycles | Focused tables mirroring contract objects | New infrastructure burden |

Choose **C, a minimal hybrid**. B plus separate versioned evidence and legacy links
is effectively C. D is not warranted by a local SQLite app's current needs. Do not
normalize every target or annotation yet; keep versioned supplied evidence in JSON
until an actual query requires a relational index.

## Stable identity

`OccurrenceKey` canonically serializes this ordered tuple with version 1:

```text
(identity_version, source_namespace, game_id, move_id, occurrence_kind,
 actor_color, motif_type, tactical_move_uci, instance_key)
```

`occurrence_id` is UUID5 of that canonical JSON using the fixed namespace in the
contract. The database also retains UNIQUE `identity_json` and the readable key
columns. Repositories must enforce their consistency rather than trust incoming
UUID strings or direct SQL. Canonical encoding and namespace changes require a
future identity-version migration, never an unnoticed refactor.

- `source_namespace` is a persistent UUID for one source/database lineage, not a
  drive path, username, analyzer run or per-session random value. A future approved
  migration must allocate it once in lineage metadata. Backup/rehearsal copies
  retain it; independent datasets get different namespaces. No such metadata is
  written in this task. Cross-dataset import deduplication/sync is deferred.
- `motif_type` is `fork`, `pin`, etc., never `missed_fork` or `played_fork`.
- `occurrence_kind` is played/missed/unknown. Actor is the side making the decision.
  Played requires tactical root = actual move; missed requires a different root.
- Review perspective is explicit at query time. The same black event is played by
  the user when the selected perspective is black and played by the opponent when
  it is white. Do not persist both as separate events. Evidence separately records
  its original evaluation perspective. Missing perspective yields UNKNOWN, never
  an assumed user. User-facing aliases map to the existing `*_BY_PERSPECTIVE` enums.
- Default `instance_key="root"` means one instance of a motif at one tactical root.
  A fork's several targets are normally one occurrence. Truly distinct same-motif
  instances may supply a stable semantic discriminator, for example an attacker
  anchored at its pre-move square. Each detector must document that discriminator;
  arbitrary counters, hashes of mutable target sets and run IDs are forbidden.
- Detector versions, profiles, evaluations, proof, target discoveries, wording,
  importance, grades and Critical Moment ownership do not participate in identity.
  Re-running another analyzer version appends evidence to the same occurrence.
- FEN, decision ply and actual move are immutable consistency guards. A mismatch
  must fail or enter a separately approved correction workflow; never silently
  replace an anchor. A corrected tactical root/motif/kind is a different claim.
  Reviewed merge/split/supersession links may later connect claims without moving
  old reviews or training history. UNKNOWN cannot silently become played/missed.
  Imports missing a reliable actor/root/decision remain unresolved outside this
  anchored contract until their source facts are available.

This is one motif claim per record, not one primary story per move. Multiple
motifs on the same decision/root get separate IDs. Attribution and shared raw
proof references can show that they overlap; storage does not decide ownership.

## Proposed models and tables

`TacticOccurrenceRecord` owns the identity and immutable decision anchor.
`OccurrenceEvidence` owns immutable supplied evidence revisions.
`OccurrenceLine` owns one explicitly typed decision-rooted line prefix.
`OccurrenceStore` is a small portable protocol; only the test implementation exists.

| Proposed table | Contents and constraints |
|---|---|
| `tactic_occurrences` | UUID primary key; identity version and unique natural-key JSON; source namespace, game/move, kind, actor, motif, tactical root, instance; immutable FEN/ply/actual root; creation timestamp; motif/kind/actor/game/ply query index |
| `tactic_occurrence_evidence` | Content-hash revision primary key; occurrence FK; detector name/version; result-currentness identity; source/evaluation perspective; separate geometry, admission, proof and recorded-consequence statuses; schema-versioned payload JSON; creation timestamp; UNIQUE occurrence/revision for binding |
| `tactic_occurrence_lines` | Stable line ID; occurrence/revision composite FK; branch key; line type; purpose; UCI moves JSON; source and extent; UNIQUE revision/branch/type/purpose |
| `tactic_occurrence_legacy_candidates` | Original candidate ID primary key/FK -> primary occurrence FK; several existing duplicate legacy IDs may map to one occurrence without deleting any candidate |
| `tactic_occurrence_review_links` | Exact legacy/audit review identity primary key -> occurrence; nullable reviewed evidence revision with composite FK |

Exact executable **test-only** DDL is `SCHEMA` in
[`occurrence_storage_prototype.py`](../tests/occurrence_storage_prototype.py).
It creates none of these tables in `merlin.db`. Its tiny `tactic_candidates` table
is a fixture stand-in, not a proposed production table replacement. A real
migration still needs source-lineage metadata and game/move binding to existing
production tables (including verifying that move belongs to game). Those details
must be rehearsed before approving executable production DDL.

Evidence facets preserve the supplying provider's vocabulary. They are independent:
geometry present + admission rejected + proof ambiguous + an actual target capture
is a valid representation. Neither recorded material nor human PASS certifies
best-defense payoff. Payloads retain targets/identities, motif attribution,
completeness, retained payoff, material/evaluations with POV, recorded consequence,
source line references and provenance through existing opportunity/assessment
codecs. The prototype uses explicit synthetic, unassessed payloads; it does not
pretend to be a production codec for every legacy format.

Evidence revision IDs include detector/currentness/source/facets/payload, but no
creation timestamp. Same payload and provenance insert once. New evidence appends;
there is no automatic "latest row wins" truth selection. A future reader must name
an accepted detector/policy/currentness view and handle disagreements explicitly.
All policy settings affecting interpreted results belong in result currentness;
raw engine identities remain separate. Wording or grading revisions must not
force duplicate engine searches or rename the event.

Insertion of an occurrence plus its evidence/lines/links should be one production
repository transaction. The prototype tests each insert-once operation and FK
binding; it intentionally does not claim to implement production concurrency or
multi-object crash recovery. A later rehearsal must test both. There are no
update/delete methods; identical inputs return False without timestamp churn,
and conflicting immutable anchors/links raise rather than overwrite.

## Actual and proof line semantics

`line_type` has exactly **actual** and **proof**. `purpose` has main, verification
or settlement. Keeping these axes separate prevents a "settlement" label from
concealing whether a continuation happened. Actual lines use main purpose;
verification/settlement belong to proof.

- Every V1 stored line is a nonempty prefix starting at the occurrence's decision
  FEN. Actual root must equal `actual_move_uci`; proof root must equal tactical root.
- An actual prefix must match trusted contiguous game history. Legal replay alone
  is insufficient. The prototype enforces equality to its supplied frozen history.
- Played actual/proof roots coincide, but later moves may differ. Counterfactual
  defenses must never be shown as historical just because the root was played.
- A missed proof is counterfactual from its first move. A root-only legacy adapter
  reference is stored as root-only/incomplete, never invented into a full PV.
- Source identity and explicit extent/completeness are retained. A legal prefix
  is not proof of a forced win or of complete settlement. SAN is derived by legal
  replay; canonical UCI/FEN remain the anchor.
- Additional branches/extensions append revision-bound lines. `branch_key` is
  stable within an evidence revision; changing an existing line under the same
  ID fails. Future Extend Merlin Line must preserve the old evidence and review
  context, distinguish proof extensions from actual-history extensions, and use
  shared services. No extension execution is added here.

## Compatibility and staged transition

1. **Next, separately approve a temporary migration rehearsal.** Copy or fixture
   the source safely, allocate rehearsal lineage metadata and inventory *all* 944
   candidate IDs, metadata variants, duplicate canonical keys, missing anchors,
   review keys, episodes and training links. Do not execute historical analysis.
2. Build read adapters for supplied existing truth, using
   `occurrence_from_legacy_candidate` where it applies. Its current positive-ID,
   known-type/status rules are not universal: the live inventory contains a dev
   sentinel candidate `-1`. Preserve it and every unsupported/rejected/unknown
   row unchanged; report unmapped reasons. Never force all 944 through that adapter
   or silently delete rows to make migration counts agree.
3. In the temporary database only, insert stable claims, exact evidence and primary
   legacy mappings. Preserve every old candidate ID/row and all training/review
   references. Ambiguous duplicate/split mappings require an explicit decision;
   never choose a winner by recency or silently redirect review history.
4. Rehearse deterministic rerun, rollback, source conflicts, reader parity, legal
   actual/proof binding, integrity, reviewed revisions and transaction failure.
   Produce a mapping/unmapped report and proposed exact production DDL.
5. Only after separate approval, take a verified backup and apply an additive
   production schema. Initial legacy readers may continue unchanged. No DROP,
   destructive rebuild, candidate delete/reinsert, or automatic backfill.
6. Activate new occurrence writers/readers behind an approved scoped rollout.
   Existing missed candidate persistence remains the compatibility writer until a
   separately tested repository transaction safely owns dual writes. Played events
   must not create fake missed candidates merely to satisfy training/query code.

Coverage needs its own later obligation design: current `(move_id, analysis_type)`
completion can neither identify several tactical roots nor freely mix played and
missed searches. Keep it unchanged now. Static/scout rejection or completed no-hit
is not an occurrence; incomplete/error evidence must not manufacture an event or
be converted into a negative truth verdict. Played support in other analyzers is
not authorized by this storage contract.

## Queries and downstream consumers

The in-memory demonstration uses explicit black perspective:

```python
store.query("fork")  # three supplied fork claims
store.query("fork", relation=Relation.PLAYED_BY_PERSPECTIVE,
            perspective=TacticColor.BLACK)  # one
store.query("fork", relation=Relation.MISSED_BY_PERSPECTIVE,
            perspective=TacticColor.BLACK)  # one
store.query("fork", relation=Relation.PLAYED_BY_OPPONENT,
            perspective=TacticColor.BLACK)  # one
```

The equivalent future SQL relation filter is `occurrence_kind='played' AND
actor_color=:perspective`; opponent uses unequal actor. For "user" across games,
join each game's user color explicitly and retain unknown for missing color.
Filtering motif gives all forks, independent of played/missed. These are claim
queries; verified-only/training eligibility additionally selects compatible
evidence facets. Do not equate presence in storage with a verified tactic.

Existing candidate-backed reviews keep exact candidate keys. Audit-only review
keys are opaque immutable strings, even when they contain artifact paths. A
future adapter attaches an additive lookup link rather than rebuilding that key
from new wording or rewriting JSONL. Known reviewed revisions stay attached to
that revision; legacy reviews without reliable revision provenance remain null,
not automatically applied to the newest evidence. New native occurrence reviews
can use `occurrence:<uuid>` with explicit revision context. A candidate's secondary
motifs do not inherit its primary verdict automatically.

Training history remains candidate-backed throughout transition. Future missed
find-the-move and played reinforcement selection can query occurrences plus
admission/proof suitability; it must not rewrite the identity of past attempts.
New attempt identities require their own approved additive compatibility design.

Critical Moment membership will reference occurrence IDs and a game/move window,
with versioned primary/supporting roles independent of motif truth. Queen blunder,
Fork, Pin and mating context may coexist; changing the story must not rename the
Fork or invalidate its review. Existing mate episodes should not be relabeled as
this new aggregation. No ownership selection is implemented.

Quality grades, Hook Mate / broader mate-pattern classifiers and discovered
attack can add versioned facets or motif claims through this same interface.
User-created sets are membership references, not event identity. Importance,
context and grades are downstream policies; they cannot override proof/admission.
No new analyzer, grade policy, game-set UI or Critical Moment service is built.
Core models and repository contracts import no Tkinter, engine or database API.
A phone frontend can consume the same model/service boundary; cross-device sync
and storage transport are deferred, not disguised as a desktop-only API.

## Risks, validation and non-goals

Identity discriminators, import lineage and reviewed merge/split semantics must be
settled before real data is mapped. JSON payload growth and query indexing need
measurement in rehearsal. Immutable revisions need an eventual retention policy
that protects training/review provenance. Conflicting versions need an explicit
reader policy; storage cannot adjudicate truth. Actual source-history validation
and multi-object transactions are mandatory in any future production writer.

The focused tests exercise deterministic IDs across processes, independent motifs,
roots/instances and perspectives, evidence revisions, source/actor/line binding,
legacy and review links, insert-once reruns, corruption rejection, independent
facets, fresh core imports without database/engine/Tkinter, and an exclusively
`:memory:` repository. Supplied fixtures are not new chess findings.

No production migration, played persistence, historical backfill, cache write,
engine search, analyzer rule, Game Review/filter, training or grade change is part
of this task. Played Fork Assessment V1 is frozen after its ten-case human review;
see [PLAYED_FORK_ASSESSMENTS.md](PLAYED_FORK_ASSESSMENTS.md). Run results and exact
safety evidence are in
[TACTIC_OCCURRENCE_STORAGE_CONTRACT_V1.md](../reports/TACTIC_OCCURRENCE_STORAGE_CONTRACT_V1.md).


## Temporary-copy rehearsal #1 (historical checkpoint)

The first real-data rehearsal attempted all 944 candidates. It preserved every
legacy row and mapped 943: 926 supplied missed-by-user claims plus 17 rejected
claims represented conservatively as UNKNOWN. Their exact rejected status,
metadata and coverage remain in immutable archival payloads. The active legacy
adapter and all analyzer rules remain unchanged; UNKNOWN is a scratch archival
fallback, not a new assertion that a rejected tactic occurred or was verified.
That fallback needs explicit policy adoption before a persistent migration.

Candidate/game/move `-1` is the remaining unmappable development sentinel. Its
negative source anchors violate the current positive-ID key contract. Eight of
11 training attempts reference it, so omitting it prevents complete resolution
through the new layer even though all old training links remain valid. Do not
renumber it or silently invent positive aliases. A future narrow correction must
decide whether source-bound signed SQLite IDs are valid key inputs or provide an
explicit unresolved-source representation. Existing positive identities must stay
unchanged, and the active analyzer/review contracts must not be loosened implicitly.

The identical legacy migration rerun inserted/updated zero rows and left scratch
byte-identical. One frozen game-2704 Nf3+ sample coexisted in scratch, retaining
confirmed geometry, admitted move, ambiguous proof and positive recorded material
as independent facets. Candidate-backed reviews, native/audit review links and
actual/proof line separation were demonstrated. All copied legacy tables and the
production database remained unchanged. The temporary database was discarded.

Recommendation: **needs contract correction**, then repeat the rehearsal before
production migration. Source-lineage allocation must also be persisted explicitly
at any future approved live migration; this rehearsal's UUID belongs only to its
temporary lineage manifest. See
[TACTIC_OCCURRENCE_TEMP_MIGRATION_REHEARSAL.md](../reports/TACTIC_OCCURRENCE_TEMP_MIGRATION_REHEARSAL.md)
for complete counts, the eight unresolved occurrence joins, safety and tests.


## Legacy developer source correction and rehearsal #2

Current recommendation: technically ready for an explicitly approved additive
production schema migration. Rehearsal #2 resolves the prior gap; production is
still unchanged. See [the second rehearsal report](../reports/TACTIC_OCCURRENCE_TEMP_MIGRATION_REHEARSAL_V2.md).

`-1` is a real persisted **synthetic developer rook-fork puzzle**, not a missing
candidate marker. `seed_dev_test_puzzle.py` explicitly creates game/move/candidate
rows with that ID, `source=dev`, source name `MERLIN_TEST_ROOK_FORK`, and developer
metadata. Its Re2 "played" move is fixture data, not a historical game claim.
Eight recorded training attempts reference this exact candidate through the normal
candidate foreign key and training API. The seeder was inspected, never executed.

The correction implements option B, separating a named occurrence key from signed
legacy references. `OccurrenceKey` retains its strict positive game/move IDs and
its exact V1 encoding. A new `NamedOccurrenceKey` uses a distinct identity family:

```text
[2, "named_source", source_namespace, source, source_game_id, decision_ply,
 kind, actor_color, motif_type, tactical_move_uci, instance_key]
```

This still generates a normal UUID5 occurrence ID. A `LegacyDecisionReference`
retains signed game/move row references outside that identity. Candidate `-1`
remains the unchanged signed FK in `tactic_occurrence_legacy_candidates`.
No fake positive IDs or arbitrary negative occurrence keys are introduced.

`TacticOccurrenceRecord.game_id/move_id` expose the source bindings consistently
for either key family. Named keys require an explicit legacy reference and matching
positive decision ply. Scratch persistence verifies the actual move/game rows,
source/name, decision FEN, actor and legal roots. Missing or mismatched references
fail. Named identity and redundant stored columns are checked on read-back.

Only the audited developer source is opted in through `NAMED_LEGACY_SOURCES` in
the rehearsal adapter. It also requires developer metadata, expected candidate
vocabulary and a valid anchored decision. A bare negative number or unknown source
cannot create an occurrence. Other named sources require their own explicit source
contract/adapter; the active legacy/UI/analyzer adapters were not loosened.

The prototype DDL now accepts `identity_version IN (1,2)`. Existing columns remain:
normal rows use their local-ID key; named rows retain signed game/move bindings and
the canonical named key in `identity_json`. No production table has been created or
altered. Reconstructing all 943 previously mapped identities under their original
namespace gives exactly the same UUIDs, including all 17 UNKNOWN rejected claims.
Those claims' handling was not changed.

Training resolution must distinguish occurrence-backed, intentionally legacy/
candidate-less, and broken references. Candidate-less history should never get a
fabricated event. This dataset contains **11 occurrence-backed attempts, zero
intentionally unlinked, zero broken**: the eight special attempts really do belong
to the named persisted puzzle. Existing attempts are not rewritten. Current
candidate-backed reviews remain untouched, and no new negative-ID review is
invented; the current review model still requires positive candidate IDs.

Rehearsal #2 mapped all 944 rows (927 supplied missed-by-user, 17 UNKNOWN), then
reran with zero inserts/updates and a byte-identical scratch file. The frozen Nf3+
played sample, actual/proof lines and multiple motifs still pass. All seven
candidate-backed reviews resolve. Production and review data remain unchanged.
A future migration must persist its source-lineage UUID once, preserve both key
families and retain the archival truth/line-decoding boundary documented above.
Production schema approval would not authorize analyzer activation or backfill.
