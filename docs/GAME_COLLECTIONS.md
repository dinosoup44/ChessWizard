# Saved Game Sets / Collections V1

A saved game set (collection) is a named **static membership set** of games in one
ChessWizard database. Games are referenced by ID, never copied. The same game may
belong to several collections. Renaming preserves the collection ID and members.
An empty collection is valid and remains until explicitly deleted.

## Using collections

1. Open **Tools → Game Explorer → Collections…**.
2. Choose **New Collection**, enter its name and description, then save.
3. In Game Explorer, select games (Ctrl-click or Shift-click for multiple rows).
4. Choose **Add selected to collection…** and select a collection. If no collections
   exist, this action offers the new-collection dialog first.
5. Select a collection in the **Collection** filter to see its games. All Games and
   Games not in a collection are also available. Other filters still combine with
   AND, including opponent, color, result, motif and compatible user accuracy.
6. To remove memberships, use **Remove from collection** in filtered Explorer, or
   select members in the collection manager and choose **Remove selected**.

The manager lists collection names/counts, edits names/descriptions, shows members
newest first, removes memberships and opens an exact selected game in Game Review.
Deleting a collection requires confirmation and leaves all games intact. Select
exactly one game to open it in Game Review; multi-selection is for membership actions.
No permanent panel was added to Game Review.

## Saved games are protected from deletion

**A game in any collection/set cannot be deleted.** This applies to normal Delete,
Delete & Ignore Future Imports, and full chess-data reset. A mixed selection with
one protected game blocks the entire deletion, with no partial game deletion and
no ignored-import entries created. The error names the blocking collections.

Remove each protected game from **every** collection first, or explicitly delete
the containing collections (which keeps the games). Removing only one membership
is insufficient if another remains. Empty collection definitions survive reset.

Protection runs during the preview and again inside the execution transaction.
Membership added after a preview therefore blocks execution too. The membership
foreign key to games uses **ON DELETE RESTRICT**, with FK enforcement enabled in
supported write services. A collection's own FK uses ON DELETE CASCADE to remove
its membership metadata when the owner deletes the collection.

This owner clarification supersedes the initial request for automatic cleanup of
memberships when deleting a game. No production cascade schema was ever installed.

## Storage and portable API

- `game_collection_models`: immutable CollectionDetails, GameCollection and
  GameCollectionMember. Names are trimmed/nonempty (maximum 120 characters), unique
  using SQLite NOCASE; descriptions are always present and may be empty (maximum
  4,000 characters). NOCASE's non-ASCII case-folding limitations are unchanged.
- `game_collection_schema`: additive tables, index, validation and explicit migration.
- `game_collection_repository`: SQL and deletion-protection query.
- `game_collection_service`: explicit DB path, read-only queries, transactions,
  shared data-activity lock, collection and membership operations.
- `merlin_ui/game_collections`: desktop dialogs/manager only.

`game_collections` stores an AUTOINCREMENT collection_id, name, description,
created_at and updated_at. `game_collection_members` stores collection_id, game_id
and added_at, with composite primary key (collection_id, game_id). A reverse index
on (game_id, collection_id) supports uncollected searches and deletion protection.
No existing table is rebuilt. Exact SQL is in `game_collection_schema.py`.

Duplicate membership adds and removal of absent memberships are no-ops. Unchanged
metadata edits do not update timestamps. Membership changes update the collection's
updated_at only when something actually changes. Batch membership additions are
atomic; missing games reject the whole batch. Development fixture games cannot be
added. IDs remain local to the selected database.

Core modules have no Tk, engine, analyzer or opening-book dependency. Per-game
notes, manual ordering, dynamic saved searches and exports are deferred. Future
dynamic searches should store typed GameSearchCriteria and distinguish their
identity from static membership; they must not silently reinterpret V1 collections.

## Migration status and procedure

New empty databases include the collection extension. Existing databases are
validated read-only by bootstrap and never automatically migrated. They retain
normal Game Explorer search; collection controls remain unavailable with an
explicit migration message. An existing profile needs a separately approved migration; this guide does not assert the state of any particular user database.

After explicit owner approval:

1. Confirm the exact active database path and quiesce imports/analysis/data writes.
   The desktop user database and a checkout-local merlin.db are distinct files; do
   not accidentally migrate the project DB in place of the active user database.
2. Use the established approved backup workflow (`backup_merlin.py`, FULL when
   required) and its verification procedure. Confirm the verified database copy
   actually corresponds to the exact migration target; a project-only backup does
   not cover a different desktop user DB. Record hashes, table counts and schema.
3. Invoke `migrate_game_collections(connection)` on that explicitly approved target.
   It owns one BEGIN IMMEDIATE transaction, adds only the two tables and index,
   verifies exact schema and checks quick_check and foreign_key_check before commit.
4. On failure it rolls back. Do not attempt an automatic restore over later writes.
5. Verify unchanged old rows/schema, new empty tables, integrity and an idempotent
   second invocation. Restart ChessWizard and perform owner acceptance.

Rehearsals cover fresh bootstrap, a pre-extension schema, byte-identical reruns,
partial/incompatible schema rejection, orphan failure/rollback and protected game
FK behavior. A 10-game isolated review database is available at
`reports/game_collections/owner_review_fixture.db`; it contains Study (4), Favorites
(3, overlapping with Study) and Empty (0). It contains synthetic users only.
