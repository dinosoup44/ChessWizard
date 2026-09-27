# Game import V1

Open **File > Import Games...** from the application menu.
Choose Chess.com or Lichess, enter a public username and click Import Games.
No password/token is requested. A clean install needs no prior Lichess account.
Saved source/usernames are selectable on later visits. Import runs on a worker
thread; status reports actual received/added/existing/error counts, not a guessed
percentage. Stop takes effect between game transactions after any current network
read returns (30-second connection/read timeout).

Import never starts analysis. Game Review refreshes after completion, including
partial successful imports; newly added games open in All Games, newest first.
Training remains empty until a separate supported analysis workflow creates tactics.

## Existing backend and shared contracts

`import_chesscom.py` and `import_games.py` remain the provider implementations.
Their existing single-game normalizers create the same games/moves, SAN, UCI,
FENs, user-color flags and time classes. The product path does not invoke CLI mains.

- `game_import_http`: standard-library HTTP, serial requests, public endpoints,
  centralized versioned User-Agent, error translation and rate-limit cooldown.
- `game_import_pgn`: shared streaming PGN reader with retained raw game text,
  validation and new-game UTC timestamp formatting.
- `game_import_models`: immutable progress/result objects and summary.
- `game_import_repository`: transaction/account ownership around existing
  normalizers; no candidate/coverage/cache/training operations.
- `game_import_service`: provider orchestration, one worker connection and
  one in-process import at a time. Usable without Tkinter.
- `merlin_ui.import_games_dialog`: controls, background task/queue and rendering.

The legacy importers previously depended on Requests. Their existing endpoints
now use standard-library urllib transport, avoiding a new bundled dependency
stack. Existing CLI download calls still return text; the product requests a
stream. The legacy Lichess CLI's 50-game default remains for compatibility;
the product passes `max_games=None`, so it does not silently cap user history.
No new site, browser, authentication, scheduler, sync daemon or PGN file UI.
PGN parsing already existed; a stable user-facing file-import backend was not
found, so no new file-import infrastructure was added.

## Fetch and duplicate semantics

Chess.com enumerates the existing monthly archive API and reads PGNs serially,
newest month first. Provider URLs must be HTTPS monthly archives on api.chess.com
for the selected username. Lichess streams its existing public user-games PGN
endpoint with no maximum and finished games only. Official PGN Site URLs provide
the eight-character Lichess ID when the legacy GameId header is absent.

Both re-fetch available history and deduplicate locally. There is no date-based
watermark, guessed early-stop or risk of missing newly finished older games.
Existing APIs offer date filters, but the old code had no proven incremental
watermark; correctness takes priority in V1. The result says **Games received**,
which covers the games actually parsed before an interruption, not a promised
complete remote-history total. Empty histories can successfully remember accounts.

Canonical identity remains `UNIQUE(source, source_game_id)`; move identity stays
`UNIQUE(game_id, ply_number)`. Dates, opponent, result and move count never serve
as deduplication identity. Re-import preserves existing games/moves and IDs;
only previously unseen games are added. A successful account's last_sync_at may
update even when no game is new. This is game/move idempotency, not byte-identical
whole-database re-import. Existing perspective/ownership is not rewritten when
a second account refers to an already stored source game.

## Accounts and transaction safety

`chess_accounts` remains the source/username authority, looked up case-insensitively.
A completed import updates its last_sync_at. An account is also retained once a
valid game commits during a subsequently interrupted import. A failed lookup
creates no account. No credentials are stored.

The legacy users table requires a non-null lichess_username. For a new profile,
the service creates one local owner using a namespaced `local:<uuid>` value in
that legacy column. It is an internal local identity, not a remote Lichess
account; real account identities live only in chess_accounts. Existing local
users are reused unchanged. No schema migration or new account table is needed.

Each new game uses BEGIN IMMEDIATE before deduplication. The account (if needed),
game and all its moves commit together. A normalization failure rolls the entire
transaction back, including partially inserted moves. Network reads happen
outside database transactions. SQLite foreign keys are enabled and writer waits
are bounded. Another process is serialized by SQLite plus the existing unique
constraints; another import in this process is rejected while one is active.

