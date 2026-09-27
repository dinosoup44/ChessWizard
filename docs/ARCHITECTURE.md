# ChessWizard architecture checkpoint

Checkpoint: September 7, 2026, after Pin V2/Skewer V1 saved-500 validation and X-ray V1 existing-evidence preflight validation.
This document describes implemented behavior, including rollout limitations.
See [ADDING_ANALYZERS.md](ADDING_ANALYZERS.md) for the specialist contract.

Skewer V1 completed its saved-500 live rollout: five new candidates, no errors,
and a byte-identical zero-work rerun. See [its rollout](../reports/SKEWER_V1_LIVE500_ROLLOUT.md).
Pin V2's saved-500 no-hit refresh is complete with five new candidates and
protected V1 IDs; see [its rollout audit](../reports/PIN_V2_LIVE500_ROLLOUT.md).
X-ray V1 is registered through the same contracts, with 176 passing tests,
20 synthetic gold cases and a read-only saved-500 preview. Existing-evidence
preflight reduces its 3,489-check queue to 2,213 without changing geometry or
thresholds. Heavy rollout still requires approval. See [MISSED_XRAY_V1.md](MISSED_XRAY_V1.md).
New shared `board_analysis.SliderLine`/`direct_slider_lines` observations expose
the first two contacts without tactic policy. `tactical_line_proof` tracks line
participants and conservative exchange costs; specialists still own causality.
Pins retain their existing ray API and behavior. X-ray composes additive
`new_slider_move_lines`, `trace_blocker_resolution` and `tactical_material`
services without inheriting Skewer's forcing policy or changing old calculations.

Modularity and extensibility are first-class requirements.

## Core portability and contributor-facing structure

A future mobile version should primarily require a new frontend, not a rewrite
of the chess-analysis system. Important chess/business logic must not live inside
Tkinter widgets or event handlers. Core services must be usable without Tkinter.

Shared core: analyzers, board analysis, candidate lines, Quality Gate, The Scale,
engine/cache adapters, repositories, TacticalOpportunity, feedback, patterns,
settings/profiles, repertoire logic and domain models. Frontend-specific code owns
widgets, layout, input handling, native dialogs and desktop navigation. Handlers
call shared services. Engine lifecycle/platform paths belong to injected adapters,
not domain models. No mobile-specific implementation is required at this stage.

Code should explain its work through focused modules, clear names, typed contracts
and predictable interfaces. Comments/docstrings explain invariants, safety, edge
cases and reasons, not obvious syntax. Understanding one analyzer should make the
next understandable by analogy. Keep shared public contracts documented as they evolve.

## Shared candidate-line infrastructure V1

The opt-in pipeline is `CandidateLineService -> CandidateLineSet -> Quality Gate
-> ApprovedCandidateLineSet -> The Scale -> WeightedCandidateLines -> specialist`.
`LineAnalysisService` composes the first stages without a historical crawler or UI.
Discovery analyzers retain their original paths and versions; an explicit Fork V3
candidate-only factory now provides the first approved-line preview adopter.

One typed `AnalysisProfile` drives both presets and the future Admin Console.
Raw engine identity includes MultiPV count, budgets, options and versions. Approved
result currentness additionally includes gate/Scale/proof settings and supplied
evidence. Cheap policy changes reuse expensive raw engine results.

The tested storage extension is one compact JSON row per exact request in
`engine_candidate_line_cache`; the existing single-PV cache is unchanged. The
additive migration is now live after a verified backup, full tests and a tiny
cache-only validation: five fixed positions, eight inserted requests, then eight
hits with zero writes/searches and a byte-identical rerun. Exact schema/constraint
validation and an optional insert-only SQLite authorizer protect the boundary.
All existing tables and IDs were unchanged. No live Fork reconciliation or new
analyzer adoption is enabled. The earlier candidate-only Fork V3 preview remains
distinct from historical discovery; its new evidence was stored in memory.

Raw cache identity includes exact FEN, engine/generator settings and normalized
root restrictions. Gate/Scale/proof settings affect result-currentness without
duplicating raw evidence. Row/payload schema versions fail closed. A future Admin
Console uses the same typed settings schema; core cache/models have no UI imports.
See [the migration and cache report](../reports/CANDIDATE_LINE_CACHE_LIVE_VALIDATION.md)
for exact schema, backup, source hashes and growth (24 KiB for this tiny rollout).
Cleanup/retention requires a separate cache-maintenance policy; reads never update
timestamps and no automatic eviction or table rebuild is enabled.

The gate always retains the best usable line. If all *normal* decisions fail an
explicit critical-position policy, it retains the configured least-bad lines and
flags forced deterioration; incomplete evidence stays separate. The Scale ranks
retained lines only, with visible components, and never substitutes for motif proof.
Engine score, quality admission, interest and tactic confidence are distinct.

See [candidate lines](CANDIDATE_LINES.md), [Quality Gate](QUALITY_GATE.md), and
[The Scale](THE_SCALE.md) for contracts, settings, cache identity and adoption.

## General module boundaries

Prefer reusable services, registries, adapters, structured result objects,
stable interfaces, and data-driven configuration.

Avoid tactic-specific logic in the central crawler, UI code that directly runs
Stockfish, features coupled to another feature's private implementation,
hard-coded one-off pattern rules, destructive rebuilds where in-place updates
are possible, and giant modules with unrelated responsibilities.

A new analyzer should be addable without rewriting existing analyzers.
A new use for position patterns should not require changing the Pattern Builder.
A new UI should consume shared services rather than duplicate analysis logic.

The central crawler owns selection and dispatch. `analysis_registry.py` registers
screeners, scouts, configurations, and callable single-move heavy adapters.
`tactic_screeners.py` owns static geometry. `engine_cache.py` owns reusable
White-POV evidence. Candidate/coverage persistence is separate from specialists.

Analyzer calculation, engine access, and persistence are three separate layers.
Single-position specialists return structured results. They never write
`tactic_candidates` or `analysis_coverage`. Engine requests use a shared position
service/cache; an ID-preserving repository stores the results.

## Shared tactical opportunity model

Interpreted tactical meaning lives in the separate
[shared tactical opportunity model](TACTICAL_OPPORTUNITIES.md). Specialists may
optionally attach a `TacticalOpportunity` to `HeavyResult`; the existing heavy
repository persists a versioned document in candidate `metadata_json`, preserving
canonical IDs and proof fields. `tactical_opportunity_repository` provides the
generic read view. No new SQL schema, legacy backfill, coverage/version change,
or Game Review wiring is required. Board facts remain in `board_analysis`.

## Shared board-analysis primitives

`board_analysis` is the tactic-agnostic library shared by analysis consumers.
It depends only on python-chess and the standard library, with no engine, database,
UI, registry, or tactic-module dependency. Public functions accept a board and
return immutable observations without modifying its position or history.

| Module | Responsibility |
| --- | --- |
| `geometry` | Alignment, ordered rays, between-squares, and neighborhoods. |
| `attacks` | Attack maps, attackers, and attacked pieces with caller-supplied filters. |
| `lines` | Blockers between endpoints and ordered ray contacts beyond blockers. |
| `safety` | Attackers, defenders, absolute pins, and attacked/undefended observations. |
| `mobility` | Legal moves for the actual side to move and pre-move capture squares, including en passant. |
| `king_safety` | King-zone attacks, checking pieces, immediate pawn shield, and legal king moves. |
| `material` | Material balance with caller-supplied piece values; no built-in evaluation or tactic policy. |

The fork static screener and Fork V2 compose `attacked_pieces`; Fork V2's
capture-square compatibility wrapper delegates to `capture_square`. Target
selection, piece values, fork realization, and engine-score thresholds remain
specialist policy. This extraction preserves their output shapes and existing
versions; it does not request coverage invalidation or live reanalysis.

Geometric attacks include pinned pieces and friendly defended squares. They
are not equivalent to legal captures. Piece-safety observations do not prove
that a piece can be won, and king-zone pressure is not an engine evaluation.
See [BOARD_ANALYSIS.md](BOARD_ANALYSIS.md) for exact semantics and examples.

Future Pattern Engine/Pattern Builder consumers should import the same public
primitives and compose their own predicates. Do not copy board logic or depend
on a tactic's private helpers. This establishes the shared dependency boundary;
no Pattern Engine integration has been added yet. The extraction passed the
full 71-test suite using synthetic positions and temporary databases, without
running live analysis.

Pin V1 now composes shared ray contacts and capture-square/material accounting
helpers. Its direct-pin definition, piece valuations, and proof thresholds live
in its specialist modules, not in the shared library.

## Current analysis pipeline

```text
saved scope -> selected user moves -> registry -> coverage currentness
    current/protected: skip
    eligible: static screener -> light scout -> optional existing-evidence preflight
                                           -> pending heavy queue -> registered specialist
                                              -> structured HeavyResult
                                              -> ID-preserving repository
                                              -> candidate + coverage

scout / specialist -> shared engine service -> engine_position_cache
```

