"""Numeric truth, evidence identity, stage safety and frontend independence."""
from contextlib import closing
from dataclasses import replace
import ast
import math
from pathlib import Path
import threading
import tkinter as tk
import unittest
from unittest.mock import patch
import chess
from analysis_settings import EngineSettings, GeneratorSettings
from board_analysis.phase import GamePhase, game_phase
from candidate_lines import CandidateLine, CandidateLineSet, LineScore
from candidate_line_request import request_identity
from candidate_line_repository import CandidateLineRepository
from candidate_line_service import CandidateLineService
from move_quality import (QualityMove, MoveQuality, GameQuality, aggregate, cp_accuracy,
                          mover_loss, assess_move, compatible_lines)
from move_quality_settings import MoveQualitySettings
from move_quality_repository import MoveQualityRepository
from move_quality_service import GameMoveQualityService
from move_quality_presentation import game_summary, game_details, move_details
from game_analysis_models import AnalysisScopeKind, GameAnalysisScope
from game_analysis_service import GameAnalysisService
from merlin_ui.game_review_view import GameReviewView
from tests.test_game_analysis import TemporaryAnalysis, candidate_definition
from tests.test_game_import import pgn


class QualityGenerator:
    def __init__(self):
        self.calls = 0
        self.after_generate = lambda: None

    def generate(self, fen, settings, *, root_moves=()):
        self.calls += 1
        board = chess.Board(fen)
        identity = request_identity(settings, root_moves)
        legal = list(board.legal_moves)
        moves = [board.parse_uci(uci) for uci in root_moves] if root_moves else legal
        lines = tuple(CandidateLine(i, move.uci(), LineScore(score_cp=(30 if board.turn else -30)),
                                    (move.uci(),), settings.engine.depth, identity)
                      for i, move in enumerate(moves[:settings.candidate_line_count], 1))
        result = CandidateLineSet(fen, 'white' if board.turn else 'black', settings.candidate_line_count,
                                  settings.engine.profile_id, identity, lines,
                                  {'complete':True, 'root_moves':list(root_moves)})
        self.after_generate()
        return result


def root_move():
    return QualityMove(1, 1, 1, chess.STARTING_FEN, 'white', 'e2e4', 'e4')


