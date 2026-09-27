"""Temporary-profile robustness, conservative uncertainty and progressive batches."""
from contextlib import closing
from concurrent.futures import Future
from dataclasses import replace
import io
import sqlite3
import threading
import tkinter as tk
from unittest.mock import patch
import chess
import chess.engine
import chess.pgn
from analysis_settings import AnalysisBatchSettings, GeneratorSettings
from analysis_failures import classify_failure, FailureDisposition
from candidate_line_engine import CandidateLineGenerator
from evidence_errors import IncompleteLineEvidence, EngineIdentityMismatch
from game_analysis_models import AnalysisScopeKind, GameAnalysisScope, AnalysisProgress
from game_analysis_service import GameAnalysisService
from game_analysis_selection import select_analysis_games
from game_hygiene import inspect_registered_moves
from analysis_readiness import readiness_moves
from game_import_service import GameImportService
from merlin_ui.analyze_games_dialog import AnalyzeGamesDialog
from tests.test_game_analysis import TemporaryAnalysis, negative_definition, candidate_definition
from tests.test_game_import import pgn, HTTPFixture


class ExactEngine:
    def __init__(self, bounded_fen=None):
        self.id={'name':'Stockfish 18'}
        self.returncode=Future()
        self.bounded_fen=bounded_fen
        self.requests=[]
    def __enter__(self): return self
    def __exit__(self,*args): self.close()
    def configure(self, options): pass
    def close(self):
        if not self.returncode.done(): self.returncode.set_result(0)
    def analyse(self, board, limit, **kwargs):
        self.requests.append(board.fen())
        move=(kwargs.get('root_moves') or list(board.legal_moves))[0]
        return [{'pv':[move], 'score':chess.engine.PovScore(chess.engine.Cp(10),chess.WHITE),
                 'depth':limit.depth, 'nodes':1, 'upperbound':board.fen()==self.bounded_fen}]


class RobustnessTests(TemporaryAnalysis):
    def test_mixed_normal_empty_bounded_and_later_normal_resume(self):
        self.import_fixture(pgn(identity='1',moves='1. d4 1-0')+
            pgn(identity='2',moves='1. e4 e5 1-0')+pgn(identity='3',moves='1. f3 1-0')+
            pgn(identity='4',moves='1. c4 1-0'))
        with closing(self.connect()) as db:
            db.execute('DELETE FROM moves WHERE game_id=3');db.commit()
            early,bounded=[r[0] for r in db.execute('SELECT fen_after FROM moves WHERE game_id=2 ORDER BY ply_number')]
        engines=[]
        def start(*args,**kwargs):
            engine=ExactEngine(bounded);engines.append(engine);return engine
        service=GameAnalysisService(self.path,definitions=[negative_definition()],quality_settings=None)
        with patch.object(chess.engine.SimpleEngine,'popen_uci',side_effect=start):
            first=service.run();before=self.digest();second=service.run()
        self.assertEqual((first.games_completed,first.games_deferred,first.games_invalid,first.errors),(2,1,1,0))
        self.assertEqual((first.games_visited,first.games_remaining),(3,1))
        self.assertIn('Game 2, Position evaluation: deferred: IncompleteLineEvidence',first.details[-1])
        with closing(self.connect()) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM engine_candidate_line_cache WHERE fen IN (?,?)',(early,bounded)).fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM analysis_coverage a JOIN moves m USING(move_id) WHERE m.game_id=2').fetchone()[0],0)
        self.assertEqual((second.games_visited,second.games_deferred,second.database_changes),(1,1,0))
        self.assertEqual(second.games_skipped,2)
        self.assertEqual(before,self.digest())
        self.assert_integrity()

    def test_recoverable_mid_tactic_failure_rolls_back_and_continues(self):
        self.import_fixture(pgn(identity='1',moves='1. e4 1-0')+pgn(identity='2')+pgn(identity='3',moves='1. d4 1-0'))
        definition=candidate_definition()
        def heavy(row,positions):
            if row['game_id']==2 and row['ply_number']==3: raise ValueError('fixture malformed branch')
            return definition.heavy(row,positions)
        result=self.service(replace(definition,heavy=heavy)).run()
        self.assertEqual((result.games_completed,result.recoverable_errors,result.fatal_errors),(2,1,0))
        with closing(self.connect()) as db:
            self.assertEqual({r[0] for r in db.execute('SELECT m.game_id FROM tactic_candidates c JOIN moves m USING(move_id)')},{1,3})
            self.assertEqual({r[0] for r in db.execute('SELECT m.game_id FROM analysis_coverage c JOIN moves m USING(move_id)')},{1,3})
        self.assertEqual(result.games_visited,3)
        self.assert_integrity()

    def test_readiness_failure_isolated_from_other_games_in_same_batch(self):
        self.import_fixture(pgn(identity='1')+pgn(identity='2')+pgn(identity='3'))
        import game_analysis_repository as repo
        original=repo._iter_valid_readiness
        def readiness(db,defs,scope,*args,**kwargs):
            if 2 in scope.game_ids: raise ValueError('broken game-local readiness')
            yield from original(db,defs,scope,*args,**kwargs)
        with patch.object(repo,'_iter_valid_readiness',readiness):
            result=self.service().run()
        self.assertEqual((result.games_completed,result.games_visited,result.recoverable_errors),(2,3,1))
        self.assertEqual(result.fatal_errors,0)

    def test_fatal_database_failure_stops_later_games(self):
        self.import_fixture(pgn(identity='1')+pgn(identity='2'))
        with patch('game_analysis_service.refresh_mate_episodes',side_effect=sqlite3.DatabaseError('fixture corruption')):
            result=self.service().run()
        self.assertEqual((result.fatal_errors,result.recoverable_errors,result.games_visited),(1,0,1))
        with closing(self.connect()) as db:
            self.assertEqual({r[0] for r in db.execute('SELECT m.game_id FROM analysis_coverage a JOIN moves m USING(move_id)')},{2})
        self.assertGreater(result.games_remaining,0)

    def test_global_engine_identity_is_fatal_and_bounded_is_not(self):
        self.assertEqual(classify_failure(EngineIdentityMismatch('wrong engine')).disposition,FailureDisposition.FATAL)
        self.assertEqual(classify_failure(IncompleteLineEvidence('bound')).disposition,FailureDisposition.DEFERRED)
        self.assertEqual(classify_failure(AssertionError('invariant')).disposition,FailureDisposition.FATAL)

    def test_reported_3253_3514_bounds_preserve_uncertainty(self):
        cases=[('r1r3k1/1p2b1pp/p4n2/q2p1P2/8/4B3/2P1Q2P/1RK2R2 w - - 0 29','b1b7'),
               ('r6r/pbNN1kbp/4R1p1/P2p2Q1/3q3P/8/2P2PP1/5RK1 b - - 0 22','a8c8')]
        for fen,move in cases:
            with self.subTest(fen=fen):
                with self.assertRaisesRegex(IncompleteLineEvidence,'Bounded score'):
                    CandidateLineGenerator(ExactEngine(fen)).generate(fen,GeneratorSettings(1),root_moves=(move,))
        self.assertEqual(self.count('engine_candidate_line_cache'),0)

    def test_malformed_history_with_legal_move_is_recoverable_not_empty(self):
        self.import_fixture()
        with closing(self.connect()) as db:
            db.execute("UPDATE moves SET fen_after='bad' WHERE ply_number=2");db.commit()
            health=inspect_registered_moves(readiness_moves(db,(1,)))
        self.assertFalse(health.empty)
        result=self.service().run()
        self.assertEqual((result.recoverable_errors,result.games_invalid,result.database_changes),(1,0,0))


