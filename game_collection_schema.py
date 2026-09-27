"""Optional additive collection schema; reads never migrate an existing database."""

COLLECTION_SCHEMA = """CREATE TABLE game_collections (
    collection_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK(length(trim(name)) BETWEEN 1 AND 120),
    description TEXT NOT NULL DEFAULT '' CHECK(length(description) <= 4000),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)"""
MEMBER_SCHEMA = """CREATE TABLE game_collection_members (
    collection_id INTEGER NOT NULL REFERENCES game_collections(collection_id) ON DELETE CASCADE,
    game_id INTEGER NOT NULL REFERENCES games(game_id) ON DELETE RESTRICT,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(collection_id, game_id)
)"""
MEMBER_INDEX = "CREATE INDEX idx_game_collection_members_game ON game_collection_members(game_id, collection_id)"
SCHEMA_STATEMENTS = (COLLECTION_SCHEMA, MEMBER_SCHEMA, MEMBER_INDEX)
SCHEMA_OBJECTS = ("game_collections", "game_collection_members", "idx_game_collection_members_game")
MIGRATION_REQUIRED = "Collections require the approved additive database migration. Existing games are unchanged."


def available(db) -> bool:
    return db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN "
                      "('game_collections','game_collection_members')").fetchone()[0] == 2


def validate_schema(db) -> None:
    """Fail closed on partial or incompatible extensions, including cascade/index changes."""
    for name, expected in zip(SCHEMA_OBJECTS, SCHEMA_STATEMENTS):
        row = db.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
        if not row or row[0] != expected:
            raise ValueError("Unexpected collection schema: " + name)


def migrate_game_collections(db) -> None:
    """Explicit migration only; caller must approve and verify the established backup first."""
    if db.in_transaction:
        raise ValueError("Migration requires its own transaction")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("BEGIN IMMEDIATE")
    try:
        existing = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
        if existing.intersection(SCHEMA_OBJECTS):
            validate_schema(db)
        else:
            for statement in SCHEMA_STATEMENTS:
                db.execute(statement)
            validate_schema(db)
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Collection migration integrity validation failed")
        db.commit()
    except Exception:
        db.rollback()
        raise