| Responsibility | Implemented owner and behavior |
| --- | --- |
| Scope | `analysis_crawler.py` selects real games and their user moves. `analysis_scope.py` loads pinned validation IDs. The saved 500 games are IDs 2701â€“3200 from `reports/scout_preview_500.json`, not a fresh last-500 selection. |
| Registry | `analysis_registry.py` maps each analysis type to an `AnalyzerDefinition`: versions, screener, scout, configuration identity, and heavy adapter. The crawler does not branch on tactic names. |
| Screener | Registered pure `screener(row)` returns whether the position should continue. `tactic_screeners.py` contains the safe fork geometry screen. Mate uses a pass-through screen. |
| Scout | Registered `scout(row, evidence)` returns `ScoutResult(send_to_heavy, reason)`. `analysis_scout.py` owns current scouts and their configuration. A scout miss is a budget-limited negative, not a proof of absence. |
| Planning/dispatch | `analysis_planner.py` plans negative outcomes and scout-positive pending checks. `heavy_dispatch.py` validates scope, records the preflight audit, creates a verified backup, dispatches pending checks, and audits preservation afterward. Negative writes are a separate mode in `negative_coverage.py`. |
| Existing-evidence preflight | `analysis_preflight.py` invokes the optional registered policy after ordinary scout planning, before dispatch. `existing_position_evidence.py` exposes current cache reads with no engine fallback; `solution_ownership.py` exposes canonical ownership reads. Only `xray_preflight.py` opts in. Unresolved evidence and exceptions retain work. Dispositions are reported, never persisted as coverage. |
| Heavy calculation | Registered adapters invoke single-position functions in Fork V2, Mate V3, Pin V2, Skewer V1 or X-ray V1. Calculators use injected evidence and return data; they do not select games or persist results. Pin and Skewer completed saved-500 validation. X-ray remains at the read-only-preview checkpoint. |
| Engine/cache | `analysis_engine.PositionAnalysisService.position(fen, profile)` uses `engine_cache.get_or_analyze`. Scouts receive `ScoutEvidence`; dry-run planning uses `DryRunEvidence`, whose misses are stored only in a temporary database. `LazyScoutEngine` starts Stockfish only when a search is needed; despite its name, heavy dispatch also uses it. |
| Persistence | `heavy_repository.save_heavy_result` handles canonical candidate lookup, in-place updates, and coverage writes in one transaction. Candidate calculation and engine-cache writes finish before that transaction. |
| Coverage | `analysis_coverage` has one row per `UNIQUE(move_id, analysis_type)`. `analysis_crawler.coverage_decision` classifies currentness. Coverage describes completed stages; pending scout-positive checks remain a queue, not a completed coverage status. |

The engine service owns engine access, cache access, and score validation. The
calculation layer must use its injected methods, never its connection or engine
attributes. Cache scores are stored from White's perspective; use
`engine_cache.score_for_color` to evaluate both before and after positions from
the same player's perspective. Do not infer perspective from the new side to move.

Current profiles are `tactic_scout_v1` (10,000 nodes), `tactic_quick_v1`
(depth 10), and `tactic_verify_v1` (depth 18), using Stockfish 18 with Threads 1
and Hash 64. Cache lookup matches exact FEN, engine name/version, profile name,
profile analysis version, limit type, and limit value. Engine options are in the
scout configuration identity but are not separate cache-key columns; a change
requiring distinct evidence must also change the cache profile identity/version.

SQL authorizers restrict specialist execution to cache inserts/updates and
repository execution to candidate/coverage inserts/updates. Deletes are denied.
These are safeguards for trusted application code, not a third-party plugin sandbox.

## Analyzer interface

`AnalyzerDefinition` is a frozen dataclass, with string versions:

| Member | Contract |
| --- | --- |
| `analysis_type`, `label` | Stable unique type matching its registry key; human-readable label. |
| `screener_version`, `has_safe_screener`, `screener` | Version and safety declaration for `screener(row) -> bool`. False may become static negative coverage only when the screener is declared safe. With no safe screen, use a pass-through function and `False` for the safety flag. |
| `screen_rejection_reason` | Useful static rejection reason; defaults to `safe_static_rejection`. |
| `scout_version`, `scout`, `scout_config` | `scout(row, evidence) -> ScoutResult`; `scout_config() -> str` returns stable canonical JSON describing the actual scout decision/evidence configuration. |
| `analyzer_version`, `heavy` | `heavy(row, positions) -> HeavyResult`, with a matching candidate `detector_version`. |
| `deduplicate_opportunities` | Default false. Opt-in repository ownership check for a proposed new canonical candidate whose move and solution already belong to another tactic; enabled for X-ray V1. |
| `preflight_existing_evidence` | Default `None`. Optional `(row, PreflightContext) -> PreflightResult` policy over read-only evidence/ownership services. Only X-ray V1 is enabled. No engine capability, coverage writes, or durable dispositions. |

Preflight results are reconsidered on every plan, using current analyzer policy,
quick-profile identity, cache rows and ownership. The five dispositions are
`heavy_required`, `cached_quick_rejected`, `mate_deferred`, `already_owned` and
`played_checkmate`; none is a coverage status. `screened_out`, `scouted_out`
and heavy coverage currentness retain their previous meanings. Stale-no-hit
refresh remains its separately authorized path; it does not implicitly opt into
this ordinary scout-planning stage.

X-ray's preflight requires every geometric alternative to fail the current
cached quick gate, or every alternative to have another canonical owner. It
does not combine partial ownership with partial quick failures. Current quick
baseline mate evidence and an actually played checkmate are separate approved
deferrals. Missing/incompatible evidence keeps work unless an independent
approved rule fully resolves it. A surviving alternative's mate score alone is
not a new preflight rule. No additional geometric filter is introduced.

`ExistingPositionEvidence` records exact FEN, engine/profile/version/budget,
established engine options, cache IDs and score provenance. Existing cache rows
lack engine-option columns: only the established Threads=1/Hash=64 contract is
accepted here; changed options fail open. Profile identities must remain
immutable for a configuration, with a version bump for changed evidence semantics.
This does not retroactively certify unknown external cache producers.
The shared ownership lookup is repeated inside `save_heavy_result`'s existing
`BEGIN IMMEDIATE` transaction before a new candidate can be persisted.

The row is a mapping with `move_id`, `game_id`, `ply_number`, `move_number`,
`color` (`white`/`black`), `san_played`, `uci_played`, `fen_before`, `fen_after`,
`source`, `source_game_id`, `white_username`, and `black_username`.

`analysis_results.HeavyResult(state, candidate=None, details={}, opportunity=None)` is a frozen
dataclass; `heavy_adapters` re-exports it for compatibility.
Allowed specialist states are `candidate`, `analyzed_no_hit`, and `error`.
Details must be JSON-serializable reasons/evidence. A candidate payload contains
`candidate_status`, `confidence`, `detector_version`, `solution_move_uci`,
`solution_move_san`, `solution_line`, `notes`, and `metadata_json` (a JSON string).
It does not supply the database candidate ID. The dispatcher validates the
stored position, legal solution move/SAN, nonempty solution line, and detector
version; it converts exceptions to retryable error results. Specialists and
tests remain responsible for proving the full solution and tactic semantics.

Coverage `candidate` means a heavy hit; it is distinct from the candidate's
review/status field. For example, Mate V3 returns a `confirmed` candidate payload
while its coverage status is `candidate`. Specialists do not return `rejected`;
that state can arise from explicit repository reconciliation.

## Versions and exact coverage rules

| Identity | Meaning and change rule |
| --- | --- |
| `screener_version` | Static rejection logic. Bump when the safe screen's meaning changes. Current fork: `2`; mate pass-through: `0`; pin: `1`. |
| `scout_version` | Scout decision logic. Bump for logic changes. All three current scouts: `1`. |
| `scout_config` | Exact canonical JSON string comparison, not just a profile label. Includes engine name/version, profile name and definition, engine options, and tactic thresholds. Current fork loss threshold: 80 cp; mate limit: 3 moves. Configuration changes invalidate dependent negatives without requiring a separate logic-version change. |
| `analyzer_version` | Heavy specialist semantics. Bump for changes to verification, thresholds, or evidence requirements that make prior heavy conclusions obsolete. Current Fork V2: `2`; Mate V3: `3`; Pin V1: `1`. Candidate payload `detector_version` must match. |

Pin's scout also uses an 80 cp loss threshold, with its own canonical config
identity. Its implementation, thresholds, proof rules, and limitations are in
[MISSED_PIN_V1.md](MISSED_PIN_V1.md). Registration added no pin-specific branch
to the crawler and changed no fork/mate version or coverage rule. A generic CLI
exception allows `--analysis` with a saved-scope **read-only negative preview**;
the existing write-mode filter restrictions remain intact.

| Coverage status | Meaning and stored evidence | Currentness |
| --- | --- | --- |
| `screened_out` | Safe static rejection; current screener version, scout version `0`, empty scout config, analyzer version `0`; static reason in details. No heavy analysis claimed. | Safe screener exists and screener version matches. Scout/config/analyzer versions are ignored. Otherwise `needs_screen`. |
| `scouted_out` | Passed/required screening, then rejected by the light scout; current screener/scout/config, analyzer version `0`, scout reason/evidence. | Screener version matches, scout version matches, and nonempty scout config matches exactly. Heavy version is ignored. Screener mismatch gives `needs_screen`; scout/config mismatch gives `needs_scout`. |
| `analyzed_no_hit` | Specialist completed verification without a hit at its configured method/budget; all current versions/config stored. | Same upstream checks as `scouted_out`, followed by matching analyzer version. A heavy-version mismatch gives `needs_reanalysis`. |
| `candidate` | Heavy hit associated with a canonical candidate. | Analyzer version matches; screener, scout version, and scout config are ignored. Otherwise `needs_reanalysis`. |
| `rejected` | Retained heavy candidate judged rejected, such as by explicit stale-version reconciliation; preserve its identity/history. | Same rule as `candidate`. |
| `error` | Failure with diagnostic details; not a completed negative conclusion. | Always `retry`, regardless of stored versions. An eligible retry passes through planning again; it is not automatically a heavy hit or miss. |

Missing coverage, unknown status, or mismatched analysis type gives
`needs_screen`. Checks are ordered: screener first, then scout/config, then heavy
where applicable. Existing `candidate`/`rejected` rows with `scout_version = 0`
are therefore current and skipped when their analyzer version matches.

