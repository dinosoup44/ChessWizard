# Analyze Games V1

Status: explicit user-started production orchestration. No automatic import
analysis, scheduler, new tactic policy, occurrence writer, or live backfill.

## Product flow

File > Import Games -> Tools > Analyze Games -> Start Analysis -> Game Review.
Analyze Games is available under Tools > Analyze Games.... Opening the dialog only reads coverage. The window appears before coverage counting finishes. Scope selection and Start
remain available during background preparation. Recent 50 is the default. The
preview inspects at most one batch; older history is explicitly uninspected.
Selected Game reads only that game. Analysis always requires an explicit click.
The worker freezes cheap scope membership at Start; later imports cannot expand it.
After completion or Stop, Game Review reloads its existing read model without an
app restart. Training loads its existing eligible candidates when closed/reopened;
an already-open training session is left alone. Analysis creates no attempts.

## Scope and completion

- **Recent 50** (default): the newest 50 actionable legal real games; completed, current stable-final deferred, and invalid/empty games are excluded before the limit.
- **Recent 100**: the newest 100 actionable legal real games, processed in two default batches.
- **All Missing / Continue Full History**: progressively inspect all real imported games with missing,
  retryable or stale negative coverage, including partially completed games.
- **New games (no current coverage)**: real games with no current analyzer checks.
  This deliberately uses coverage, not candidate presence or an import date.
- **Selected game**: the game selected in Review when the dialog opens. The core
  scope supports explicit multiple IDs; the V1 desktop offers its current game.

Development games and zero-legal-move records are excluded. A legal one-move game
remains valid even when that move belongs to the opponent. Empty records do not
acquire evaluation, quality or tactical completion rows. No approximate candidate-count shortcut determines completion.
`game_analysis_repository.analysis_snapshot` composes the existing
`analysis_crawler.coverage_decision` and planner protection semantics for every
user move and registered analyzer. It runs off the Tk thread.

| Existing state | Product behavior |
|---|---|
| screened_out | Current only with safe screener and matching screener version |
| scouted_out | Current with matching screener, scout version and scout config |
| analyzed_no_hit | Current with matching screener/scout/config and analyzer version |
| candidate / rejected | Current by analyzer version; scout version 0 stays valid |
| error / absent | Retryable / pending |
| stale heavy result or canonical candidate without current coverage | Protected; separately reported, not silently called complete or reconciled |
| X-ray preflight disposition | Planning only; never a coverage completion status |

Protected stale heavy rows need an explicit maintenance/reconciliation workflow;
this user workflow cannot erase them. This is the existing planner's restriction,
not a new version or admission policy. A game is complete only when all required
checks and exact actual-position evaluations are current and its mate presentation is ready. Candidate existence alone
never makes a game complete.

## Reused pipeline and profile

`GameAnalysisService` owns the worker connection/lifecycle and calls the new
incremental entry **in the existing central crawler**, `iter_analysis_checks`.
Each unit uses the existing `plan_negatives`, registry screen/scout/preflight,
`dispatch_heavy`, shared `PositionAnalysisService`/`engine_position_cache`,
`apply_negatives`, and ID-preserving `save_heavy_result`. Negative rows retain
analyzer_version=0. Candidate plus coverage commit atomically. No legacy launcher
or destructive full scan is invoked. Controlled 10/500 validation commands retain
their original scope guards.

The unchanged `analysis_registry.ANALYZERS` currently selects Fork V2, Mate V3,
Pin V2, Skewer V1 and X-ray V1. Their geometry, thresholds, proof/settlement,
attribution, versions and ownership behavior are unchanged. Fork V3.1 discovery,
backbone experiments, played-fork assessment and Major Material Blunder are not
normal registry entries. They are not newly activated. SEE remains advisory.

Profile is **Production defaults**, described by the shared typed
`ProductionAnalysisProfile`. The production specialists currently use existing
`tactic_scout_v1` (10,000 nodes), `tactic_quick_v1` (depth 10), and
`tactic_verify_v1` (depth 18) profiles; shared scout engine options remain one
thread/64 MiB Hash. The separate multi-line `AnalysisProfile` Normal/Quick/Deep
presets do not control these adapters. Labelling this run Normal or applying that
preset would misrepresent or change their policies, so V1 offers no profile picker.
Admin retains its existing profile/status interfaces. There is no parallel hidden
budget configuration; the descriptor does not override engine-cache identities.

`LazyScoutEngine` resolves the existing Stockfish relative path under
`application_root()`, which is the bundled module directory when frozen, never
under the writable user DB directory. It starts lazily on an actual cache miss.
No engine download/version change. Candidate-line cache is not newly adopted.

