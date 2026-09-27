# Shared candidate lines V1

This is an opt-in core service. Fork V3 has a separate read-only approved-line
candidate verifier. Existing discovery analyzers and the default single-line
verifier remain unchanged. The additive live cache migration and eight-request
cache-only validation are complete; no live Fork reconciliation is enabled.

```text
CandidateLineService -> CandidateLineGenerator -> injected shared engine
        |                        |
        +-- exact cache <--------+
        |
CandidateLineSet -> Quality Gate -> ApprovedCandidateLineSet
                                      |
                                   The Scale
                                      |
                              WeightedCandidateLines
                                      |
                         future specialist / proof service
                                      |
                              TacticalOpportunity
```

`LineAnalysisService` composes generation, approval and weighting. It does not
crawl games, select historical moves, create candidates, or update coverage.
Specialists still own motif proof and confidence. These core modules have no
Tkinter dependency; a desktop, phone, server, test or command-line caller can use
the same interfaces with a suitable engine and repository adapter.

## Contracts

| Module | Responsibility |
| --- | --- |
| `candidate_lines.py` | Immutable `LineScore`, `CandidateLine`, `CandidateLineSet`; legal PV validation and JSON codec |
| `analysis_settings.py` | Typed settings, presets, schema, engine and currentness identities |
| `candidate_line_engine.py` | One bounded MultiPV request through an injected `analyse` adapter |
| `candidate_line_repository.py` | Exact cache read and insert-once persistence; caller owns transaction |
| `candidate_line_service.py` | Cache-first generation; caller explicitly supplies read/write stores |
| `candidate_line_pipeline.py` | Opt-in composition and complete result-currentness identity |
| `quality_gate.py` | Objective decisions and explicit critical-position retention |
| `continuation_quality.py` | Cheap legal replay and optional compatible proof evidence |
| `the_scale.py` | Visible interest components and versioned event-provider hooks |

`CandidateLine` carries engine rank, root UCI/SAN move, a separate `LineScore`,
UCI/SAN PV, depth, nodes, engine-request identity, analysis version and immutable
JSON metadata. The score contains exactly one integer cp or signed mate distance,
an explicit POV and mate ownership (needed to distinguish opposite mate-zero
states). Never convert mate into an arbitrary large cp number.

`CandidateLineSet` carries the exact FEN, side to move, requested count, engine
profile/identity, ordered unique root lines, generation metadata and schema version.
`generated_line_count` is derived from `lines`. Lists and nested metadata are copied
into immutable containers. SAN is regenerated from the legal UCI PV on cache reads.
PV serialization preserves scores, perspective and legal move identity.

One set contains distinct **root moves**. Different opponent replies to Qxb7 belong
in a separate set at the position after Qxb7, not duplicate Qxb7 entries in the root
set. Fork V3's opt-in verifier uses this distinction for explicit child searches.

