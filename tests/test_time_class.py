import argparse
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import contextmanager

import chess.pgn

from analysis_crawler import get_selected_game_ids
from import_chesscom import import_single_game as import_chesscom
from import_games import import_single_game as import_lichess
from migrate_games_time_class import migrate
from time_class import classify_time_control


@contextmanager
def database(path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


class ClassificationTests(unittest.TestCase):
    def test_provider_boundaries_and_increment(self):
        cases = [
            ("lichess", "179", "bullet"), ("lichess", "180", "blitz"),
            ("lichess", "479", "blitz"), ("lichess", "480", "rapid"),
            ("lichess", "1499", "rapid"), ("lichess", "1500", "classical"),
            ("chesscom", "179", "bullet"), ("chesscom", "180", "blitz"),
            ("chesscom", "599", "blitz"), ("chesscom", "600", "rapid"),
            ("chesscom", "3600", "rapid"), ("chesscom", "120+12", "rapid"),
            ("lichess", "300+5", "rapid"), ("chesscom", "300+5", "blitz"),
            ("chesscom", "1/86400", "correspondence"),
        ]
        for source, clock, expected in cases:
            with self.subTest(source=source, clock=clock):
                self.assertEqual(classify_time_control(source, clock), expected)

    def test_explicit_labels_win(self):
        self.assertEqual(classify_time_control("lichess", "600", {"Event": "rated blitz game"}), "blitz")
        self.assertEqual(classify_time_control("chesscom", "300", provider_class="daily"), "correspondence")
        self.assertEqual(classify_time_control("lichess", "600", {"Speed": "ultraBullet"}), "bullet")
        self.assertEqual(classify_time_control("lichess", "600", {"Event": "Blitz Memorial"}), "rapid")

    def test_uncertain_clocks(self):
        for clock in (None, "", "?", "-", "0", "test", "40/7200:3600", "1/60", "-1+5"):
            self.assertEqual(classify_time_control("chesscom", clock), "unknown")
        self.assertEqual(classify_time_control("dev", "300"), "unknown")


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test.db"
        with database(self.path) as c:
            c.executescript("""
                CREATE TABLE games(game_id INTEGER PRIMARY KEY, source TEXT, time_control TEXT, raw_pgn TEXT);
                INSERT INTO games VALUES(1,'lichess','300+0','[Event "rated blitz game"]');
                INSERT INTO games VALUES(2,'chesscom','600',NULL);
                INSERT INTO games VALUES(3,'dev','test',NULL);
                CREATE TABLE tactic_candidates(candidate_id INTEGER PRIMARY KEY, notes TEXT);
                INSERT INTO tactic_candidates VALUES(42,'preserve');
                CREATE TABLE training_attempts(candidate_id INTEGER);
                INSERT INTO training_attempts VALUES(42);
            """)

    def test_migration_backup_preservation_and_idempotence(self):
        backup = migrate(self.path)
        with database(backup) as c:
            self.assertNotIn("time_class", [r[1] for r in c.execute("PRAGMA table_info(games)")])
            original = c.execute("SELECT * FROM games").fetchall()
        with database(self.path) as c:
            self.assertEqual(c.execute("SELECT game_id,source,time_control,raw_pgn FROM games").fetchall(), original)
            self.assertEqual(c.execute("SELECT time_class FROM games ORDER BY game_id").fetchall(), [("blitz",),("rapid",),("unknown",)])
            self.assertEqual(c.execute("SELECT * FROM tactic_candidates").fetchall(), [(42,"preserve")])
            self.assertEqual(c.execute("SELECT * FROM training_attempts").fetchall(), [(42,)])
            before = c.execute("SELECT * FROM games").fetchall()
        migrate(self.path)
        with database(self.path) as c:
            self.assertEqual(c.execute("SELECT * FROM games").fetchall(), before)

    def test_migration_rolls_back_column_on_failure(self):
        with patch("migrate_games_time_class.classify_stored_game", side_effect=RuntimeError("test")):
            with self.assertRaises(RuntimeError):
                migrate(self.path)
        with database(self.path) as c:
            self.assertNotIn("time_class", [r[1] for r in c.execute("PRAGMA table_info(games)")])

    def test_scope_filters_before_limit_and_excludes_dev(self):
        migrate(self.path)
        args = argparse.Namespace(source=None, time_class=["blitz"], all_games=False, last_games=1)
        with database(self.path) as c:
            self.assertEqual(get_selected_game_ids(c,args), [1])
            args.time_class = ["blitz", "rapid"]
            args.all_games = True
            self.assertEqual(get_selected_game_ids(c,args), [1,2])
            args.source = "lichess"
            self.assertEqual(get_selected_game_ids(c,args), [1])

    def test_both_importers_populate_time_class_and_preserve_pgn(self):
        with database(":memory:") as c:
            c.executescript("""
                CREATE TABLE games(game_id INTEGER PRIMARY KEY, user_id, account_id, source,
                  source_game_id, lichess_game_id, played_at, white_username, black_username,
                  user_color, white_rating, black_rating, result, termination, time_control,
                  time_class, rated, variant, raw_pgn);
                CREATE TABLE moves(move_id INTEGER PRIMARY KEY, game_id, ply_number, move_number,
                  color, is_user_move, fen_before, fen_after, san_played, uci_played);
            """)
            for importer, source, tag, clock, label in (
                (import_lichess, "lichess", '[GameId "abc"]', "300+0", "blitz"),
                (import_chesscom, "chesscom", '[Link "https://www.chess.com/game/live/123"]', "600", "rapid"),
            ):
                raw = f'[White "ExampleUser"]\n[Black "Other"]\n[TimeControl "{clock}"]\n{tag}\n\n1. e4 e5 *\n'
                game = chess.pgn.read_game(io.StringIO(raw))
                self.assertTrue(importer(c,1,1,"ExampleUser",game,raw))
                self.assertFalse(importer(c,1,1,"ExampleUser",game,raw))
                self.assertEqual(c.execute("SELECT time_class,time_control,raw_pgn FROM games WHERE source=?", (source,)).fetchone(), (label,clock,raw))
            self.assertEqual(c.execute("SELECT COUNT(*) FROM moves").fetchone()[0], 4)


if __name__ == "__main__":
    unittest.main()
