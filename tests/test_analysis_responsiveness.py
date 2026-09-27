"""Temporary-only contracts for responsiveness, stage rollback and crash recovery."""
from contextlib import ExitStack, closing
from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import tkinter as tk
from unittest.mock import patch

import chess.engine
from analysis_control import AnalysisCancelled, cancellable_reads
from analysis_engine import LazyScoutEngine
from candidate_line_repository import CandidateLineRepository
from data_activity import exclusive_analysis_activity, DataBusyError
from game_analysis_models import AnalysisScopeKind, GameAnalysisScope, AnalysisSnapshot, GameAnalysisResult
from game_analysis_service import GameAnalysisService
from merlin_ui.analyze_games_dialog import AnalyzeGamesDialog
from sqlite_transaction import SqliteTransaction
from tests.test_game_analysis import TemporaryAnalysis, candidate_definition, negative_definition, imports


class TransactionTests(TemporaryAnalysis):
    def test_nested_repository_commit_cannot_publish_cancelled_stage(self):
        self.import_fixture()
        cancel = threading.Event()
        with closing(self.connect()) as db:
            before = db.execute('SELECT count(*) FROM analysis_coverage').fetchone()[0]
            with self.assertRaises(AnalysisCancelled):
                with SqliteTransaction(db, cancel):
                    with SqliteTransaction(db):
                        db.execute("INSERT INTO analysis_coverage(move_id,analysis_type,coverage_status,screener_version,analyzer_version) VALUES(1,'fixture','error','0','0')")
                    cancel.set()
            self.assertEqual(db.execute('SELECT count(*) FROM analysis_coverage').fetchone()[0], before)
            self.assertFalse(db.in_transaction)
        self.assert_integrity()

    def test_completed_game_kept_cancelled_game_candidates_and_cache_rolled_back(self):
        self.import_fixture(imports.pgn(identity='1',day='2026.09.14',moves='1. e4 1-0')
                            + imports.pgn(identity='2',day='2026.09.13'))
        service = self.service(candidate_definition())
        cancel = threading.Event()
        def progress(event):
            if event.game_id == 2 and event.checks_processed == 2:
                cancel.set()
        result = service.run(cancel=cancel, progress=progress)
        self.assertTrue(result.cancelled)
        self.assertEqual((result.errors,result.games_completed,result.candidates_created),(0,1,1))
        with closing(self.connect()) as db:
            kept = [tuple(r) for r in db.execute('SELECT candidate_id,move_id FROM tactic_candidates')]
            self.assertEqual(len(kept),1)
            self.assertEqual(db.execute('SELECT count(*) FROM analysis_coverage').fetchone()[0],1)
        resumed=service.run()
        self.assertEqual((resumed.candidates_created,resumed.errors),(2,0))
        with closing(self.connect()) as db:
            self.assertEqual(tuple(db.execute('SELECT candidate_id,move_id FROM tactic_candidates ORDER BY candidate_id').fetchone()),kept[0])
        before=self.digest()
        self.assertEqual(service.run().database_changes,0)
        self.assertEqual(self.digest(),before)
        self.assert_integrity()

    def test_stop_while_commit_waits_for_reader_rolls_back(self):
        self.import_fixture()
        reader=self.connect()
        reader.execute('BEGIN')
        reader.execute('SELECT * FROM games').fetchall()
        cancel=threading.Event();entered=threading.Event();outcome=[]
        def write():
            db=sqlite3.connect(self.path,timeout=.05)
            try:
                with SqliteTransaction(db,cancel):
                    db.execute("UPDATE games SET result='*' WHERE game_id=1")
                    entered.set()
            except AnalysisCancelled:
                outcome.append('cancelled')
            finally:db.close()
        worker=threading.Thread(target=write);worker.start()
        try:
            self.assertTrue(entered.wait(1))
            cancel.set();worker.join(1)
            self.assertFalse(worker.is_alive())
        finally:
            reader.rollback();reader.close();worker.join(1)
        self.assertEqual(outcome,['cancelled'])
        with closing(self.connect()) as db:
            self.assertEqual(db.execute('SELECT result FROM games').fetchone()[0],'1-0')

    def test_sql_read_cancel_uses_control_flow_not_failed_evidence(self):
        self.import_fixture()
        cancel=threading.Event()
        with closing(self.connect()) as db:
            with self.assertRaises(AnalysisCancelled), cancellable_reads(db,cancel):
                cancel.set()
                db.execute('WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<100000) SELECT sum(x) FROM n').fetchone()
            self.assertEqual(db.execute('SELECT 1').fetchone()[0],1)


