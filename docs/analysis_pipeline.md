# Time classes and light scout preview

Implemented September 6, 2026. For the maintained public system overview, see
[the architecture checkpoint](ARCHITECTURE.md). The original product handoff is
private and is not required to use this guide.

## Time classes

`time_class.py` is the shared classifier used by both PGN importers and
`migrate_games_time_class.py`. Explicit provider/header labels take priority.
Clock fallback uses base seconds plus 40 increments and provider boundaries:

| Provider | Bullet | Blitz | Rapid | Classical |
| --- | --- | --- | --- | --- |
| Lichess | under 180s | 180–479s | 480–1499s | 1500s or longer |
| Chess.com | under 180s | 180–599s | 600s or longer | no separate clock-derived category |

Sources: [Lichess FAQ](https://lichess.org/faq#time-controls) and
[Chess.com rating categories](https://support.chess.com/en/articles/8705367-why-are-there-different-ratings-in-live-chess).
Provider categories intentionally differ. Exact `time_control` remains unchanged
so a future cross-provider clock-duration comparison is still possible.

Daily maps to correspondence; UltraBullet maps to bullet. Recognized daily PGN
clocks such as `1/86400` map to correspondence. Missing, malformed, unsupported
multi-stage clocks and unknown providers remain unknown unless explicit metadata
supplies the class. Only exact rated/casual/unrated event labels are interpreted;
an arbitrary tournament name containing "Blitz" is not authoritative.

The migration first verifies a SQLite backup, then transactionally adds the
column, backfills unknown values, creates an index, and runs `PRAGMA quick_check`.
Rerunning preserves valid existing labels. Both importers now populate the
class immediately and give a clear migration error on an old schema.

Actual migration result: 1,990 blitz, 1,205 rapid, 1 bullet, 3 correspondence.
One development game remains unknown. All 3,199 imported games were classified.
Backup: `merlin_before_time_class_20260906_094551_701133.db` in the project root.

## Running previews in PowerShell

From the project directory:

```powershell
# Static preview, read-only and no engine work (the default).
.\.venv\Scripts\python.exe analysis_crawler.py --last-games 500

# Select the last 500 imported rapid games, applying filters before the limit.
.\.venv\Scripts\python.exe analysis_crawler.py --last-games 500 --time-class rapid

# Combine classes and source; development fixtures are always excluded.
.\.venv\Scripts\python.exe analysis_crawler.py --all-games --source chesscom --time-class blitz --time-class rapid

# Scout preview: writes reusable engine evidence only, plus a JSON report.
.\.venv\Scripts\python.exe analysis_crawler.py --last-games 500 --scout --report reports/scout_preview_500.json

# Focused tests use only temporary/in-memory databases.
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

"Last games" currently retains the original crawler's **import order** (`game_id`),
not game date. Date/account scope controls are future work. Scope filters never
delete or invalidate records outside the selection.

## Scout architecture and limits

`ANALYZERS` registers a screener, scout, and their versions per motif. Scout mode
walks selected moves once and dispatches registered analyzers. `ScoutEvidence`
shares before-position results between motifs and uses `engine_position_cache`.
The new `tactic_scout_v1` profile runs Stockfish 18 with a 10,000-node search limit,
one thread, and 64 MB hash. Scores remain White POV in the cache; the scout
converts to player POV for decisions. Limits are search-node budgets, not fixed
wall-clock or depth guarantees.

The mate scout asks whether the player has a positive mate score within three
moves. The fork scout asks whether the played move loses at least 80 centipawns
in shallow evidence, after the geometric screen. Mate-score ambiguity is kept
for the fork specialist. A scout pass is only a work-queue hypothesis: it does
not establish a missed tactic or the final solution.

No heavy analyzers run. No candidates, training attempts, or coverage records
are written. SQLite authorization also restricts data writes to engine cache
evidence. Interrupted runs can reuse evidence on the next preview. Invalid
positions remain errors; engine failure aborts rather than producing negatives.

## Coverage statuses and exact currentness rules

`migrate_analysis_scout_rejection.py` adds `scouted_out` to the status constraint
and adds `scout_config TEXT NOT NULL DEFAULT ''`. SQLite requires a table rebuild
to expand this CHECK constraint; the migration follows its
[documented table-rebuild procedure](https://www.sqlite.org/lang_altertable.html#making_other_kinds_of_table_schema_changes).
It preserves all existing columns, rows, IDs, timestamps, indexes, triggers,
foreign keys, and the AUTOINCREMENT high-water mark. The new status requires
a nonzero scout version and nonempty configuration. It does not infer or
backfill any negative evidence.

Applied safely on September 6, 2026, with verified backup
`merlin_before_scout_rejection_20260906_102234_361573.db`. All 907 candidate and
17 rejected coverage rows retained their original fields, including scout
version `0`; their new `scout_config` is empty (unknown historical config).
SQLite `quick_check` and `foreign_key_check` passed.

| Status | Current only when | If stale |
| --- | --- | --- |
| `screened_out` | Analyzer has a safe static screener and its screener version matches. Scout/config/analyzer versions are ignored. | `needs_screen` |
| `scouted_out` | Screener version, scout version, and nonempty scout config match. A safe static screener is **not** required; heavy version is ignored. | Screener mismatch: `needs_screen`; otherwise `needs_scout`. |
| `analyzed_no_hit` | Screener, scout version, nonempty scout config, and heavy-analyzer version all match. | In order: screener mismatch → `needs_screen`; scout/config mismatch → `needs_scout`; heavy mismatch → `needs_reanalysis`. |
| `candidate` | Heavy-analyzer version matches. All upstream versions/config are ignored. | `needs_reanalysis` |
| `rejected` | Heavy-analyzer version matches. All upstream versions/config are ignored. | `needs_reanalysis` |
| `error` | Never current. | `retry` |
| Missing/unknown status, or different analysis type | Never used as current coverage for this analyzer. | `needs_screen` |

`scouted_out` retains a screener-version dependency conservatively: a changed
static stage re-enters the pipeline there. This is a version check only; the
mate analyzer's pass-through screener is version `0` and needs no safe static
negative rule. If the static pass is still current but scout evidence is stale,
`needs_scout` reuses the static pass. The default read-only preview reports this
queue separately; scout preview reruns its light scout without rescreening.

The canonical JSON `scout_config` records engine name/version, engine profile
name/version/search limit, engine options, and motif-specific thresholds. The
current identity includes `tactic_scout_v1`, 10,000 nodes, Threads=1, Hash=64;
fork loss threshold=80 cp or mate limit=3 moves. Changing these values changes
the configuration identity automatically. A fork threshold change does not
invalidate mate coverage. Scout algorithm changes still require a
`scout_version` bump. Future writers must store the configuration actually used
for that result, not fabricate provenance for legacy rows.

Historical `candidate`/`rejected` rows with `scout_version='0'` and empty config
remain current at heavy versions Fork V2 / Mate V3. They are not downgraded or
sent to heavy analysis just because a scout has been added or changed.
Historical `analyzed_no_hit` rows without scout provenance conservatively require
fresh scout work (there were none in the live migration).

This migration only establishes validity rules and schema support. Negative
coverage writes and heavy dispatch remain disabled pending validation.

## Measurements

500 games, 13,679 user moves, using the same selection as the original handoff.
These queues exclude already-current coverage; active candidates are separately
audited through the proposed pipeline to measure recall.

| Analyzer | After static screen | After scout | Reduction | Known active candidates retained |
| --- | ---: | ---: | ---: | ---: |
| Missed fork | 6,245 | 2,579 | 58.7% | 73 / 73 |
| Missed mate | 13,601 | 427 | 96.9% | 78 / 78 |

The original fork screen required a rook-or-king target and lost five existing
forks of minor pieces. Screener version 2 accepts any two non-pawn targets,
matching Fork V2's geometry. This increases the static queue compared with the
old 5,647, while recovering all five known forks. The first-run report with the
old screen is preserved as `reports/scout_preview_500_screener_v1.json`.

The first scout run performed 18,230 engine searches in 384 seconds. The corrected
run reused those 18,230 cached positions, added 600 searches, and finished in
22.54 seconds. Final reports: `reports/static_preview_500.json` and
`reports/scout_preview_500.json`. No errors occurred.

These are positive-history recall checks, not proof that unseen tactics cannot
be missed. Before persisting negative coverage, compare a sample of scout rejects
with deeper analysis and validate on other game scopes. Heavy integration still
requires safe adapters that reconcile candidates in place and preserve IDs.

Twenty-five focused tests cover provider boundaries, metadata precedence, migration
backup/rollback/idempotence, importer persistence, filters, score POV, cache reuse,
mate limits, saving/equalizing forks, the minor-piece regression, and retry/version
logic, scout configuration identity, explicit negative stages, table rebuild
rollback, preserved constraints/triggers/IDs, and migration idempotence.
`verify_time_class_migration.py` compares original data with the safety
backup and checks that all prior engine evidence is still present.
