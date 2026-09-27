"""Temporary-profile analysis contracts; real engine integration is explicitly opt-in."""
from contextlib import closing
from dataclasses import replace
import hashlib
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
from unittest.mock import Mock, patch

import chess.engine
from analysis_registry import ANALYZERS
from analysis_results import HeavyResult
from analysis_scout import ScoutResult
from database_bootstrap import ensure_database
from game_analysis_models import AnalysisScopeKind, GameAnalysisScope
from game_analysis_service import GameAnalysisService
from data_activity import exclusive_analysis_activity
from game_import_service import GameImportService
from game_review_sets import ALL_GAMES
from merlin_ui.analyze_games_dialog import AnalyzeGamesDialog
from merlin_ui.game_review_view import GameReviewView
from tactic_query import TacticQuery
from tests import test_game_import as imports

ROOT = Path(__file__).resolve().parents[1]
MATE_FEN = '6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1'
FORK_FEN = 'r3k3/8/8/3N4/8/8/4P3/4K3 w - - 0 1'


def position_pgn(fen, move, identity='mate', day='2026.09.14'):
    raw = imports.pgn(identity=identity, day=day, moves='1. '+move+' 1-0')
    return raw.replace('[Result', f'[SetUp "1"]\n[FEN "{fen}"]\n[Result')


def negative_definition():
    return replace(ANALYZERS['missed_fork'], screener=lambda row: False)


def candidate_definition():
    return replace(ANALYZERS['missed_fork'], screener=lambda row: True,
        scout=lambda row, evidence: ScoutResult(True, 'fixture'),
        heavy=lambda row, positions: HeavyResult('candidate', {
            'candidate_status':'candidate','confidence':1.0,'detector_version':'2',
            'solution_move_uci':'d2d4','solution_move_san':'d4','solution_line':'d4 d5',
            'notes':'fixture','metadata_json':'{}'}))