## Mate presentation and occurrence boundary

Mate visibility already requires a generated episode. The scoped
`analysis_presentation.refresh_mate_episodes` reuses the existing pure
`build_candidate`/`build_episodes` rules and insertion routine. It processes only
the visited game, preserves episode/member/candidate IDs, appends missing members,
and refuses a protected primary/status change or merge. It never calls the legacy
clear/rebuild launcher. Presentation is a separate atomic, retryable transaction;
a candidate saved before interruption is detected as needing presentation next run.

The current heavy repository writes canonical legacy candidates and coverage, with
TacticalOpportunity payloads where supplied. It does **not** write occurrence
storage. This task leaves that boundary unchanged: no occurrence backfill, new
occurrence semantics, duplicate occurrence, or training write. Existing occurrence
and training consumers remain intact.

## Progress, cancellation and errors

Typed progress separates coverage preparation from actual analysis. Coverage
shows games checked / frozen total and a real percentage. Analysis reports games
processed / queued, the current game and stage (position evaluation, move quality,
tactical analyzers, presentation), completed checks and elapsed time. No ETA is
invented. Counts shown during a stage are provisional until its commit; final
counts exclude rolled-back work.

The Tk thread only collects scope and renders messages. Superseded previews receive
their own cancellation event; stale preview results cannot overwrite a newer scope.
SQLite reads use an interruptible progress handler, and evidence validation observes
Stop between records. Start cancels its own obsolete preview without waiting on a
global backlog. There is no automatic full rescan after Stop.

**One worker per resolved database, across processes.** An OS-held
'.analysis-lock' gives analysis-specific busy feedback; the existing '.activity-lock'
also excludes supported import/training/data-management writers. Review remains
read-only and usable. Empty lock files carry no ownership: normal exit and process
crash release the OS lock, without PID guessing or unsafe stale-file deletion.
Read-only previews in separate app processes may still run concurrently and consume
CPU; they cannot start extra engines. A second worker fails immediately.

**Atomic unit: one stage of one game.** Evaluation, move quality, the game's tactical
checks, and presentation each commit separately. SqliteTransaction composes existing
repositories through savepoints. Cache services leave an enclosing transaction open.
If Stop arrives mid-stage, every insertion/update in that unfinished stage rolls
back, including evidence and candidate/coverage rows. Earlier completed stages and
games remain durable. No staging tables, migration or persistent resume cursor exist.
For example, cancelling tactical checks retains this game's completed evaluation
and quality evidence but repeats the unfinished tactical stage next time.

Stop terminates only the worker-owned Stockfish process. Normal requests still use
the same SimpleEngine.analyse calls, budgets, options and engine identity.
AnalysisCancelled is control flow outside ordinary analyzer error handling:
aborted searches cannot become error coverage, no-hit results or cached partial PVs.
The next run starts a fresh engine only on a genuine miss. A cancelled startup can
still wait for python-chess's bounded engine-initialization timeout (10 seconds);
a process-exit confirmation failure is reported, not silently called successful.
Commit retries tolerate brief read locks while checking Stop at bounded SQLite
timeout intervals.

Closing during work offers **Stop analysis and exit** or **Keep running / Cancel
exit**. Confirmed exit resumes automatically after cancellation/rollback. No second
close click is needed. Genuine errors retain the existing retry/protection rules.

Readiness batches contain only requested games, validity metadata and exact raw
requests. Repeated requests share validated in-memory summaries within the snapshot.
Every loaded payload still passes the original model's legal-PV and compatibility
validation; no approximate completion flag replaces evidence. Current stages are
skipped precisely. Completed games are rechecked individually, with no final global
scan. Existing candidate/episode IDs and occurrence/training boundaries remain intact.

GameAnalysisService.has_incomplete_work is the lightweight, cancellable background
startup-detection foundation. It stops at the first unfinished game and performs no
engine work or writes. Automatic launch-time execution is intentionally not enabled:
a future preference can offer Resume after the main window is usable. No scheduler
or new settings subsystem is introduced.


## Idempotency and storage

Current checks are skipped before screening/scouting/heavy analysis. Exact cached
evidence is reused by existing services. Identical completed work creates no new
candidate IDs, coverage updates, timestamps, searches or cache entries. Errors
remain pending. X-ray planning-only dispositions are intentionally recomputed on
later runs: such a game can remain pending even when no heavy work is needed.
The UI reports these as deferred and does not invent durable negative statuses.

