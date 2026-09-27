"""Controlled public-HTTP fixtures; never use a production account or database."""
from contextlib import contextmanager, closing
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import chess.engine
from database_bootstrap import ensure_database
from game_import_models import ImportResult
from game_import_service import GameImportService, _import_lock
from game_review_repository import GameReviewRepository
from merlin_ui.import_games_dialog import ImportGamesDialog
from merlin_ui.game_review_view import GameReviewView
from game_review_sets import ALL_GAMES
import game_import_http
import import_chesscom
import import_games


def pgn(source="chesscom", identity="100", day="2026.09.12", clock="12:00:00", moves="1. e4 e5 2. Nf3 Nc6 1-0"):
    site = f'[Link "https://www.chess.com/game/live/{identity}"]' if source == "chesscom" else f'[Site "https://lichess.org/{identity}"]'
    return f'[Event "rated blitz game"]\n{site}\n[White "Example_User"]\n[Black "Opponent"]\n[UTCDate "{day}"]\n[UTCTime "{clock}"]\n[Result "1-0"]\n[TimeControl "300+0"]\n\n{moves}\n\n'


class HTTPFixture:
    def __init__(self, text, archives=None):
        self.text = text
        self.archives = archives if archives is not None else ["https://api.chess.com/pub/player/example_user/games/2026/09"]
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request.full_url, timeout, dict(request.headers)))
        if request.full_url.endswith("/archives"):
            return io.BytesIO(json.dumps({"archives": self.archives}).encode())
        return io.BytesIO(self.text.encode())


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "merlin.db"
        profile = patch.dict(os.environ, CHESSWIZARD_DATA_DIR=str(self.path.parent))
        profile.start(); self.addCleanup(profile.stop)
        theme = patch("theme_core.active._default_service", None)
        theme.start(); self.addCleanup(theme.stop)
        ensure_database(self.path)
        self.service = GameImportService(self.path)
        self.guard = patch.object(chess.engine.SimpleEngine, "popen_uci", side_effect=AssertionError("No analysis"))
        self.guard.start(); self.addCleanup(self.guard.stop)
        self.cooldown = patch.object(game_import_http, "_retry_after", 0.0)
        self.cooldown.start();self.addCleanup(self.cooldown.stop)

    def run_import(self, source, text, username="Example_User"):
        fixture = HTTPFixture(text)
        with patch("game_import_http.urlopen", fixture):
            result = self.service.run(source, username)
        return result, fixture

    def rows(self, table):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT * FROM "' + table + '"').fetchall()

    def assert_clean(self):
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        for table in ("tactic_candidates", "tactic_occurrences", "analysis_coverage", "engine_position_cache", "engine_candidate_line_cache", "training_attempts"):
            self.assertEqual(self.rows(table), [])

    def test_both_sources_first_repeat_then_new(self):
        for source, first_id, next_id in [("chesscom","100","101"),("lichess","Abcd1234","Efgh5678")]:
            with self.subTest(source=source):
                text=pgn(source,first_id)
                first,fixture=self.run_import(source,text)
                self.assertEqual((first.found,first.added,first.existing,first.errors),(1,1,0,0))
                before=self.rows("games"),self.rows("moves")
                repeat,_=self.run_import(source,text,"EXAMPLE_USER")
                self.assertEqual((repeat.added,repeat.existing,repeat.errors),(0,1,0))
                self.assertEqual((self.rows("games"),self.rows("moves")),before)
                later,_=self.run_import(source,text+pgn(source,next_id,"2026.09.13"))
                self.assertEqual((later.added,later.existing,later.errors),(1,1,0))
                self.assertEqual(sum(a[0]==source for a in self.service.accounts()),1)
                if source=="lichess":
                    self.assertNotIn("max=",fixture.requests[0][0])
                self.assert_clean()
        self.assertEqual(len(self.rows("games")),4)
        self.assertEqual(len(self.rows("moves")),16)
        self.assertEqual(len(self.rows("users")),1)

    def test_existing_normalizer_is_used(self):
        with patch.object(import_chesscom,"import_single_game",wraps=import_chesscom.import_single_game) as existing:
            result,_=self.run_import("chesscom",pgn())
            self.assertEqual(result.added,1)
            existing.assert_called_once()
        game=self.rows("games")[0]
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT played_at,time_class,raw_pgn FROM games").fetchone(),("2026-09-12T12:00:00Z","blitz",pgn()))

    def test_no_games_saves_successful_account(self):
        for source in ("chesscom","lichess"):
            result,_=self.run_import(source,"")
            self.assertEqual((result.found,result.errors),(0,0))
        self.assertEqual(len(self.service.accounts()),2)
        self.assertEqual(self.rows("games"),[])

    def test_not_found_and_offline_do_not_create_accounts(self):
        for source in ("chesscom","lichess"):
            for error in (HTTPError("https://example",404,"not found",{},None),URLError("offline")):
                with patch("game_import_http.urlopen",side_effect=error):
                    result=self.service.run(source,"Example_User")
                self.assertEqual(result.errors,1)
                self.assertEqual(self.service.accounts(),())
                self.assert_clean()

    def test_bad_archive_response_and_foreign_url(self):
        for data in ({}, {"archives":"wrong"}, {"archives":["https://other.test/private"]}):
            with patch("game_import_http.urlopen",return_value=io.BytesIO(json.dumps(data).encode())):
                result=self.service.run("chesscom","Example_User")
            self.assertEqual(result.errors,1)
            self.assertEqual(self.rows("games"),[])

    def test_malformed_game_is_reported_and_next_valid_game_imports(self):
        bad=pgn(identity="bad",moves="1. e4 e5 2. Bh6 1-0")
        result,_=self.run_import("chesscom",bad+pgn())
        self.assertEqual((result.found,result.added,result.errors),(2,1,1))
        self.assertEqual(len(self.rows("moves")),4)
        self.assert_clean()

    def test_truncated_pgn_does_not_commit_partial_game(self):
        result,_=self.run_import("chesscom",pgn(moves="1. e4 e5"))
        self.assertEqual((result.added,result.errors),(0,1))
        self.assertEqual(self.rows("games"),[])
        self.assertEqual(self.rows("moves"),[])

    def test_normalization_failure_rolls_back_game_and_account(self):
        original=import_chesscom.import_single_game
        def fail(*args):
            original(*args)
            raise ValueError("failure after move insertion")
        with patch.object(import_chesscom,"import_single_game",side_effect=fail):
            result,_=self.run_import("chesscom",pgn())
        self.assertEqual(result.errors,1)
        self.assertEqual(self.rows("games"),[])
        self.assertEqual(self.rows("moves"),[])
        self.assertEqual(self.rows("chess_accounts"),[])
        self.assertEqual(self.rows("users"),[])
        self.assert_clean()

    def test_network_failure_keeps_previous_archive_and_retry_is_safe(self):
        archives=["https://api.chess.com/pub/player/example_user/games/2026/08","https://api.chess.com/pub/player/example_user/games/2026/09"]
        fixture=HTTPFixture(pgn(),archives)
        def http(request,timeout):
            if '/08/pgn' in request.full_url:
                raise URLError("interrupted")
            return fixture(request,timeout)
        with patch("game_import_http.urlopen",side_effect=http):
            result=self.service.run("chesscom","Example_User")
        self.assertEqual((result.added,result.errors),(1,1))
        retry,_=self.run_import("chesscom",pgn()+pgn(identity="new"))
        self.assertEqual((retry.added,retry.existing,retry.errors),(1,1,0))
        self.assert_clean()

    def test_lichess_stream_failure_keeps_completed_game(self):
        class Interrupted(io.StringIO):
            def readline(self):
                line=super().readline()
                if not line:
                    raise OSError("connection lost")
                return line
        @contextmanager
        def stream(*args,**kwargs):
            yield Interrupted(pgn("lichess","Abcd1234"))
        with patch.object(import_games,"download_games",side_effect=stream):
            result=self.service.run("lichess","Example_User")
        self.assertEqual((result.added,result.errors),(1,1))
        self.assert_clean()

    def test_rate_limit_enforced_without_automatic_retry(self):
        with patch("game_import_http.urlopen",side_effect=HTTPError("https://example",429,"limit",{"Retry-After":"90"},None)) as request:
            first=self.service.run("lichess","Example_User")
            second=self.service.run("lichess","Example_User")
            self.assertEqual(request.call_count,1)
        self.assertIn("rate limit",first.details[0])
        self.assertEqual(second.errors,1)

    def test_progress_for_many_games_is_real(self):
        text="".join(pgn(identity=str(i)) for i in range(125))
        events=[]
        with patch("game_import_http.urlopen",HTTPFixture(text)):
            result=self.service.run("chesscom","Example_User",progress=events.append)
        self.assertEqual(result.added,125)
        self.assertTrue(any(e.found==100 and e.added==100 for e in events))
        self.assertEqual(len(self.rows("moves")),500)

    def test_busy_cancel_and_invalid_username_do_not_fetch(self):
        event=threading.Event();event.set()
        with patch("game_import_http.urlopen",side_effect=AssertionError("must not fetch")):
            self.assertTrue(self.service.run("lichess","Example_User",cancel=event).cancelled)
            self.assertEqual(self.service.run("lichess","../bad").errors,1)
            with _import_lock:
                self.assertEqual(self.service.run("lichess","Example_User").errors,1)

    def test_newest_date_then_id_with_old_and_unknown_dates(self):
        self.run_import("chesscom",pgn(identity="newest",day="2026.09.14")+pgn(identity="old",day="2026.09.01")+pgn(identity="tie",day="2026.09.14"))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual([g["source_game_id"] for g in GameReviewRepository(db).games()],["tie","newest","old"])
            db.execute("UPDATE games SET played_at='2026.09.15' WHERE source_game_id='old'")
            self.assertEqual(GameReviewRepository(db).games()[0]["source_game_id"],"old")

    def test_lichess_many_games_and_http_server_failure(self):
        text="".join(pgn("lichess",f"ID{i:06}") for i in range(125))
        first,_=self.run_import("lichess",text)
        second,_=self.run_import("lichess",text)
        self.assertEqual((first.added,second.added,second.existing),(125,0,125))
        with patch("game_import_http.urlopen",side_effect=HTTPError("https://example",503,"unavailable",{},None)):
            result=self.service.run("lichess","Example_User")
        self.assertEqual(result.errors,1)
        self.assertEqual(len(self.rows("games")),125)
        self.assert_clean()

    def test_unknown_identity_wrong_player_and_variant_are_errors(self):
        cases=[pgn().replace('[Link "https://www.chess.com/game/live/100"]', ''),
               pgn().replace('[White "Example_User"]','[White "SomeoneElse"]'),
               pgn().replace('[Event "rated blitz game"]','[Event "rated blitz game"]\n[Variant "Chess960"]')]
        for raw in cases:
            result,_=self.run_import("chesscom",raw)
            self.assertEqual((result.added,result.errors),(0,1))
        self.assertEqual(self.rows("games"),[])

    def test_core_import_has_no_tkinter_or_engine_process_dependency(self):
        import ast
        root=Path(__file__).resolve().parents[1]
        for name in ("game_import_service.py","game_import_repository.py","game_import_http.py","game_import_pgn.py","game_import_models.py","import_games.py","import_chesscom.py"):
            tree=ast.parse((root/name).read_text())
            imports=[alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names]
            imports += [node.module or "" for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
            self.assertFalse(any(n.startswith(("tkinter","merlin_ui","chess.engine","subprocess","engine_cache")) for n in imports),name)


class ImportUITests(unittest.TestCase):
    run_import = ImportTests.run_import
    rows = ImportTests.rows
    def setUp(self):
        ImportTests.setUp(self)
        self.root=tk.Tk()
        self.addCleanup(self.root.destroy)

    def test_dialog_source_username_remember_and_result(self):
        self.run_import("lichess",pgn("lichess","Abcd1234"))
        dialog=ImportGamesDialog(self.root,self.path)
        self.assertEqual(dialog.source.get(),"Lichess")
        self.assertEqual(dialog.username.get(),"Example_User")
        dialog.source.set("Chess.com");dialog.source_changed(object())
        self.assertEqual(dialog.username.get(),"")
        dialog.username.set("Example_User")
        with patch("game_import_http.urlopen",HTTPFixture(pgn())):
            dialog.start()
            deadline=time.monotonic()+5
            while dialog.busy and time.monotonic()<deadline:
                self.root.update();time.sleep(.01)
        self.assertFalse(dialog.busy)
        self.assertIn("New games added: 1",dialog.output.get("1.0","end"))
        self.assertIn("Analysis has not been run",dialog.output.get("1.0","end"))

    def test_empty_review_import_and_new_game_refresh(self):
        view=GameReviewView(self.root,self.path,review_sets=(ALL_GAMES,))
        self.addCleanup(view.connection.close)
        self.root.update()
        self.assertIn("No games imported",view.title_label.cget("text"))
        menu=self.root.nametowidget(self.root.cget("menu"))
        file=self.root.nametowidget(menu.entrycget("File","menu"))
        file.invoke("Import Games...");self.root.update()
        self.assertTrue(view.import_window.winfo_exists())
        dialog=view.import_dialog;dialog.username.set("Example_User")
        with patch("game_import_http.urlopen",HTTPFixture(pgn(day="2026.09.14")+pgn(identity="older"))):
            dialog.start()
            deadline=time.monotonic()+5
            while dialog.busy and time.monotonic()<deadline:
                self.root.update();time.sleep(.01)
        self.assertFalse(dialog.busy)
        self.assertEqual(len(view.games),2)
        self.assertEqual(view.current_game["source_game_id"],"100")
        self.assertEqual(len(view.moves),4)

    def test_slow_network_keeps_ui_responsive_and_blocks_duplicate_start(self):
        entered=threading.Event();release=threading.Event()
        fixture=HTTPFixture(pgn())
        def http(request,timeout):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test wait expired")
            return fixture(request,timeout)
        dialog=ImportGamesDialog(self.root,self.path)
        dialog.username.set("Example_User")
        with patch("game_import_http.urlopen",side_effect=http):
            dialog.start()
            try:
                self.assertTrue(entered.wait(2))
                tick=[];self.root.after(1,lambda:tick.append(True))
                deadline=time.monotonic()+1
                while not tick and time.monotonic()<deadline:
                    self.root.update();time.sleep(.005)
                self.assertTrue(tick)
                self.assertEqual(str(dialog.import_button.cget("state")),"disabled")
                dialog.start()
                self.assertTrue(dialog.busy)
            finally:
                release.set()
                deadline=time.monotonic()+5
                while dialog.busy and time.monotonic()<deadline:
                    self.root.update();time.sleep(.01)
            self.assertFalse(dialog.busy)
            self.assertEqual(len(self.rows("games")),1)
