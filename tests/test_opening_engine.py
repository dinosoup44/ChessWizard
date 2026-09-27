"""Isolated engine advice and atomic authoring contracts; no production writes."""
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
import chess
from analysis_control import AnalysisCancelled
from analysis_settings import BUILTIN_PROFILES
from candidate_line_repository import CandidateLineRepository
from candidate_line_request import request_identity
from candidate_lines import CandidateLine, CandidateLineSet, LineScore
from migrate_candidate_line_cache import migrate
from opening_book_line import plan_book_line
from opening_book_models import BookDetails, MoveDetails
from opening_book_polyglot import export_entries, export_polyglot
from opening_book_repository import OpeningBookRepository
from opening_book_service import OpeningBookService
from opening_book_session import OpeningBookSession
from opening_engine_authoring import OpeningEngineAuthoringService
from opening_engine_models import OpeningEngineAnalysis, saved_opening_anchor
from opening_engine_presentation import opening_engine_playback, opening_engine_line_text, opening_engine_score_text
from opening_engine_service import OpeningEngineService
from tests.opening_book_fixtures import add_line


def engine_lines(fen, settings, sans=None):
    board=chess.Board(fen)
    identity=request_identity(settings)
    lines=[]
    if sans is None:
        sans=[]
        for root in list(board.legal_moves)[:settings.candidate_line_count]:
            current=board.copy();tokens=[current.san(root)];current.push(root)
            for _ in range(5):
                if current.is_game_over():break
                move=next(iter(current.legal_moves));tokens.append(current.san(move));current.push(move)
            sans.append(' '.join(tokens))
    for index,text in enumerate(sans,1):
        current=board.copy();moves=[]
        for san in text.split():
            move=current.parse_san(san);moves.append(move.uci());current.push(move)
        lines.append(CandidateLine(index,moves[0],LineScore(score_cp=25-index),tuple(moves),settings.engine.depth,identity))
    return CandidateLineSet(fen,'white' if board.turn else 'black',settings.candidate_line_count,
        settings.engine.profile_id,identity,tuple(lines),{'complete':True,'root_moves':[]})


def advice(anchor, san, profile='quick'):
    settings=BUILTIN_PROFILES[profile]
    return OpeningEngineAnalysis(anchor,settings,engine_lines(anchor.fen,settings.generator,[san]),
        '2026-09-26T12:00:00+00:00',False,1,0,.01)


class OpeningEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.path=self.folder/'copy.cwbook'
        self.repo=OpeningBookRepository.create(self.path);self.addCleanup(self.repo.close)
        self.author=OpeningBookService(self.repo)
        self.bid=self.author.create_book(BookDetails('Fixture French'))
        self.session=OpeningBookSession(self.author,self.bid)
        add_line(self.session,'e4 e6 d4 d5')
        self.anchor=saved_opening_anchor(self.repo.snapshot(self.bid),'fixture-library',self.session.history)
        self.cache=self.folder/'scratch.sqlite3'
        self.engine=OpeningEngineService(cache_path=self.cache)
        self.writer=OpeningEngineAuthoringService(self.repo,'fixture-library')
        guard=patch('chess.engine.SimpleEngine.popen_uci',side_effect=AssertionError('No real engine in unit tests'))
        guard.start();self.addCleanup(guard.stop)

    def generate(self, fen, settings, **kwargs):
        return engine_lines(fen,settings)

    def test_explicit_only_exact_cache_rerun_and_profile_separation(self):
        before=self.path.read_bytes()
        self.assertFalse(self.cache.exists())
        with patch('opening_engine_service.CandidateLineGenerator.generate',side_effect=self.generate) as generator:
            normal=self.engine.analyze_opening_position(self.anchor)
            cached=self.engine.analyze_opening_position(self.anchor)
            quick=self.engine.analyze_opening_position(self.anchor,'quick')
            deep=self.engine.analyze_opening_position(self.anchor,'deep')
            self.assertEqual(generator.call_count,3)
        self.assertEqual((normal.lines.generated_line_count,quick.lines.generated_line_count,deep.lines.generated_line_count),(3,1,5))
        self.assertEqual((cached.cache_hit,cached.engine_searches,cached.cache_inserts),(True,0,0))
        self.assertEqual(normal.lines,cached.lines)
        self.assertEqual(len({v.lines.engine_identity for v in (normal,quick,deep)}),3)
        self.assertEqual(before,self.path.read_bytes())
        cache_bytes=self.cache.read_bytes()
        again=self.engine.analyze_opening_position(self.anchor)
        self.assertEqual(again.engine_searches,0);self.assertEqual(cache_bytes,self.cache.read_bytes())

    def test_existing_game_cache_is_read_only_and_no_advisory_copy_on_hit(self):
        source=self.folder/'game-evidence.sqlite3'
        with closing(sqlite3.connect(source)) as db:
            migrate(db);CandidateLineRepository(db).put(engine_lines(self.anchor.fen,BUILTIN_PROFILES['normal'].generator));db.commit()
        before=source.read_bytes()
        result=OpeningEngineService(source,cache_path=self.cache).analyze_opening_position(self.anchor)
        self.assertTrue(result.cache_hit);self.assertFalse(self.cache.exists())
        self.assertEqual(before,source.read_bytes())
        with self.assertRaises(ValueError):OpeningEngineService(source,cache_path=source)

    def test_refresh_searches_without_overwriting_exact_insert_once_cache(self):
        with patch('opening_engine_service.CandidateLineGenerator.generate',side_effect=self.generate) as generator:
            self.engine.analyze_opening_position(self.anchor)
            before=self.cache.read_bytes()
            result=self.engine.analyze_opening_position(self.anchor,refresh=True)
            self.assertEqual(generator.call_count,2)
        self.assertEqual((result.cache_hit,result.engine_searches,result.cache_inserts),(False,1,0))
        self.assertEqual(before,self.cache.read_bytes())

    def test_failure_incomplete_and_cancellation_never_cache_or_mutate_book(self):
        before=self.path.read_bytes()
        with patch('opening_engine_service.CandidateLineGenerator.generate',side_effect=RuntimeError('engine failed')):
            with self.assertRaisesRegex(RuntimeError,'engine failed'):self.engine.analyze_opening_position(self.anchor)
        value=engine_lines(self.anchor.fen,BUILTIN_PROFILES['normal'].generator)
        for bad in (replace(value,generation_metadata={'complete':False}),
                    replace(value,lines=value.lines[:1]),
                    replace(value,lines=tuple(replace(line,depth=1) for line in value.lines))):
            with patch('opening_engine_service.CandidateLineGenerator.generate',return_value=bad):
                with self.assertRaises(ValueError):self.engine.analyze_opening_position(self.anchor)
        cancel=threading.Event()
        def cancelled(*args,**kwargs):cancel.set();return value
        with patch('opening_engine_service.CandidateLineGenerator.generate',side_effect=cancelled):
            with self.assertRaises(AnalysisCancelled):self.engine.analyze_opening_position(self.anchor,cancel=cancel)
        self.assertFalse(self.cache.exists());self.assertEqual(before,self.path.read_bytes())

    def test_stop_during_insert_rolls_back_cache_row(self):
        with closing(sqlite3.connect(self.cache)) as db:migrate(db);db.commit()
        before=self.cache.read_bytes();cancel=threading.Event();put=CandidateLineRepository.put
        def stop_after_put(repo,value):
            result=put(repo,value);cancel.set();return result
        with patch('opening_engine_service.CandidateLineGenerator.generate',side_effect=self.generate),patch.object(CandidateLineRepository,'put',stop_after_put):
            with self.assertRaises(AnalysisCancelled):self.engine.analyze_opening_position(self.anchor,cancel=cancel)
        self.assertEqual(before,self.cache.read_bytes())

    def test_malformed_cached_evidence_is_not_reused_or_repaired(self):
        with closing(sqlite3.connect(self.cache)) as db:
            migrate(db)
            db.execute('INSERT INTO engine_candidate_line_cache(fen,engine_identity,schema_version,payload_json) VALUES(?,?,1,?)',
                (self.anchor.fen,request_identity(BUILTIN_PROFILES['normal'].generator),'{}'));db.commit()
        before=self.cache.read_bytes()
        with patch('opening_engine_service.CandidateLineGenerator.generate',side_effect=self.generate):
            result=self.engine.analyze_opening_position(self.anchor)
        self.assertFalse(result.cache_hit);self.assertEqual(result.cache_inserts,0)
        self.assertEqual(before,self.cache.read_bytes())

    def test_scores_and_numbered_black_start_preview(self):
        black=saved_opening_anchor(self.session.snapshot,'fixture-library',self.session.history[:3])
        result=advice(black,'d5 e5 c5 c3')
        line=result.lines.lines[0]
        self.assertEqual(opening_engine_score_text(line),'+0.24')
        self.assertEqual(opening_engine_score_text(replace(line,score=LineScore(mate_score=3))),'M3')
        self.assertEqual(opening_engine_score_text(replace(line,score=LineScore(mate_score=-4))),'-M4')
        self.assertTrue(opening_engine_line_text(result,1).startswith('2… d5 3. e5 c5'))
        before=self.path.read_bytes();playback=opening_engine_playback(result,1)
        self.assertEqual(playback.step(-1),playback)
        end=playback.step(100);self.assertEqual(end.step(1),end)
        self.assertEqual(end.reset().fen,black.fen)
        self.assertEqual(before,self.path.read_bytes())

    def test_full_line_custom_name_neutral_metadata_export_and_reopen(self):
        result=advice(self.anchor,'e5 c5 c3 Nc6 Nf3 Qb6')
        before=self.repo.snapshot(self.bid)
        plan=self.writer.preview_add(result,1,self.anchor,variation_name='My testing line')
        self.assertEqual(plan.new_edges,6)
        ids=self.writer.add_engine_line_to_book(result,1,self.anchor,plan)
        snapshot=self.repo.snapshot(self.bid)
        self.assertEqual(snapshot.moves[:len(before.moves)],before.moves)
        new=[m for m in snapshot.moves if m.move_id in ids]
        self.assertEqual({m.weight for m in new},{MoveDetails().weight})
        self.assertFalse(any(m.preferred for m in new))
        self.assertEqual(new[0].variation_name,'My testing line')
        self.assertTrue(all(not m.variation_name for m in new[1:]))
        self.assertIn('authoring_engine',json.loads(new[0].metadata_json))
        reopened=OpeningBookRepository.open(self.path)
        try:self.assertEqual(snapshot,reopened.snapshot(self.bid))
        finally:reopened.close()
        output=self.folder/'export.bin';receipt=export_polyglot(snapshot,output)
        self.assertEqual(receipt.entry_count,len(export_entries(snapshot)))
        self.assertEqual(receipt.entry_count,len(snapshot.moves))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0],'ok')
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())

    def test_existing_prefix_preserves_details_and_entire_existing_line_is_noop(self):
        add_line(self.session,'e4 e6 d4 d5 e5 c5')
        edge=self.session.snapshot.moves[-2]
        self.author.edit_move(self.bid,edge.move_id,MoveDetails(91,True,True,'Keep notes','Keep teaching',
            metadata_json='{"keep":true}',variation_name='Owner name'))
        snapshot=self.repo.snapshot(self.bid)
        anchor=saved_opening_anchor(snapshot,'fixture-library',self.anchor.path)
        result=advice(anchor,'e5 c5 c3 Nc6')
        plan=self.writer.preview_add(result,1,anchor,variation_name='New continuation')
        self.assertEqual((plan.existing_prefix,plan.new_edges),(2,2))
        ids=self.writer.add_engine_line_to_book(result,1,anchor,plan)
        after=self.repo.snapshot(self.bid)
        self.assertEqual(snapshot.moves,after.moves[:len(snapshot.moves)])
        self.assertEqual(ids[0],edge.move_id)
        fresh=saved_opening_anchor(after,'fixture-library',anchor.path)
        whole=advice(fresh,'e5 c5 c3 Nc6')
        noop=self.writer.preview_add(whole,1,fresh,variation_name='Do not rename')
        before=self.path.read_bytes()
        self.assertEqual(noop.new_edges,0)
        self.assertEqual(self.writer.add_engine_line_to_book(whole,1,fresh,noop),ids)
        self.assertEqual(before,self.path.read_bytes())

    def test_transposition_and_repeated_edge_reuse(self):
        other=self.author.create_book(BookDetails('Transposition'))
        session=OpeningBookSession(self.author,other)
        add_line(session,'Nf3 Nf6 d4 d5 Nc3')
        before=session.snapshot
        anchor=saved_opening_anchor(before,'fixture-library')
        result=advice(anchor,'d4 Nf6 Nf3 d5 Nc3')
        plan=self.writer.preview_add(result,1,anchor)
        ids=self.writer.add_engine_line_to_book(result,1,anchor,plan)
        self.assertEqual(plan.new_edges,3)
        self.assertEqual(ids[-2:],session.history[-2:])
        after=self.repo.snapshot(other)
        self.assertEqual(len({p.canonical_fen for p in after.positions}),len(after.positions))
        self.assertEqual(len({(m.from_position_id,m.move_uci) for m in after.moves}),len(after.moves))
        third=self.author.create_book(BookDetails('Cycle'))
        snapshot=self.repo.snapshot(third)
        anchor=saved_opening_anchor(snapshot,'fixture-library')
        cycle=advice(anchor,'Nf3 Nf6 Ng1 Ng8 Nf3 Nf6')
        plan=self.writer.preview_add(cycle,1,anchor)
        self.assertEqual(plan.new_edges,4)
        ids=self.writer.add_engine_line_to_book(cycle,1,anchor,plan)
        self.assertEqual(ids[:2],ids[4:])

    def test_stale_selection_library_book_revision_and_confirmed_plan_are_blocked(self):
        result=advice(self.anchor,'e5 c5')
        plan=self.writer.preview_add(result,1,self.anchor)
        root=saved_opening_anchor(self.session.snapshot,'fixture-library')
        before=self.path.read_bytes()
        for wrong in (root,replace(self.anchor,library_identity='another-library'),replace(self.anchor,book_id=999)):
            with self.assertRaisesRegex(ValueError,'different book position'):self.writer.preview_add(result,1,wrong)
        with self.assertRaises(ValueError):self.writer.add_engine_line_to_book(result,1,self.anchor,replace(plan,variation_name='changed'))
        self.assertEqual(before,self.path.read_bytes())
        self.repo.set_position_note(self.bid,self.anchor.position_id,'Changed after analysis')
        with self.assertRaisesRegex(ValueError,'different book position'):self.writer.preview_add(result,1,self.anchor)

    def test_insert_failure_rolls_back_entire_line(self):
        result=advice(self.anchor,'e5 c5 c3 Nc6')
        plan=self.writer.preview_add(result,1,self.anchor)
        self.repo.connection.execute("CREATE TRIGGER fail_third BEFORE INSERT ON book_moves WHEN NEW.san='c3' BEGIN SELECT RAISE(ABORT,'fixture third move'); END")
        self.repo.connection.commit()
        before=self.path.read_bytes()
        with self.assertRaisesRegex(sqlite3.DatabaseError,'fixture third move'):
            self.writer.add_engine_line_to_book(result,1,self.anchor,plan)
        self.assertEqual(before,self.path.read_bytes())

    def test_inactive_existing_move_is_never_silently_enabled(self):
        add_line(self.session,'e4 e6 d4 d5 e5')
        edge=self.session.snapshot.moves[-1]
        self.author.edit_move(self.bid,edge.move_id,MoveDetails(active=False))
        anchor=saved_opening_anchor(self.repo.snapshot(self.bid),'fixture-library',self.anchor.path)
        before=self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'inactive'):self.writer.preview_add(advice(anchor,'e5 c5'),1,anchor)
        self.assertEqual(before,self.path.read_bytes())

    def test_terminal_and_fewer_legal_moves_do_not_fabricate_extra_lines(self):
        add_line(self.session,'f3 e5 g4 Qh4#')
        terminal=saved_opening_anchor(self.session.snapshot,'fixture-library',self.session.history)
        result=self.engine.analyze_opening_position(terminal)
        self.assertEqual((result.lines.generated_line_count,result.engine_searches),(0,0))
        self.assertTrue(result.lines.generation_metadata['terminal'])
        one=self.author.create_book(BookDetails('One legal reply'),root_fen='7k/8/6K1/8/8/8/8/R7 b - - 0 1')
        anchor=saved_opening_anchor(self.repo.snapshot(one),'fixture-library')
        self.assertEqual(chess.Board(anchor.fen).legal_moves.count(),1)
        with patch('opening_engine_service.CandidateLineGenerator.generate',side_effect=self.generate):
            result=self.engine.analyze_opening_position(anchor)
        self.assertEqual(result.lines.requested_line_count,3)
        self.assertEqual(result.lines.generated_line_count,1)
