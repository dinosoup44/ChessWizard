"""Exact opening metrics with synthetic legal evidence; no engine or live writes."""
from tests.opening_ui_wait import wait_for_opening
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import ast
from unittest.mock import patch
import chess
import chess.engine
from candidate_lines import CandidateLine, CandidateLineSet, LineScore
from candidate_line_request import request_identity
from candidate_line_repository import CandidateLineRepository
from move_quality import assess_move, cp_accuracy
from move_quality_repository import MoveQualityRepository
from move_quality_settings import MoveQualitySettings
from opening_book_repository import OpeningBookRepository
from opening_book_service import OpeningBookService
from opening_book_session import OpeningBookSession
from opening_book_models import MoveDetails
from opening_library_service import OpeningLibraryService
from opening_intelligence_service import OpeningIntelligenceService
from opening_accuracy import derive_opening_accuracy, variation_accuracy
from opening_accuracy_service import OpeningAccuracyService
from opening_accuracy_settings import OpeningAccuracySettings
from opening_accuracy_query import OpeningAccuracyQuery, matches_opening_accuracy
from opening_accuracy_presentation import opening_metrics_text, selected_opening_quality
from tests.test_game_analysis import TemporaryAnalysis
from tests.opening_intelligence_fixtures import french_book, pgn
from tests.opening_book_fixtures import add_line


def evidence(move, loss=0, *, root_score=None, played_score=None, settings=MoveQualitySettings()):
    """Legal one-ply test evidence with exact root/restricted identities."""
    board=chess.Board(move.fen)
    played=board.parse_uci(move.played_move)
    best=played if loss == 0 and played_score is None else next(m for m in board.legal_moves if m != played)
    sign=1 if board.turn else -1
    root_score=root_score or LineScore(score_cp=sign*100)
    played_score=played_score or LineScore(score_cp=sign*(100-loss))
    def lines(selected,score,restrictions):
        identity=request_identity(settings.generator,restrictions)
        return CandidateLineSet(move.fen,move.mover_color,1,settings.generator.engine.profile_id,identity,
            (CandidateLine(1,selected.uci(),score,(selected.uci(),),settings.generator.engine.depth,identity),),
            {'complete':True,'root_moves':list(restrictions)})
    root=lines(best,root_score,())
    restricted=lines(played,played_score,(played.uci(),)) if best != played else None
    return root,restricted


