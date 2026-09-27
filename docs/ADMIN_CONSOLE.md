# Admin Console V1

Open **Tools > Admin Console...** from Game Review or Training, or run
`run_admin_console.py`. Snapshots and diagnostics remain read-only. Reset Chess Data is a separate, explicit destructive workflow; this console is not an analyzer launcher.
The shared shell keeps one Admin window per host view. The console uses the
existing UI palette and shared ActiveThemeService, shows the resolved active
theme. Theme editing remains under the application View > Appearance menu. It adds no chess board or theme
controls. Game Review and Training forward their actual opened database path.

## Sections and current sources

- **Overview:** source-checkout/build information, actual database path and size,
  SQLite schema/user versions, aggregate game/move/candidate/occurrence/training/
  cache counts, active theme, engine presence and last requested health checks.
- **Analysis:** real `analysis_settings.BUILTIN_PROFILES` (Quick, Normal, Deep,
  Targeted verification, Normal with targeted verification), inspected through a
  read-only selector. Breadth depth/budgets/MultiPV, verification defaults, proof
  windows and request/branch caps are sourced from the typed profile objects.
  Persisted coverage counts and candidate versions are separate summaries.
- **Analyzers:** `analysis_registry.ANALYZERS` provides central crawler
  registration, versions, screener/scout identities and specialist implementation.
  `CANDIDATE_VERIFIERS` and `DISCOVERY_ANALYZERS` appear separately as optional
  workflows. Registration is not a running scheduler state or global enablement.
- **Toolkits/report-only capabilities:** the known module entry points and
  documentation identify Major Material Blunder, Position/Range Evidence,
  board_analysis and SEE. Missing documentation/module files are reported.
  Maturity is not invented: crawler entries currently have no formal maturity
  field. Blunder's documented controlled-use Robust/Validated boundary and SEE's
  Validated/advisory/no-consumer freeze are shown with their sources. SEE's
  non-authoritative/hard-rejection flags come from StaticExchangeResult fields;
  literal field defaults are read from the source AST without importing or executing
  SEE, preserving its consumer-free production boundary.
- **Engine:** the actual `engine_cache.STOCKFISH_PATH`, file presence/size,
  configured `ENGINE_VERSION`, existing position profiles and last explicit
  UCI handshake result. Configured cache identity and observed engine name are
  labelled separately.
- **Data / Storage:** table counts, pages/page size/journal, database file size,
  available allocated table/index bytes, cache text/blob content size and
  occurrence schema/manifest/link/relationship summaries.
- **Diagnostics:** explicit quick_check/foreign_key_check, Python/SQLite versions,
  source fingerprint, paths, settings/theme validation and read/query errors.
- **Settings:** existing typed application settings, active/resolved theme and
  path information, read-only. Theme editing is accessed from the application menu.

There is **no global persisted active analysis profile** in current application
settings. Individual callers select profiles. The preset selector only changes
which existing preset is displayed; it never changes analysis behavior.
`AnalysisProfile()` is labelled a default model, not a global runtime selection.
There is no supported persisted Stockfish-path editor, so the path is read-only.

The canonical release identity comes from `chesswizard_version`: ChessWizard
1.0.0-beta. Overview, Diagnostics and JSON export use the same value. The console
also provides a fingerprint of explicitly listed source modules, Python version
and source/frozen mode; this is not a complete packaged-build signature.
The standalone launcher uses the shared clean-user bootstrap before constructing
the read-only console. Existing DBs and all snapshot services remain read-only;
see [FIRST_RUN.md](FIRST_RUN.md). New-user bootstrap metadata is reported
separately from a production lineage manifest and never activates analyzers.

## Database and occurrence semantics

`admin_database` uses a separate SQLite `mode=ro`, query_only connection and
consistent read transaction for each snapshot, closed afterward. Queries have a
bounded SQLite progress budget and a two-second busy timeout. The Tk frontend
runs reads off the UI thread, applies results on the Tk thread, disables duplicate
actions while reading, and cancels UI polling/subscriptions when closed. A pending
read may finish after close; it cannot update a destroyed widget or write data.

Absent optional tables/counts are unavailable, not fabricated zeros. Coverage rows
count tactic obligations, not unique positions, analyzed games or a live queue.
Candidate counts include all stored statuses/versions; they do not certify truth
or imply the currently registered analyzer produced every historical row.

Occurrence status separates table presence, declarative lineage/migration metadata,
linked candidate count and broken links. The manifest is type-validated and only
approved version/schema fields are displayed. This is not a migration replay or
a claim that occurrence-native application writers were activated. Relationship
counts use occurrence kind/actor against current games.user_color. Missing/invalid
perspective or unknown kind stays unknown; actor equality alone is not enough.

