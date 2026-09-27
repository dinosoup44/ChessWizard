# Manage Data V1.2

Shared services own deletion planning, import suppression and theme ownership.
Tk only displays plans, asks for confirmation and coordinates views.

## Ownership graph

| Classification | Tables / records | Treatment |
|---|---|---|
| Direct game ownership | games; moves; game-owned engine_analysis; analysis_coverage | Remove selected game descendants |
| Candidate ownership | tactic_candidates; training_attempts; tactic_episode_members | Remove only selected games' candidates, attempts and memberships |
| Game/episode ownership | tactic_episodes; analysis_runs.last_game_id checkpoint | Remove selected episodes and legacy run records anchored to deleted games |
| Occurrence ownership | tactic_occurrences; evidence; lines; legacy candidate map; review links | Explicit child-first deletion; occurrence game/move references checked even without FK constraints |
| Shared/global | engine_position_cache; engine_candidate_line_cache | Preserve for ordinary game deletion; clear during full chess-data reset |
| Account/global | chess_accounts; users; analysis_runs | Preserve accounts for ordinary deletion; reset clears accounts/runs and user sync dates, retains local user identity |
| External historical | Human Review JSONL; QA catalogs; audit reports | Preserve bytes. Deleted game/candidate IDs are unreachable in live selectors |
| App metadata | application_metadata; schema; sqlite_sequence | Preserve, including monotonic IDs; never recycle IDs to attach old QA records to new games |

Episode primary/member candidates must belong to the episode's game. Coverage
candidate references must agree with their move. Legacy occurrence maps must agree
with candidate moves. Training episode references must belong to the same game.
The stored legacy development game ID -1 is valid for reset; game keys are not
assumed positive. Unknown tables/triggers fail closed until their ownership is reviewed.

## Plans and transactions

DataManagementRepository.plan_game_deletion returns an immutable GameDeletionPlan.
The read-only plan contains exact per-table counts, canonical source identities
and a fingerprint of selected rows/schema. It creates no files or database writes.
Execution takes a BEGIN IMMEDIATE transaction and rebuilds the plan. Changed data
requires a new preview and confirmation; another database cannot use the plan.

Delete & Ignore inserts unique (source, source_game_id) records and deletes all
owned rows in that same transaction. Both roll back on failure. Explicit child
deletion handles non-cascading legacy foreign keys. FK checks and logical ownership
checks run before and after; quick_check runs before commit. Nothing drops tables,
rebuilds the DB or resets AUTOINCREMENT sequences.

Supported import, analysis, Training sessions and data-management writes share an
OS-held activity lock. The empty .activity-lock sidecar remains to prevent a split
lock race; it contains no user data and stale ownership cannot survive process
exit. Older app binaries and standalone legacy tools do not participate: close
them before managing data. UI previews/cancel do not acquire this write lock.

## Delete, ignore, allow

File > Manage Data lists newest remote games first and supports multi-selection.
Delete Selected Games permits later re-import. Delete & Ignore suppresses the
exact authoritative provider/source ID, independent of PGN, opponent, result or
date. Import checks suppression inside its identity transaction before any account,
game or move insertion. Import summaries separate ignored from already imported.

Allow Import Again removes only the suppression record. It does not fetch games.
Ignore identities store only source, source ID and timestamp, with a composite
primary key. There is no duplicate PGN or opponent dataset.

## Schema / migration

Clean-user bootstrap includes ignored_import_games. Existing installations remain
readable without it: no startup or preview migration. Without the table, ordinary
deletion/reset work, Ignore is unavailable and the UI explains the prerequisite.

The explicit ignored_imports.migrate_ignored_imports(connection) API creates and
validates the exact additive schema inside one transaction. Before production use,
create and verify the approved SQLite/project backup, then approve the migration
against that exact database. No production migration is performed by this task.
Rehearse on a SQLite API backup into an isolated temporary directory first; check
all old table fingerprints and definitions, integrity and a byte-identical rerun.

## Reset

Admin > Data / Storage > Reset Chess Data opens a separate preview/confirmation.
It removes all chess history, accounts/sync history, analysis, occurrences and both
shared caches. Ignored identities stay unless Also clear ignored-game list is
checked (default unchecked). Themes, active appearance, app settings, schema and
application_metadata remain. A second empty reset performs no database writes.

After a successful operation, Game Review reloads and Training clears/reloads its
puzzles. Idle Import/Analyze dialogs close to discard stale accounts/scopes; reopen
them from the menus. Active import/analysis/training must finish before deletion.
Admin reset refreshes status. Historical QA files remain available as historical
artifacts, but no candidate is synthesized and no missing-game entry is made live.
ID sequences survive reset so re-import cannot attach legacy QA by reused IDs.

## Theme deletion

Only valid user-owned managed packages may be deleted. Default Merlin Classic is
protected. The service validates the manifest and exact asset allowlist, refuses
traversal, ancestor symlinks/junctions/reparse points and hard-linked/shared files,
and requires a direct child of the managed theme root. There are no arbitrary
path inputs. Preview shows name, ID, asset count, bytes and active status.

Deleting the active theme persists default first, then refreshes board listeners,
deletes the managed package and reloads resolution. A filesystem deletion error
attempts to restore the validated package from bounded in-memory bytes; fallback
remains valid. If the filesystem also refuses recovery, surface the error for
manual recovery rather than claiming success. No downloaded asset executes.

## Footprint and portability

The ignore table adds a table and composite index (normally two 4 KiB pages).
Growth is proportional to the short source identities, not game size. SQLite
retains freed pages after deletion/reset; this version does not VACUUM, so file
size need not shrink. Empty lock sidecars are reusable coordination files.

Models, repository, suppression and theme management have no Tk dependencies.
Future frontends can call the same plan/execute contracts. No analyzer policy,
proof, occurrence identity or cache evidence format changes are part of this work.


The new TrainingSession lifetime wrapper owns the activity lock, candidate existence
check and attempt creation; Tk handlers call it without implementing SQL policy.
ThemeRepository exposes its validated managed_directory contract for theme services.
Theme deletion notifies open boards and refreshes open Appearance selectors, including
inactive themes that no longer exist.