Analysis grows the position cache. The dialog states this; Admin shows actual
storage/cache counts. No size prediction, pruning, full-history automatic run,
schema migration or backup-on-every-position is introduced. Per-unit negative
writes retain transaction/scope/protection checks; controlled audit runners still
perform their full integrity checks. End-to-end acceptance checks DB integrity.

## Validation and release boundary

Focused tests cover read-only preview, selection, partial resume, current/protected
rows, error retry, transactional rollback, duplicate start, start/stop/progress,
central-runner reuse, presentation recovery, UI refresh and bundled engine paths.
The opt-in real-engine acceptance imports two synthetic PGNs through the existing
fixture HTTP path into a clean temporary profile, runs the full production registry,
and renders resulting mate/fork moments in Game Review. It does not contact live
providers or use production data. Rerun checks DB bytes, candidate IDs, zero searches
and zero writes. Occurrence/training rows stay empty.

Run focused real-engine acceptance explicitly:

```powershell
$env:CHESSWIZARD_TEST_REAL_ANALYSIS='1'
.venv/Scripts/python.exe -B -m unittest tests.test_game_analysis -v
```

The dialog contains scope, profile, Start/Stop and real progress/status. The
redundant Open Game Review button was removed; close the dialog to return to Review.
Game Review still refreshes after completion/Stop. The shared information surface
changes presentation only. Registry selection, analyzer policy, scoring formulas and raw request identities
remain unchanged. The testing-week orchestration/transaction changes are described above.

The certified final V1 rehearsal remains evidence of its earlier source snapshot.
UI polish has source tests only until a separately authorized frozen rehearsal;
no packaging or publication is automatic. See reports/UI_POLISH_ROUND_1.md.


## Actual-position evaluation stage (2.0 priority 1)

Analyze Games now also fills missing actual-game position evaluations through the
existing CandidateLineService/cache and shared Quick generator (depth 10, one line,
Stockfish 18, Threads 1, Hash 64 MiB). It processes the starting FEN and every actual
played ply, including opponent moves. Scope, locking, Stop/resume and worker lifetime
remain owned by GameAnalysisService. No engine work happens on preview or Review
navigation. The product commits the completed evaluation stage atomically; the second completed run
needs zero writes/searches. Evaluation progress and counts are separate from tactic
coverage. Existing analyzer policies and protected rows remain unchanged.

Games previously complete for tactics may now need evaluation evidence. No production
backfill was performed. Legacy position-cache scores without complete option identity
are excluded rather than mixed into a timeline. See [EVALUATION_UI.md](EVALUATION_UI.md)
for score/identity semantics, footprint and the actual-versus-proof boundary.


## Move-quality evidence stage (2.0)

Explicit Analyze Games also fills compatible root/played continuation evidence for
Move Quality V1, using Stockfish 18 depth 16 / MultiPV 1 / Threads 1 / Hash 64 MiB.
It runs after the unchanged Quick position-evaluation stage and before registered
tactics. A played root-best move reuses the unrestricted request; otherwise an exact
played-move restriction is cached separately through the shared service/repository.
No new table, standalone runner, candidate writes or quality coverage status is added.

Preview counts quality obligations separately, including both players. Progress and
result summaries expose quality moves, cache hits, searches and inserts. Stop rolls
back the unfinished quality stage, including an incomplete root/played pair.
Completed exact evidence is skipped on rerun, including contradictory estimates that
remain unscored in Review. Scoring/phase changes only recompute derived metrics.
`quality_settings=None` is an explicit service-level opt-out for isolated tools/tests.
No production backfill was performed. See [MOVE_QUALITY_ACCURACY.md](MOVE_QUALITY_ACCURACY.md).


## Progressive batching and recoverable failures

`AnalysisBatchSettings.batch_size` defaults to 50 (range 1–500). It uses the shared
settings schema and affects neither raw engine identity nor result-currentness.
It is not an analyzer profile or a new Admin UI. Recent 50/100 cap the newest eligible
stored games, not a promise of 50/100 new analyses. All Missing continues to the next
metadata window even if the current window is already complete or contains failures.
Each window is validated exactly before processing; no full cache-proof scan gates
its first game. Ordering remains canonical normalized played_at descending, then
game_id descending, with unknown dates last. No artificial completion summary is used.

The display distinguishes batch number, eligible game range, exact completed games,
deferred games, recoverable errors and fatal errors. The total eligible-game count
is not represented as a fully validated pending-work count. A partial preview cannot
truncate an All Missing run or disable Start merely because its first batch is current.
Completed stages are visible through normal read-only Review repositories immediately.
Batch notifications refresh ordinary Review without resetting its current move; active
proof/opening/tactic selections remain stable until the owner reselects a game.

