# Durable conservative analysis outcomes

The optional `analysis_deferred_checks` ledger records that a scoped obligation
was checked under an exact analyzer/profile/evidence contract and intentionally
produced **no tactic conclusion**. It is separate from `analysis_coverage`, candidates,
occurrences, scores and training. It never means verified, rejected, erroneous or
missing work. The current rollout is approved on isolated copies only.

## Components and integration

- `analysis_deferred_schema`: explicit additive schema; no startup/bootstrap migration.
- `analysis_deferred_evidence`: deterministic JSON/SHA256 plus read-only dependency lookup.
- `analysis_deferred_repository`: scope-checked, ID-preserving, transactional receipts.
- Registry `deferred_contract`: explicit analyzer opt-in providing current policy identity.
- Planner/crawler/readiness: generic reuse through the repository; no tactic-name branch.
- Shared result models: completed conservative checks/games remain separate from conclusions.

Only X-ray V1 opts in. Existing static/scout/heavy rules and versions are unchanged.
Without the table, the prior planning-only behavior and diagnostics remain available.
The presence of an exact migrated table enables receipts; an incompatible table is
an error, not an implicit schema repair. Fresh-profile bootstrap is unchanged pending
separate production rollout approval.

## Supported outcomes

| Disposition | Complete predicate |
|---|---|
| `cached_quick_rejected` | Every geometric alternative fails the existing cached quick policy |
| `mate_deferred` | Both baseline evaluations exist and the material-family mate-routing rule applies |
| `played_checkmate` | The actual played move delivered checkmate, validated from its legal board transition |
| `already_owned` | Every alternative has another canonical solution owner under the existing policy |

The exact disposition **and reason code** must be on the approved shared completion
list. A save re-evaluates the whole registered preflight inside the write transaction
and requires identical provenance. Arbitrary labels, missing/partial/mixed evidence,
`heavy_required`, errors and unknown predicates cannot create receipts. Ownership-only
predicates can legitimately have missing engine evidence because all ownership facts
are complete; mixed ownership/quick failures remain ineligible exactly as before.

## Identity and invalidation

A receipt records:

- move ID, game identity, source identity, player perspective, ply, before/after FEN,
  and actual played move;
- analyzer type/version, screener version, scout version/config and completion version;
- preflight version and full frozen policy data, quick engine/profile/version/budget/options;
- exact request keys, availability and full raw evidence content fingerprints;
- applicable canonical owner IDs, solutions and candidate revision fingerprints;
- disposition/reason, full provenance and an integrity hash over the structured receipt.

Currentness re-reads these dependencies but does not screen/scout, reconstruct geometry,
rerun preflight, request engines or update timestamps. Changed/missing/corrupt evidence,
changed profiles/policies/versions, changed move/game identity, or changed relevant
ownership makes a receipt non-current. Changes to unrelated rows do not invalidate it.
Policy/version identity is separate from raw evidence identity; no duplicate engine
cache rows are created by result-currentness changes.

Existing candidate/rejected/heavy coverage and canonical candidate protections take
precedence. A receipt cannot override them. Invalid receipts remain stale until the
normal scoped pipeline resolves the obligation; there is no global reconciliation.

## Transactions and cancellation

The repository uses `SqliteTransaction`, nesting within the crawler's tactical stage.
Stop is checked on entry, after predicate/dependency verification, after insertion
and before commit. Cancellation or exceptions roll back the unfinished unit and its
provisional rows. A stage failure rolls back receipts with other provisional work.
Completed stages from earlier games remain durable under the existing Stop/resume
contract. Repeated exact saves cause no inserts, updates, ID or timestamp churn.

## Schema and lifecycle

```sql
CREATE TABLE analysis_deferred_checks (
    move_id INTEGER NOT NULL REFERENCES moves(move_id) ON DELETE CASCADE,
    analysis_type TEXT NOT NULL,
    completion_state TEXT NOT NULL CHECK(completion_state = 'complete_deferred'),
    disposition TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    contract_version INTEGER NOT NULL CHECK(contract_version = 1),
    contract_json TEXT NOT NULL,
    dependency_json TEXT NOT NULL,
    details_json TEXT NOT NULL,
    receipt_sha256 TEXT NOT NULL CHECK(length(receipt_sha256) = 64),
    checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(move_id, analysis_type)
);
```

The JSON contract keeps nested shared profile/policy identity extensible without a
column for every future setting. The game identity is validated against the move's
owning game; there is no duplicate mutable game foreign key. The composite primary
key provides one outcome per move/analyzer. The new ledger has no AUTOINCREMENT
sequence and does not rebuild any existing table. SHA256 is an integrity/currentness
check, not authentication against an actor who can rewrite the database.

Data Management explicitly includes the optional ledger in its reviewed ownership,
preview fingerprint, deletion and reset paths before parent moves; collection
protection still applies. No deletion/reset is performed by ledger analysis.

Apply schema only inside an explicitly approved transaction. Verify exact schema,
unchanged old schema/data, quick_check and foreign_key_check before commit; roll back
and stop on failure. Production requires the existing verified FULL backup workflow,
activity-lock coordination and separate scope approval. Never restore automatically
over possible intervening owner/training writes.

Do not backfill merely by labeling old absent/error rows. Each approved scope must
run the unchanged planner and prove the full stable predicate under its current
inputs before a receipt can be written. No heavy analysis is needed for the validated
145-check Recent 50 scope; a production reconciliation should abort if fresh evidence
or heavy work unexpectedly becomes necessary.

The repository stores full preflight provenance plus compact dependency hashes.
Growth depends on the number of alternatives and evidence references. The isolated
rehearsal covered 145 stable checks; its detailed storage receipt is private, so no
universal bytes-per-row estimate is claimed. Measure file and payload growth on an
explicitly scoped copy before approving a larger migration.
Future retention must delete only stale/orphaned ledger bookkeeping with an approved
policy, never candidates, training or shared engine evidence. There is no automatic
cleanup or evidence promotion.

All modules are frontend-independent and have no Tkinter imports. Future Admin
Console settings continue to flow through existing shared scout/profile/policy models;
the ledger fingerprints those settings rather than defining parallel configuration.