`dbstat` is optional and unavailable in the installed Python SQLite build.
When available, allocated bytes group table and index pages. Independently, cache
text/blob byte sums measure actual content bytes without returning those contents.
They exclude record/index/page overhead, numeric storage and free space and must
not be described as total cache disk footprint. Full database file size remains
available regardless. No cache-size cap/pruning system is implied.

## Explicit actions and safety

**Refresh Status** reads a fresh snapshot without launching Stockfish. Health is shown as
Not run until requested. **Run Diagnostics** adds PRAGMA quick_check and counts
foreign_key_check violations; it validates settings/theme paths without repair or
a write probe. Writability is an os.access hint on the nearest existing ancestor,
not a guarantee that future writes will succeed.

**Check Stockfish**, under Diagnostics, runs only the configured executable with the input:

```text
uci
isready
quit
```

The five-second subprocess timeout kills and waits on a timeout. Windows launches
without a console window. Only a bounded engine name and handshake status enter
the report; raw engine stdout/stderr is not exported. No position/go command,
game search, production cache connection, analyzer or settings mutation occurs.
Missing executables, timeout and invalid responses produce failure status safely.

**Export Diagnostic Report** writes the currently displayed snapshot as JSON to
an explicitly chosen new .json file. Exclusive creation refuses to overwrite any
existing file. Refresh/diagnostics never save exports automatically. The V1 UI
has no setting mutation controls or Appearance launcher. The application View
menu retains the explicit Theme Editor workflow.

There are no pause/resume controls, invented progress/queue, repair, arbitrary
SQL, cache clearing, migration/backfill, profile activation or destructive actions.

## Diagnostic privacy and growth

Export contains captured time, versions/source provenance, necessary local paths,
aggregate counts/statuses, profile defaults and schema summaries, settings/theme
health, optional migration version/schema fields and diagnostic errors.

It contains no usernames, raw game rows, moves/FENs, candidate/occurrence IDs,
review records, lineage UUID, backup locations, cache contents, theme authors/
binary assets, environment dump, credentials or raw engine output. Local paths
can include an account name: review them before sharing. Export never uploads
anything. Tests place distinctive private markers in every relevant fixture
payload and verify none appear in the report.

Each export is a separate explicit file; there is no periodic log/export generation,
retention or automatic deletion. Current full exports are roughly 254 KiB, mostly
the five existing typed-profile schemas. Services and UI add only Python source;
no dependencies, assets or binaries are bundled. Exact task footprint and test
results are in [ADMIN_CONSOLE_V1.md](../reports/ADMIN_CONSOLE_V1.md).

## V1 boundaries

No formal maturity metadata for all analyzers, scheduler
telemetry, global profile preference, persistent engine path editor, physical
per-table footprint without dbstat, repair or cleanup is invented. Missing sources
and incomplete diagnostics stay visible rather than becoming green health claims.
The console remains reusable through frontend-neutral status models/services;
Tk owns only presentation, background-result delivery, dialogs and navigation.

Cache content scans run only during explicit Diagnostics, after integrity checks.
They share the bounded query budget; a timed-out estimate is unavailable and
reported as an error without discarding completed quick/FK results. Refresh
loads counts and file size without scanning every cache payload.

Read-only work has separate phase budgets: 20 seconds for aggregates, 60 seconds
for explicit whole-file integrity checks on removable storage, and 20 seconds for
optional footprint queries. These are service timeout limits, not chess-analysis
settings. A timed-out phase reports incomplete diagnostics and never a clean bill
of health. All database work stays off the Tk event thread.

## UI polish round 1

A fresh snapshot is read automatically when Admin opens. Entering a tab rerenders
its existing snapshot without repeating potentially expensive storage queries;
Refresh Status explicitly requests fresh data. Diagnostics owns Run Diagnostics,
Check Stockfish and Export Diagnostic Report. None starts chess analysis.

The Analysis preset selector stays read-only and automatically updates its details.
A concise labelled summary precedes the advanced exact settings. The displayed
settlement window is identified as verification; baseline and selective-extension
settings remain available below. Inspection never activates a preset. Information
surfaces share the dark/green terminal style; selectors/buttons stay native.

## Manage Data V1.2: Reset Chess Data

Data / Storage now offers Reset Chess Data... with a separate dialog, exact
database impact preview and a default-No confirmation. Also clear ignored-game
list defaults unchecked. Reset clears games, derived tactics/occurrences/training,
account/sync history and both analysis caches. It preserves schema, metadata,
ID sequences, themes and general settings. Ordinary deletion lives under File >
Manage Data and preserves shared caches.

The frontend calls DataManagementRepository; no table deletion SQL lives in Admin.
Active supported writers must finish. Reset refreshes Game Review/Training and
Admin; idle Import/Analyze windows close and can be reopened. The base status
and diagnostic services remain read-only. See [DATA_MANAGEMENT.md](DATA_MANAGEMENT.md).
