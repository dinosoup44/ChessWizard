"""Stored-fact search, isolated fixtures, navigation and no-engine/write contracts."""
from contextlib import closing
from dataclasses import asdict, replace
import ast
import json
from pathlib import Path
import sqlite3
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import chess
import chess.engine
from game_search_models import GameSearchCriteria as Criteria
from game_search_repository import GameSearchRepository, metadata_query
from game_search_service import GameSearchService
from game_search_tactics import OccurrenceEvidenceSelection
from tactic_occurrence_storage import OccurrenceKey, TacticOccurrenceRecord, OccurrenceEvidence
from candidate_line_repository import CandidateLineRepository
from candidate_line_request import request_identity
from candidate_lines import CandidateLine, CandidateLineSet, LineScore
from move_quality_settings import MoveQualitySettings
from merlin_ui.game_explorer import GameExplorerWindow, COLUMNS
from merlin_ui.game_review_view import GameReviewView
from game_review_sets import ALL_GAMES
from tests.test_game_analysis import TemporaryAnalysis
from tests.test_game_import import pgn


class SearchFixture(TemporaryAnalysis):
    def setUp(self):
        super().setUp()
        for number in range(1, 6):
            self.import_fixture(pgn(identity=str(number), day=f'2026.09.{number:02}',
                moves='1. e4 e5 2. Nf3 Nc6 1-0' if number != 5 else '1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 1-0'))
        with closing(self.connect()) as db:
            db.execute("UPDATE games SET user_color='black',white_username='OtherPlayer',black_username='Example_User',result='0-1' WHERE game_id=2")
            db.execute("UPDATE games SET result='0-1',source='lichess',time_control='900+10' WHERE game_id=3")
            db.execute("UPDATE games SET result='1/2-1/2',played_at=NULL,time_control=NULL,user_color=NULL WHERE game_id=4")
            db.execute("UPDATE games SET result='1/2-1/2',white_username='Example_User',black_username='MixedCase' WHERE game_id=5")
            db.commit()
        self.service = GameSearchService(self.path)
        guard = patch.object(chess.engine.SimpleEngine, 'popen_uci', side_effect=AssertionError('Search must never run an engine'))
        guard.start(); self.addCleanup(guard.stop)

    def ids(self, **criteria):
        return [row.game_id for row in self.service.search(Criteria(**criteria)).games]

    def candidate(self, gid, motif='fork', *, status='candidate', rejected=False, ply=1):
        with closing(self.connect()) as db:
            move = db.execute('SELECT * FROM moves WHERE game_id=? AND ply_number=?', (gid, ply)).fetchone()
            solution = 'd2d4' if move['color']=='white' else 'd7d5'
            cursor = db.execute('INSERT INTO tactic_candidates(move_id,tactic_type,candidate_status,solution_move_uci,solution_line) VALUES(?,?,?,?,?)',
                (move['move_id'],'missed_'+motif,status,solution,'d4' if ply==1 else 'd5'))
            if rejected:
                db.execute("INSERT INTO analysis_coverage(move_id,analysis_type,coverage_status,candidate_id) VALUES(?,?,'rejected',?)", (move['move_id'],'missed_'+motif,cursor.lastrowid))
            db.commit()
            return cursor.lastrowid

    def occurrence(self, gid, *, kind='played', motif='fork', ply=1):
        with closing(self.connect()) as db:
            move = db.execute('SELECT * FROM moves WHERE game_id=? AND ply_number=?', (gid, ply)).fetchone()
            root = move['uci_played'] if kind=='played' else ('d2d4' if move['color']=='white' else 'd7d5')
            key = OccurrenceKey('00000000-0000-4000-8000-000000000001',gid,move['move_id'],kind,move['color'],motif,root)
            record = TacticOccurrenceRecord(key,ply,move['fen_before'],move['uci_played'])
            db.execute('INSERT INTO tactic_occurrences(occurrence_id,identity_version,identity_json,source_namespace,game_id,move_id,occurrence_kind,actor_color,motif_type,tactical_move_uci,instance_key,decision_ply,decision_fen,actual_move_uci) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (key.occurrence_id,1,key.identity_json,key.source_namespace,gid,move['move_id'],kind,move['color'],motif,root,'root',ply,move['fen_before'],move['uci_played']))
            evidence = OccurrenceEvidence(key.occurrence_id,'fixture','1','explicit-fixture-policy','fixture','white','supplied','accepted','verified','supplied','{}')
            data = asdict(evidence); data['revision_id'] = evidence.revision_id
            db.execute('INSERT INTO tactic_occurrence_evidence('+','.join(data)+') VALUES('+','.join('?' for _ in data)+')', tuple(data.values()))
            db.commit()
            return evidence.revision_id, record.occurrence_id

    def quality(self, gid, *, partial=False):
        settings = MoveQualitySettings()
        with closing(self.connect()) as db:
            moves = db.execute('SELECT * FROM moves WHERE game_id=? ORDER BY ply_number',(gid,)).fetchall()
            for row in moves[:1] if partial else moves:
                identity = request_identity(settings.generator)
                line = CandidateLine(1,row['uci_played'],LineScore(score_cp=30),(row['uci_played'],),16,identity)
                evidence = CandidateLineSet(row['fen_before'],row['color'],1,settings.generator.engine.profile_id,
                    identity,(line,),{'complete':True,'root_moves':[]})
                CandidateLineRepository(db).put(evidence)
            db.commit()


class SearchTests(SearchFixture):
    def test_exact_hit_miss_and_local_ids(self):
        self.assertEqual(self.ids(game_id=2),[2])
        self.assertEqual(self.ids(game_id=999991),[])
        self.assertEqual(self.service.search(Criteria(game_id=999991)).summary,'Game ID 999991 was not found in this database.')
        self.assertIn('selected filters',self.service.search(Criteria(game_id=2,color='white')).summary)

    def test_metadata_and_newest_first(self):
        self.assertEqual(self.ids(),[5,3,2,1,4])
        self.assertEqual(self.service.search().total_games,5)
        self.assertEqual(self.ids(opponent='mixedCASE'),[5])
        self.assertEqual(self.ids(opponent='%'),[])
        self.assertEqual(self.ids(color='black',result='win'),[2])
        self.assertEqual(self.ids(result='loss'),[3])
        self.assertEqual(self.ids(result='draw'),[5,4])
        self.assertEqual(self.ids(source='lichess'),[3])
        self.assertEqual(self.ids(source_game_id='2'),[2])
        self.assertEqual(self.ids(date_from='2026-09-02',date_to='2026-09-03'),[3,2])
        self.assertEqual(self.ids(min_moves=3,max_moves=4),[5])
        self.assertEqual(self.ids(time_control='900+10'),[3])
        self.assertEqual(self.ids(opponent='opponent',color='white',result='loss',source='lichess',min_moves=2,max_moves=2),[3])

    def test_validation_and_serialization(self):
        for values in ({'game_id':'2'},{'game_id':True},{'game_id':0},{'min_moves':-1},{'min_accuracy':float('nan')},
                       {'max_accuracy':101},{'min_moves':3,'max_moves':2},{'date_from':'2026-09-40'},
                       {'date_from':'2026-09-03','date_to':'2026-09-02'},{'motifs':['invented']}):
            with self.subTest(values=values), self.assertRaises(ValueError): Criteria(**values)
        original=Criteria(game_id=2,motifs=('fork','pin'),relationships=('missed_by_perspective',))
        self.assertEqual(Criteria(**json.loads(json.dumps(asdict(original)))),original)

    def test_unknown_metadata_and_no_tactics_remain_visible(self):
        row=self.service.search(Criteria(game_id=4)).games[0]
        self.assertIsNone(row.played_at)
        self.assertIsNone(row.time_control)
        self.assertIsNone(row.accuracy)
        self.assertEqual(row.tactic_count,0)
        self.assertEqual(self.ids(min_accuracy=0),[])

    def test_active_legacy_relationships_exclude_rejected_and_duplicates(self):
        self.candidate(1)
        self.candidate(2,ply=2)
        self.candidate(3,rejected=True)
        self.candidate(4,status='rejected')
        self.candidate(5); self.candidate(5)
        self.assertEqual(self.ids(motifs=('fork',),relationships=('missed_by_perspective',)),[2,1])
        self.assertEqual(self.ids(relationships=('played_by_perspective',)),[])
        self.assertEqual(self.service.search(Criteria(game_id=1)).games[0].tactic_count,1)

    def test_relationship_uses_actor_and_same_claim_for_and(self):
        self.candidate(1,'fork')
        self.candidate(1,'pin',ply=2)
        self.assertEqual(self.ids(motifs=('fork',),relationships=('missed_by_opponent',)),[])
        self.assertEqual(self.ids(motifs=('pin',),relationships=('missed_by_opponent',)),[1])
        self.assertEqual(self.ids(motifs=('fork','pin'),relationships=('missed_by_opponent','missed_by_perspective')),[1])
        self.candidate(4)
        self.assertEqual(self.ids(relationships=('unknown',)),[4])

    def test_standalone_claim_requires_explicit_revision_selection(self):
        own,_=self.occurrence(1)
        opponent,_=self.occurrence(2)
        unknown,_=self.occurrence(3,kind='unknown')
        self.assertEqual(self.ids(relationships=('played_by_perspective',)),[])
        self.service=GameSearchService(self.path,occurrence_selection=OccurrenceEvidenceSelection(frozenset((own,opponent,unknown))))
        self.assertEqual(self.ids(relationships=('played_by_perspective',)),[1])
        self.assertEqual(self.ids(relationships=('played_by_opponent',)),[2])
        self.assertEqual(self.ids(relationships=('unknown',)),[3])

    def test_linked_archive_cannot_revive_rejected_candidate_or_double_count(self):
        cid=self.candidate(1)
        rev,oid=self.occurrence(1,kind='missed')
        with closing(self.connect()) as db:
            db.execute('INSERT INTO tactic_occurrence_legacy_candidates VALUES(?,?)',(cid,oid));db.commit()
        self.service=GameSearchService(self.path,occurrence_selection=OccurrenceEvidenceSelection(frozenset((rev,))))
        self.assertEqual(self.service.search(Criteria(game_id=1)).games[0].tactic_count,1)
        with closing(self.connect()) as db:
            db.execute("UPDATE tactic_candidates SET candidate_status='rejected' WHERE candidate_id=?",(cid,));db.commit()
        self.assertEqual(self.ids(motifs=('fork',)),[])

    def test_accuracy_uses_shared_complete_compatible_metrics(self):
        self.quality(5,partial=True)
        self.assertEqual(self.ids(min_accuracy=0),[])
        self.quality(1)
        # Shared starting positions are reusable raw evidence, but game 5 is still partial.
        self.assertEqual(set(self.ids(min_accuracy=99,max_accuracy=100)),{1,2,3})
        self.assertEqual(self.ids(max_accuracy=99),[])
        self.assertIsNone(self.service.search(Criteria(game_id=5)).games[0].accuracy)

    def test_sorting_numeric_unknowns_and_timezone_dates(self):
        from game_search_models import sorted_games
        rows=self.service.search().games
        self.assertEqual([r.game_id for r in sorted_games(rows,'game_id')],[1,2,3,4,5])
        self.assertEqual(sorted_games(rows,'played_at',True)[-1].game_id,4)
        dated=(replace(rows[0],game_id=7,played_at='2026-09-01T01:00:00+02:00'),
               replace(rows[0],game_id=8,played_at='2026-08-31T23:30:00Z'))
        self.assertEqual([r.game_id for r in sorted_games(dated,'played_at',True)],[8,7])

    def test_query_plan_no_full_move_scan_and_bounded_exact_read(self):
        with closing(self.connect()) as db:
            sql,params=metadata_query(Criteria(game_id=2))
            plan=' '.join(str(tuple(r)) for r in db.execute('EXPLAIN QUERY PLAN '+sql,params))
            self.assertIn('INTEGER PRIMARY KEY',plan)
            self.assertIn('sqlite_autoindex_moves_1',plan)
            self.assertNotIn('SCAN m',plan)
            queries=[];db.set_trace_callback(queries.append)
            GameSearchRepository(db).search(Criteria(game_id=2))
            self.assertLess(len(queries),12)

    def test_read_only_bytes_and_core_without_ui(self):
        before=self.digest()
        self.service.search();self.service.options();self.service.search(Criteria(motifs=('fork',)))
        self.assertEqual(before,self.digest())
        with closing(self.service._connect()) as db:
            with self.assertRaises(sqlite3.OperationalError):db.execute('DELETE FROM games')
        for name in ('game_search_models.py','game_search_repository.py','game_search_tactics.py','game_search_service.py'):
            tree=ast.parse(Path(name).read_text(encoding='utf-8-sig'))
            imports=[node.module or '' for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
            self.assertFalse(any(item.startswith(('tkinter','merlin_ui','analyze_')) for item in imports))


class ExplorerUITests(SearchFixture):
    def wait_search(self, window, root):
        deadline=time.monotonic()+8
        while window.busy and time.monotonic()<deadline:
            root.update();time.sleep(.01)
        self.assertFalse(window.busy)
        root.update()

    def test_results_sort_validation_reset_and_handoff(self):
        root=tk.Tk();root.withdraw()
        opened=[]
        window=GameExplorerWindow(root,self.path,on_open_game=opened.append)
        self.addCleanup(lambda: window.close() if not window.closed else None)
        self.wait_search(window,root)
        self.assertIn('game_id',[c[0] for c in COLUMNS])
        window.sort('game_id')
        self.assertEqual(window.tree.get_children(),('1','2','3','4','5'))
        window.variables['game_id'].set('2');window.search();self.wait_search(window,root)
        self.assertEqual(window.tree.selection(),('2',))
        window.open_selected();self.assertEqual(opened,[2])
        window.variables['game_id'].set('999991');window.search();self.wait_search(window,root)
        self.assertEqual(window.tree.get_children(),())
        self.assertIn('not found in this database',window.status.get())
        window.variables['game_id'].set('abc');window.search()
        self.assertIn('integer',window.status.get())
        window.reset();self.wait_search(window,root)
        self.assertEqual(len(window.tree.get_children()),5)

    def test_scaling_and_resize_leave_results_usable(self):
        for scaling in (1.0,1.25,1.5):
            with self.subTest(scaling=scaling):
                root=tk.Tk();root.withdraw();root.tk.call('tk','scaling',96/72*scaling)
                window=GameExplorerWindow(root,self.path,on_open_game=lambda gid: None)
                try:
                    self.wait_search(window,root)
                    root.geometry('1100x780');root.deiconify();root.update()
                    from tkinter import font
                    row_height=window.tree.bbox(window.tree.get_children()[0])[3]
                    self.assertGreaterEqual(row_height,font.nametofont('TkDefaultFont').metrics('linespace')+4)
                    self.assertGreater(window.tree.winfo_height(),180)
                    self.assertLess(window.open_button.winfo_rooty()+window.open_button.winfo_height(),root.winfo_rooty()+root.winfo_height()+1)
                finally: window.close()

    def test_game_review_exact_handoff_resets_filters_and_actual_position(self):
        root=tk.Tk();root.withdraw()
        view=GameReviewView(root,self.path,review_sets=(ALL_GAMES,))
        self.addCleanup(view.close)
        view.filter_var.set('Fork')
        view.open_game_position(2,None)
        self.assertEqual(view.current_game['game_id'],2)
        self.assertEqual(view.current_game['user_color'],'black')
        self.assertEqual(view.current_step,0)
        self.assertIsNone(view.line_playback)
        self.assertEqual(view.filter_var.get(),'All games')
        self.assertIn('Game ID 2',view.subtitle_label.cget('text'))
        self.assertEqual(len(view.moves),4)
        self.assertEqual(len(view.evaluation_values),5)