class BlockingEngine:
    def __init__(self):
        self.entered=threading.Event()
        self.closed=threading.Event()
        self.returncode=Future()
        self.id={'name':'Stockfish 18'}
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def configure(self,options):pass
    def analyse(self,*args,**kwargs):
        self.entered.set()
        if not self.closed.wait(4):
            raise AssertionError('Cancellation did not terminate engine')
        raise chess.engine.EngineTerminatedError('Cancelled test process')
    def close(self):
        self.closed.set()
        if not self.returncode.done():self.returncode.set_result(0)


class EngineStopTests(TemporaryAnalysis):
    def test_stop_during_engine_request_no_partial_rows_or_error_coverage(self):
        self.import_fixture()
        class OneCompleteThenBlock(BlockingEngine):
            calls = 0
            def analyse(self, board, limit, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    move = next(iter(board.legal_moves))
                    return [{'pv':[move], 'score':chess.engine.PovScore(chess.engine.Cp(0),chess.WHITE),
                             'depth':limit.depth, 'nodes':1}]
                return super().analyse(board, limit, **kwargs)
        engine=OneCompleteThenBlock()
        cancel=threading.Event()
        results=[]
        def work():
            results.append(GameAnalysisService(self.path).run(cancel=cancel))
        with patch.object(chess.engine.SimpleEngine,'popen_uci',return_value=engine):
            worker=threading.Thread(target=work);worker.start()
            self.assertTrue(engine.entered.wait(3))
            before=time.monotonic();cancel.set();worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertLess(time.monotonic()-before,1.0)
        result=results[0]
        self.assertTrue(result.cancelled)
        self.assertEqual((result.errors,result.database_changes,result.candidates_created),(0,0,0))
        self.assertTrue(engine.closed.is_set())
        for table in ('engine_candidate_line_cache','engine_position_cache','analysis_coverage','tactic_candidates'):
            self.assertEqual(self.count(table),0)
        self.assert_integrity()

    def test_completed_evaluation_stage_survives_quality_stop(self):
        self.import_fixture(imports.pgn(moves='1. e4 1-0'))
        cancel=threading.Event()
        from candidate_line_engine import CandidateLineGenerator
        from candidate_line_service import CandidateLineService
        from evaluation_service import GameEvaluationService
        class EvidenceEngine:
            def analyse(self,board,limit,**kwargs):
                move=next(iter(board.legal_moves))
                return [{'pv':[move],'score':chess.engine.PovScore(chess.engine.Cp(10),chess.WHITE),'depth':limit.depth,'nodes':1}]
        class LocalEvaluation(GameEvaluationService):
            def __init__(self,db,engine,settings):
                super().__init__(db,engine,settings,line_service=CandidateLineService(
                    CandidateLineGenerator(EvidenceEngine()),write_store=CandidateLineRepository(db)))
        def progress(event):
            if event.message=='Move quality':
                cancel.set()
        with patch('game_analysis_service.GameEvaluationService',LocalEvaluation):
            result=GameAnalysisService(self.path).run(cancel=cancel,progress=progress)
        self.assertTrue(result.cancelled);self.assertEqual(result.errors,0)
        self.assertEqual(self.count('engine_candidate_line_cache'),2)
        self.assertEqual(self.count('analysis_coverage'),0)
        snapshot=GameAnalysisService(self.path).preview()
        self.assertEqual(snapshot.games[0].evaluation_pending,0)
        self.assertEqual(snapshot.games[0].quality_pending,1)
        self.assert_integrity()


class OwnershipTests(TemporaryAnalysis):
    def test_same_database_busy_different_database_allowed_and_review_reads(self):
        self.import_fixture()
        with exclusive_analysis_activity(self.path):
            result=self.service().run()
            self.assertIn('Another ChessWizard analysis session',result.details[0])
            self.assertEqual(self.service().preview().queued[0].game_id,1)
            with exclusive_analysis_activity(self.path.parent/'different.db'):
                pass
        self.assertEqual(self.service().run().errors,0)

    def test_os_lock_crash_releases_without_deleting_stale_file(self):
        self.import_fixture()
        code="from data_activity import exclusive_analysis_activity; import sys,time\nwith exclusive_analysis_activity(sys.argv[1]):\n print('ready',flush=True)\n time.sleep(30)"
        child=subprocess.Popen([sys._base_executable,'-B','-c',code,str(self.path)],cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            self.assertEqual(child.stdout.readline().strip(),'ready')
            with self.assertRaises(DataBusyError),exclusive_analysis_activity(self.path):pass
            with closing(self.connect()) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM games').fetchone()[0],1)
            child.terminate();child.wait(timeout=5)
            self.assertTrue(Path(str(self.path)+'.analysis-lock').exists())
            with exclusive_analysis_activity(self.path):pass
        finally:
            if child.poll() is None:child.kill();child.wait(timeout=5)
            child.stdout.close();child.stderr.close()
        self.assert_integrity()


class ReadinessTests(TemporaryAnalysis):
    def test_selected_scope_does_not_decode_other_games_evidence(self):
        self.import_fixture(imports.pgn(identity='1',moves='1. e4 1-0')+
                            imports.pgn(identity='2',moves='1. d4 1-0'))
        seen=[]
        original=CandidateLineRepository.get_many
        def read(repo,requests,**kwargs):
            requests=tuple(requests);seen.extend(requests)
            return original(repo,requests,**kwargs)
        with patch.object(CandidateLineRepository,'get_many',read):
            snapshot=GameAnalysisService(self.path).preview(GameAnalysisScope(AnalysisScopeKind.SELECTED,(1,)))
        self.assertEqual(len(snapshot.games),1)
        with closing(self.connect()) as db:
            other=db.execute('SELECT fen_after FROM moves WHERE game_id=2').fetchone()[0]
        self.assertNotIn(other,{fen for fen,identity in seen})
        self.assertLessEqual(len(seen),3)

    def test_progress_and_early_incomplete_detection_no_engine_no_writes(self):
        self.import_fixture(imports.pgn(identity='1')+imports.pgn(identity='2'))
        service=self.service();events=[];before=self.digest()
        with patch.object(chess.engine.SimpleEngine,'popen_uci',side_effect=AssertionError('No engine')):
            service.preview(progress=events.append)
            self.assertTrue(service.has_incomplete_work())
        self.assertEqual([e.checked for e in events],[0,1,2])
        self.assertEqual(events[-1].percent,100)
        self.assertEqual(before,self.digest())


class ResponsivenessTests(TemporaryAnalysis):
    def setUp(self):
        super().setUp()
        self.root=tk.Tk();self.addCleanup(self.root.destroy)

    def pump(self,predicate,seconds=3):
        end=time.monotonic()+seconds
        while not predicate() and time.monotonic()<end:
            self.root.update();time.sleep(.005)
        self.assertTrue(predicate())

    def test_selected_game_starts_while_global_preview_pending_and_ignores_stale_result(self):
        self.import_fixture()
        entered=threading.Event();release=threading.Event();ran=threading.Event();scopes=[]
        base=self.service()
        class Service:
            profile=base.profile;quality_settings=None
            def preview(self,scope,**kwargs):
                if scope.kind!=AnalysisScopeKind.SELECTED:
                    entered.set();release.wait(3)
                return base.preview(scope,**kwargs)
            def run(self,scope,**kwargs):
                scopes.append(scope);ran.set()
                return base.run(scope,**kwargs)
        child=tk.Toplevel(self.root)
        start=time.monotonic()
        dialog=AnalyzeGamesDialog(child,self.path,service=Service(),selected_game_ids=(1,))
        self.root.update()
        self.assertLess(time.monotonic()-start,.75)
        self.assertTrue(entered.wait(1));self.assertTrue(dialog.loading)
        self.assertEqual(str(dialog.scope_picker.cget('state')),'readonly')
        old_generation=dialog.preview_generation
        dialog.scope.set(AnalysisScopeKind.SELECTED)
        dialog.refresh();dialog.start()
        try:
            self.assertTrue(ran.wait(1))
            self.assertEqual(scopes[0].game_ids,(1,))
            dialog.events.put(('snapshot',AnalysisSnapshot(()),old_generation))
            self.pump(lambda:not dialog.busy)
            self.assertIsNone(dialog.snapshot)
        finally:
            release.set();dialog.close()
        self.assertEqual(self.count('analysis_coverage'),2)

    def test_pending_review_layout_is_cancelled_when_window_closes(self):
        from merlin_ui.review_splitter import ReviewSplitter
        child=tk.Toplevel(self.root)
        split=ReviewSplitter(child,fraction=.4,on_resize=lambda fraction:None,background='white')
        split.pack()
        split.add_panels(tk.Frame(split),tk.Frame(split))
        pending=split._layout_pending
        self.assertIsNotNone(pending)
        child.destroy()
        self.assertNotIn(pending,self.root.tk.call('after','info'))
        self.root.update()

    def test_stop_exit_confirmation_and_automatic_continuation(self):
        self.import_fixture()
        entered=threading.Event();release=threading.Event()
        def screen(row):
            entered.set();release.wait(3);return False
        child=tk.Toplevel(self.root)
        dialog=AnalyzeGamesDialog(child,self.path,service=self.service(replace(negative_definition(),screener=screen)))
        dialog.start()
        self.assertTrue(entered.wait(2))
        finished=[]
        try:
            with patch('merlin_ui.analyze_games_dialog.choose_action',return_value='cancel'):
                self.assertFalse(dialog.request_close(lambda:finished.append(True)))
            self.assertFalse(dialog.cancel.is_set())
            with patch('merlin_ui.analyze_games_dialog.choose_action',return_value='stop'):
                self.assertFalse(dialog.request_close(lambda:finished.append(True)))
            self.assertTrue(dialog.cancel.is_set())
        finally:release.set()
        self.pump(lambda:bool(finished))
        self.assertEqual(self.count('analysis_coverage'),0)
        dialog.close()



class TrainingSmokeTests(TemporaryAnalysis):
    def test_start_puzzle_play_legal_solution_and_grade(self):
        self.import_fixture(imports.pgn(moves='1. e4 1-0'))
        self.assertEqual(self.service(candidate_definition()).run().candidates_created,1)
        from merlin_ui.candidate_viewer import CandidateViewer
        root=tk.Tk()
        viewer=CandidateViewer(root,self.path)
        try:
            root.update()
            with patch.object(chess.engine.SimpleEngine,'popen_uci',side_effect=AssertionError('Training cannot analyze')):
                viewer.practice_button.invoke()
                self.assertTrue(viewer.puzzle_mode_var.get())
                move=chess.Move.from_uci('d2d4')
                self.assertIn(move,viewer.build_board_at_step().legal_moves)
                viewer.on_move_attempt(move)
                end=time.monotonic()+3
                while viewer.get_current_attempt()['result']=='in_progress' and time.monotonic()<end:
                    root.update();time.sleep(.01)
                attempt=viewer.get_current_attempt()
                self.assertEqual(attempt['result'],'solved')
                self.assertEqual(attempt['wrong_move_attempts'],0)
                self.assertEqual(attempt['move_attempts'],1)
        finally:
            for callback in root.tk.call('after','info'):
                root.after_cancel(callback)
            viewer.close()
        with closing(self.connect()) as db:
            self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