class QualityModelTests(unittest.TestCase):
    def test_mover_relative_signs_and_zero(self):
        for color, before, after, loss in [('white',150,70,80),('black',-150,-70,80),
                ('white',-100,-200,100),('black',100,200,100),('white',0,0,0)]:
            value = mover_loss(LineScore(score_cp=before),LineScore(score_cp=after),color)
            self.assertEqual(value.eval_loss_cp,loss)
            self.assertEqual(value.accuracy,cp_accuracy(loss))

    def test_smooth_transform_bounds_and_monotonicity(self):
        samples = [cp_accuracy(n) for n in range(0,10001)]
        self.assertEqual(samples[0],100)
        self.assertEqual(samples[100],50)
        self.assertTrue(all(0 <= x <= 100 for x in samples))
        self.assertTrue(all(a>b for a,b in zip(samples,samples[1:])))
        self.assertGreater(cp_accuracy(10),99)
        self.assertLess(cp_accuracy(1000),1)
        self.assertIsNone(cp_accuracy(None))
        for invalid in (-1, float("nan"), float("inf"), 1.5, True):
            with self.assertRaises(ValueError):cp_accuracy(invalid)

    def test_unknown_and_contradictory_estimates_stay_unscored(self):
        self.assertIsNone(mover_loss(None,LineScore(score_cp=0),'white').accuracy)
        for side,a,b in [('white',0,1),('black',0,-1)]:
            result=mover_loss(LineScore(score_cp=a),LineScore(score_cp=b),side)
            self.assertEqual(result.state,'inconsistent_estimates')
            self.assertEqual(result.raw_difference_cp,-1)
            self.assertIsNone(result.eval_loss_cp);self.assertIsNone(result.accuracy)
        with self.assertRaises(ValueError):replace(root_move(),mover_color='black')

    def test_mate_transitions_never_fabricate_cp(self):
        cases=[(LineScore(mate_score=3),LineScore(mate_score=3),'mate_preserved',100),
               (LineScore(mate_score=3),LineScore(mate_score=5),'mate_preserved',96),
               (LineScore(mate_score=3),LineScore(mate_score=50),'mate_preserved',80),
               (LineScore(mate_score=3),LineScore(score_cp=900),'lost_forced_mate',40),
               (LineScore(score_cp=0),LineScore(mate_score=-4),'walked_into_mate',0),
               (LineScore(mate_score=3),LineScore(mate_score=-4),'walked_into_mate',0),
               (LineScore(mate_score=-5),LineScore(mate_score=-3),'forced_mate_retained',96),
               (LineScore(mate_score=-5),LineScore(score_cp=-100),'mate_escaped_unresolved',None),
               (LineScore(score_cp=100),LineScore(mate_score=3),'mate_found_unresolved',None)]
        for a,b,state,score in cases:
            for color,x,y in [('white',a,b),('black',a.pov('black'),b.pov('black'))]:
                # Flip absolute colors as well when mirroring the winning player.
                if color=='black':
                    x=LineScore(score_cp=-a.score_cp) if a.score_cp is not None else LineScore(mate_score=-a.mate_score)
                    y=LineScore(score_cp=-b.score_cp) if b.score_cp is not None else LineScore(mate_score=-b.mate_score)
                result=mover_loss(x,y,color)
                self.assertEqual((result.state,result.accuracy),(state,score))
                self.assertIsNone(result.eval_loss_cp)
        zero=LineScore(mate_score=0,mate_winner='white')
        self.assertEqual(mover_loss(LineScore(mate_score=1),zero,'white').accuracy,100)

    def test_profile_and_policy_identity_separation(self):
        settings=MoveQualitySettings()
        changed=replace(settings,half_accuracy_loss_cp=150)
        self.assertEqual(settings.raw_identity,changed.raw_identity)
        self.assertNotEqual(settings.currentness_identity,changed.currentness_identity)
        self.assertEqual(cp_accuracy(150,changed),50)
        for invalid in (0,-10):
            with self.assertRaises(ValueError):replace(settings,half_accuracy_loss_cp=invalid)

    def test_board_phase_uses_material_and_development(self):
        self.assertEqual(game_phase(chess.Board()),GamePhase.OPENING)
        developed=chess.Board('r2q1rk1/ppp2ppp/2npbn2/4p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 9')
        self.assertEqual(game_phase(developed),GamePhase.MIDDLEGAME)
        self.assertEqual(game_phase(chess.Board('4k3/8/8/8/8/8/PP6/R3K2r w Q - 0 8')),GamePhase.ENDGAME)
        late=chess.Board();late.fullmove_number=50
        self.assertEqual(game_phase(late),GamePhase.OPENING)

    def test_exact_best_and_restricted_played_evidence(self):
        move=root_move();settings=MoveQualitySettings();gen=QualityGenerator()
        root=gen.generate(move.fen,settings.generator)
        first=assess_move(move,root,settings=settings)
        self.assertFalse(first.evidence_complete)
        played=gen.generate(move.fen,settings.generator,root_moves=(move.played_move,))
        value=assess_move(move,root,played,settings)
        self.assertTrue(value.evidence_complete);self.assertEqual(value.accuracy,100)
        self.assertFalse(value.best_move_match);self.assertIsNone(value.top_n_match)
        best=replace(move,played_move=root.lines[0].move_uci,played_san=root.lines[0].move_san)
        self.assertTrue(assess_move(best,root,settings=settings).best_move_match)
        self.assertEqual(assess_move(best,root,settings=settings).eval_loss_cp,0)

    def test_incompatible_depth_profile_restriction_and_incomplete_rejected(self):
        move=root_move();settings=MoveQualitySettings();gen=QualityGenerator()
        for config in (replace(settings.generator,engine=EngineSettings(depth=10)),
                       replace(settings.generator,engine=EngineSettings(depth=16,profile_id='other'))):
            self.assertFalse(assess_move(move,gen.generate(move.fen,config),settings=settings).evidence_complete)
        restricted=gen.generate(move.fen,settings.generator,root_moves=(move.played_move,))
        self.assertFalse(compatible_lines(restricted,move.fen,settings))
        root=gen.generate(move.fen,settings.generator)
        self.assertFalse(compatible_lines(replace(root,generation_metadata={'complete':False}),move.fen,settings))
        shallow=replace(root,lines=(replace(root.lines[0],depth=10),))
        self.assertFalse(compatible_lines(shallow,move.fen,settings))

    def test_compatible_multipv_uses_supplied_played_line(self):
        settings=MoveQualitySettings(generator=GeneratorSettings(3,engine=EngineSettings(depth=16)))
        root=QualityGenerator().generate(chess.STARTING_FEN,settings.generator)
        move=replace(root_move(),played_move=root.lines[1].move_uci)
        result=assess_move(move,root,settings=settings)
        self.assertTrue(result.evidence_complete);self.assertTrue(result.top_n_match)
        self.assertFalse(result.best_move_match)

    def test_partial_aggregates_color_phase_denominators_and_unknown(self):
        a=MoveQuality(root_move(),GamePhase.OPENING,'centipawn',True,best_move_match=True,accuracy=100,eval_loss_cp=0)
        b=replace(a,move=QualityMove(1,2,2,'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1','black','e7e5','e5'),accuracy=50,eval_loss_cp=100,best_move_match=False,phase=GamePhase.MIDDLEGAME)
        unknown=replace(a,state='missing_best_evidence',evidence_complete=False,accuracy=None,eval_loss_cp=None,best_move_match=None)
        full=GameQuality((a,b),'black')
        self.assertEqual(full.overall.accuracy,75);self.assertTrue(full.overall.complete)
        self.assertEqual(full.user.accuracy,50);self.assertEqual(full.opponent.accuracy,100)
        self.assertEqual(full.for_phase(GamePhase.OPENING).accuracy,100)
        self.assertIsNone(full.for_phase(GamePhase.ENDGAME).accuracy)
        partial=GameQuality((a,b,unknown),'white')
        self.assertEqual(partial.overall.accuracy,75);self.assertFalse(partial.overall.complete)
        self.assertEqual(partial.overall.best_move_rate,50)
        self.assertIn('Partial · 2/3',game_summary(partial))
        self.assertEqual(partial.overall.average_loss_cp,50)
        self.assertEqual(partial.overall.median_loss_cp,50)
        self.assertIn('not analyzed',move_details(unknown))
        self.assertIsNone(aggregate(()).accuracy)
        self.assertIn('finite-score moves',game_details(partial))

    def test_core_imports_are_ui_independent(self):
        for filename in ('move_quality.py','move_quality_settings.py','move_quality_repository.py','move_quality_service.py','move_quality_presentation.py','board_analysis/phase.py'):
            tree=ast.parse(Path(filename).read_text(encoding='utf-8'))
            imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
            self.assertFalse(any(m.startswith(('tkinter','merlin_ui')) for m in imports))