class OpeningAccuracyTests(TemporaryAnalysis):
    def setUp(self):
        super().setUp()
        guard=patch.object(chess.engine.SimpleEngine,'popen_uci',side_effect=AssertionError('No engine'))
        guard.start();self.addCleanup(guard.stop)
        self.library=OpeningLibraryService();self.lib=self.library.create_library('My Openings')
        self.repo=OpeningBookRepository.open(self.lib.path);self.addCleanup(self.repo.close)
        self.author=OpeningBookService(self.repo);self.bid=french_book(self.author)
        add_line(OpeningBookSession(self.author,self.bid),'e4 e6 d4 d5 e5 Nf6 Nf3 c5')
        cases=(
            'e4 e6 d4 d5 e5',
            'e4 e6 d4 d5 a3',
            'e4 e6 d4 d5 e5 a6 Nf3 h6 Bd3 g6',
            'e4 e6 d4 d5 Nf3 Nf6 e5 c5',
            'e4 e6 d4 d5 exd5 exd5',
            'b3 e5 Bb2 Nc6',
            'e4 e6 d4 d5 e5 c5 c3 Nc6 Bd3 Qb6 Nf3 cxd4 cxd4',
            'e4 e6 d4 d5 Nf3 Nf6 e5 a6 Bd3',
        )
        for index,line in enumerate(cases,1):self.import_fixture(pgn(line,'opening-accuracy-'+str(index)))
        self.service=OpeningAccuracyService(self.path,self.library)

    def facts(self,gid):
        lookup=self.service.books.lookup_for_book(self.lib.library_id,self.bid)
        return OpeningIntelligenceService(self.path,lookup).assess_game(gid)

    def qualities(self,gid,losses=None,*,store=False):
        values=[]
        with closing(self.connect()) as db:
            repo=MoveQualityRepository(db)
            for move in repo.moves(gid):
                root,played=evidence(move,(losses or {}).get(move.step,0))
                values.append(assess_move(move,root,played))
                if store:
                    CandidateLineRepository(db).put(root)
                    if played:CandidateLineRepository(db).put(played)
            if store:db.commit()
        return tuple(values)

    def result(self,gid,losses=None):
        return derive_opening_accuracy(self.facts(gid),self.qualities(gid,losses))

    def test_controlled_in_book_out_of_book_and_exact_aggregation(self):
        complete=self.result(1)
        self.assertEqual((complete.user.quality.accuracy,complete.user.in_book_moves,complete.user.book_opportunities),(100,3,3))
        inside=self.result(1,{5:100})
        self.assertEqual(inside.user.adherence,100)
        self.assertAlmostEqual(inside.user.quality.accuracy,250/3)
        for loss in (0,18,118,1000):
            result=self.result(2,{5:loss})
            self.assertEqual((result.user.in_book_moves,result.user.book_opportunities),(2,3))
            self.assertAlmostEqual(result.user.adherence,200/3)
            self.assertAlmostEqual(result.user.quality.accuracy,(200+cp_accuracy(loss))/3)
            self.assertEqual(result.user.first_deviation.eval_loss_cp,loss)
        perfect=self.result(2)
        self.assertEqual(perfect.user.first_deviation.accuracy,100)
        self.assertIn('Accuracy: 100.0 · Eval loss: 0 cp',opening_metrics_text(perfect))
        self.assertLess(self.result(2,{5:1000}).user.quality.accuracy,67)
        self.assertGreater(self.result(2,{5:1000}).user.quality.accuracy,66)

    def test_opponent_deviation_unknown_gap_and_bounded_window(self):
        result=self.result(3,{7:100,9:0})
        self.assertEqual((result.phase.start_ply,result.phase.end_ply,result.phase.last_known_ply),(1,9,5))
        self.assertEqual((result.user.in_book_moves,result.user.book_opportunities),(3,3))
        self.assertEqual(result.user.quality.total_moves,5)
        self.assertEqual(result.opponent.first_deviation.book.ply,6)
        self.assertIsNone(result.user.first_deviation)
        self.assertEqual(result.user.quality.accuracy,90)
        self.assertEqual(result.moves[6].book.position_in_book,False)
        late=self.result(7)
        self.assertEqual(late.phase.end_ply,12)
        self.assertEqual(late.phase.end_reason,'book_gap_limit')
        shorter=derive_opening_accuracy(self.facts(3),self.qualities(3),settings=OpeningAccuracySettings(continuation_plies=2))
        self.assertEqual(shorter.phase.end_ply,7)
        self.assertNotEqual(shorter.policy_identity,result.policy_identity)

    def test_reentry_resumes_opportunities_without_penalizing_gap(self):
        result=self.result(4)
        self.assertEqual((result.phase.start_ply,result.phase.end_ply),(1,8))
        self.assertTrue(result.moves[6].book.reentry)
        self.assertEqual((result.user.in_book_moves,result.user.book_opportunities),(2,3))
        self.assertEqual((result.opponent.in_book_moves,result.opponent.book_opportunities),(3,3))
        self.assertIsNotNone(result.user.first_deviation)
        self.assertIsNone(result.opponent.first_deviation)
        self.assertFalse(result.moves[5].book.position_in_book)
        self.assertTrue(result.moves[7].book.position_in_book)
        self.assertEqual(self.result(5).user.adherence,100)
        self.assertTrue(self.result(5).moves[4].book.played_move_in_book)
        self.assertFalse(self.result(5).moves[4].book.deviation)

    def test_partial_missing_incompatible_and_no_meaningful_match(self):
        facts=self.facts(1);values=self.qualities(1)
        partial=derive_opening_accuracy(facts,values[:3])
        self.assertEqual((partial.user.status,partial.user.quality.evaluated_moves,partial.user.quality.total_moves),('partial',2,3))
        self.assertEqual(partial.user.quality.accuracy,100)
        self.assertFalse(matches_opening_accuracy(partial))
        self.assertTrue(matches_opening_accuracy(partial,OpeningAccuracyQuery(require_complete=False)))
        missing=derive_opening_accuracy(facts,())
        self.assertEqual(missing.user.status,'not_analyzed');self.assertIsNone(missing.user.quality.accuracy)
        incompatible=derive_opening_accuracy(facts,tuple(replace(v,best_request_identity='depth10') for v in values))
        self.assertEqual(incompatible.user.quality.evaluated_moves,0)
        unrelated=self.result(6)
        self.assertFalse(unrelated.applicable);self.assertEqual(unrelated.moves,())
        self.assertIn('not applicable',opening_metrics_text(unrelated))
        with self.assertRaises(ValueError):
            derive_opening_accuracy(facts,(replace(values[0],move=replace(values[0].move,move_id=999)),))

    def test_black_user_unknown_color_and_both_deviations(self):
        with closing(self.connect()) as db:
            db.execute("UPDATE games SET user_color='black' WHERE game_id=3");db.commit()
        result=self.result(3,{6:100})
        self.assertEqual((result.user.color,result.user.quality.total_moves),('black',4))
        self.assertEqual(result.user.first_deviation.book.ply,6)
        self.assertEqual(result.user.quality.accuracy,87.5)
        with closing(self.connect()) as db:
            db.execute('UPDATE games SET user_color=NULL WHERE game_id=3');db.commit()
        unknown=self.result(3)
        self.assertIsNone(unknown.user);self.assertTrue(all(r.party=='unknown' for r in unknown.moves))
        # First user root departure and a later opponent leaf departure are independent.
        both=self.result(8)
        self.assertEqual(both.user.first_deviation.book.ply,5)
        self.assertEqual(both.opponent.first_deviation.book.ply,8)

    def test_mate_and_contradictory_evidence_keep_frozen_semantics(self):
        facts=self.facts(1);values=list(self.qualities(1));move=values[-1].move
        root,played=evidence(move,1,root_score=LineScore(mate_score=3),played_score=LineScore(score_cp=900))
        values[-1]=assess_move(move,root,played)
        result=derive_opening_accuracy(facts,values)
        self.assertEqual(result.moves[-1].accuracy,40)
        self.assertIsNone(result.moves[-1].eval_loss_cp)
        self.assertEqual(result.user.quality.cp_loss_moves,2)
        root,played=evidence(move,1,root_score=LineScore(score_cp=0),played_score=LineScore(score_cp=10))
        values[-1]=assess_move(move,root,played)
        unresolved=derive_opening_accuracy(facts,values)
        self.assertEqual(unresolved.user.unresolved_moves,1)
        self.assertEqual(unresolved.user.status,'partial')

    def test_live_naming_weight_preference_graph_provenance(self):
        original=self.result(1)
        edge=next(m for m in self.repo.snapshot(self.bid).moves if m.variation_name=='Advance Variation')
        details=MoveDetails(**{name:getattr(edge,name) for name in MoveDetails.__dataclass_fields__})
        for updated in (replace(details,variation_name='Renamed'),replace(details,weight=15),replace(details,preferred=False)):
            self.author.edit_move(self.bid,edge.move_id,updated)
            result=self.result(1)
            self.assertEqual(result.user.quality.accuracy,original.user.quality.accuracy)
            self.assertEqual(result.user.adherence,original.user.adherence)
            self.assertNotEqual(result.opening.provenance.content_identity,original.opening.provenance.content_identity)
        self.author.edit_move(self.bid,edge.move_id,replace(details,active=False,preferred=False))
        changed=self.result(1)
        self.assertEqual(changed.user.in_book_moves,2)
        self.assertIsNotNone(changed.user.first_deviation)

    def test_readonly_services_variations_queries_draft_and_failures(self):
        self.qualities(1,store=True);self.qualities(2,{5:118},store=True)
        before=self.digest();book=self.repo.path.read_bytes()
        batch=self.service.get_opening_accuracy_for_games(self.lib.library_id,self.bid,(1,2,6,1,9999))
        self.assertEqual(len(batch.results),3);self.assertEqual(len(batch.errors),1)
        self.assertEqual(self.repo.snapshot(self.bid).book.status,'draft')
        groups=self.service.get_variation_accuracy_summary(self.lib.library_id,self.bid,(1,2))
        self.assertEqual(sum(g.games for g in groups.groups),2)
        self.assertEqual(sum(g.user.quality.total_moves for g in groups.groups),6)
        deviations=self.service.get_opening_deviation_quality(self.lib.library_id,self.bid,(1,2))
        self.assertEqual(len(deviations.deviations),1)
        self.assertTrue(matches_opening_accuracy(batch.results[1],OpeningAccuracyQuery(user_deviation=True,deviation_loss_min_cp=100)))
        self.assertFalse(matches_opening_accuracy(batch.results[2]))
        self.assertEqual(self.digest(),before);self.assertEqual(self.repo.path.read_bytes(),book)
        for path in Path('.').glob('opening_accuracy*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node,ast.ImportFrom):self.assertFalse((node.module or '').startswith(('tkinter','merlin_ui','chess.engine')))


    def test_opening_summary_selected_detail_none_and_session_selection(self):
        import tkinter as tk
        from merlin_ui.game_review_view import GameReviewView
        self.qualities(2,store=True)
        before=self.digest();root=tk.Tk();root.withdraw();view=GameReviewView(root,database_path=self.path)
        try:
            view.open_game_position(2,None);wait_for_opening(view)
            item=self.library.get_library(self.lib.library_id).books[0]
            picker=view.opening_reference;picker.service.select(2,item.installation_id);picker.refresh(force=True);wait_for_opening(view)
            view._set_step(5)
            panel=view.opening_panel
            self.assertIn('Opening Accuracy: 100.0',panel.metrics.cget('text'))
            self.assertIn('2/3 user opening opportunities',panel.metrics.cget('text'))
            self.assertTrue(any('User deviation' in m.tags for m in panel.moments))
            self.assertEqual(panel.accuracy.moves[4].quality.accuracy,100.0)
            view.open_game_position(6,None);wait_for_opening(view)
            self.assertEqual(picker.selected_id,item.installation_id)
            self.assertIn('not applicable',panel.metrics.cget('text'))
            picker.service.select(6,None);picker.refresh(force=True);wait_for_opening(view)
            self.assertEqual(panel.metrics.cget('text'),'');self.assertIsNone(panel.accuracy)
            self.assertIsNotNone(view.game_quality)
            self.assertEqual(self.digest(),before)
        finally:view.close()