**Current rollout limitation:** currentness classification and dispatch eligibility
are separate. `plan_negatives` protects all existing `candidate`, `rejected`, and
`analyzed_no_hit` rows, even stale ones; it records stale ones as
`pending_heavy_refresh` rather than adding them to the dispatched queue. It also
protects rows with a candidate reference and canonical candidates without coverage.
The default controlled heavy runner consumes the eligible scout-positive
queue. Automatic version-refresh/reconciliation orchestration is not enabled.
Changing a version does not, by itself, activate that refresh path.

An explicit source-no-hit refresh operation is available only for one analyzer
in the exact saved ten- or 500-game scopes: `--refresh-no-hits-from VERSION` with
`--heavy-test-10` or `--heavy-validation-500`. It uses `plan_stale_no_hits`, bypasses static/scout work, and
rechecks source coverage/candidate absence atomically in the generic repository.
Candidate reconciliation remains a separate operation. Expanding a rollout
requires separate approval; all-games heavy execution remains unavailable.

## Candidate identity and write safety

- Canonical identity is `(move_id, tactic_type)`. Reuse the existing
  `candidate_id`; never delete/reinsert to refresh an analysis. Multiple matching
  candidates cause an error rather than an arbitrary choice or deletion.
- The repository updates result fields in place and retains `created_at`,
  `reviewed_at`, the ID, and training references. Insert only when no canonical
  match exists. Candidate and coverage writes commit atomically.
- Current coverage short-circuits persistence. Negative-only writes never
  overwrite candidate/rejected coverage or canonical candidates. A normal heavy
  no-hit also cannot demote an existing canonical candidate.
- The repository offers explicit `reconcile_stale=True` for separately controlled
  stale-version handling. A no-hit may mark an older candidate rejected in place,
  retaining its solution and history anchor; a candidate whose detector version
  already matches stays protected. The current rollout does not enable this option.
- Preserve all training history and all rows outside the authorized scope/queue.
  Before live writes, run tests, preview/record the queue, and create a SQLite
  backup using the backup API with integrity checks. Afterward compare protected
  data, IDs, counts, and duplicates, and run `quick_check` and `foreign_key_check`.
- A same-version rerun skips completed rows without timestamp churn, cache
  searches, candidate ID churn, or unnecessary inserts/updates.

## Adding specialists and retiring legacy launchers

Add a calculation module and adapter, then register an `AnalyzerDefinition` in
`analysis_registry.ANALYZERS`. The existing crawler, planner, dispatcher, and
repository consume that interface; do not add tactic-specific branches to them.
See [ADDING_ANALYZERS.md](ADDING_ANALYZERS.md) for the implementation/test checklist.

The following legacy code remains on disk but must not be used as the central
pipeline's execution or persistence path:

| Legacy path | Reason / replacement |
| --- | --- |
| `analyze_forks.py` standalone `main`, `clear_existing_fork_candidates`, `delete_fork_candidate`, `save_fork_candidate` | Old independent scan and destructive candidate persistence. Use the registered Fork V2 specialist. |
| `analyze_forks_v2.py` standalone `main`, `load_batch`, `clear_existing_fork_candidates`, `delete_fork_candidate`, `save_fork_payload`, `analyze_position` | Independent crawl or delete/reinsert persistence. `analyze_position` is a legacy wrapper that saves. Only the public `analyze_single_move` calculation and pure helpers belong behind the adapter. |
| Fork V2 `apply_existing_candidates` / `audit_existing_candidates` standalone modes | Separate selection, engine access, and run bookkeeping bypass central orchestration. The apply path includes in-place updates, but is not the central repository workflow. |
| `analyze_mates.py` standalone `main`, `get_move_batch`, `remove_old_mate_results`, `delete_missed_mate_candidate`, `save_missed_mate_candidate`, `save_engine_analysis`, direct-engine `analyze_position` | Independent scan, deletion of older candidates, delete/reinsert saves, or unshared engine access. Use `analyze_single_move` through the registered Mate V3 adapter and shared engine service. |

These entry points have not been removed or technically disabled. Do not launch
them from a UI, adapter, script, or future analyzer integration. UIs consume
shared services and must not start Stockfish directly.

## Validated 500-game benchmark

Historical Fork V2/Mate V3 benchmark (before Pin V1 registration): exactly
**500 games**, **13,679 user moves**, IDs 2701â€“3200. Tests: **56
passed** before the expansion. The earlier 10-game test had already completed
66 fork and 7 mate checks, reducing the original queue of 2,579/427 to 2,513/420.

| Remaining-queue result | Missed fork | Missed mate |
| --- | ---: | ---: |
| Heavy checks attempted | 2,513 | 420 |
| Candidate hits | 0 | 4 |
| `analyzed_no_hit` | 2,513 | 416 |
| Rejected / errors | 0 / 0 | 0 / 0 |
| Engine cache hits / misses | 11,387 / 0 | 201 / 827 |

Four new mate candidates received IDs **1831â€“1834**. All **925** existing IDs
were preserved, including **154** in scope; no existing candidate was updated.
Candidates: **925 -> 929**; training attempts: **11 -> 11**; coverage:
**25,195 -> 28,128**. Outside-scope game/candidate/coverage/history data was
unchanged; the shared position cache gained reusable evidence. Both SQLite
integrity checks passed. Run time was **49.55 s**, followed by a **2.04 s** rerun.

The identical rerun proved **zero pending heavy checks, zero database row
changes, zero duplicate candidates, zero ID churn, and zero engine searches**.
This establishes scope safety/idempotency for the recorded fork/mate versions;
it does not establish exhaustive tactical recall or validate unimplemented
analyzers/version-refresh orchestration.

The zero-heavy-work result at that checkpoint applied to those two specialists.
Pin subsequently received its own controlled validation; these historical
metrics are retained separately from later Pin/Skewer results above.

Pin V1's original separate preview covered the same 13,679 user moves: 0 current,
4,511 static negatives, 9,168 scout inputs, 5,810 scout negatives, and 3,358
proposed heavy checks; 0 errors, 63.91 seconds. All 89 tests passed beforehand.
At that preview checkpoint, no live writes or pin heavy calculations ran, and the live database SHA-256
was unchanged. See [pin preview](../reports/missed_pin_preview_500.json).

Subsequent Pin V1 heavy validation yielded two candidates (1835/1836) and 3,363
no-hits across the saved scope. The [Pin V2 implementation](MISSED_PIN_V2.md)
preserves those rows and V1 source, changes only the heavy analyzer version to
`2`, and introduces bounded proof/attribution helpers and shared opportunities.
Its initial gold validation and [500-game proposal](../reports/PIN_V2_VALIDATION.md)
were read-only. The subsequent [saved-500 refresh](../reports/PIN_V2_LIVE500_ROLLOUT.md)
is complete. Stale heavy refresh still requires explicit scope/version selection;
registration does not automatically activate it.

Evidence: [preflight](../reports/heavy_write_500_preflight.json),
[run report](../reports/heavy_write_500.json), and
[rerun report](../reports/heavy_write_500_rerun.json).
Safety backup: `merlin_before_heavy_analysis_20260906_115031_097026.db` in the
project root. Heavy execution remains limited to the saved 10- and 500-game
validation modes. Expansion to all games is not enabled or validated.

## Stored tactics in Game Review

The review read path is `TacticQuery -> TacticReadService -> TacticalMoment ->
TacticalMomentsPanel`. `GameReviewRepository` provides real games and canonical
moves. Candidate Viewer shares the query visibility policy. Game Review uses
a read-only SQLite connection, outcome-first opportunity presentation with a
canonical legacy fallback, and its existing replay state for pre-move jumps.
No analyzer, engine/cache request, reconciliation, or persistence operation is
part of this path. Future missed-tactic types appear through shared policy and
presentation defaults, without tactic-specific UI branches.

See [Game Review developer guide](GAME_REVIEW_TACTICS.md).

Tactical selection reloads one active candidate/result by ID and renders all
details through a single panel method, clearing absent optional fields. Proof
visibility is explicit and independent of detail scrolling. `StoredLine` prepares
canonical SAN/UCI/position data for future Merlin Line navigation; it has no engine
or persistence access. Review retains its actual-game step. Future Explore and
Compare remain separate session-state concerns, not new database history.

## Feedback generation

Fork V3 adds a separate existing-candidate verification registry and orchestration
service. It supplies the stored move to a pure calculator, shared engine/cache and
bounded proof/target-settlement helpers. Geometry, realized targets and retained
payoff are distinct. Its generic reconciliation repository updates existing IDs
only; the current command is read-only and has no apply flag. Normal Fork V2
discovery and screener/scout versions remain unchanged. See
[Fork V3](MISSED_FORK_V3.md) for policy, ambiguity and live-write safeguards.

The shared `CandidateLineSet` pipeline now has an opt-in read-only Fork V3 adopter:
existing candidate -> verification registry -> shared line/cache service -> gate
-> approved root/child lines -> Fork proof and shared settlement -> conservative
consensus -> Scale evidence -> opportunity/feedback proposal. Root lines are
unique user moves; alternative defenses belong to child positions. A required
stored move omitted from top-N receives an explicit restricted shared request,
not an automatic rejection or fabricated global rank.

The same typed `AnalysisProfile` controls generation, gate, proof windows and
interest weights. One-line and multi-line modes share the interface. A future
Admin Console must consume this settings schema. Fork-specific material proof
remains distinct from objective admission. Every approved first opponent reply
and first player response is compared; later plies follow the best approved move
within bounded settlement. Disagreement and incomplete/critical evidence remain
ambiguous. Scale never overrides proof or selects an optimistic representative.

This preview wrote new line evidence only to in-memory SQLite. The subsequent
additive cache migration and tiny cache-only live test are complete; existing
position-cache keys, coverage currentness and ID-preserving persistence are unchanged. No other
analyzer or full-history discovery path is migrated. See
[CandidateLineSet](CANDIDATE_LINES.md) and [Fork V3](MISSED_FORK_V3.md).