The generator uses python-chess's supported `analyse(..., multipv=N)` API, whose
result may contain fewer than N lines when fewer legal moves exist. See the
[official engine API](https://python-chess.readthedocs.io/en/latest/engine.html#chess.engine.Protocol.analyse).
One line still uses the same contract. Partial results are marked incomplete;
bound scores, missing scores and illegal PVs fail validation. Terminal positions
return an empty terminal set without an engine search.

## Settings and identities

Quick: 1 line, depth 10. Normal: 3 lines, depth 12. Deep: 5 lines, depth 16.
These are conservative initial opt-in presets, not a change to existing analyzers.
`candidate_line_count` accepts configurable N from 1 to 256. Profiles also expose
node/time budgets, engine options, gate settings, Scale weights/material accounting
and proof/settlement defaults consumed by opt-in specialists. Engine budget limits are combined using the
engine API; time-limited searches are not promised to reproduce identical PVs.

`load_profile('normal')` and `load_profile(json_object)` return the same typed
`AnalysisProfile`. Unknown fields, wrong types, invalid ranges and nonfinite values
are rejected. `profile.schema()` recursively exposes `SettingDefinition` records
with labels, types, defaults, limits, options, descriptions, basic/advanced level,
and cache/currentness flags. A future preset picker and Admin Console must use
this schema and loader; they must not create a parallel settings system.

There are two identities:

- **Engine identity:** line count/MultiPV, engine name/version/profile, generator
  version, depth/node/time budgets, Threads and Hash. Any change causes a raw cache miss.
- **Result currentness:** engine evidence plus gate policy/thresholds/reference,
  Scale configuration, event-provider IDs/versions, supplied continuation evidence,
  emitted events and proof defaults. Cheap policy changes reuse compatible raw
  engine results but produce a new currentness identity.

Preset display names do not invalidate results. All behavior-affecting settings do.
The engine adapter must truthfully identify the engine it provides. Current requests
are standard-chess **FEN-only** requests; no repetition history is silently assumed.
History-aware analysis or another engine protocol requires an explicit identity
extension. The shared desktop launcher owns its platform path, never the models.

## Live storage and migration

Keep `engine_position_cache` unchanged. Its unique key, single score and single PV
cannot honestly identify MultiPV results or all new engine options. Do not overload
its existing analysis profiles or treat an old single PV as a complete multi-line set.

The additive migration is live as of September 7, 2026. Its exact schema is:

```sql
CREATE TABLE IF NOT EXISTS engine_candidate_line_cache (
    line_set_id INTEGER PRIMARY KEY,
    fen TEXT NOT NULL,
    engine_identity TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK(schema_version = 1),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(fen, engine_identity)
);
```

One compact versioned JSON payload stores one expensive engine request. Each PV
is stored once in UCI; redundant SAN and per-line shared identities are omitted.
The exact generator/engine settings are recorded once in generation metadata, so
an old request's budgets, options and engine version remain auditable after presets change.
SQLite keys provide deduplication; JSON extraction can serve occasional line queries.
A child table would add complexity without a current per-line query requirement.
Policy decisions, weights, attack maps and board geometry are recomputed, not stored.

`CandidateLineRepository.put` does not update an existing row or churn its timestamp.
It rejects incomplete results. The caller controls transaction boundaries and
whether the destination is scratch, an explicitly approved persistent cache, or absent.
Reads tolerate an unmigrated database. Construction never migrates automatically.

`CandidateLineService` checks caller-supplied read stores and its write store before
generating evidence. An exact hit returns the stored immutable set, regenerating
SAN from legal UCI moves during decoding. A miss generates once and inserts only
complete evidence. The optional `insert_only_authorizer` blocks updates, deletes,
DDL and writes to any other table; the caller installs it after migration.

`migrate_candidate_line_cache.migrate(connection)` requires explicit authorization
and caller-owned transaction/backup. `validate_schema` verifies exact column
definitions, the schema-version CHECK and the composite UNIQUE index. A separately
approved migration must run the suite, create a fresh backup through SQLite's safe
backup API, verify full table/schema snapshots and integrity, acquire an explicit
transaction, recheck the baseline, create/validate the table, confirm existing
tables unchanged, then commit and recheck integrity. Roll back an uncommitted
failure and stop; never automatically restore over intervening training writes.

The bounded rollout script `reports/validate_live_candidate_line_cache.py` requires
`--apply-cache-only` and refuses an already-migrated database. It is a recorded
migration operation, not a general analyzer launcher. The completed live test used
five fixed positions/eight requests, inserted eight rows, and proved an identical
rerun had eight hits, zero writes/searches and a byte-identical database. All prior
tables, candidate IDs and training links matched. See
[the live validation report](../reports/CANDIDATE_LINE_CACHE_LIVE_VALIDATION.md).

### Identity and settings

The key is exact FEN plus a hash of the shared generator settings. Engine name/
version/request-family profile, MultiPV count, depth/nodes/time, Threads, Hash and
generator analysis version distinguish requests. Sorted unique root restrictions
also participate. Normal/3, Quick/1, Normal at depth 16 and restricted Qxb7 all
occupy separate rows at the same FEN. FEN differences separate rows even when the
generator hash is identical. Scores preserve White POV and separate mate ownership.

Serialization schema 1 is checked in both the row envelope and decoded payload;
unsupported versions fail closed. It is not a hidden engine-search setting. A
future incompatible schema needs an explicit migration/version plan. The generator
contract's `analysis_version` is part of raw identity.

Gate/Scale/proof settings affect result-currentness but do not change raw engine
identity. Preset labels/identifiers alone also do not duplicate engine evidence;
the engine request-family profile is distinct from the preset's display identity.
Future Admin Console controls must continue through `AnalysisProfile` and its
schema/loader. There is no parallel cache configuration or Tkinter dependency.

### Growth and future maintenance

The empty table/index added 8 KiB; eight request payloads totalled 10,133 bytes and
added another 16 KiB of file allocation, for 24 KiB total growth. The earlier
458-candidate scratch preview occupied about 44.79 MiB for 21,299 requests. These
are workload measurements, not an all-history growth forecast.

No automatic expiration, eviction, cleanup or VACUUM is enabled. Future maintenance
should define explicit retention for obsolete engine/request versions, protect
active consumers, take a verified backup and operate only on cache data in a
separately approved scope. Reads must remain insert-once and must not renew
timestamps. Deleting cache rows and reclaiming SQLite file space are distinct
operations; neither permits changing candidates, coverage or training history.

## Adoption

Fork V3 is the first read-only adopter; see [its guide](MISSED_FORK_V3.md).
`candidate_line_selection.admit_required_move` supplements a missing stored move
through the shared service's `root_moves` restriction. The request identity includes
the normalized restriction, and the generator validates the returned move. The
temporary comparison set merges unique moves under the same gate; supplemented
rank is relative to that set, never an invented global engine rank. Profile N
remains unchanged; the audit explicitly records the additional required move.

`candidate_line_proof.ApprovedPositionEvidence` adapts only approved lines to shared
bounded proof callbacks. Incomplete results fail closed; critical retention stays
visible. Each child request retains the same profile count and budgets. No shared
helper discovers candidate rows or knows Fork geometry.

Keep proof/settlement and ID-preserving repository boundaries intact. Migrate one
specialist at a time through an opt-in adapter, independent regressions, a scratch
preview and a separately approved scope. Pin, Skewer, X-ray, Mate and Fork V2
discovery have not adopted this path.

Future Human Practical, Tactics Hunter or Goblin presets can vary these settings.
Sacrifice, zugzwang and critical-moment classifiers may consume the same approved
lines and contribute events. None of those classifiers or UIs is implemented here.

## Targeted verification evidence

The opt-in shared [proof escalation service](PROOF_ESCALATION.md) separates Normal
three-line/depth-12 breadth from one-line/depth-18 verification at selected child
positions. Both use this same cache/service/settings contract. Exact verification
requests reuse their rows; they never reinterpret shallow evidence as deep evidence.
Gate/Scale/escalation budget changes affect proposal currentness, not compatible
raw-engine cache identity. Candidate-only Fork V3.1 is the first opt-in consumer;
no live reconciliation or other analyzer adoption is enabled.

## Consolidated consumption and diagnostics

`AnalysisBackbone` now provides the common request/admission/proof/Scale composition
contract. `LineAnalysisService` remains a compatible lightweight wrapper using the
same stages. See [ANALYSIS_BACKBONE.md](ANALYSIS_BACKBONE.md) for public model
distinctions, explicit evidence states and deterministic analyzer provenance.

`CandidateLineDiagnosticsService.inspect()` reads counts, UTF-8 payload bytes,
profile/request groups, timestamp bounds, duplicate keys and invalid envelopes.
Full legal/model payload checks are opt-in. SQLite allocation describes the whole
database, not this table alone. Diagnostics never creates tables, updates, deletes,
evicts or vacuums. Future cleanup is separately approved maintenance, not analysis.
