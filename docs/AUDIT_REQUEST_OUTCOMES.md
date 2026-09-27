# Scratch audit request outcomes

`reports.audit_request_outcomes` is audit-only infrastructure. Production analyzers,
settings, repositories and evidence schemas do not import or depend on it.

An immutable `AuditRequestOutcome` records the exact FEN, shared generator settings,
canonical root restrictions and `candidate_line_request.request_identity`. Its
JSONL representation also records a disposition, diagnostic and source provenance.
It contains no score, PV or CandidateLineSet payload. Even a `complete_result` marker
is not reusable evidence: the actual result must come from an evidence cache.

Supported dispositions are `complete_result`, `incomplete_bounded_score`,
`normalization_rejected`, `engine_error`, `interrupted`, and `incomplete_line_set`.
The last type records a returned partial set without pretending it can be reconstructed
from a marker. Unknown/incompatible records fail validation.

The audit runner inserts `OutcomeGenerator` at the generator fallback boundary of
the unchanged `CandidateLineService`. Lookup is therefore:

1. Valid exact production evidence.
2. Valid exact scratch evidence, including the caller's write store.
3. An exact recorded audit outcome.
4. The explicitly enabled normal-eight-ply namespace compatibility rule below.
5. The permitted scratch generator, or the NoEngine guard.

A bounded/normalization failure rethrows its original ValueError diagnostic. The
existing proof layer converts that to incomplete evidence and preserves its ordinary
conservative decision and request-budget accounting. It cannot become an approved
line or be inserted by CandidateLineRepository. A later valid exact result takes
precedence over any journal outcome.

An interrupted request has no completed response. Encountering it without valid
cached evidence raises `UnreplayableOutcome` and records an explicit interrupted
counter. Engine-error, partial-result and complete-result markers without their
required evidence also stop replay; they are not fabricated as successful results.
Retryable means a future explicitly authorized attempt may retry, not automatic
fallback during deterministic replay. An abrupt process termination can leave only
a started event in the separate search log; that is not automatically labeled an
incomplete outcome. Recovery requires documented provenance.

First-cohort files are `reports/fork_first_500_mode_a_outcomes.jsonl` and the equivalent
Mode B path. First passes append future observed outcomes. NoEngine reruns open
journals and evidence databases read-only and verify file hashes afterward. Runtime,
cache counters and journal metrics are excluded from structured-result equality;
proof, gate, profile, request budgets and analyzer truth remain included.

The recovered Qh4 outcome is supported by its original request-start event and stored
incomplete proof attempt. The original bound direction, numerical score and raw PV
were not retained and remain unknown. The earlier interrupted request is a separate
record with later valid evidence. The portable Qh4 fixture exercises the actual Fork
analyzer and compares its full canonical result without a database or engine.

Unrecognized profile/depth/engine/restriction mismatches do not reuse outcomes.
Existing evidence-cache compatibility rules do not implicitly authorize aliases for
non-reusable outcome records.

## Approved normal eight-ply settlement namespace

`reports.settlement_outcome_compatibility.SettlementOutcomeCompatibility` is an
explicit audit opt-in. It recognizes only `candidate_lines_verify_v1` to
`candidate_lines_verify_v1:settlement=8`. The unchanged source journal remains keyed
by its original exact identity. No alias row is inserted into either journal or cache.

The source must be a bounded/normalization incomplete outcome tied to the final
request of a recorded incomplete **normal eight-ply** verification attempt. The audit
loader checks the recorded verification settings, proof settings and disabled
extension flag against the frozen baseline. A matching profile name alone is not
an attestation. Complete, interrupted, operational-error and partial-set markers do
not qualify.

The resolver removes only that recognized namespace and requires equality of the
entire typed GeneratorSettings, including engine name/version, depth/nodes/time,
MultiPV, Threads/Hash and analysis/request-family version. FEN and canonical root
restrictions must match exactly. It cannot map eight-ply to twelve-ply, breadth to
verification, arbitrary profile names, or changed engine settings.

CandidateLineService still exhausts valid caches first. Exact audit outcomes take
precedence over compatibility. Compatible reuse only rethrows the recorded
normalization diagnostic; existing proof logic retains incomplete evidence. The
adapter does not return a CandidateLineSet or manufacture scores, PVs or approval.

Each compatibility use records FEN, `requested_request_identity`,
`source_outcome_identity`, `compatibility_reason`, `source_profile`,
`requested_profile`, and `reusable_as_engine_evidence=false`. First-cohort per-case
`audit_outcome_reuse` and session `compatibility_uses` preserve that provenance;
NoEngine result comparison includes it. Source journal records are never rewritten.

The eight-ply constant names the expressly approved compatibility obligation; it
is not an analyzer threshold or a configurable global proof policy. Production
services do not import this audit-only contract.