`IncompleteLineEvidence` retains the existing ValueError-compatible uncertainty
contract in a shared engine-independent module. Bound-marked aggregate engine results
remain inadmissible as exact scores. The active stage rolls back, its game is reported
as deferred/incomplete, and the next game proceeds. No score, accuracy, tactic, cache
row or completed coverage is invented. Repeated deferrals are visited once per run;
there is no infinite retry loop or automatic threshold adjustment.

Other local input/unsupported-position/analysis failures are reported as recoverable,
with game, stage, exception type and reason. Readiness failures are isolated to their
game too. The orchestrated tactical stage rolls back adapter error coverage along with
other unfinished writes: absence remains retryable, and existing committed error rows
remain retryable under the unchanged currentness rule. Earlier completed stages remain.

SQLite failures, engine startup/termination/identity failures, explicit assertions,
memory failures and unsafe lifecycle failures stop the run. Cancellation is separate
control flow. The final result distinguishes safe fatal stop, stopped-by-owner,
completed-with-recoverable-failures and fully completed work. No production error
journal/schema was added; per-game diagnostics are carried in the result/UI.

For the two reported Move Quality failures (3253/3514), raw UCI packets demonstrate
that python-chess retains earlier bound flags in its aggregate dictionary despite a
later unbounded score packet. This pass does not strip flags or change evidence
aggregation. Those aggregate objects are conservatively deferred. An adapter-level
score-packet provenance correction, if desired, needs separate truth/parity review.
For the related empty-record import boundary, see [import hygiene](IMPORT_GAMES.md).
Detailed production audit receipts are private; the behavior and limits are
summarized in this section.


## Completion diagnostics and run progress (2026-09-26)

Run progress counts games inspected/finished or skipped, independently of whether
all chess obligations have durable completed coverage. A fully visited 50-game
window reports 50/50 and 100%; Stop and fatal errors retain partial progress.
Coverage preparation keeps its own checked-count text and no longer resets the
run bar to a per-batch percentage. The final result retains exact per-game
preflight reason codes and separates stable planning stops from retryable work.

`analysis_completion` provides typed COMPLETE_DECISION, COMPLETE_DEFERRED,
INCOMPLETE_RETRYABLE, FAILED_RECOVERABLE and FAILED_FATAL classifications. Only
exact approved, successfully evaluated preflight predicates qualify as stable.
Unknown/mixed/missing evidence, cancellation and incomplete-score exceptions do
not establish terminal uncertainty. This classification is reporting-only until
a reviewed durable outcome migration is approved. It does not authorize a
coverage write or make an absent obligation current.

Current schema has no safe completed-defer status. Recent 50's 145 X-ray preflight
stops therefore still leave 44 games queued, now explicitly reported as awaiting
deferred-coverage support rather than needing fresh engine evidence. Do not put
these outcomes in analyzed_no_hit, screened_out, scouted_out or error to hide the
queue. Do not store them in settings or application_metadata as a schema workaround.

The proposed deferred ledger and its exact evidence/policy/ownership invalidation
contract need migration approval and temporary-copy acceptance before production
reconciliation. No schema or currentness change was applied at this audit
checkpoint. The subsequent [deferred-outcome contract](DEFERRED_ANALYSIS_OUTCOMES.md)
documents the additive schema, invalidation rules and approval boundary.


## Deferred ledger on explicitly migrated profiles

On an approved migrated profile, current conservative receipts satisfy their tactic
obligations without claiming a tactic result. The summary reports completed games
with conservative deferrals separately. Retryable/missing evidence and cancellation
never become final receipts. Exact reruns skip current receipts without writes or
engine searches. Profiles without the ledger retain the earlier explicit
"awaiting deferred-coverage support" reporting; no automatic production migration
is performed. See [the contract](DEFERRED_ANALYSIS_OUTCOMES.md).


## Actionable Recent scopes (Opening Workspace V2)

`select_actionable_scope` composes the existing exact readiness contract before counting Recent 50/100. Current stable-final receipts count as completion; stale receipts remain work. Recent preparation may inspect older records before finding 50/100 obligations, always read-only and cancellable. All Missing retains progressive batching; Selected retains game-local invalid diagnostics. No analyzer, cache/profile or proof policy changed. See [workspace guide](GAME_REVIEW_OPENING_WORKSPACE.md).
