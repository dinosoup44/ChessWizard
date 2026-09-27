"""Internal frozen validator, built separately and never shipped in the app folder."""
import ctypes
import gc
from contextlib import closing
import threading
from dataclasses import asdict
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import traceback
import zipfile


def pump(root, predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    assert predicate(), "Frozen UI operation timed out"


def import_ui_smoke(app, root, menu, result, network):
    root.nametowidget(menu.entrycget("File", "menu")).invoke("Import Games...")
    root.update()
    dialog = app.review.import_dialog
    assert dialog.root.winfo_exists()
    assert tuple(dialog.source_picker.cget("values")) == ("Chess.com", "Lichess")
    assert not dialog.accounts
    assert tuple(dialog.username_picker.cget("values")) == ()
    root.nametowidget(menu.entrycget("File", "menu")).invoke("Import Games...")
    assert app.review.import_dialog is dialog
    assert not hasattr(app.review, "import_button")
    assert "No games imported" in app.review.title_label.cget("text")
    dialog.import_button.invoke()
    assert "username" in dialog.status.get()
    dialog.username.set("FrozenFixture")
    network["pause"] = True
    dialog.import_button.invoke()
    try:
        pump(root, network["entered"].is_set)
        assert str(dialog.import_button.cget("state")) == "disabled"
        assert str(dialog.stop_button.cget("state")) == "normal"
        dialog.stop_button.invoke()
        assert dialog.cancel.is_set()
    finally:
        network["release"].set()
    pump(root, lambda: not dialog.busy)
    assert "stopped" in dialog.status.get().lower()
    network["pause"] = False
    for source in ("Chess.com", "Lichess"):
        dialog.source.set(source)
        dialog.source_changed(object())
        dialog.username.set("FrozenFixture")
        dialog.import_button.invoke()
        pump(root, lambda: not dialog.busy)
        assert "Connection failed" in dialog.output.get("1.0", "end")
        assert "Errors: 1" in dialog.output.get("1.0", "end")
        assert str(dialog.import_button.cget("state")) == "normal"
        assert str(dialog.stop_button.cget("state")) == "disabled"
    dialog.close()
    root.update()
    root.nametowidget(menu.entrycget("File", "menu")).invoke("Import Games...")
    root.update()
    assert app.review.import_dialog is not dialog
    assert app.review.import_window.winfo_exists()
    app.review.import_dialog.close()
    result["import_games"] = {"result": "PASS", "sources": ["Chess.com", "Lichess"],
        "navigation_and_empty_state_same_dialog": True, "editable_username": True,
        "remembered_account_control": "renders empty on clean profile",
        "start_stop_states_and_cancellation": True, "reopen": True,
        "offline_both_sources": "clear failure; no external socket or DNS request allowed",
        "controlled_provider_import": "Controlled HTTP fixtures in end-to-end test; live-provider owner test previously performed (reported)"}


def newest_first_fixture(profile, root, result):
    """Local fixture exercises frozen normalizers/repository, not a provider transport."""
    from database_bootstrap import ensure_database
    from game_import_repository import GameImportRepository
    from merlin_ui.game_review_view import GameReviewView
    import import_games
    path = profile / "ordering-fixture.db"
    ensure_database(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        repository = GameImportRepository(connection)
        for identity, day in (("F0000001", "2026.09.14"), ("F0000002", "2026.09.12"), ("F0000003", "2026.09.14")):
            raw = (f'[Site "https://lichess.org/{identity}"]\n[White "FrozenFixture"]\n'
                   f'[Black "Opponent"]\n[UTCDate "{day}"]\n[UTCTime "12:00:00"]\n'
                   '[Result "1-0"]\n[TimeControl "300+0"]\n\n1. e4 e5 1-0\n\n')
            game, preserved = next(import_games.split_pgn_games(raw))
            assert repository.import_game(import_games, "FrozenFixture", game, preserved)
        assert not repository.import_game(import_games, "FrozenFixture", game, preserved)
        counts = {name: connection.execute('SELECT count(*) FROM "' + name + '"').fetchone()[0]
                  for name in ("games", "moves", "tactic_candidates", "tactic_occurrences", "training_attempts",
                               "analysis_coverage", "engine_position_cache", "engine_candidate_line_cache")}
        assert counts["games"] == 3 and counts["moves"] == 6
        assert all(value == 0 for key, value in counts.items() if key not in {"games", "moves"})
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    import tkinter as tk
    window = tk.Toplevel(root)
    view = GameReviewView(window, path)
    try:
        root.update()
        order = [game["source_game_id"] for game in view.games]
        assert order == ["F0000003", "F0000001", "F0000002"]
        assert view.current_game["source_game_id"] == order[0]
        result["newest_first_fixture"] = {"result": "PASS", "order": order, "counts": counts,
            "origin": "local synthetic PGN through frozen repository/normalizer; no provider fetch"}
    finally:
        view.close()


def database_snapshot(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        counts = {n: db.execute('SELECT count(*) FROM "' + n + '"').fetchone()[0] for n in names}
        candidates = db.execute("SELECT candidate_id FROM tactic_candidates ORDER BY candidate_id").fetchall()
        quick = db.execute("PRAGMA quick_check").fetchall()
        foreign = db.execute("PRAGMA foreign_key_check").fetchall()
        assert quick == [("ok",)] and foreign == []
    return dict(counts=counts, candidate_ids=candidates, quick_check=quick,
                foreign_key_check=foreign, sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def frozen_workflow(profile, root, result, launch_engine, forbid_engine, *, cancel_test=False):
    """Exercise shipped UI/services with fixture HTTP bytes and real bundled Stockfish.

    Only the unshipped validator replaces the HTTP boundary. Cancellation pauses a
    progress callback after one completed check so the actual Stop button is deterministic.
    """
    import chess.engine
    import game_import_http
    import tkinter as tk
    from database_bootstrap import ensure_database
    from merlin_ui.application import ChessWizardApplication
    from game_analysis_models import AnalysisScopeKind
    name = "cancel-resume" if cancel_test else "end-to-end"
    path = profile / (name + ".db")
    ensure_database(path)
    window = tk.Toplevel(root)
    app = ChessWizardApplication(window, path)
    imported, completed, progress_events, engine_paths = [], [], [], []
    original_http = game_import_http.urlopen
    entered, release = threading.Event(), threading.Event()
    raw_games = []
    for fen, played, identity, day in (
        ("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", "h3", "mate", "2026.09.14"),
        ("r3k3/8/8/3N4/8/8/4P3/4K3 w - - 0 1", "Kf1", "fork", "2026.09.13")):
        raw_games.append(f'[Link "https://www.chess.com/game/live/{identity}"]\n'
            '[White "FrozenFixture"]\n[Black "Opponent"]\n'
            f'[UTCDate "{day}"]\n[UTCTime "12:00:00"]\n[SetUp "1"]\n[FEN "{fen}"]\n'
            f'[Result "1-0"]\n[TimeControl "300+0"]\n\n1. {played} 1-0\n\n')
    requests = []
    def fixture_http(request, timeout):
        requests.append(request.full_url)
        payload = (json.dumps({"archives": ["https://api.chess.com/pub/player/frozenfixture/games/2026/09"]})
            if request.full_url.endswith("/archives") else "".join(raw_games))
        return io.BytesIO(payload.encode())
    def observed_engine(command, *args, **kwargs):
        engine_path = Path(command if isinstance(command, (str, Path)) else command[0]).resolve()
        assert engine_path.is_relative_to(Path(sys._MEIPASS).resolve())
        assert hashlib.sha256(engine_path.read_bytes()).hexdigest() == "c86215fa1977d53b82ed854540a4c7b025be4cd042276c85ba3de53fb9118911"
        engine_paths.append(str(engine_path))
        result["engine_launching"] = True
        try:
            return launch_engine(command, *args, **kwargs)
        finally:
            result["engine_launching"] = False
    try:
        root.update()
        assert not app.review.games
        menu = window.nametowidget(window.cget("menu"))
        root.nametowidget(menu.entrycget("Tools", "menu")).invoke("Analyze Games...")
        empty = app.review.analysis_dialog
        pump(root, lambda: not empty.loading)
        assert not empty.snapshot.queued and str(empty.start_button.cget("state")) == "disabled"
        empty.close()
        root.nametowidget(menu.entrycget("File", "menu")).invoke("Import Games...")
        importer = app.review.import_dialog
        importer.source.set("Chess.com")
        importer.source_changed(object())
        importer.username.set("FrozenFixture")
        original_import_complete = importer.on_complete
        def finish_import(value):
            imported.append(value)
            original_import_complete(value)
        importer.on_complete = finish_import
        game_import_http.urlopen = fixture_http
        importer.import_button.invoke()
        pump(root, lambda: bool(imported) and not importer.busy)
        assert imported[0].added == 2 and imported[0].errors == 0, imported
        importer.close()
        game_import_http.urlopen = original_http
        root.update()
        assert [g["source_game_id"] for g in app.review.games] == ["mate", "fork"]
        references = app.review.opening_reference.service.library.list_books()
        if references:
            picker = app.review.opening_reference
            picker.service.select(app.review.current_game['game_id'], references[0].installation_id)
            picker.refresh(force=True)
            assert picker.selected_id == references[0].installation_id
            result['opening_library']['review_reference_selected'] = True
        before = database_snapshot(path)
        assert before["counts"]["tactic_candidates"] == before["counts"]["analysis_coverage"] == before["counts"]["engine_position_cache"] == 0
        root.nametowidget(menu.entrycget("File", "menu")).invoke("Import Games...")
        assert app.review.import_dialog.accounts
        assert "FrozenFixture".lower() in str(app.review.import_dialog.username_picker.cget("values")).lower()
        app.review.import_dialog.close()
        root.nametowidget(menu.entrycget("Tools", "menu")).invoke("Analyze Games...")
        dialog = app.review.analysis_dialog
        pump(root, lambda: not dialog.loading)
        assert len(dialog.snapshot.queued) == 2
        assert sum(g.pending_checks for g in dialog.snapshot.games) == 10
        assert tuple(dialog.scope_picker.cget("values")) == tuple(k.value for k in AnalysisScopeKind)
        assert dialog.service.profile.label == "Production defaults"
        original_complete = dialog.on_complete
        def finish(value):
            completed.append(value)
            original_complete(value)
        dialog.on_complete = finish
        service_run = dialog.service.run
        def observe_run(scope, *, cancel, progress):
            def observed(event):
                progress_events.append(asdict(event))
                progress(event)
                if cancel_test and event.checks_processed == 1 and not entered.is_set():
                    entered.set()
                    assert release.wait(15), "Stop test did not release worker"
            return service_run(scope, cancel=cancel, progress=observed)
        dialog.service.run = observe_run
        chess.engine.SimpleEngine.popen_uci = observed_engine
        dialog.start_button.invoke()
        assert dialog.busy and str(dialog.stop_button.cget("state")) == "normal"
        assert str(dialog.start_button.cget("state")) == "disabled"
        stopped = None
        if cancel_test:
            pump(root, entered.is_set, 60)
            pump(root, lambda: "Analyzer checks processed: 1" in dialog.output.get("1.0", "end"))
            dialog.stop_button.invoke()
            assert dialog.cancel.is_set()
            release.set()
            pump(root, lambda: len(completed) == 1 and not dialog.loading, 60)
            assert completed[0].cancelled and completed[0].checks_processed == 1 and completed[0].errors == 0
            stopped = database_snapshot(path)
            assert stopped["counts"]["analysis_coverage"] == 1
            assert dialog.snapshot.queued
            dialog.start_button.invoke()
        pump(root, lambda: len(completed) == (2 if cancel_test else 1) and not dialog.loading, 60)
        chess.engine.SimpleEngine.popen_uci = forbid_engine
        first = completed[-1]
        assert first.errors == first.games_remaining == 0, first
        assert sum(r.checks_processed for r in completed) == 10
        assert sum(r.candidates_created for r in completed) == 2, [asdict(r) for r in completed]
        # Current Analyze Games also fills timeline and depth-16 quality evidence.
        assert sum(r.engine_searches-r.evaluation_searches-r.quality_searches for r in completed) == 13, [asdict(r) for r in completed]
        assert sum(r.positions_evaluated for r in completed) == (6 if cancel_test else 4), [asdict(r) for r in completed]
        assert sum(r.quality_moves_processed for r in completed) == (3 if cancel_test else 2), [asdict(r) for r in completed]
        assert not dialog.snapshot.queued and str(dialog.start_button.cget("state")) == "disabled"
        assert "Analysis complete" in dialog.status.get()
        moments = []
        for index in range(2):
            app.review.show_game(index)
            root.update()
            assert len(app.review.moments) == 1
            moment = app.review.moments[0]
            app.review.jump_to_tactic(moment)
            root.update()
            assert app.review.get_board_for_current_step().fen() == app.review.moves[0]["fen_before"]
            moments.append(str(moment))
        app.open_training()
        root.update()
        assert len(app.training.candidates) == 2 and app.training.current_candidate is not None
        app.training.close()
        post = database_snapshot(path)
        expected = dict(games=2, moves=2, tactic_candidates=2, analysis_coverage=10,
            engine_position_cache=13, tactic_episodes=1, tactic_episode_members=1,
            tactic_occurrences=0, training_attempts=0,
            engine_candidate_line_cache=sum(r.evaluation_inserts+r.quality_inserts for r in completed))
        assert all(post["counts"][k] == v for k, v in expected.items()), post
        dialog.service.run = service_run
        repeat = service_run()
        assert repeat.checks_processed == repeat.engine_searches == repeat.database_changes == repeat.candidates_created == 0
        after = database_snapshot(path)
        assert post == after, "Completed rerun changed rows, IDs or database bytes"
        assert len(after["candidate_ids"]) == len(set(tuple(r) for r in after["candidate_ids"])) == 2
        assert progress_events and any(e["analyzer"] for e in progress_events)
        result[name] = dict(result="PASS", import_result=asdict(imported[0]), fixture_requests=requests,
            fixture_boundary="Unshipped helper supplies controlled HTTP response bytes; shipped UI/provider/service/repository unchanged",
            first_runs=[asdict(r) for r in completed], rerun=asdict(repeat), stopped=stopped,
            before_analysis=before, before_rerun=post, after_rerun=after,
            bundled_engine_paths=engine_paths, progress_events=progress_events, review_moments=moments,
            real_menu_and_buttons=True, remembered_account_visible=True, training_healthy=True,
            zero_rerun_changes=True, candidate_ids_unchanged=True)
    finally:
        release.set()
        game_import_http.urlopen = original_http
        chess.engine.SimpleEngine.popen_uci = forbid_engine
        if app.review.analysis_dialog and app.review.analysis_dialog.busy:
            app.review.analysis_dialog.stop()
            pump(root, lambda: not app.review.analysis_dialog.busy, 60)
        app.close()



def opening_smoke(app, root, profile, result):
    """Exercise the current installed opening services and windows on a new library."""
    from opening_library_service import OpeningLibraryService
    from opening_book_repository import OpeningBookRepository
    from opening_book_service import OpeningBookService
    from opening_book_models import BookDetails, MoveDetails
    from opening_book_session import OpeningBookSession
    from opening_library_package import inspect_package
    library = OpeningLibraryService()
    assert library.list_libraries() == ()
    item = library.create_library("Beta fixture library")
    with closing(OpeningBookRepository.open(item.path)) as repository:
        author = OpeningBookService(repository)
        bid = author.create_book(BookDetails("Beta fixture book"))
        session = OpeningBookSession(author, bid)
        for notation in ('e4', 'e6', 'd4', 'd5'):
            move = session.board.parse_san(notation)
            session.stage(move.uci()); session.save(MoveDetails())
        assert len(repository.snapshot(bid).moves) == 4
    reopened = OpeningLibraryService().get_library(item.library_id)
    assert len(reopened.books) == 1 and len(reopened.books[0].snapshot.moves) == 4
    exported = profile / 'beta-fixture-export.cwbook'
    library.export_library(item.library_id, exported)
    assert len(inspect_package(exported).books[0].moves) == 4
    app.review.open_opening_library();root.update()
    assert app.review.opening_library_window.winfo_exists()
    app.review.open_installed_book(reopened.books[0]);root.update()
    assert app.review.opening_book_window.winfo_exists()
    assert len(app.review.opening_book_studio.session.snapshot.moves) == 4
    # Manual selection is available even before a real game is imported.
    picker = app.review.opening_reference
    picker.refresh(force=True)
    assert any(book.library_id == item.library_id for book in picker.service.library.list_books())
    app.review.open_game_explorer();root.update()
    assert app.review.explorer_window.winfo_exists()
    result['opening_library'] = dict(result='PASS', new_library=True, created_book=True,
        saved_branch_plies=4, reopened=True, managed_library_visible=True,
        studio_opened=True, review_reference_available=True, exported=True,
        owner_books_absent=True)
    result['game_explorer'] = 'PASS: empty installed window opened'


def run():
    assert getattr(sys, "frozen", False), "This test must run frozen"
    profile = Path(os.environ["CHESSWIZARD_DATA_DIR"]).resolve()
    report = Path(sys.argv[1])
    result = {"frozen": True, "callback_errors": [], "engine_searches": 0, "blocked_network_attempts": 0}
    network = {"pause": False, "entered": threading.Event(), "release": threading.Event()}
    source_root = Path(os.environ["CHESSWIZARD_AUDIT_SOURCE_ROOT"]).resolve()
    def audit(event, args):
        # Windows asyncio creates a loopback self-pipe during engine startup.
        if (event == "socket.connect" and result.get("engine_launching")
                and isinstance(args[1], tuple) and args[1][0] in {"127.0.0.1", "::1"}):
            return
        if event in {"socket.getaddrinfo", "socket.connect"}:
            result["blocked_network_attempts"] += 1
            network["entered"].set()
            if network["pause"]:
                network["release"].wait(10)
            raise OSError("Network disabled by isolated frozen validation")
        if event == "open" and isinstance(args[0], (str, bytes)):
            target = Path(os.fsdecode(args[0])).resolve()
            if target.is_relative_to(source_root) and target != report.resolve():
                raise AssertionError("Runtime attempted to read the development tree: " + str(target))
        if event == "sqlite3.connect":
            target = str(args[0])
            if target == ":memory:":
                return
            if target.startswith("file:"):
                from urllib.parse import urlparse, unquote
                target = unquote(urlparse(target).path).lstrip("/")
            assert Path(target).resolve().is_relative_to(profile), target
    sys.addaudithook(audit)
    import chess.engine
    def forbidden(*args, **kwargs):
        result["engine_searches"] += 1
        raise AssertionError("Analysis engine call forbidden")
    launch_engine = chess.engine.SimpleEngine.popen_uci
    chess.engine.SimpleEngine.popen_uci = forbidden
    import tkinter as tk
    from merlin_ui.application import ChessWizardApplication
    from merlin_ui.startup import prepare_database
    from chesswizard_version import DISPLAY_VERSION
    from admin_engine import test_engine
    from PIL import Image
    from theme_core.packages import _archive_theme
    root = tk.Tk()
    root.report_callback_exception = lambda *e: result["callback_errors"].append(str(e[1]))
    path = prepare_database(root)
    assert path is not None and path.is_relative_to(profile)
    app = ChessWizardApplication(root, path)
    try:
        root.update()
        assert DISPLAY_VERSION in root.title()
        assert not app.review.games and not app.review.moments
        assert len(app.review.review_sets) == 1
        assert app.review.review_set_picker is None
        assert app.review.human_review_panel is None
        result["game_review"] = "empty state; QA metadata absent and hidden"
        menu = root.nametowidget(root.cget("menu"))
        view_menu = root.nametowidget(menu.entrycget("View", "menu"))
        root.nametowidget(menu.entrycget("Tools", "menu")).invoke("Training...")
        root.update()
        assert app.training and not app.training.candidates and app.training.current_candidate is None
        first = app.training
        root.nametowidget(menu.entrycget("Tools", "menu")).invoke("Training...")
        assert app.training is first
        result["training"] = "empty state; same DB; repeated navigation reused window"
        view_menu.invoke("Appearance...")
        root.update()
        assert app.review.shell._theme_window.winfo_exists()
        assert app.review.shell.theme_service.current.loaded.theme.theme_id == "default"
        assert app.training.shell.theme_service is app.review.shell.theme_service
        result["appearance"] = "default Unicode theme; shared theme service"
        root.nametowidget(menu.entrycget("Tools", "menu")).invoke("Admin Console...")
        console = app.review.shell._admin_console
        deadline = time.monotonic() + 20
        while console.snapshot is None and time.monotonic() < deadline:
            root.update()
            time.sleep(0.05)
        assert console.snapshot is not None, console.status.get()
        assert console.snapshot.database.counts["games"] == 0
        assert DISPLAY_VERSION in console.pages["Overview"].get("1.0", "end")
        assert DISPLAY_VERSION in console.pages["Diagnostics"].get("1.0", "end")
        result["admin"] = asdict(console.snapshot)
        opening_smoke(app, root, profile, result)
        import_ui_smoke(app, root, menu, result, network)
        newest_first_fixture(profile, root, result)
        gc.collect()  # Dispose destroyed fixture widgets on the Tk thread before new workers.
        frozen_workflow(profile, root, result, launch_engine, forbidden)
        gc.collect()
        frozen_workflow(profile, root, result, launch_engine, forbidden, cancel_test=True)
        gc.collect()
        assert result["engine_searches"] == 0
        assert all(str(entry).startswith(str(Path(sys.executable).parent)) for entry in sys.path)
        result["source_tree_independent"] = True
        engine = test_engine(Path(sys._MEIPASS))
        assert engine.found and engine.diagnostic == "Passed", engine
        result["engine"] = asdict(engine)
        image = Image.new("RGBA", (4, 4), "red")
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        stream.seek(0)
        assert Image.open(stream).getpixel((0, 0)) == (255, 0, 0, 255)
        result["pillow_png"] = "encode/decode passed"
        bad = profile / "bad-theme.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("unsafe.js", "do not execute")
        try:
            _archive_theme(bad)
            raise AssertionError("Script theme was accepted")
        except ValueError:
            result["theme_security"] = "script pack rejected"
        bad.unlink()
        result["tcl"] = root.tk.call("info", "patchlevel")
        result["tk"] = root.tk.call("package", "require", "Tk")
        result["title"] = root.title()
        assert not result["callback_errors"]
    finally:
        app.close()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        names = [r[0] for r in db.execute("select name from sqlite_master where type='table'")]
        counts = {n: db.execute('select count(*) from "' + n + '"').fetchone()[0] for n in names}
        assert all(count == 0 for name, count in counts.items() if name != "application_metadata")
        assert counts["application_metadata"] == 5
        result["counts"] = counts
        result["quick_check"] = db.execute("pragma quick_check").fetchall()
        result["foreign_key_check"] = db.execute("pragma foreign_key_check").fetchall()
        assert result["quick_check"] == [("ok",)] and not result["foreign_key_check"]
    result["db_bytes"] = path.stat().st_size
    assert result["db_bytes"] > 0
    assert {"game_collections", "game_collection_members", "tactic_occurrences", "ignored_import_games"} <= set(names)
    before = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
    # Launch the actual shipped entry as well as exercising its same frozen PYZ above.
    environment = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    process = subprocess.Popen([str(Path(sys.executable).with_name("ChessWizard.exe"))], env=environment,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    user32 = ctypes.windll.user32
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_ssize_t)
    windows = []
    def enumerate_window(hwnd, _):
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == process.pid:
            title = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, title, len(title))
            if DISPLAY_VERSION in title.value:
                windows.append((hwnd, title.value))
        return True
    callback = callback_type(enumerate_window)
    deadline = time.monotonic() + 20
    try:
        while not windows and time.monotonic() < deadline and process.poll() is None:
            user32.EnumWindows(callback, 0)
            time.sleep(0.1)
        assert windows, "Shipped executable did not open its versioned window"
        time.sleep(0.5)
        assert process.poll() is None
        for hwnd, _ in windows:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
        assert process.wait(timeout=10) == 0
        result["shipped_executable"] = {"window": windows[0][1], "exit_code": 0}
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
    after = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
    assert before == after, "Repeat launch changed DB"
    result["repeat_database_unchanged"] = True
    result["result"] = "PASS"
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Frozen smoke PASS", flush=True)


if __name__ == "__main__":
    try:
        run()
    except Exception:
        Path(sys.argv[1]).write_text(json.dumps({"result": "FAIL", "traceback": traceback.format_exc()}, indent=2))
        raise
