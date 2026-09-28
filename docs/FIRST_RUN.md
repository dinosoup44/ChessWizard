# First launch and clean-user storage

ChessWizard 1.0.0-beta creates its empty database automatically when Game Review,
Training, or the standalone Admin Console first starts. No developer initializer,
personal database copy, or engine search is required. Appearance can also run by
itself without a database. Empty game and training views are expected until the
user has their own data; bootstrap does not import games or generate tactics.

## Data location

`application_paths` is the shared, dependency-free resolver. In order:

1. A database path explicitly supplied by a caller.
2. An absolute `CHESSWIZARD_DATA_DIR` profile override, or an existing normal
   user database.
3. For an unfrozen source checkout only, an existing `merlin.db` beside the source.
   This preserves established development installations.
4. A new user database at `%LOCALAPPDATA%/ChessWizard/merlin.db` on Windows,
   or `~/.local/share/ChessWizard/merlin.db` when LOCALAPPDATA is unavailable.

An override selects that profile even if its DB does not exist; it never falls
back to another database. Frozen applications ignore source-adjacent DBs. Paths
are independent of the process working directory and any named developer machine.
Settings and themes use the same profile directory; missing preferences use the
existing in-memory defaults. Normal startup creates neither settings nor reviews.
The profile override is for isolation/support, not an alternate analysis config.

## Initialization and existing-user safety

`database_schema.py` contains schema version 1's approved SQL definitions: all
18 business tables and 20 explicit indexes from the current post-Occurrence
Storage V1 schema. There are no personal rows or runtime reads from a template DB.
SQLite also creates its empty internal `sqlite_sequence` table.

`database_bootstrap.ensure_database` creates a temporary DB in the destination
folder, runs schema creation in one explicit transaction, validates the required
structure, runs `quick_check` and `foreign_key_check`, and commits. Only then is
it published through an exclusive operation that cannot overwrite another file.
Concurrent launchers keep whichever complete database was published first.
Initialization failure rolls back and removes the unpublished temporary file.
The desktop startup adapter shows the cause and selected path, logs the exception
with its traceback, and stops that launch. It does not switch to another DB.

An existing DB is opened read-only for structural compatibility checks. It is
never reset, rebuilt, stamped with new metadata, or automatically migrated.
Existing approved production databases without bootstrap metadata are supported.
Invalid/incomplete files and unsupported bootstrap versions produce a clear error;
resolve those separately rather than deleting the file or invoking legacy repair.
`database.py` is an older developer initializer, not the supported first-run path.
Future migrations require their own reviewed version transition; increasing the
bootstrap version alone is not a migration mechanism.

## Empty database contents

Measured first-run DB: **253,952 bytes (248 KiB)**. All 18 business tables have zero
rows, including games, moves, users/accounts, candidates/episodes, occurrences,
occurrence evidence/lines/links, training, analysis runs/coverage and both engine
caches. `sqlite_sequence` is also empty. No personal identities or lineage are copied.

The only non-empty table is `application_metadata`, with five installation facts:

| Key | Value / purpose |
|---|---|
| bootstrap_version | `1`; supported clean-schema initialization contract |
| base_schema_sha256 | Fingerprint of the checked-in approved base DDL |
| occurrence_storage_version | `1`; included occurrence-storage contract |
| occurrence_identity_versions | `[1,2]`; supported occurrence identity formats |
| source_namespace | Fresh installation UUID, never the development namespace |

These facts are not analyzer activation or candidate-generation permissions. Admin
reports clean initialization separately from an existing migration manifest and
omits the namespace UUID from diagnostic exports. Production receives no new table.
A repeated initialization preserves DB bytes, namespace and timestamps.

## Optional QA data and version

Ordinary Game Review requires no `reviews/`, `review_data/`, or `reports/` files.
Without the optional catalog, All Games remains available, the QA-set picker is
disabled and the Human Review panel is hidden. Tactics, board/line replay, filters,
training callbacks and themes retain their normal paths. See
[HUMAN_ANALYZER_REVIEWS.md](HUMAN_ANALYZER_REVIEWS.md) for QA data classification.

`chesswizard_version.py` owns product, semantic and display versions. Window titles,
Admin Overview/Diagnostics and JSON export consume it. No automatic incrementing.

## Validation and distribution boundary

The source-only temporary launch fixture omitted the production DB, settings,
themes, review catalog, notes, audit reports and lineage manifest. All four screens
opened, including repeat launches with identical DB bytes and timestamps. The
base schema matched production DDL exactly; quick_check passed and FK check was
empty. Stockfish 18 passed an isolated relative-path UCI readiness test, without
chess searches. The fixture only created `merlin.db` in its profile.

This is source-launch validation, not certification of a frozen package. A future
package must include the schema/bootstrap/path/version modules and runtime closure;
it must exclude every personal DB, review artifact and scratch cache. Licensing,
notices and source-distribution requirements remain a separate release blocker.

## Import your games

The empty Game Review screen now says “No games imported yet” and points to
its visible **Import Games** action. The main menu also opens this dialog.
Select Chess.com or Lichess, enter your username, then import public games.
Accounts are remembered; repeat imports add only previously unseen source game
IDs. No password, developer command, seeded database or automatic analysis.
Game Review refreshes and shows newest games first after new games are imported.
Offline failures leave local games usable. See [GAME_IMPORT.md](GAME_IMPORT.md).

This source feature requires a fresh frozen rehearsal; the earlier beta
rehearsal executable does not contain it.

## Analyze imported games

Choose **Analyze Games** from the main navigation or Game Review, inspect the
pending count, then click **Start Analysis**. Import never starts it automatically.
Default scope includes all real games needing work, including partial games;
new-only and the currently selected game are also available. Profile is the
existing **Production defaults**. No proof-depth settings are needed here.

Progress shows real move-analyzer checks, current game/analyzer, new candidates,
errors and elapsed time. **Stop** finishes the current check safely, preserving
completed work. The next run resumes from coverage and cached evidence. While busy,
closing the window/app requests Stop; close again once it finishes.

Game Review refreshes after completion/Stop. Training sees new eligible candidates
when reopened. Analysis itself creates no training attempts. It uses disk space
for engine evidence; Admin exposes storage counts. No pruning is automatic.
See [ANALYZE_GAMES.md](ANALYZE_GAMES.md) for deferred/protected work semantics.
The existing post-import rehearsal must be rebuilt before this new source workflow
can be tested in a frozen executable; no package is built by this task.

## Repair, upgrade, and reinstall

The installer keeps application files separate from your profile. Reinstalling
after the default uninstall retains your games, preferences, authored openings,
and compatible plugins. Choosing and confirming full local-data removal makes
the next launch a fresh profile instead. See [installation/removal](INSTALLATION.md)
and [repair/upgrade](UPGRADING.md) before troubleshooting by deleting anything.