class QualityStageTests(TemporaryAnalysis):
    def stage(self,db,gen):
        return GameMoveQualityService(db,None,line_service=CandidateLineService(gen,write_store=CandidateLineRepository(db)))

    def test_selected_stage_exact_reuse_and_no_other_table_changes(self):
        self.import_fixture(pgn(identity='1')+pgn(identity='2',moves='1. d4 d5 1-0'))
        gen=QualityGenerator();service=GameAnalysisService(self.path,definitions=(),evaluation_settings=None)
        scope=GameAnalysisScope(AnalysisScopeKind.SELECTED,(1,))
        self.assertEqual(service.preview(scope).queued[0].quality_pending,4)
        with patch('move_quality_service.CandidateLineGenerator',return_value=gen):
            first=service.run(scope)
        self.assertEqual(first.errors,0,first.details)
        self.assertEqual(first.quality_moves_processed,4)
        self.assertEqual(first.quality_searches,gen.calls)
        self.assertEqual(first.quality_inserts,gen.calls)
        self.assertFalse(service.preview(scope).queued)
        self.assertEqual(service.preview().queued[0].game_id,2)
        before=self.digest()
        with patch('chess.engine.SimpleEngine.popen_uci',side_effect=AssertionError('No rerun engine')):
            second=service.run(scope)
        self.assertEqual((second.database_changes,second.engine_searches),(0,0))
        self.assertEqual(before,self.digest())
        for table in ('tactic_candidates','analysis_coverage','training_attempts','engine_position_cache'):
            self.assertEqual(self.count(table),0)
        self.assert_integrity()

    def test_shared_game_reuse_policy_recompute_and_result_independence(self):
        self.import_fixture(pgn(identity='1')+pgn(identity='2'))
        with closing(self.connect()) as db:
            gen=QualityGenerator()
            list(self.stage(db,gen).run(1,threading.Event()))
            repository=MoveQualityRepository(db)
            self.assertEqual(repository.readiness_by_game({1,2}),{1:[4,0],2:[4,0]})
            first=repository.game(1,'white')
            db.execute("update games set result='0-1' where game_id=1");db.commit()
            self.assertEqual(first,repository.game(1,'white'))
            self.assertEqual(repository.game(1,'black').user,first.opponent)
            changed=MoveQualityRepository(db,replace(MoveQualitySettings(),half_accuracy_loss_cp=150))
            before=self.digest();calls=gen.calls
            self.assertEqual(changed.readiness_by_game({1}),{1:[4,0]})
            self.assertNotEqual(changed.game(1,'white').moves[0].result_identity,first.moves[0].result_identity)
            self.assertEqual(gen.calls,calls);self.assertEqual(self.digest(),before)

    def test_corrupt_cached_evidence_is_visible_as_missing(self):
        self.import_fixture()
        with closing(self.connect()) as db:
            list(self.stage(db,QualityGenerator()).run(1,threading.Event()))
            db.execute("update engine_candidate_line_cache set payload_json='{}' where line_set_id=1");db.commit()
            before=self.digest()
            value=MoveQualityRepository(db).game(1,'white').moves[0]
            self.assertFalse(value.evidence_complete);self.assertIsNone(value.accuracy)
            self.assertEqual(before,self.digest())

    def test_cancel_before_root_commit_rolls_back_and_resumes_cleanly(self):
        from analysis_control import AnalysisCancelled
        self.import_fixture();gen=QualityGenerator();cancel=threading.Event()
        gen.after_generate=cancel.set
        with closing(self.connect()) as db:
            with self.assertRaises(AnalysisCancelled):
                list(self.stage(db,gen).run(1,cancel))
            self.assertEqual(db.execute('select count(*) from engine_candidate_line_cache').fetchone()[0],0)
            cancel.clear();gen.after_generate=lambda:None
            events=list(self.stage(db,gen).run(1,cancel))
            self.assertEqual(sum(e['cache_hits'] for e in events),0)
            self.assertTrue(all(v.evidence_complete for v in MoveQualityRepository(db).game(1,'white').moves))

    def test_legal_replay_before_writes_and_invalid_cache_remains_unknown(self):
        self.import_fixture();gen=QualityGenerator()
        with closing(self.connect()) as db:
            db.execute("update moves set fen_after=? where move_id=1",(chess.STARTING_FEN,));db.commit()
            with self.assertRaises(ValueError):list(self.stage(db,gen).run(1,threading.Event()))
            self.assertEqual(gen.calls,0)

    def test_incomplete_generated_evidence_rolls_back(self):
        self.import_fixture();gen=QualityGenerator();original=gen.generate
        gen.generate=lambda *a,**kw:replace(original(*a,**kw),generation_metadata={'complete':False})
        with closing(self.connect()) as db:
            with self.assertRaises(ValueError):list(self.stage(db,gen).run(1,threading.Event()))
            self.assertEqual(db.execute('select count(*) from engine_candidate_line_cache').fetchone()[0],0)

    def test_ui_selection_summary_and_proof_separation_no_engine_or_writes(self):
        self.import_fixture(pgn(moves='1. e4 1-0'));self.service(candidate_definition()).run()
        with closing(self.connect()) as db:list(self.stage(db,QualityGenerator()).run(1,threading.Event()))
        before=self.digest();root=tk.Tk();self.addCleanup(root.destroy)
        with patch('chess.engine.SimpleEngine.popen_uci',side_effect=AssertionError('UI engine')):
            view=GameReviewView(root,self.path);self.addCleanup(view.connection.close);root.update()
            self.assertIn('1/1',view.accuracy_panel.summary.cget('text'))
            view.next_move();self.assertIn('Played: e4',view.position_info.get('1.0','end'))
            self.assertEqual(view.eval_timeline.selected_step,1)
            view.accuracy_panel.open_details();root.update()
            self.assertIn('Your opening',view.accuracy_panel.details_text.get('1.0','end'))
            panel=view.tactics_panel;panel.listbox.selection_set(0);panel._select()
            view.set_line_visible(True)
            self.assertIn('actual moves only',view.position_info.get('1.0','end'))
            view.set_line_visible(False);view.next_move()
            self.assertIn('Accuracy: 100.0',view.position_info.get('1.0','end'))
        self.assertEqual(before,self.digest())
