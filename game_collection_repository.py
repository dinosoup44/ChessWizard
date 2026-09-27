"""SQL-only collection persistence; the service owns connections and transactions."""
from game_collection_models import GameCollection, GameCollectionMember
from game_collection_schema import available, MIGRATION_REQUIRED, validate_schema


class GameCollectionRepository:
    def __init__(self, connection):
        self.db = connection

    def require_schema(self):
        if not available(self.db):
            raise ValueError(MIGRATION_REQUIRED)
        validate_schema(self.db)

    def list_collections(self):
        if not available(self.db):
            return ()
        return tuple(GameCollection(*row) for row in self.db.execute("""SELECT c.*,
            (SELECT count(*) FROM game_collection_members m WHERE m.collection_id=c.collection_id)
            FROM game_collections c ORDER BY name COLLATE NOCASE,collection_id"""))

    def require_collection(self, collection_id):
        self.require_schema()
        if not self.db.execute("SELECT 1 FROM game_collections WHERE collection_id=?", (collection_id,)).fetchone():
            raise ValueError("Collection no longer exists. Refresh the list.")

    def members(self, collection_id):
        self.require_collection(collection_id)
        return tuple(GameCollectionMember(*row) for row in self.db.execute("""SELECT
            m.collection_id,m.game_id,m.added_at,g.played_at,g.white_username,g.black_username,g.result
            FROM game_collection_members m JOIN games g USING(game_id) WHERE m.collection_id=?
            ORDER BY julianday(replace(substr(g.played_at,1,10),'.','-') || substr(g.played_at,11)) DESC,g.game_id DESC""", (collection_id,)))

    def create(self, details):
        self.require_schema()
        return self.db.execute("INSERT INTO game_collections(name,description) VALUES (?,?)",
                               (details.name, details.description)).lastrowid

    def edit(self, collection_id, details):
        self.require_collection(collection_id)
        return self.db.execute("""UPDATE game_collections SET name=?,description=?,
            updated_at=strftime('%Y-%m-%d %H:%M:%f','now') WHERE collection_id=?
            AND (name COLLATE BINARY<>? OR description<>?)""",
            (details.name, details.description, collection_id, details.name, details.description)).rowcount

    def delete(self, collection_id):
        self.require_collection(collection_id)
        self.db.execute("DELETE FROM game_collections WHERE collection_id=?", (collection_id,))

    def change_members(self, collection_id, game_ids, *, add):
        self.require_collection(collection_id)
        changed = 0
        for game_id in game_ids:
            if add:
                if not self.db.execute("SELECT 1 FROM games WHERE game_id=? AND COALESCE(source,'')<>'dev'", (game_id,)).fetchone():
                    raise ValueError(f"Game {game_id} is missing or is not a user game; nothing was added.")
                sql = "INSERT INTO game_collection_members(collection_id,game_id) VALUES (?,?) ON CONFLICT(collection_id,game_id) DO NOTHING"
            else:
                sql = "DELETE FROM game_collection_members WHERE collection_id=? AND game_id=?"
            changed += self.db.execute(sql, (collection_id, game_id)).rowcount
        if changed:
            self.db.execute("UPDATE game_collections SET updated_at=strftime('%Y-%m-%d %H:%M:%f','now') WHERE collection_id=?", (collection_id,))
        return changed


def require_uncollected_games(db, game_ids):
    """Protect saved games at both deletion preview and transactional execution."""
    if not game_ids or not available(db):
        return
    placeholders = ",".join("?" for _ in game_ids)
    blockers = db.execute(f"""SELECT c.name,count(*) FROM game_collection_members m
        JOIN game_collections c USING(collection_id) WHERE m.game_id IN ({placeholders})
        GROUP BY c.collection_id ORDER BY c.name COLLATE NOCASE,c.collection_id""", game_ids).fetchall()
    if blockers:
        names = "; ".join(f"{name} ({count} selected game(s))" for name, count in blockers)
        raise ValueError("Deletion blocked: games belong to saved collections/sets: " + names +
                         ". Remove these games from every collection/set first. No games were deleted.")
