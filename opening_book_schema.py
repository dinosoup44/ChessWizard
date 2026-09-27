"""Versioned, separate .cwbook library schema; never applied to a game database."""
APPLICATION_ID = 0x4357424B
SCHEMA_VERSION = 2

SCHEMA = (
    """CREATE TABLE positions (
        position_id INTEGER PRIMARY KEY, canonical_fen TEXT NOT NULL UNIQUE,
        polyglot_key TEXT NOT NULL CHECK(length(polyglot_key)=16),
        side_to_move TEXT NOT NULL CHECK(side_to_move IN ('white','black')))""",
    """CREATE TABLE books (
        book_id INTEGER PRIMARY KEY, root_position_id INTEGER NOT NULL REFERENCES positions,
        name TEXT NOT NULL, description TEXT NOT NULL, version TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('draft','active','archived')),
        revision INTEGER NOT NULL DEFAULT 1, metadata_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE book_positions (
        book_id INTEGER NOT NULL REFERENCES books ON DELETE CASCADE,
        position_id INTEGER NOT NULL REFERENCES positions,
        position_note TEXT NOT NULL DEFAULT '', metadata_json TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY(book_id,position_id))""",
    """CREATE TABLE book_moves (
        move_id INTEGER PRIMARY KEY AUTOINCREMENT, book_id INTEGER NOT NULL REFERENCES books,
        from_position_id INTEGER NOT NULL, move_uci TEXT NOT NULL, san TEXT NOT NULL,
        to_position_id INTEGER NOT NULL, weight INTEGER NOT NULL CHECK(weight BETWEEN 1 AND 100),
        preferred INTEGER NOT NULL CHECK(preferred IN (0,1)),
        active INTEGER NOT NULL CHECK(active IN (0,1)),
        move_note TEXT NOT NULL, instructional_note TEXT NOT NULL, metadata_json TEXT NOT NULL,
        variation_name TEXT NOT NULL DEFAULT '', variation_description TEXT NOT NULL DEFAULT '',
        CHECK(preferred=0 OR active=1), UNIQUE(book_id,from_position_id,move_uci),
        UNIQUE(move_id,book_id),
        FOREIGN KEY(book_id,from_position_id) REFERENCES book_positions(book_id,position_id),
        FOREIGN KEY(book_id,to_position_id) REFERENCES book_positions(book_id,position_id))""",
    """CREATE UNIQUE INDEX one_preferred_branch ON book_moves(book_id,from_position_id)
        WHERE preferred=1""",
    """CREATE TABLE source_references (
        source_ref_id INTEGER PRIMARY KEY AUTOINCREMENT, book_id INTEGER NOT NULL,
        position_id INTEGER NOT NULL, move_id INTEGER,
        title TEXT NOT NULL, author TEXT NOT NULL, edition TEXT NOT NULL,
        chapter TEXT NOT NULL, page TEXT NOT NULL, private_note TEXT NOT NULL,
        FOREIGN KEY(book_id,position_id) REFERENCES book_positions(book_id,position_id),
        FOREIGN KEY(move_id,book_id) REFERENCES book_moves(move_id,book_id) ON DELETE CASCADE)""",
)

