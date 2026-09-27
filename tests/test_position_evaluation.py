"""Position semantics, exact reuse, cancellation and real Tk navigation on isolated data."""
from contextlib import closing
from dataclasses import replace
import ast
import json
from pathlib import Path
import threading
import tkinter as tk
import unittest
from unittest.mock import patch
import chess
from analysis_settings import GeneratorSettings, EngineSettings
from candidate_lines import CandidateLine, CandidateLineSet, LineScore
from candidate_line_repository import CandidateLineRepository
from candidate_line_request import request_identity
from candidate_line_service import CandidateLineService
from position_evaluation import (GamePosition,PositionEvaluation,EvaluationSettings,actual_positions,evaluation_from_lines)
from evaluation_service import GameEvaluationService
from evaluation_repository import EvaluationRepository
from game_analysis_service import GameAnalysisService
from game_analysis_models import GameAnalysisScope,AnalysisScopeKind
from merlin_ui.evaluation_widgets import EvaluationBar
from merlin_ui.game_review_view import GameReviewView
from tests.test_game_analysis import TemporaryAnalysis

class RecordedGenerator:
    def __init__(self): self.calls=0
    def generate(self,fen,settings):
        self.calls+=1
        b=chess.Board(fen);key=request_identity(settings)
        if b.is_game_over():
            return CandidateLineSet(fen,'white' if b.turn else 'black',1,settings.engine.profile_id,key,(),{'complete':True,'terminal':True})
        move=next(iter(b.legal_moves))
        line=CandidateLine(1,move.uci(),LineScore(score_cp=35),(move.uci(),),10,key,nodes=100)
        return CandidateLineSet(fen,'white' if b.turn else 'black',1,settings.engine.profile_id,key,(line,),{'complete':True,'root_moves':[]})

class EvaluationModelTests(unittest.TestCase):
    def value(self,score):
        return PositionEvaluation(GamePosition(1,None,0,chess.STARTING_FEN,'Start'),score,complete=score is not None)

    def test_white_black_zero_unknown_are_distinct(self):
        for cp,label in [(100,'+1.00'),(-142,'-1.42'),(0,'+0.00')]:
            value=self.value(LineScore(score_cp=cp))
            self.assertEqual(value.label(),label)
            self.assertEqual(value.label('black'),f'{-cp/100:+.2f}')
        value=self.value(None)
        self.assertEqual(value.label(),'—');self.assertIsNone(value.white_fraction())
        self.assertEqual(value.evaluation_type,'unknown')

    def test_mate_sign_and_zero_owner(self):
        for score,label,fraction in [(LineScore(mate_score=3),'M3',1),(LineScore(mate_score=-4),'-M4',0),(LineScore(mate_score=0,mate_winner='black'),'-M0',0)]:
            value=self.value(score)
            self.assertEqual(value.label(),label);self.assertEqual(value.white_fraction(),fraction)
            self.assertIsNone(value.score.score_cp)

    def test_bar_clamp_preserves_numeric_score(self):
        for cp,fraction in [(0,.5),(400,.75),(-400,.25),(2400,1),(-3000,0)]:
            self.assertEqual(self.value(LineScore(score_cp=cp)).white_fraction(),fraction)
        self.assertEqual(self.value(LineScore(score_cp=2400)).label(),'+24.00')

    def test_canonical_pov_and_completeness_enforced(self):
        with self.assertRaises(ValueError):self.value(LineScore(score_cp=42,score_pov='black'))
        with self.assertRaises(ValueError):PositionEvaluation(GamePosition(1,None,0,chess.STARTING_FEN,'Start'),complete=True)

    def test_identity_mismatch_cannot_stitch_profiles(self):
        point=GamePosition(1,None,0,chess.STARTING_FEN,'Start')
        settings=EvaluationSettings();lines=RecordedGenerator().generate(point.fen,settings.generator)
        other=replace(settings,generator=replace(settings.generator,engine=replace(settings.generator.engine,depth=12)))
        with self.assertRaises(ValueError):evaluation_from_lines(point,lines,other)
        restricted=replace(lines,generation_metadata={'complete':True,'root_moves':['e2e4']})
        with self.assertRaises(ValueError):evaluation_from_lines(point,restricted,settings)

    def test_terminal_draw_and_checkmate_without_cp_sentinel(self):
        settings=EvaluationSettings();gen=RecordedGenerator()
        for fen,kind,label in [('7k/6Q1/6K1/8/8/8/8/8 b - - 0 1','mate','M0'),('7k/5Q2/6K1/8/8/8/8/8 b - - 0 1','cp','+0.00')]:
            point=GamePosition(1,None,0,fen,'End')
            value=evaluation_from_lines(point,gen.generate(fen,settings.generator),settings)
            self.assertEqual((value.evaluation_type,value.label()),(kind,label))

    def test_core_has_no_ui_dependencies(self):
        for name in ('position_evaluation','evaluation_repository','evaluation_service'):
            tree=ast.parse(Path(name+'.py').read_text(encoding='utf-8-sig'))
            modules=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            modules += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
            self.assertFalse(any(m.startswith(('tkinter','merlin_ui')) for m in modules))