class ZeroMoveTests(TemporaryAnalysis):
    def test_both_providers_skip_empty_keep_short_and_dedupe(self):
        for source in ('chesscom','lichess'):
            text=pgn(source,identity='Empty001',moves='1-0')+pgn(source,identity='Short001',moves='1. e4 1-0')
            with patch('game_import_http.urlopen',HTTPFixture(text)):
                result=GameImportService(self.path).run(source,'Example_User')
            self.assertEqual((result.skipped_empty,result.added,result.errors),(1,1,0))
            self.assertIn('Skipped empty/zero-move games: 1',result.summary())
            with patch('game_import_http.urlopen',HTTPFixture(text)):
                repeat=GameImportService(self.path).run(source,'Example_User')
            self.assertEqual((repeat.skipped_empty,repeat.existing,repeat.errors),(1,1,0))
        self.assertEqual(self.count('games'),2);self.assertEqual(self.count('moves'),2)

    def test_zero_rows_excluded_selected_and_all_without_engine(self):
        self.import_fixture()
        with closing(self.connect()) as db:
            db.execute('DELETE FROM moves');db.commit()
            self.assertEqual(select_analysis_games(db,GameAnalysisScope()).empty_ids,(1,))
        service=self.service()
        with patch.object(chess.engine.SimpleEngine,'popen_uci',side_effect=AssertionError('No engine')):
            for scope in (GameAnalysisScope(),GameAnalysisScope(AnalysisScopeKind.SELECTED,(1,))):
                self.assertEqual(service.preview(scope).queued,())
                result=service.run(scope)
                self.assertEqual((result.games_queued,result.games_invalid,result.errors),(0,1,0))
                self.assertEqual(result.database_changes,0)

    def test_valid_opponent_only_short_game_is_not_empty(self):
        self.import_fixture(pgn(moves='1. e4 1-0'))
        with closing(self.connect()) as db:
            db.execute('UPDATE moves SET is_user_move=0');db.commit()
        snapshot=self.service().preview()
        self.assertEqual(snapshot.complete_games,1)
        self.assertEqual(snapshot.games[0].registered_moves,1)