class TemporaryAnalysis(unittest.TestCase):
    def setUp(self):
        import gc
        gc.collect()  # Dispose prior Tk test cycles on the main thread before starting workers.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'merlin.db'
        for target in (patch.dict(os.environ, CHESSWIZARD_DATA_DIR=str(self.path.parent)),
                       patch('theme_core.active._default_service', None),
                       patch('game_import_http._retry_after', 0.0)):
            target.start(); self.addCleanup(target.stop)
        ensure_database(self.path)

    def import_fixture(self, text=None):
        with patch('game_import_http.urlopen', imports.HTTPFixture(text or imports.pgn())):
            result = GameImportService(self.path).run('chesscom','Example_User')
        self.assertEqual(result.errors, 0, result.details)
        return result

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def count(self, table):
        with closing(self.connect()) as db:
            return db.execute('SELECT count(*) FROM "'+table+'"').fetchone()[0]

    def digest(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def service(self, definition=None):
        return GameAnalysisService(self.path, definitions=[definition or negative_definition()], evaluation_settings=None,quality_settings=None)

    def assert_integrity(self):
        with closing(self.connect()) as db:
            self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(self.count('training_attempts'), 0)


class AnalysisContractTests(TemporaryAnalysis):
    def test_preview_is_read_only_and_never_starts_engine(self):
        self.import_fixture(); before=self.digest()
        with patch.object(chess.engine.SimpleEngine,'popen_uci',side_effect=AssertionError('Engine during preview')):
            snapshot=self.service().preview()
        self.assertEqual((len(snapshot.queued),snapshot.queued[0].pending_checks),(1,2))
        self.assertEqual(before,self.digest())

    def test_registered_production_set_and_profile_do_not_activate_experiments(self):
        service=GameAnalysisService(self.path)
        self.assertEqual(service.definitions,tuple(ANALYZERS.values()))
        self.assertEqual(service.profile.label,'Production defaults')
        self.assertEqual({d.analysis_type for d in service.definitions},
            {'missed_fork','missed_mate','missed_pin','missed_skewer','missed_xray'})

    def test_negative_completion_rerun_zero_writes_or_engine(self):
        self.import_fixture();service=self.service()
        with patch.object(chess.engine.SimpleEngine,'popen_uci',side_effect=AssertionError('No engine needed')):
            first=service.run();before=self.digest();second=service.run()
        self.assertEqual((first.screened_out,first.games_completed,first.errors),(2,1,0))
        self.assertEqual((second.checks_processed,second.database_changes,second.engine_searches),(0,0,0))
        self.assertEqual(before,self.digest());self.assert_integrity()

    def test_selected_scope_and_new_scope(self):
        self.import_fixture(imports.pgn(identity='1')+imports.pgn(identity='2'))
        service=self.service();scope=GameAnalysisScope(AnalysisScopeKind.SELECTED,(1,))
        self.assertEqual(service.run(scope).games_completed,1)
        snapshot=service.preview(GameAnalysisScope(AnalysisScopeKind.NEW))
        self.assertEqual([g.game_id for g in snapshot.games],[2])
        with closing(self.connect()) as db:
            self.assertEqual({r[0] for r in db.execute('SELECT m.game_id FROM analysis_coverage a JOIN moves m ON m.move_id=a.move_id')},{1})
        with self.assertRaises(ValueError):service.preview(GameAnalysisScope(AnalysisScopeKind.SELECTED,(99,)))

    def test_cancel_rolls_back_unfinished_tactical_stage_and_resumes(self):
        self.import_fixture();service=self.service();cancel=threading.Event()
        def progress(event):
            if event.checks_processed==1:cancel.set()
        stopped=service.run(progress=progress,cancel=cancel)
        self.assertTrue(stopped.cancelled);self.assertEqual(self.count('analysis_coverage'),0)
        self.assertEqual(service.preview().queued[0].pending_checks,2)
        resumed=service.run()
        self.assertEqual((resumed.checks_processed,resumed.games_completed,resumed.errors),(2,1,0))
        self.assertEqual(self.count('analysis_coverage'),2);self.assert_integrity()

    def test_candidate_without_coverage_is_protected_not_completed(self):
        self.import_fixture(imports.pgn(moves='1. e4 1-0'))
        service=self.service(candidate_definition());self.assertEqual(service.run().candidates_created,1)
        with closing(self.connect()) as db:
            db.execute('DELETE FROM analysis_coverage');db.commit()
        before=self.digest();snapshot=service.preview()
        self.assertEqual((snapshot.protected_checks,snapshot.complete_games),(1,0))
        self.assertEqual(service.run().checks_processed,0);self.assertEqual(before,self.digest())

    def test_current_heavy_with_scout_zero_and_stale_candidate_protection(self):
        self.import_fixture(imports.pgn(moves='1. e4 1-0'));service=self.service(candidate_definition())
        self.assertEqual(service.run().candidates_created,1)
        with closing(self.connect()) as db:
            db.execute("UPDATE analysis_coverage SET scout_version='0'");db.commit()
        self.assertEqual(service.preview().complete_games,1)
        with closing(self.connect()) as db:
            db.execute("UPDATE analysis_coverage SET analyzer_version='old'");db.commit()
        before=self.digest();self.assertEqual(service.run().protected_checks,1)
        self.assertEqual(before,self.digest())

    def test_atomic_candidate_and_coverage_failure(self):
        self.import_fixture(imports.pgn(moves='1. e4 1-0'))
        with closing(self.connect()) as db:
            db.execute("CREATE TRIGGER fixture_failure BEFORE INSERT ON analysis_coverage BEGIN SELECT RAISE(ABORT,'fixture write failure'); END");db.commit()
        result=self.service(candidate_definition()).run()
        self.assertEqual(result.errors,1)
        self.assertEqual((self.count('tactic_candidates'),self.count('analysis_coverage')),(0,0))
        self.assertIn('fixture write failure',result.details[0])

    def test_analyzer_error_retry_and_other_game_continues(self):
        self.import_fixture(imports.pgn(identity='1',moves='1. e4 1-0')+imports.pgn(identity='2',moves='1. e4 1-0'))
        original=candidate_definition()
        heavy=lambda row,positions: (_ for _ in ()).throw(ValueError('fixture bad game')) if row['game_id']==1 else original.heavy(row,positions)
        result=self.service(replace(original,heavy=heavy)).run()
        self.assertEqual((result.errors,result.candidates_created),(1,1))
        self.assertEqual(self.service(original).run().candidates_created,1)
        self.assertEqual(self.count('tactic_candidates'),2);self.assert_integrity()

    def test_malformed_data_remains_retryable(self):
        self.import_fixture(imports.pgn(moves='1. e4 1-0'))
        with closing(self.connect()) as db:
            db.execute("UPDATE moves SET fen_before='invalid'");db.commit()
        result=self.service().run()
        self.assertEqual((result.errors,result.games_invalid),(0,1))
        self.assertEqual(self.count('analysis_coverage'),0)
        self.assertEqual(len(self.service().preview().queued),0)

    def test_preflight_defer_is_not_completed_coverage(self):
        from analysis_preflight import PreflightResult
        definition=replace(candidate_definition(),preflight_existing_evidence=lambda row,context: PreflightResult('mate_deferred','fixture',{}))
        self.import_fixture(imports.pgn(moves='1. e4 1-0'))
        service=self.service(definition);result=service.run()
        self.assertEqual((result.deferred,result.games_completed,result.games_remaining),(1,0,1))
        self.assertEqual(self.count('analysis_coverage'),0)
        rerun=service.run();self.assertEqual((rerun.engine_searches,rerun.database_changes),(0,0))

    def test_missing_engine_is_clear_and_stops_without_false_completion(self):
        self.import_fixture()
        service=GameAnalysisService(self.path,definitions=[ANALYZERS['missed_mate']],engine_root=self.path.parent,evaluation_settings=None,quality_settings=None)
        with patch('chess.engine.SimpleEngine.popen_uci', side_effect=FileNotFoundError('Synthetic missing engine')):
            result=service.run()
        self.assertEqual(result.errors,1);self.assertIn('FileNotFoundError',result.details[0])
        self.assertGreater(result.games_remaining,0);self.assert_integrity()

    def test_duplicate_run_lock_and_cancel_before_start(self):
        self.import_fixture();service=self.service()
        with exclusive_analysis_activity(self.path):self.assertEqual(service.run().errors,1)
        cancel=threading.Event();cancel.set();result=service.run(cancel=cancel)
        self.assertTrue(result.cancelled);self.assertEqual(result.database_changes,0)

    def test_central_crawler_entry_is_reused(self):
        from analysis_crawler import iter_analysis_checks
        self.import_fixture()
        with patch('game_analysis_service.iter_analysis_checks',wraps=iter_analysis_checks) as runner:
            self.assertEqual(self.service().run().games_completed,1)
        self.assertEqual(runner.call_count,1)

    def test_mate_episode_projection_is_retryable_without_engine(self):
        from analysis_presentation import refresh_mate_episodes
        self.import_fixture(position_pgn(MATE_FEN,'h3'))
        definition=replace(ANALYZERS['missed_mate'],scout=lambda row,e:ScoutResult(True,'fixture'),
            heavy=lambda row,p:HeavyResult('candidate',{'candidate_status':'confirmed','confidence':1,
                'detector_version':'3','solution_move_uci':'d1d8','solution_move_san':'Rd8#',
                'solution_line':'Rd8#','notes':'fixture','metadata_json':None}))
        service=self.service(definition)
        with patch('game_analysis_service.refresh_mate_episodes',side_effect=ValueError('fixture presentation interruption')):
            first=service.run()
        self.assertEqual((first.candidates_created,first.errors),(1,1))
        self.assertTrue(service.preview().queued[0].presentation_pending)
        repaired=service.run()
        self.assertEqual((repaired.checks_processed,repaired.engine_searches,repaired.games_completed),(0,0,1))
        before=self.digest();self.assertEqual(service.run().database_changes,0)
        self.assertEqual(before,self.digest())
        with closing(self.connect()) as db:
            self.assertEqual(len(TacticQuery(db).candidates()),1)
        self.assertEqual(self.count('tactic_occurrences'),0);self.assert_integrity()

    def test_stockfish_startup_failure_stops_once_and_is_retryable(self):
        self.import_fixture()
        with patch.object(chess.engine.SimpleEngine,'popen_uci',side_effect=chess.engine.EngineTerminatedError('fixture startup failure')) as startup:
            result=GameAnalysisService(self.path,definitions=[ANALYZERS['missed_mate']],evaluation_settings=None,quality_settings=None).run()
        self.assertEqual((result.errors,startup.call_count),(1,1))
        self.assertIn('startup failure',result.details[0])
        self.assertEqual(self.count('analysis_coverage'),0)
        self.assertEqual(result.fatal_errors,1)

    def test_core_is_ui_independent_and_engine_root_is_application_not_database(self):
        import ast
        for name in ('game_analysis_service','game_analysis_repository','game_analysis_models','analysis_presentation'):
            tree=ast.parse((ROOT/(name+'.py')).read_text(encoding='utf-8-sig'))
            modules=[a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
            modules += [n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            self.assertFalse(any(m.startswith(('tkinter','merlin_ui')) for m in modules))
        with patch('game_analysis_service.application_root',return_value=Path('bundle/_internal')):
            self.assertEqual(GameAnalysisService(self.path).engine_root,Path('bundle/_internal'))


class AnalysisUITests(TemporaryAnalysis):
    def setUp(self):
        super().setUp();self.root=tk.Tk();self.addCleanup(self.root.destroy)

    def pump(self,predicate,seconds=10):
        until=time.monotonic()+seconds
        while not predicate() and time.monotonic()<until:self.root.update();time.sleep(.01)
        self.assertTrue(predicate())

    def test_dialog_pending_start_stop_status_and_no_duplicate_start(self):
        self.import_fixture()
        entered=threading.Event();release=threading.Event()
        def screen(row):
            entered.set();release.wait(5);return False
        service=self.service(replace(negative_definition(),screener=screen))
        dialog=AnalyzeGamesDialog(self.root,self.path,service=service)
        self.pump(lambda:not dialog.loading)
        self.assertIn('Games needing analysis: 1',dialog.pending.get())
        dialog.start();dialog.start()
        try:
            self.assertTrue(entered.wait(2))
            tick=[];self.root.after(1,lambda:tick.append(True));self.pump(lambda:bool(tick))
            self.assertEqual(str(dialog.start_button.cget('state')),'disabled')
            self.assertEqual(str(dialog.stop_button.cget('state')),'normal')
            dialog.stop();self.assertTrue(dialog.cancel.is_set());self.assertTrue(self.root.winfo_exists())
        finally:release.set()
        self.pump(lambda:not dialog.busy and not dialog.loading)
        self.assertIn('stopped',dialog.status.get())
        self.assertEqual(self.count('analysis_coverage'),0)
        dialog.start();self.pump(lambda:not dialog.busy and not dialog.loading)
        self.assertEqual(self.count('analysis_coverage'),2)
        self.assertIn('Analysis complete',dialog.status.get())

    def test_review_entry_and_fresh_tactical_moments(self):
        self.import_fixture(imports.pgn(moves='1. e4 1-0'))
        view=GameReviewView(self.root,self.path,review_sets=(ALL_GAMES,))
        self.addCleanup(view.connection.close)
        with patch('merlin_ui.analyze_games_dialog.GameAnalysisService',return_value=self.service(candidate_definition())):
            menu=self.root.nametowidget(self.root.cget("menu"))
            tools=self.root.nametowidget(menu.entrycget("Tools","menu"))
            tools.invoke("Analyze Games...");self.root.update();dialog=view.analysis_dialog
            self.pump(lambda:not dialog.loading)
            view.open_analyze_games();self.assertIs(dialog,view.analysis_dialog)
            self.assertEqual(dialog.selected_game_ids,(1,))
            dialog.start();self.pump(lambda:not dialog.busy and not dialog.loading)
        self.assertEqual(len(view.moments),1)
        self.assertEqual(self.count('training_attempts'),0)


@unittest.skipUnless(os.environ.get('CHESSWIZARD_TEST_REAL_ANALYSIS')=='1','Explicit tiny real-engine acceptance only')
class RealAnalysisAcceptance(TemporaryAnalysis):
    def test_import_analyze_review_and_identical_rerun(self):
        self.import_fixture(position_pgn(MATE_FEN,'h3','mate')+position_pgn(FORK_FEN,'Kf1','fork','2026.09.13'))
        service=GameAnalysisService(self.path)
        events=[];result=service.run(progress=events.append)
        self.assertEqual(result.errors,0,result.details)
        self.assertGreater(result.engine_searches,0)
        self.assertGreater(result.candidates_created,0)
        self.assertGreater(self.count('analysis_coverage'),0)
        self.assertGreater(self.count('engine_position_cache'),0)
        self.assertEqual(self.count('tactic_occurrences'),0)
        with closing(self.connect()) as db:
            visible=TacticQuery(db).candidates()
            self.assertTrue(visible)
            ids=[r[0] for r in db.execute('SELECT candidate_id FROM tactic_candidates')]
        before=self.digest();second=service.run()
        self.assertEqual((second.errors,second.candidates_created,second.database_changes,second.engine_searches),(0,0,0,0),second)
        self.assertEqual(before,self.digest())
        with closing(self.connect()) as db:
            self.assertEqual(ids,[r[0] for r in db.execute('SELECT candidate_id FROM tactic_candidates')])
        self.assert_integrity()
        root=tk.Tk()
        view=GameReviewView(root,self.path,review_sets=(ALL_GAMES,))
        callback_errors=[]
        root.report_callback_exception=lambda *error: callback_errors.append(str(error[1]))
        try:
            root.update()
            self.assertEqual([g['source_game_id'] for g in view.games],['mate','fork'])
            for index in range(2):
                view.show_game(index);root.update()
                self.assertEqual(len(view.moments),1)
                view.jump_to_tactic(view.moments[0])
                self.assertEqual(view.get_board_for_current_step().fen(),view.moves[0]['fen_before'])
            self.assertEqual(callback_errors,[])
        finally:
            view.close()
        self.assertEqual(before,self.digest())
        from dataclasses import asdict
        receipt=os.environ.get('CHESSWIZARD_ANALYSIS_TEST_RECEIPT')
        if receipt:
            Path(receipt).write_text(json.dumps({'first':asdict(result),'rerun':asdict(second),'visible_candidates':visible,'events':len(events),'database_unchanged_after_rerun':True},indent=2),encoding='utf-8')