class EvaluationStageTests(TemporaryAnalysis):
    def stage(self,db,generator):
        service=CandidateLineService(generator,write_store=CandidateLineRepository(db))
        return GameEvaluationService(db,None,line_service=service)

    def test_all_plies_exact_reuse_cancel_resume_and_no_duplicates(self):
        self.import_fixture();cancel=threading.Event();gen=RecordedGenerator()
        with closing(self.connect()) as db:
            repo=EvaluationRepository(db);positions=repo.positions(1)
            self.assertEqual(len(positions),5)
            events=self.stage(db,gen).run(1,cancel)
            first=next(events);cancel.set();self.assertEqual(list(events),[])
            self.assertEqual(repo.readiness(1),(5,4))
            cancel.clear();second=list(self.stage(db,gen).run(1,cancel))
            self.assertEqual(sum(e['cache_hits'] for e in second),1)
            self.assertEqual(gen.calls,5)
            self.assertEqual(repo.readiness(1),(5,0))
            before=self.digest();changes=db.total_changes
            third=list(self.stage(db,gen).run(1,cancel))
            self.assertEqual(sum(e['cache_hits'] for e in third),5)
            self.assertEqual(sum(e['engine_searches'] for e in third),0)
            self.assertEqual(db.total_changes,changes);self.assertEqual(self.digest(),before)
            self.assertEqual(db.execute('select count(*) from engine_candidate_line_cache').fetchone()[0],5)
            self.assertEqual(db.execute('select count(*) from analysis_coverage').fetchone()[0],0)

    def test_incomplete_evidence_never_persists(self):
        self.import_fixture()
        gen=RecordedGenerator();original=gen.generate
        gen.generate=lambda fen,settings:replace(original(fen,settings),generation_metadata={'complete':False})
        with closing(self.connect()) as db:
            with self.assertRaises(ValueError):list(self.stage(db,gen).run(1,threading.Event()))
            self.assertEqual(db.execute('select count(*) from engine_candidate_line_cache').fetchone()[0],0)

    def test_legal_replay_rejects_corruption_before_search(self):
        self.import_fixture();gen=RecordedGenerator()
        with closing(self.connect()) as db:
            db.execute("update moves set fen_after=? where move_id=1",(chess.STARTING_FEN,));db.commit()
            with self.assertRaises(ValueError):list(self.stage(db,gen).run(1,threading.Event()))
            self.assertEqual(gen.calls,0)

    def test_default_stage_queue_scope_and_completed_no_engine(self):
        self.import_fixture();gen=RecordedGenerator()
        service=GameAnalysisService(self.path,definitions=(),quality_settings=None)
        self.assertEqual(service.preview().queued[0].evaluation_pending,5)
        with patch('evaluation_service.CandidateLineGenerator',return_value=gen):
            events=[];first=service.run(progress=events.append)
        self.assertEqual((first.errors,first.positions_evaluated,first.evaluation_inserts),(0,5,5),first.details)
        self.assertEqual(first.games_completed,1)
        self.assertEqual(max(e.evaluation_completed for e in events),5)
        before=self.digest()
        with patch('chess.engine.SimpleEngine.popen_uci',side_effect=AssertionError('Engine on completed rerun')):
            second=service.run()
        self.assertEqual((second.engine_searches,second.database_changes),(0,0))
        self.assertEqual(before,self.digest())

    def test_invalid_cached_point_leaves_other_points_visible(self):
        self.import_fixture();gen=RecordedGenerator()
        with closing(self.connect()) as db:
            list(self.stage(db,gen).run(1,threading.Event()))
            db.execute("update engine_candidate_line_cache set payload_json='{}' where line_set_id=2")
            db.commit()
            values=EvaluationRepository(db).timeline(1)
            self.assertEqual(sum(v.complete for v in values),4)
            self.assertEqual(values[1].provenance,'invalid_cached_evidence')

    def test_raw_request_identity_ignores_display_clamp(self):
        settings=EvaluationSettings()
        self.assertEqual(request_identity(settings.generator),request_identity(replace(settings,display_limit_cp=1000).generator))