Malformed PGNs, absent canonical IDs, wrong-player games, unsupported variants,
invalid boards, zero-move games and unfinished/truncated PGNs are reported as
errors instead of partial imports. Valid games already committed survive source
failures. Re-running is safe. Standard chess is supported; variant analysis is
not implied. Error details are bounded while the error count remains complete.

Public-provider failures (404, 429, server errors, offline/interrupted reads)
produce a user-facing result without disabling local browsing. A 429 ends this
run and enforces an in-process cooldown of at least 60 seconds (or a longer
numeric Retry-After). There are no automatic retries. The UI does not display
fake totals. Restarting the app does not persist this transient cooldown; users
should observe the displayed provider wait before retrying.

## Newest-first ordering

New imports store UTCDate + UTCTime as ISO UTC in played_at when valid. Existing
rows are untouched. GameReviewRepository orders by the parsed stored played_at
(date-only dotted legacy dates are supported), descending, then game_id descending.
Unparseable/unknown dates sort last with deterministic ID ties. All existing
review/tactic filters preserve this order.

## Verification and release boundary

Automated tests use temporary clean databases/profiles and mock HTTP, never
production account imports. They exercise both real normalizers, repeat imports,
new-game additions, malformed/truncated input, partial failures, rollback, FK
integrity, source/account controls, live Tk menu/dialog refresh, and responsiveness
under a blocked network request. Engine creation is forbidden in these fixtures.
No candidate, occurrence, training, coverage or engine-cache rows are written.

The previous frozen rehearsal predates this feature. A new frozen build, smoke
test, exact manifest and licensing/privacy audit are required. No build or package
is produced by this task; the old 87-file manifest is historical evidence only.

API references checked for this implementation:
- [Chess.com public API](https://support.chess.com/en/articles/9650547-what-is-the-pubapi-and-how-do-i-use-it)
- [Lichess public export contract](https://raw.githubusercontent.com/lichess-org/api/master/doc/specs/tags/games/api-games-user-username.yaml)
- [Lichess request/rate-limit guidance](https://lichess.org/page/api-tips)

## UI polish round 1

Selectors and Import/Stop remain standard modern controls. The results surface
uses the shared restrained dark/green monospace information style. Provider APIs,
normalization, import/re-import behavior, progress and cancellation are unchanged.
Import no longer occupies the area below the chessboard.

## Manage Data V1.2 suppression

File > Manage Data offers Delete Selected Games (eligible for later re-import)
and Delete & Ignore Future Imports (suppress exact provider identity). Import
consults the optional ignored_import_games table using source + source_game_id
inside its insertion transaction. Missing extension on an older DB means no
suppression and does not trigger migration. Ignored counts are separate from
already imported counts in progress and final summaries. Allow Import Again
removes suppression only; the next manual import can recreate the game.

Import, analysis, active Training sessions and data mutation share an OS-held
activity lock. Preview/confirmation cancellation do not write. See
[DATA_MANAGEMENT.md](DATA_MANAGEMENT.md) for migration, reset and preservation rules.


## Zero-move hygiene

Shared PGN validation now reports `EmptyImportedGame` when no legal registered move
exists. The importer skips that record before account/game/move insertion and exposes
**Skipped empty/zero-move games: N**, separately from duplicates, ignores and errors.
Valid one-move/short games are retained. Both legacy provider normalizers also guard
against empty insertion. Identity-based deduplication and ignored-source checks are
unchanged for normal games. Malformed/truncated nonempty records remain errors.

Import still does not start analysis. The recommended explicit next step is **Recent
50** in Analyze Games, followed by Recent 100 or All Missing if desired. Existing empty
rows are not deleted by import or readiness. Any cleanup needs a separate approved,
verified-backup-backed, dependency-aware plan. Collection membership continues to block
deletion. See [import entry guide](IMPORT_GAMES.md) and [analysis](ANALYZE_GAMES.md).
