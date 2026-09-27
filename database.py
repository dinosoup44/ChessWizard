import sqlite3


DB_NAME = "merlin.db"


def create_database():
    connection = sqlite3.connect(DB_NAME)
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            lichess_username TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_sync_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS games (
            game_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            lichess_game_id TEXT NOT NULL UNIQUE,
            played_at TEXT,

            white_username TEXT,
            black_username TEXT,
            user_color TEXT,

            white_rating INTEGER,
            black_rating INTEGER,
            result TEXT,
            termination TEXT,

            time_control TEXT,
            time_class TEXT NOT NULL DEFAULT 'unknown',
            rated INTEGER,
            variant TEXT,

            raw_pgn TEXT,
            imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS moves (
            move_id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,

            ply_number INTEGER NOT NULL,
            move_number INTEGER NOT NULL,
            color TEXT NOT NULL,
            is_user_move INTEGER NOT NULL,

            fen_before TEXT NOT NULL,
            fen_after TEXT NOT NULL,

            san_played TEXT NOT NULL,
            uci_played TEXT NOT NULL,

            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (game_id, ply_number),

            FOREIGN KEY (game_id) REFERENCES games(game_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS engine_analysis (
            analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
            move_id INTEGER NOT NULL,

            engine_name TEXT,
            engine_version TEXT,
            analysis_version INTEGER NOT NULL DEFAULT 1,

            depth INTEGER,
            seldepth INTEGER,
            nodes INTEGER,
            time_ms INTEGER,

            score_type TEXT,
            score_cp_before INTEGER,
            mate_before INTEGER,

            best_move_uci TEXT,
            best_move_san TEXT,
            principal_variation TEXT,

            score_cp_after INTEGER,
            mate_after INTEGER,

            analyzed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (move_id) REFERENCES moves(move_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tactic_candidates (
            candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
            move_id INTEGER NOT NULL,

            tactic_type TEXT NOT NULL,
            candidate_status TEXT NOT NULL DEFAULT 'candidate',

            confidence REAL,
            detector_version INTEGER NOT NULL DEFAULT 1,

            solution_move_uci TEXT,
            solution_move_san TEXT,
            solution_line TEXT,

            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TEXT,
            notes TEXT,

            FOREIGN KEY (move_id) REFERENCES moves(move_id)
        )
    """)

    connection.commit()
    connection.close()

    print("Merlin database created successfully!")


if __name__ == "__main__":
    create_database()