class EvaluationUITests(TemporaryAnalysis):
    def test_navigation_and_missing_point_no_engine(self):
        self.import_fixture()
        with closing(self.connect()) as db:
            repo=EvaluationRepository(db);pos=repo.positions(1)
            cache=CandidateLineRepository(db);gen=RecordedGenerator()
            for p in pos[:-1]:cache.put(gen.generate(p.fen,EvaluationSettings().generator))
            db.commit()
        before=self.digest();root=tk.Tk();root.withdraw()
        self.addCleanup(root.destroy)
        with patch('chess.engine.SimpleEngine.popen_uci',side_effect=AssertionError('Navigation started engine')):
            view=GameReviewView(root,self.path);self.addCleanup(view.connection.close)
            root.update_idletasks()
            self.assertEqual(len(view.evaluation_values),5)
            for step in range(5):
                view._set_step(step)
                self.assertEqual(view.eval_timeline.selected_step,step)
                self.assertEqual(view.board_widget.board.fen(),pos[step].fen)
                self.assertEqual(view.eval_bar.value.position.step,step)
            self.assertIsNone(view.eval_bar.value.score)
            view.previous_move();self.assertEqual(view.eval_timeline.selected_step,3)
            view.next_move();self.assertEqual(view.eval_timeline.selected_step,4)
            event=type('Event',(),{'x':view.eval_timeline.x_for_step(2)})()
            view.eval_timeline.click(event);self.assertEqual(view.current_step,2)
            view.actual_moves.on_jump(1);self.assertEqual(view.current_step,1)
            view.current_game['user_color']='black';view.refresh_info()
            self.assertIn('Evaluation: +0.35 White',view.position_info.get('1.0','end'))
            self.assertNotIn('for you',view.position_info.get('1.0','end'))
            self.assertEqual(view.eval_timeline.selected_step,1)
        self.assertEqual(before,self.digest())

    def test_merlin_line_never_advances_actual_timeline(self):
        from tests.test_game_analysis import candidate_definition
        self.import_fixture();self.service(candidate_definition()).run()
        root=tk.Tk();root.withdraw();self.addCleanup(root.destroy)
        view=GameReviewView(root,self.path);self.addCleanup(view.connection.close)
        panel=view.tactics_panel;panel.listbox.selection_set(0);panel._select()
        actual=view.current_step
        view.set_line_visible(True);view.next_move()
        self.assertTrue(view.eval_bar.proof_mode)
        self.assertEqual(view.eval_timeline.selected_step,actual)
        self.assertTrue(view.eval_timeline.proof_mode)
        view.set_line_visible(False);self.assertFalse(view.eval_bar.proof_mode)

    def test_bar_renders_unknown_cp_and_mate(self):
        root=tk.Tk();self.addCleanup(root.destroy)
        widget=EvaluationBar(root);widget.pack();root.update_idletasks()
        point=GamePosition(1,None,0,chess.STARTING_FEN,'Start')
        for score in (None,LineScore(score_cp=0),LineScore(score_cp=9999),LineScore(mate_score=-3)):
            value=PositionEvaluation(point,score,complete=score is not None)
            widget.show(value)
            texts=[widget.itemcget(item,'text') for item in widget.find_all() if widget.type(item)=='text']
            self.assertIn(value.label() if value.complete else "Not analyzed",texts)

    def test_layout_preserves_board_moves_and_position_at_supported_sizes(self):
        self.import_fixture()
        root=tk.Tk();self.addCleanup(root.destroy)
        view=GameReviewView(root,self.path);self.addCleanup(view.connection.close)
        for geometry in ('1120x760','900x650'):
            root.geometry(geometry);root.update()
            self.assertGreater(view.board_widget.winfo_height(),250)
            self.assertGreaterEqual(view.eval_bar.winfo_x(),view.board_widget.winfo_x()+view.board_widget.winfo_width())
            self.assertGreater(view.actual_moves.winfo_height(),50)
            self.assertGreater(view.eval_timeline.winfo_height(),80)
            self.assertIn('Evaluation: Not analyzed',view.position_info.get('1.0','4.0'))