class ProgressiveTests(TemporaryAnalysis):
    def setUp(self):
        super().setUp()
        self.import_fixture(''.join(pgn(identity=str(n),moves='1. e4 1-0') for n in range(1,106)))

    def test_first_50_start_before_later_readiness_and_partial_last_batch(self):
        from game_analysis_service import analysis_snapshot
        inspected=[];events=[]
        def snapshot(db,defs,scope,*args,**kwargs):
            if len(scope.game_ids)>1:
                inspected.append(scope.game_ids)
                if len(inspected)>1:
                    self.assertGreaterEqual(db.execute('SELECT count(*) FROM analysis_coverage').fetchone()[0],50)
            return analysis_snapshot(db,defs,scope,*args,**kwargs)
        with patch('game_analysis_service.analysis_snapshot',side_effect=snapshot):
            result=self.service().run(progress=events.append)
        self.assertEqual([len(ids) for ids in inspected],[50,50,5])
        self.assertEqual(tuple(gid for ids in inspected for gid in ids),tuple(range(105,0,-1)))
        self.assertEqual((result.games_completed,result.batches_completed,result.errors),(105,3,0))
        batches=[e for e in events if e.phase=='Batch completed']
        self.assertEqual([e.batch_completed for e in batches],[50,50,5])
        self.assertEqual(batches[-1].overall_completed,105)
        before=self.digest();repeat=self.service().run()
        self.assertEqual((repeat.database_changes,repeat.engine_searches,repeat.games_visited),(0,0,0))
        self.assertEqual(before,self.digest())

    def test_recent_scopes_and_partial_preview_do_not_expand(self):
        for kind,expected in ((AnalysisScopeKind.RECENT_50,50),(AnalysisScopeKind.RECENT_100,100)):
            with closing(self.connect()) as db:
                selected=select_analysis_games(db,GameAnalysisScope(kind))
            self.assertEqual(selected.game_ids,tuple(range(105,105-expected,-1)))
        snapshot=self.service().preview()
        self.assertEqual((len(snapshot.games),snapshot.eligible_games,snapshot.scope_complete),(50,105,False))
        result=self.service().run(GameAnalysisScope(AnalysisScopeKind.RECENT_50))
        self.assertEqual((result.games_completed,result.scope_total),(50,50))
        with closing(self.connect()) as db:
            self.assertEqual({r[0] for r in db.execute('SELECT m.game_id FROM analysis_coverage a JOIN moves m USING(move_id)')},set(range(56,106)))

    def test_stop_after_37_preserves_and_resumes(self):
        cancel=threading.Event()
        def progress(event):
            if event.checks_processed==38:cancel.set()
        result=self.service().run(cancel=cancel,progress=progress)
        self.assertTrue(result.cancelled)
        self.assertEqual((result.games_completed,self.count('analysis_coverage')),(37,37))
        self.assertFalse(result.queue_complete)
        resumed=self.service().run()
        self.assertEqual((resumed.games_completed,resumed.games_skipped,resumed.errors),(68,37,0))
        self.assertEqual(self.count('analysis_coverage'),105)

    def test_canonical_dates_then_id_and_config_identity(self):
        with closing(self.connect()) as db:
            db.execute('UPDATE games SET played_at=NULL')
            db.execute("UPDATE games SET played_at='2026.09.15' WHERE game_id=1")
            db.execute("UPDATE games SET played_at='2026-09-14T22:00:00Z' WHERE game_id=2")
            db.commit()
            self.assertEqual(select_analysis_games(db,GameAnalysisScope()).game_ids[:3],(1,2,105))
        setting=AnalysisBatchSettings().schema()[0]
        self.assertEqual(setting.default,50)
        self.assertFalse(setting.affects_cache_identity or setting.affects_analysis_currentness)
        with self.assertRaises(ValueError):AnalysisBatchSettings(0)

    def test_ui_defaults_recent_and_batch_notification_is_main_thread(self):
        root=tk.Tk();root.withdraw();self.addCleanup(root.destroy)
        batches=[]
        dialog=AnalyzeGamesDialog(root,self.path,service=self.service(),on_batch_complete=lambda:batches.append(threading.get_ident()))
        self.assertEqual(dialog.scope.get(),AnalysisScopeKind.RECENT_50.value)
        dialog._progress(AnalysisProgress('Saved',phase='Batch completed',batch_index=1,batch_count=3,
            batch_start=1,batch_end=50,scope_total=105,batch_completed=49,overall_completed=49,recoverable_errors=1))
        text=dialog.output.get('1.0','end')
        self.assertIn('Batch 1 of 3',text);self.assertIn('Recoverable errors: 1',text)
        self.assertEqual(batches,[threading.get_ident()])
        dialog._cancel_preview()

class BatchReviewTests(TemporaryAnalysis):
    def test_batch_refresh_preserves_current_actual_move_and_active_tactic(self):
        from merlin_ui.game_review_view import GameReviewView
        from game_review_sets import ALL_GAMES
        self.import_fixture()
        root=tk.Tk();root.withdraw()
        view=GameReviewView(root,self.path,review_sets=(ALL_GAMES,))
        try:
            view._set_step(3)
            view.analysis_batch_completed()
            self.assertEqual(view.current_step,3)
            marker=object();view.tactics_panel.selected=marker
            with patch.object(view,'load_games',side_effect=AssertionError('Do not disturb selected proof')):
                view.analysis_batch_completed()
            self.assertIs(view.tactics_panel.selected,marker)
            view.tactics_panel.selected=None
        finally:
            view.close()