Verified facts, wording and UI rendering have separate owners. The read service
passes records through `feedback.FeedbackContextBuilder` (opportunity first,
registered legacy metadata adapters second, canonical fallback), then through
the deterministic `FeedbackGenerator` to a structured `FeedbackResult`.
Game Review renders that result. Feedback has no engine, database, analyzer or
UI dependencies. Unknowns and attribution remain intact; contextual motifs cannot
become primary causes. It never backfills candidates or changes TacticalOpportunity.

Concise review, teaching, alert and summary share the same context. Trusted template
providers and legacy adapters have separate registries. Future feedback packs must
be JSON/data only with an explicit file-type allowlist, no scripts/executables,
dynamic plugins or pack-defined fact calculations. Simple placeholders are
validated; external wording requires fact-fidelity review before activation.
No community importer or online prose generation exists in V1.

Feedback packs control wording. Future chess personas/bot profiles describe play
style and are a separate, unimplemented system. See the
[Feedback Generator guide](FEEDBACK_GENERATOR.md) for contracts, limitations,
extension points and the provisional pack schema.

## Community theme-pack security

Community packs are data and assets only; no scripts, executables, installers,
dynamic plugins, or execution of any kind. Use an explicit allowlist, initially
`.json`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`, `.wav`, `.ogg`, `.mp3`, `.txt`,
and `.md`, subject to content validation. SVG support must not allow scripting
or active/external content. JSON is parsed as data only.

On import, inspect every archive entry, reject unknown extensions and nested
archives unless explicitly supported, reject path traversal, absolute paths,
and symlinks, enforce file-count and size limits, validate the manifest before
installation, and copy approved assets only into a controlled theme directory.

Always reject executable/script types including `.exe`, `.com`, `.bat`, `.cmd`,
`.ps1`, `.vbs`, `.js`, `.msi`, `.dll`, `.scr`, `.py`, `.pyw`, `.jar`, `.reg`, and
`.lnk`. These examples do not replace the allowlist. Never run Python, shell,
PowerShell, executables, installers, or plugins from a community theme pack.

## Shared targeted proof escalation

`ProofEscalationPolicy` lives in shared typed settings.
`ProofEscalationRequest`/`Result` and `ProofEscalationService` provide bounded exact
child evidence through `CandidateLineService`; `candidate_line_settlement` replays
legal deeper PVs and refreshes endpoints. Specialists interpret motif causality;
repositories own persistence. No SQL or raw engine lifecycle enters calculation.

Fork V3.1 is an explicit existing-candidate-only consumer through the verification
registry. Its optional branch hook retains Normal evidence and compares every
approved branch conservatively. Chess ambiguity has a candidate-only structured
state; it does not become a coverage status. Default analyzers and discovery are
unchanged. See [the contract, budgets and adoption guide](PROOF_ESCALATION.md).

Breadth, verification, gate, Scale, proof windows and escalation limits all use
`AnalysisProfile`; raw evidence identity remains separate from result-currentness.
A future Admin Console can consume the schema without knowing Fork internals.
These services have no Tkinter dependency: mobile portability continues to mean
a new frontend consuming the shared core, not moving chess logic out of widgets.

## Multi-line backbone V1 consolidation

[ANALYSIS_BACKBONE.md](ANALYSIS_BACKBONE.md) is the canonical end-to-end guide.
`AnalysisBackbone` composes the existing exact-cache line service, shared gate,
explicit bounded escalation and downstream Scale. It owns no motif or persistence
policy. Fork V3.1 is the reference consumer; all saved logical results remain
equivalent. Raw engine identity stays separate from analyzer/attribution/proof/
Scale result-currentness in `AnalysisProvenance`.

`SettlementEvidence` normalizes a legally replayed bounded proof without claiming
motif causality. `CandidateLineDiagnosticsService` exposes read-only cache health
and storage metrics. The future Admin Console and mobile frontends consume these
shared services. Pattern Engine remains a sibling consumer of board/history facts.
See the [Pin adoption checkpoint](PIN_BACKBONE_MIGRATION.md); live Pin activation remains pending.

## Pin V2 read-only backbone adoption

Fork and Pin now share the candidate-only backbone boundary. The live Pin registry
remains unchanged; an explicit factory creates read-only Pin proposals. Engine
requests, caches, generic proof/settlement, interest weights and result identity
are shared. Pin geometry, causality and original admission thresholds remain in
Pin modules. Recorded legacy evidence uses an honest separate namespace, never a
new-cache identity. Full equivalence and curated results are documented in
[PIN_BACKBONE_MIGRATION.md](PIN_BACKBONE_MIGRATION.md).

No UI logic or database write path was added. Services/settings/results remain
frontend-independent so a future mobile frontend can reuse the same core.

## Proposal policy: primary consensus and threshold confirmation

Pin's opt-in backbone adapter composes `pin_consensus` and the reusable
`ThresholdReviewService`; the central backbone, live crawler and repositories do
not own these decisions. Primary causal identity/payoff consensus is distinct from
secondary annotation variance. All branch evidence remains available, and genuine
primary disagreement stays unresolved.

Threshold confirmation uses shared typed settings, exact-cache requests, bounded
request accounting and approved evidence. A just-below-threshold comparison can
request one stronger depth; it does not lower a specialist's threshold or replace
its proof. Scale remains downstream. Margin/consensus settings affect result
currentness; actual engine settings affect raw evidence identity. These core
services have no Tkinter, raw engine process or SQL ownership and remain portable
to future frontends. Only read-only Pin proposals opt in today.

The [Pin policy checkpoint](PIN_BACKBONE_MIGRATION.md) records targeted 33-case
validation and recommends separately approved activation; live dispatch is still
unchanged.

## Position / Range Evidence Toolkit V1

`position_range_evidence` is the pure factual layer above `board_analysis`: one
identity-preserving legal replay produces material, target/attacker fate, selected
attack state, relevant legal captures, and rules-only terminal/history facts.
Promotions retain identity; castling moves both identities; EP records the actual
victim square. Geometric attacks and legal captures remain distinct. No engine,
repository, analyzer, or Tkinter dependency is permitted.

This shared core is available to future desktop/mobile frontends and analyzers.
It adds no tactical verdict, compensation, ownership, or semantic-settlement rule.
No existing analyzer is adopted or activated by this addition. API, history limits,
fixtures, and timings: [Position / Range Evidence](POSITION_RANGE_EVIDENCE.md).


## Shared production board and artist themes

Game Review, Training and Art Tester use `merlin_ui.chess_board.ChessBoard`.
Future Merlin Line and Pattern Builder desktop boards must reuse that component.
Its square-coordinate contract is shared with portable `theme_core.board_geometry`;
fixed decoration slots cannot alter layout or hit-testing. Legacy, unthemed board
behavior remains unchanged. PNG/Tk image resources live in `merlin_ui.theme_images`.

`theme_core` contains data-only typed themes, bounded PNG validation/loading,
additive managed-file storage, editor state, and deterministic preview FENs without
Tkinter, database, analyzer or engine dependencies. This is the portability boundary
for future mobile/frontends. Themes cannot execute code. The standalone Art Tester
still saves/previews immutable sets independently. The integrated Appearance screen
reuses those controls through ThemeEditor; see [THEMES.md](THEMES.md).

ApplicationSettings extends the existing typed Settings/schema contract with
active_theme_id (default: default; no analysis/cache currentness impact). A shared
ApplicationSettingsRepository persists explicit changes under the user application
data directory; reads create nothing. ActiveThemeService resolves that preference
through the existing ThemeRepository, with a built-in zero-image Unicode fallback.
The UI binds data-only notifications through BoardThemeBinding in MerlinViewShell;
Game Review and Training require no tactic-specific theme code. Same-process
changes apply immediately with ChessBoard.set_theme; other windows/processes reload
when focused. Artwork draft previews do not activate a saved theme.

Color-only presets live in `theme_core.presets`: 30 base palettes, eight alternates,
and the unchanged default square colors. `board_preset_id` defaults to `custom`, so
existing user themes keep their colors. Optional paired `board_custom_light` /
`board_custom_dark` preferences retain the last manual square colors. The shared
service overlays only squares on the resolved artwork theme; it never rewrites
saved theme files, copies assets, or changes analysis/cache identity. Explicit
activation of a complete saved theme clears square overrides and uses that theme's
own colors. ThemeEditor applies palette/manual square changes immediately through
this service; other draft fields retain the existing Save as / Use selected theme
workflow. Thin renderer contrast edges preserve marker roles and fallback glyph
readability across palettes; PNG art and hit-testing remain unchanged.

The existing PNG/JSON manifest, image decoder, managed snapshots, board geometry and
preview fixtures are reused. A bounded folder/ZIP importer validates every entry,
never extracts untrusted paths, and saves only canonical approved assets. Public
Art Tester source/builds remain untouched. Existing immutable snapshots intentionally
support Save as; deletion/overwrite and feature-specific copies are not introduced.
No chess database, analyzer, engine or occurrence writer participates in appearance.
See [THEMES_AND_ART.md](THEMES_AND_ART.md) for the format, security limits, launcher,
and original Art Tester design; THEMES.md documents the completed application integration. Ghost pieces are outside V1.


## Critical Moment Context V1 (experimental, report-only)

`CriticalMomentContext` is a sibling interpretation model above stored analyzer
evidence; it does not replace TacticalOpportunity, analyzer results or The Scale.
Analyzer answers "what tactic?"; Scale answers "how interesting is the approved
line?"; context answers "what kind of learning moment, and provisional display
importance?". No production ranking/scheduling integration is active.

- `critical_moment_context.py`: immutable evidence/context/score models, pure
  interpretation, and experimental `ContextPolicy` using the shared typed
  Settings/schema/identity conventions. Defaults are report-local, not global
  settings or analyzer thresholds; no tuning from human verdicts.
- `critical_moment_evidence.py`: factual actual-game loss observations composed
  from LegalReplay, MaterialTransition, TargetFate and AttackState. A recorded
  unrecouped loss is bounded evidence, not proof about all counterplay or later
  compensation.
- `critical_moment_repository.py`: SELECT-only exact-FEN score reader. Before/
  after scores must share recorded engine/version/profile/analysis-version/
  budget identity; score POV is normalized explicitly. Missing or incompatible
  evidence stays unknown. There is no engine fallback or cache write method.
- `reports/build_critical_moment_context_report.py`: report adapter for frozen
  human reviews, existing shortlist JSON, stored candidates and legal proof
  replay. Private analyzer code is not imported. Input analyzer states remain
  visible and unchanged alongside provisional context outputs.

The portable model/toolkit adapter has no Tkinter, database or engine imports.
The repository owns database reads separately; desktop code only consumes
shared presentation data. A future frontend or scheduler can use source IDs,
material/evaluation facts, importance band, completeness and policy identity,
but incomplete context must not be treated as a complete prioritization verdict.

V1 supports tactical opportunity, concrete major material loss, explicitly
proven defensive resource/forced simplification, verified settled neutral early
geometry, evidence-backed near-equal low-material context and unresolved
positions. Repeated checks do not prove mate prevention; queen trades do not
prove lost initiative or forced simplification. Early move number is not opening
theory; rook/pawn structure alone is not a theoretical draw. Strong verified
larger outcomes prevent neutral-geometry downranking.

See [Critical Moment Context contracts](CRITICAL_MOMENT_CONTEXT.md). Future work
remains Tempo/Opening/time-pressure analysis, full blunder taxonomy, advanced
aggregation, custom game sets, Extend Merlin Line and ghost pieces.


## Report-only major material blunder checker

`major_material_blunders.check_major_material_blunder` consumes one actual move and a short supplied continuation. Frozen results and local typed policy live in `major_material_blunder_models`; `major_material_blunder_evidence` composes Position/Range Evidence for direct avoidance and recovery facts. Calculation has no engine, database or Tkinter dependency. The separate report exporter reads six explicit fixture moves through SQLite `mode=ro`; it does not activate ranking, a crawler or persistence. This boundary preserves frontend/mobile portability. See [MAJOR_MATERIAL_BLUNDERS.md](MAJOR_MATERIAL_BLUNDERS.md) for the conservative free-loss standard and unresolved compensation policy.


### Material Blunder V1 freeze and audit-status presentation

Major Material Blunder Checker V1 is **frozen after successful audit + human
review**, with maturity **ROBUST / VALIDATED FOR CONTROLLED USE**, not globally
Trusted. The 150-game/4,470-position audit had 8 confirmations, 238 unresolved,
4,224 not_blunder and zero errors. All 8 original confirmations received human
PASS; no false positive or false negative was established in this review.
Recall and population precision remain unestablished. No production activation
or checker-policy change accompanies the freeze.

`review_audit_status` is a portable, immutable presentation adapter over explicit
original audit metadata. `HumanReviewPanel` renders status independently of
human verdicts; it never determines whether a move is a blunder. Missing status
clears the labels. This keeps shared semantics reusable by mobile/frontends
without moving logic out of Tkinter later. Existing review records and older
review-set meanings remain intact.

The future design map retains **Discovered Attack Analyzer â€” future candidate**:
game 2666, reviewed move 163398, preceding tactical move 163397 / 30...Rc1+
(check plus uncovered bishop attack on the queen). This is outside active V1.
The recommended next separately approved design item is **Mate-Enabling Blunder
Checker V1 â€” design contract and frozen fixtures only**. Neither is implemented
or activated here. See [material checker checkpoint](MAJOR_MATERIAL_BLUNDERS.md)
and [human review status contract](HUMAN_ANALYZER_REVIEWS.md).


## Tactical event relationship V1 (inactive contract)

Analyzers identify the tactic. A separate relationship layer identifies whether
the tactic was played, missed, played by the opponent, or missed by the opponent.
Do not create permanent separate PlayedFork/MissedFork analyzer frameworks.

`tactic_occurrences` models motif independently from occurrence kind, actor and
explicit review perspective. Its derived relation and distinct actual-game /
counterfactual lines cannot be substituted for tactic truth. Existing
TacticalOpportunity geometry relationships remain separate and unchanged.
`tactic_occurrence_adapters` translates supplied known legacy missed rows,
validates root moves through LegalReplay, preserves candidate references and
fails closed on inconsistent metadata. Both are usable without Tkinter, engines
or persistence; no production consumer is connected.

Existing missed-only scope, registry identities, queries, coverage and training
remain compatibility paths. No schema, activation, historical scan or policy
change is included. See [TACTICAL_EVENT_RELATIONSHIPS.md](TACTICAL_EVENT_RELATIONSHIPS.md)
for inspection findings, storage limitations and the next separately approved
Fork Played-Tactics Pilot's required guard/proof separation.


The subsequent [Fork played-tactics pilot](../reports/FORK_PLAYED_TACTICS_PILOT.md)
adds a neutral `evaluate_fork_move` entry to the existing multiline/V3.1 pipeline.
Both legacy missed discovery and explicit actual-root discovery share one proof
body; only the former enforces the unplayed guard. `fork_occurrence_adapter` keeps
actual historical lines separate from alternate proof and has no persistence.
Legacy proof-provider identifiers remain compatibility metadata, not occurrence
labels. The cache-only 150-game pilot yielded no verified shortlist because exact
evidence was incomplete; no live played-tactic behavior is activated.


### Report-only played Fork assessment V1

`played_fork_assessment` now composes independent geometry, supplied admission,
supplied payoff proof, and recorded consequence. `played_fork_proof` consumes
saved evidence without invoking analyzers; `played_fork_descriptions` provides
qualified deterministic report wording. Existing Fork adapters and missed proof
remain unchanged. No engine, persistence, UI, filters or grading are activated.
The models reuse LegalReplay identities/material and TacticOccurrence relations
and remain portable to future frontends. See
[PLAYED_FORK_ASSESSMENTS.md](PLAYED_FORK_ASSESSMENTS.md) for contracts and scope.

### Proposed occurrence storage contract (not activated)

`tactic_occurrence_storage` defines stable, perspective-independent motif claim
identity plus immutable evidence and explicit actual/proof line models. It reuses
`tactic_occurrences` relationships and imports no database, engine or Tkinter code.
Only an in-memory test repository exists. The recommended additive hybrid keeps
legacy candidates/training/reviews intact through explicit links; no production
schema or caller is changed. See
[TACTIC_OCCURRENCE_STORAGE.md](TACTIC_OCCURRENCE_STORAGE.md) for the options, exact
identity contract, transition plan and deferred Critical Moment/mobile consumers.
Played Fork Assessment V1 is frozen after ten human reviews (8 PASS, 2 INVESTIGATE;
context ownership concerns, no Fork-truth change).


## Advisory Static Exchange Evaluation Toolkit V1

`board_analysis.static_exchange.evaluate_static_exchange` provides a pure, frozen local-exchange estimate using shared `MaterialValues`, updated-board legal captures and deterministic optional stopping. Calculation and typed contracts live in `static_exchange.py` and `static_exchange_models.py`; there is no engine, database, analyzer or UI dependency. Unknown material (`None`) remains distinct from a neutral estimate (`0`). Both tactic-truth authority and hard-rejection authority are permanently false. Optional stopping is not a legal pass or a guaranteed material bound.

No analyzer consumes SEE yet, and the package root does not eagerly import it. The retired research module only aliases the shared implementation. Existing factual replay and proof services remain responsible for full-line costs, terminal outcomes, counterplay and motif causality. See [STATIC_EXCHANGE_EVALUATION.md](STATIC_EXCHANGE_EVALUATION.md) for the API, frozen corpus, limitations and prohibited uses. This portable fact provider is available to future frontends without Tkinter and requires no persistence migration.


## Admin Console V1

The read-only Admin Console consumes admin_service, admin_database, admin_capabilities
and admin_engine through frontend-neutral status dataclasses. It reports registered
capabilities, caller-selectable typed profiles and aggregate SQLite state without
activating analyzers or inventing scheduler/profile controls. The database is opened
mode=ro/query_only; engine testing is an explicit bounded UCI handshake only. Export
is an explicit aggregate-only JSON file. Tk owns asynchronous result delivery and
navigation, while Appearance uses the existing shared theme service. See
[ADMIN_CONSOLE.md](ADMIN_CONSOLE.md) for sources, missing-data semantics, privacy
and read/write boundaries.

## Clean-user bootstrap and release identity

`application_paths` owns dependency-free profile/database/review path resolution.
`application_settings` re-exports the existing directory API; typed analysis and
appearance settings keep their current contracts. `database_schema` owns versioned
empty-schema definitions, including Occurrence Storage V1. `database_bootstrap`
owns atomic new-file initialization and read-only existing-file validation.
`merlin_ui.startup` only presents failures and connects this service to launchers.
No database/domain initialization lives inside widget handlers. These core paths
remain usable by tools, tests and a future mobile frontend without Tkinter.

New installations have all current business tables empty plus five bootstrap facts
in `application_metadata`. Existing production databases are never modified to
add this table. Admin distinguishes clean initialization from declarative migration
lineage; neither implies new analyzer activation. Shared path selection preserves
existing development DBs but places clean/frozen users in writable profile storage.

Human Review catalogs and notes are optional development resources. Their absence
leaves ordinary Game Review intact and hides/disables QA controls; the generic
selection, feedback and tactic paths remain unchanged. Review file creation still
requires explicit Save Review. `chesswizard_version` is the single release identity
source for titles, Admin and diagnostic exports, independent of analyzer versions.
See [FIRST_RUN.md](FIRST_RUN.md) and
[HUMAN_ANALYZER_REVIEWS.md](HUMAN_ANALYZER_REVIEWS.md). No analysis policy, live data,
occurrence writer activation or production schema migration accompanies this work.

## User game import V1

Import Games composes the existing provider modules (`import_chesscom`,
`import_games`) with shared `game_import_service`, `game_import_repository`,
`game_import_http`, `game_import_pgn` and typed `game_import_models`. The service
owns one background connection and sequential fetching; the repository wraps
existing normalization in per-game transactions and preserves canonical
(source, source_game_id) identity. No analysis is triggered. The Tk dialog
only gathers input and renders queued progress/results. These services remain
usable by a future mobile frontend without Tkinter.

Existing chess_accounts stores real remote identities. New clean profiles use
one local owner in the legacy users schema without inventing a remote account
or running a migration. GameReviewRepository owns newest-first date/ID ordering;
widgets do not implement normalization, deduplication or SQL persistence.
See [GAME_IMPORT.md](GAME_IMPORT.md) for fetch, failure and identity contracts.

## Explicit user analysis V1

`game_analysis_models` defines portable scope/progress/result contracts;
`game_analysis_repository` derives readiness from the existing stage-aware coverage
and protection rules. `GameAnalysisService` owns a worker connection and invokes
`analysis_crawler.iter_analysis_checks`, the incremental product entry to the same
planner/registry/scout/preflight/specialist/cache/repository pipeline used by
controlled audits. Saved validation CLI scope guards remain unchanged. No analyzer
policy/version, schema, occurrence writer, scheduler or experimental registry is
activated. `ProductionAnalysisProfile` describes the existing registered budgets;
it does not apply multi-line Normal/Quick/Deep settings to legacy adapters.

Calculation, engine/cache access and persistence remain separate. Atomic candidate/
coverage units and per-unit cancellation allow coverage-driven resume. Mate
presentation composes existing grouping rules through a scoped additive repository,
retaining IDs and refusing destructive regrouping. Pending presentation is retryable
without rerunning completed analyzers. Current occurrence tables remain untouched.

`merlin_ui.analyze_games_dialog` renders queued typed events only. Main navigation
and Game Review open it; import never starts analysis. Review reloads after a run,
while an active training session is not mutated. Shared services work without Tk
and remain reusable by a future mobile frontend. See [ANALYZE_GAMES.md](ANALYZE_GAMES.md)
for exact completion, profile, engine-path, cancellation and release boundaries.

## UI presentation boundary (polish round 1)

`merlin_ui/application_menu.py` composes existing callbacks. `information_panel.py`
provides shared Tk styling without new assets/fonts. `actual_moves_view.py` renders
actual move cells; stored Merlin proof remains the separate ProofLineTable.
`game_context.py` is a Tk-independent read-only presentation adapter over
GameReviewRepository: immutable move rows and previous/continuation context may be
consumed by a future mobile frontend. No analyzer or engine dependency is added.

ApplicationSettings.show_last_move is a UI preference only, atomically persisted
on an explicit toggle; it affects neither raw evidence nor result currentness.
Training context is local to each puzzle and hidden by default. Existing training
history methods remain the only attempt persistence path. Review routing uses
(game_id, move_id), not guessed move indices. Admin remains read-only.

Menus own permanent actions, board-adjacent panels own position context, and
services own chess/business logic. The portable core remains usable without Tk;
a future mobile implementation primarily supplies a new frontend. No schema,
proof, occurrence identity, analyzer activation or production data change belongs
to this UI work. Deferred ideas: UI_ROADMAP_2_0.md.

### UI round 1.1 navigation contract

Right panel = whole-game information/history. Bottom panel = current-position
information. Actual move-list highlight = last actual move applied to the board.
ActualMovesView remains separate from Merlin proof playback; proof mode clears
its marker, and Hide Line restores the saved actual position and marker.

GameReviewView owns one Training child for both application and standalone launch
paths. Shared menus expose Tools > Training and Human Review / QA permanently.
HumanReviewWindow composes the existing QA panel/repository; it adds no business
logic or persistence path. Normal review does not build QA controls. The shared
desktop ScrollablePanel bounds long tactic/QA detail content while actual history
and game navigation stay available. Core modules, engine services and analyzer
interfaces remain unchanged and independent of Tk.

## Manage Data V1.2

data_management_models defines immutable plans/results; data_management_repository
owns the explicit ownership graph, read-only preview, locked revalidation and
atomic deletion/reset. ignored_imports defines the optional additive suppression
extension and explicit migration API. Clean bootstrap includes it; startup never
silently migrates an existing database. Provider source + source_game_id is the
only suppression identity.

data_activity provides process-independent OS lock ownership for supported
import/analysis/training/data operations. training_session wraps existing training
history creation with candidate validation and lifetime exclusion. Calculation,
analyzer policy and proof modules are unchanged. Theme management composes shared
repository/settings/active-theme services and validates managed ownership before
deleting files. All these core services work without Tk.

Desktop Manage Data and Admin reset render previews, request explicit confirmation,
and refresh registered views. External QA records remain historical, with missing
live targets detached and numeric IDs never recycled. Full ownership, cache/reset,
rollback and migration contracts: [DATA_MANAGEMENT.md](DATA_MANAGEMENT.md).

## Fork Pass 2: functional threats and separate exchange detail

The registered Fork V2 specialist composes `fork_threats` after geometric discovery;
shared attack maps remain geometric. `exchange_presentation` separately replays
bounded supplied evidence for detail, retaining the short Training answer. The
read-only `StoredExchangeReader` uses existing cache evidence; FeedbackResult owns
presentation and the UI neither calculates chess facts nor starts an engine.
Experimental V3/V3.1 replay contracts and live candidate history remain unchanged.
See [FORK_PASS_2_CONTRACTS.md](FORK_PASS_2_CONTRACTS.md) for legality, provenance,
settings, incomplete evidence and the explicit reconciliation boundary.


## Shared actual-position evaluations

`position_evaluation` is the portable score/position/settings contract;
`evaluation_repository` reads exact shared evidence; `evaluation_service` composes
CandidateLineGenerator/Service/Repository inside existing Analyze Games orchestration.
`merlin_ui.evaluation_widgets` only draws values and emits actual-step selections.
There is no evaluation-specific database, coverage status, standalone runner or engine
inside Tkinter. The canonical score is White POV with explicit mate ownership and
unknownness. Move Quality and Accuracy remain separate consumers with their own evidence contract. This boundary
preserves the mobile goal: another frontend can reuse the evaluation core unchanged.
See [EVALUATION_UI.md](EVALUATION_UI.md).


Game Review's `ReviewSplitter` owns only desktop pane geometry and an explicit
resize callback. The view persists its fraction through the existing typed
ApplicationSettingsRepository; there is no analysis/cache identity impact.
Centered evaluation bars and missing-data presentation remain Tk-only projections
of PositionEvaluation. No chess calculation or persistence moved into widgets.


## Move Quality / Accuracy V1

The shared `move_quality` model computes mover-relative loss from compatible best
and played continuations at one decision FEN. `move_quality_settings` uses the typed
settings schema; `board_analysis.phase` supplies a reusable board-state phase fact.
`move_quality_repository` derives metrics read-only from existing candidate-line
cache rows; `move_quality_service` requests missing exact evidence through the shared
engine and cache, with per-request commits. Existing GameAnalysisService orchestrates
scope, progress and cancellation. No accuracy-specific table or runner is introduced.

`move_quality_presentation` is frontend-independent. The desktop AccuracyPanel and
Game Review simply render these models; a mobile frontend can reuse all calculations,
repositories and services. Position evaluation, accuracy and tactic admission remain
separate. Raw engine identity excludes scoring/phase policy; result identity includes
it. Missing/contradictory evidence stays explicit, with no synthetic cp for mate.
See [MOVE_QUALITY_ACCURACY.md](MOVE_QUALITY_ACCURACY.md) for contracts and policy.

## Game Explorer V1

The portable GameSearchCriteria/Row/Result contracts support read-only SQL metadata
search and typed result sorting. GameSearchService opens only its explicit active
database in read-only mode with a consistent snapshot. GameSearchRepository composes
the existing MoveQualityRepository and shared candidate/occurrence adapters; it
never calls engine generation or persistence. GameSearchTactics preserves active
canonical visibility and requires an explicit provider-selected evidence revision
for standalone occurrence claims. No timestamp-based currentness is invented.

The dedicated desktop GameExplorerWindow performs reads off the Tk thread and
hands the exact selected ID to normal Game Review navigation. Core search remains
usable without Tkinter for future mobile clients. No schema, analysis semantics,
accuracy formulas or stored history changed. See [GAME_EXPLORER.md](GAME_EXPLORER.md).

## Opening Book Foundation V1

The separate, explicitly created .cwbook library owns books, canonical positions,
book-scoped commentary, legal move edges and source references. It is the rich
master; Polyglot .bin is a verified lossy export. No production game-schema migration
is involved. OpeningBookService/Session own legal pending/save and graph navigation;
OpeningBookRepository owns transactions; frozen snapshots feed deterministic export
and read-only membership application. The desktop Studio reuses ChessBoard and
renders these shared contracts. Core logic has no Tk/engine dependency and remains
portable to future mobile frontends.

Position identity merges move-order transpositions using Polyglot-compatible state
without move clocks. First deviation means a selected-book membership fact, never
an engine quality judgment. Lookup continues through transposition re-entry. Applied
results are derived, include book version/revision/snapshot provenance, and are not
persisted in game databases. See OPENING_BOOK_ARCHITECTURE.md, OPENING_BOOK_STUDIO.md,
and POLYGLOT_EXPORT.md. No Opening Accuracy, ECO identification or live bulk
application is activated; existing accuracy, evaluation and tactic policies stay frozen.


### Shared desktop notebook styling

All desktop tab navigation uses `merlin_ui.notebook.MerlinNotebook`, a native
`ttk.Notebook` with palette-aware styling. Opening Book Studio, Admin Console,
Manage Data and Art Tester / Theme Editor share this control. New tabbed screens
should use it rather than introduce local tab styles.

The optional `ui_skin` inherits from the owning MerlinViewShell window, falling
back to DEFAULT_UI_SKIN for standalone tools. Chessboard asset themes remain
independent of application chrome. Selected tabs use an accent fill, readable
foreground and bold text; inactive and hover fills come from the UI skin. Color
resolution guarantees at least 4.5:1 text contrast and a 2:1 selected/inactive fill
contrast, with a fallback for indistinguishable custom accents. Padding uses Tk
physical units and fonts use the shared default font.

Only notebook tab/client elements use the clam renderer: Windows native tab
rendering ignores custom fill maps. The global ttk theme is not switched. Native
selection, focus, events and keyboard bindings remain intact. Palette styles can
coexist within one Tk interpreter. This module has no data or engine access and
belongs exclusively to the desktop frontend.


### Saved Game Sets / Collections V1

Static game collections are optional organization metadata, accessed through the
portable game_collection_models/schema/repository/service modules. Collection IDs
are stable, games are referenced rather than duplicated, and GameSearchCriteria
adds collection_id/uncollected filters composed in SQL before existing read-only
fact enrichment. Desktop dialogs consume the service; no core logic depends on Tk.

Existing databases never auto-migrate. Fresh bootstrap includes the extension;
explicit migration of older files requires the approved verified-backup workflow.
Saved games are protected: DataManagementRepository checks collection membership
before both preview and transactional execution; game FKs use ON DELETE RESTRICT.
Delete, Delete & Ignore and reset cannot silently discard saved membership. Explicit
collection deletion cascades only membership metadata and leaves all games intact.

Duplicate adds and unchanged edits do not churn timestamps. Supported metadata
writes use the shared activity lock and atomic repository transactions. Static
membership is distinct from future dynamic criteria-based collections; per-member
notes, export and manual ordering are deferred. See GAME_COLLECTIONS.md.

### Expanded tactic relationships V1

`tactic_relationships` is the portable typed boundary between provider-owned tactic
truth and ownership/actual-move comparison. `tactic_relationship_repository` is a
read-only adapter/planner; it reuses TacticQuery visibility and preserves frozen
occurrence UUIDs, including named signed-ID sources. It cannot write production.
Game Explorer projects accepted roots through this shared assessor; standalone
revisions remain explicit provider selections, with accepted admission and verified
proof. Archived or rejected rows cannot become active through relationship mapping.
No analyzer, Training, UI layout, engine/cache or Opening Book policy changed.
The isolated replay/backfill proposal requires separate approval before production
writes. See TACTIC_RELATIONSHIPS.md for contracts, mate handling and mobile/core use.

### FULL backup retention

After each new FULL backup is completely verified, rotate exactly one oldest
eligible ordinary FULL. Preserve milestones, release baselines, required rollback
points and ambiguous backups. If none is eligible, retain all and report why.
QUICK backups remain outside this rule. Verification, eligibility and deletion
receipts are mandatory; no filename-only automatic deletion was added. The approved
backup workflow remains backup_merlin.py. See BACKUP_RETENTION.md.


## Opening knowledge application

Opening Intelligence V1 is a frontend-independent read-only layer over authored
books and legal stored game sequences. Reader → indexed book lookup → typed game
assessment → batch/query helpers → provisional Review window. Engine evaluation
and book membership remain separate; an outside-book move may be engine-best.
No production assessment cache/schema is added. Names, preferences, membership,
policy and complete source provenance have explicit identities for invalidation.
Future mobile/API, Explorer and Professor consumers reuse these same services.
See [OPENING_INTELLIGENCE.md](OPENING_INTELLIGENCE.md) for contracts and limits.


## Opening Book Management + Active Reference V1

Opening Library Management separates untrusted package validation, clean authoring serialization, profile catalog persistence, management operations and factual reference selection. Its core remains reusable without Tkinter; mobile/frontends consume the same services. Managed and archived books are protected FULL-backup data. See [Opening Library Manager](OPENING_LIBRARY_MANAGER.md).


## Opening Library Live Integration V1.1

Canonical managed opening libraries now unify Studio, Review, matching and future
consumers. The library UUID and authored book ID are distinct identities. Typed
catalog options preserve V1 storage without migration, while coherent read-only
library snapshots expose new books without registration. Desktop notifications
provide live refresh; domain logic remains outside Tkinter. External files are
read-only until explicitly adopted. Opening Accuracy retains library, book,
version/content and game provenance through its separate composition layer.
See [Opening Library Manager](OPENING_LIBRARY_MANAGER.md).


## Opening Intelligence Application V1 — managed application

OpeningIntelligenceService remains the indexed, read-only stored-game replay layer;
ManagedOpeningIntelligenceService resolves fresh canonical library/book snapshots
for direct single-game, batch, meaningful-match and aggregation APIs. Query results
retain provenance and typed failures. The compact Review block renders shared
presentation output. No opening domain logic is embedded in Tkinter, and no engine
quality is inferred from book adherence. Derived/session-only results avoid schema
migration; membership, labels and preferences have distinct invalidation identities.
These services are reusable by a future mobile frontend and Professor/Lessons.


## Game Review Opening UX V1

ManualOpeningSelection separates session-wide intent from automatic per-game
matching. OpeningExplorationState is an immutable, Tk-independent model containing
game identity, book provenance, actual anchor, decision board, authored continuation
and variation context. Pure exploration follows authored Preferred/sole edges and
stops at branches, leaves or cycles. UI controls render it without altering actual
replay state. Game Review owns restoration and overlay switching; it never invokes
an engine. Changed game/book evidence invalidates exploration. Future Professor or
mobile clients can consume the same model. The bottom Opening mode can host future
opening metrics without crowding game/tactic panels.


## Opening Accuracy V1

The portable opening_accuracy models/settings/pure derivation/service/query/presentation modules compose Opening Intelligence with frozen Move Quality V1. Membership and engine accuracy remain separate; user and opponent metrics have separate ownership. The service reads a managed book snapshot and joins actual moves/exact depth-16 evidence within one read-only game-DB transaction. Shared public snapshot interfaces avoid feature-private dependencies.

Game Review projects already-loaded evidence through the same pure derivation. Authored-window provenance and explicit scored/total denominators protect partial results; variation statistics pool moves rather than game means. No persistent summaries, schema changes or engine-generation path are added. These APIs need no Tkinter and can serve mobile/Professor clients. See [Opening Accuracy](OPENING_ACCURACY.md) for boundaries, invalidation and APIs.

### Active project portability and recovery media

Runtime paths derive from the checkout, wherever the contributor keeps it. Runtime engines, schema/resources, build scripts and developer entry points derive paths from the checkout. Desktop/user databases, settings and opening libraries stay in normal user-data locations. External recovery media is optional and configured by its owner. `backup_merlin.py` uses the established SQLite/project backup API, `backup_verification.py` verifies local recovery contents, and `backup_recovery.py` safely replaces only owned latest recovery slots after verification. None of these services imports Tkinter. See BACKUP_RETENTION.md for commands and interruption/retention rules.

## Opening Studio single-screen authoring V1.3

Opening Studio is the daily authoring surface: one Book selector, inline New Book,
direct edits, rename/delete and external import/export. Opening Library Manager is
advanced management. `OpeningStudioService` provides one logical workspace and a
single durable destination for new books, while existing managed files and IDs
remain in place. No owner consolidation or game-DB migration is needed.

In-memory drafts persist only on explicit Save/Create. `opening_book_transfer`
validates/remaps selected graphs in one transaction; duplicate imports reuse exact
content. Confirmed book deletion hides the stable ID through existing catalog JSON,
clears removed primary choices, and retains graph rows for recovery/ID reservation.
The shared listings exclude removed books from Review. This core has no Tkinter or
engine dependency. Desktop workflow/dialog modules contain presentation only;
existing branch navigation, Polyglot and live Review refresh contracts are retained.
See [Studio guide](OPENING_BOOK_STUDIO.md) and [storage contracts](OPENING_BOOK_ARCHITECTURE.md#studio-v13-workspace-contract).


## Testing-week analysis responsiveness and atomic stages

GameAnalysisService remains the reusable orchestration boundary. Its cancellable
read-only readiness APIs, typed progress models, per-database OS ownership, engine
lifetime and stage transactions have no Tkinter dependency. Mobile/frontends can
consume the same services. The UI keeps selection responsive, ignores superseded
preview results and owns only confirmation/presentation and exit continuation.

Readiness reads selected games in bounded batches; only validity fields and exact
evidence requests are loaded. Immutable candidate-line models still validate legal
PV/score/identity contracts before a row counts as current. No new schema, analysis
profile, accuracy formula or proof policy is introduced.

SqliteTransaction owns either a top-level transaction or a nested savepoint.
Repositories commit only their own scope. A worker's unfinished evaluation,
move-quality, tactical or presentation stage rolls back on AnalysisCancelled.
Completed stages remain durable, with stable candidate IDs. Cancelled engine
output never crosses the evidence boundary. Normal request arguments stay unchanged.
OS-held locks release on crashes; Review is not an exclusive writer.

See [Analyze Games](ANALYZE_GAMES.md) for exact cancellation, preview and startup
detection contracts, and the [measured pass](../reports/ANALYSIS_RESPONSIVENESS_PERFORMANCE_PASS.md).
New/materially changed reusable APIs use explicit types and Google-style PEP 257
docstrings; no repository-wide documentation rewrite was performed.


## Progressive analysis and record hygiene

Cheap `game_analysis_selection` freezes canonical newest-first IDs without reading
engine proof payloads. `GameAnalysisService` validates/processes windows from the shared
`AnalysisBatchSettings` (50 by default), keeping exact evidence/currentness unchanged.
`game_hygiene` validates registered transitions without an engine or UI. Zero-legal-move
records cannot enter a work queue; malformed nonempty histories are isolated per game.

`evidence_errors.IncompleteLineEvidence` is re-exported from the existing proof bridge
for compatibility. `analysis_failures` maps typed uncertainty to deferral, local failures
to continue-after-rollback, and unsafe DB/engine/invariant failures to a safe stop.
No frontend interprets engine bounds, changes policy, or writes error coverage itself.
This core is reusable without Tkinter. UI batch notifications preserve active Review
navigation. No scheduler, analyzer activation, storage migration or cleanup is implicit.

Importer empty-record skipping uses the same factual legal-move concept. Production
cleanup remains a separately approved Data Management transaction with collection
protection and a fresh verified full backup. See [analysis](ANALYZE_GAMES.md),
[imports](IMPORT_GAMES.md) and [validation](../reports/ANALYSIS_ERROR_ZERO_MOVE_BATCHING_FIX.md).


## Obligation completion versus run progress

`analysis_completion` is the shared, frontend-independent diagnostic contract for
current decisions, proven conservative preflight stops, retryable missing work,
and recoverable/fatal failures. The crawler carries structured preflight provenance
through its event boundary; GameAnalysisService aggregates diagnostics; frontends
render the result. No tactic-name branches or engine interpretation belong in UI.
Inspection progress measures finished/skipped games, not positive/negative coverage.

A logical COMPLETE_DEFERRED is not yet durable coverage. The live schema admits
only six older statuses and must not overload a negative/error status. Durable
reuse requires an explicitly approved migration plus policy, exact evidence and
canonical-ownership currentness checks. This pass changes reporting only; existing
coverage/currentness and every analyzer policy remain unchanged. The audit records
why X-ray's deliberate planning stops currently requeue and proposes an additive
ledger without rebuilding owner tables. See
[completion audit](../reports/ANALYZER_COMPLETION_DEFERRAL_AUDIT.md).


## Optional durable conservative outcomes — copy rollout

The additive `analysis_deferred_checks` ledger now supports explicit registry opt-in.
Generic planner, crawler and readiness services reuse current receipts without
re-screening/scouting/proof. Shared dependency fingerprints invalidate on relevant
policy, raw evidence, move/game and ownership changes. The repository transactionally
rechecks complete preflight predicates before writes and never changes tactic truth.

This is enabled only on explicitly migrated databases; bootstrap does not create the
ledger automatically. Production remains unmigrated. See the
[portable contract](DEFERRED_ANALYSIS_OUTCOMES.md) and
[copy validation](../reports/DEFERRED_LEDGER_COPY_VALIDATION.md).


## Opening Analysis Engine and repertoire-side foundation

`opening_repertoire` provides explicit White/Black/Both-reference intent in existing book metadata, without a schema addition. The explicit authoring setter uses OpeningBookService/repository and preserves IDs; the analysis path only reads snapshots. Legacy books without a side require configuration for repertoire-specific statistics.

`OpeningAnalysisService` coordinates selected-library lookup, the existing Opening Intelligence legal replay, a read-only metadata repository and shared `assess_opening_evidence`. The latter is also used by OpeningAccuracyService; scoring/window rules still live in existing pure Accuracy/Move Quality modules. `opening_analysis` composes immutable facts; `opening_analysis_statistics` aggregates them; query/accessor modules serve future Explorer, Collections and Professor clients without repeated database work. No automatic persistence or engine fallback exists.

The transient matching set retains scope, owner, book/version/provenance and exclusions. Full-game known-position user adherence is explicitly distinct from bounded-window engine Accuracy and legacy Review's window adherence. Common departures group by canonical FEN; repeated unanswered opponent moves are neutral gap candidates. Nested variation IDs remain stable and late re-entry does not rename an expired accuracy window.

All new core modules import without Tkinter. A future mobile frontend can use the same service/model contracts; no analysis/business policy is added to desktop callbacks. Final Opening Analysis UI, Lessons and scheduling are deferred. See [contracts](OPENING_ANALYSIS_ENGINE.md) and [audit](../reports/OPENING_ANALYSIS_ENGINE_V1.md).


## Opening Studio advisory service (2.5)

On-demand Stockfish authoring assistance composes shared candidate-line profiles, request identity, cache repository, cancellation and legal playback. `opening_engine_models/service/presentation` contain reusable evidence/anchor contracts; `opening_book_line` contains pure merge planning; `opening_engine_authoring` checks confirmed destination/currentness; the normal book repository commits an insert-only whole line atomically. Tk (`opening_engine_panel/dialog`) owns presentation and worker delivery only. All core pieces import without Tkinter for future mobile/Professor/gap consumers.

Engine advice is distinct from repertoire intent, tactic admissions, book weights and Accuracy. Navigation starts no engine. The selected saved route/revision is immutable across preview and revalidated before Add. Existing authored metadata/IDs are never replaced; new edges are neutral. Production game/cache evidence is read-only; optional complete advice uses the shared candidate-line schema in the separate writable user-data `cache/opening_lines.sqlite3`. No production or book schema migration, historical analysis, automatic gap filling or global analyzer activation. [Full contracts and guide](OPENING_STUDIO_STOCKFISH.md).


## Game Review Opening Workspace V2

Opening Review V2 consolidates multi-game opening study inside Game Review. `opening_library_listing`, `opening_workspace` and `opening_studio_handoff` are reusable frontend-independent services/models; Tk manages widgets, worker cancellation and rendering. Existing Opening Analysis/Accuracy determine all facts. Studio handoff takes its cursor and facts from the displayed game, independently of browsed Opening Moments. The portable `studio_source_step` validates the displayed board and exact game/opening identity without I/O; the existing planner reuses exact authored/transposed positions or stages only the suffix after the nearest authored ancestor on the actual route. Studio handoff is an immutable revision-bound proposal; persistence remains the generic atomic book-line repository path after explicit confirmation. The pure `handoff_disposition` inspects authored graphs to retire satisfied/superseded proposals. Ordinary Save Move needs no later handoff commit, and redundant creates retire without writes; inspection never rebases stale write consent. Recent analysis membership now composes exact existing readiness before its 50/100 limit, without modifying analyzer or deferred-ledger truth. See [workspace guide](GAME_REVIEW_OPENING_WORKSPACE.md).

## Default opening content (V1)

`default_opening_source` validates pinned CC0 rows and data-driven curation; `default_opening_builder` produces deterministic `.cwbook` graphs through existing package persistence and the shared Polyglot exporter. `opening_entry` is an optional metadata contract consumed by the existing lookup/replay services, not a second analysis subsystem. Explicit family entry gates deviations/gaps and window eligibility; Accuracy arithmetic and engine policies remain unchanged. Legacy unanchored books preserve their matching policy.

`default_opening_install` explicitly seeds an editable user-data copy only for a new opening-library profile. UI startup calls this shared service; no core content module imports Tkinter. Catalog reads and later launches never overwrite authored content. The runtime asset allowlist contains only the public default, companion, CC0 text and manifest; owner books and private audit rows are excluded. See [DEFAULT_OPENING_LIBRARY.md](DEFAULT_OPENING_LIBRARY.md) for provenance, regeneration, anchor semantics and upgrade/rollback boundaries.

## Opening selection performance (V1)

Opening selectors read `opening_library_metadata` headers: the managed catalog and
`books` rows only. `managed_book_choices` deliberately carries no content digest;
its optional `content_identity` is `None`. Header revisions are display/refresh
metadata, never substitutes for selected-snapshot provenance. Explicit graph
resolution uses `OpeningLibraryService.get` and reads only the selected book.
The automatic `OpeningReferenceService.choose` API remains available for explicit
core consumers; Game Review no longer calls it implicitly.

Opening Review starts with **Select an Opening**. Its selection loader owns at
most one read-only worker and one replaceable pending request. Worker output is
applied on Tk's thread only when its generation, selected identity, displayed-game
inputs, and managed file/WAL fingerprint still match. Switching or clearing the
selection invalidates prior output immediately. The existing aggregation worker
continues to own all-game matching, stored-quality reads, and statistics. Neither
worker requests an engine or persists assessments. Closing the view detaches its
callbacks; a late read-only result cannot access destroyed widgets.

Studio keeps one immutable selected graph. `BranchNavigation` caches projections
by snapshot object and route prefix; any refreshed snapshot discards those
projections. Branch widgets are rebuilt only for a new snapshot or newly exposed
contextual paths. Ordinary clicks update the active heading, move highlight,
board, and detail controls. Committed edits still refresh selectors and Review;
navigation no longer broadcasts an edit notification. These caches are transient
and introduce no schema or data migration. Chess entry, transposition, variation,
accuracy and deviation contracts are unchanged.

Measured costs and regression/safety evidence are recorded in
`reports/OPENING_PERFORMANCE_SELECTION_UX_V1.md`.

## Contributor-facing documentation and source boundaries

See [API overview](API_OVERVIEW.md), [development setup](DEVELOPMENT.md) and
[public-source boundaries](PUBLIC_SOURCE.md) for source orientation and local-data
exclusions. `tools/public_api.json` indexes reusable modules; `tools/check_pydoc.py`
imports/renders them in a bounded worker that denies runtime side effects, while
`tools/build_pydoc.py` writes ignored HTML pages. This is documentation tooling, not
an engine/cache path or runtime API change. Existing historical report references
are local evidence, not dependencies shipped to end users. Older API doc/type gaps
are tracked separately from pydoc render success. Important chess/business logic
remains frontend-independent, including for possible future mobile clients.
