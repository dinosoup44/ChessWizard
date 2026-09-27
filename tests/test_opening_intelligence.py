"""Book knowledge truth, search, provenance and read-only UI contracts."""
from tests.opening_ui_wait import wait_for_opening
from contextlib import closing
from dataclasses import replace,FrozenInstanceError,asdict
from pathlib import Path
import ast,json,sqlite3,time
import unittest
from unittest.mock import patch
import chess
from opening_book_models import MoveDetails,BookDetails,position_identity
from opening_book_reader import read_book,read_books
from opening_book_repository import OpeningBookRepository
from opening_book_service import OpeningBookService
from opening_book_session import OpeningBookSession
from opening_intelligence_models import OpeningMatchPolicy,OpeningQuery,OpeningFailure
from opening_intelligence_lookup import OpeningBookLookup
from opening_intelligence_application import assess_game
from opening_intelligence_service import OpeningIntelligenceService,matches_opening,variation_distribution,get_deviations
from opening_intelligence_presentation import opening_summary
from tests.test_opening_book import LibraryFixture
from tests.test_game_analysis import TemporaryAnalysis
from tests.opening_book_fixtures import add_line
from tests.opening_intelligence_fixtures import french_book,transposed_book,FRENCH_CASES,ucis,pgn


class OpeningKnowledgeTests(LibraryFixture):
    def setUp(self):
        super().setUp();self.bid=french_book(self.service)
        self.lookup=OpeningBookLookup.from_library(self.path,self.bid)

    def assess(self,key,user='white'):
        return assess_game(self.lookup,ucis(FRENCH_CASES[key]),user_color=user)

    def test_every_french_fixture_per_move_against_independent_graph_lookup(self):
        before=self.path.read_bytes();snapshot=self.repo.snapshot(self.bid)
        reachable=snapshot.reachable()
        positions={p.canonical_fen:p.position_id for p in snapshot.positions if p.position_id in reachable}
        for key,line in FRENCH_CASES.items():
            result=self.assess(key);board=chess.Board()
            for evidence,san in zip(result.moves,line.split()):
                position=positions.get(position_identity(board).canonical_fen)
                alternatives=snapshot.branches(position,active_only=True) if position else ()
                uci=board.parse_san(san).uci();edge=next((m for m in alternatives if m.move_uci==uci),None)
                self.assertEqual(evidence.position_id,position,(key,san))
                self.assertEqual(evidence.played_move_in_book,edge is not None,(key,san))
                self.assertEqual(evidence.played_weight,edge.weight if edge else None)
                self.assertEqual(evidence.preferred_move,next((m for m in alternatives if m.preferred),None))
                board.push_uci(uci);self.assertEqual(evidence.after_position,position_identity(board))
            self.assertEqual(result.total_plies,len(line.split()))
        self.assertEqual(before,self.path.read_bytes())

    def test_trunk_names_nested_and_nonpreferred(self):
        trunk=self.assess('trunk');self.assertTrue(trunk.entered_book);self.assertIsNone(trunk.final_named_variation)
        for key,name in [('advance','Advance Variation'),('exchange','Exchange Variation'),('tarrasch','Tarrasch Variation')]:
            result=self.assess(key);self.assertEqual(result.final_named_variation,name);self.assertIsNone(result.first_deviation)
        nested=self.assess('nested');self.assertEqual([v.name for v in nested.final_variation.path],['Nc3 branches','Winawer Variation','Advance structure'])
        row=self.assess('nonpreferred').moves[4]
        self.assertTrue(row.played_move_in_book);self.assertEqual(row.played_weight,40)
        self.assertEqual((row.preferred_move.san,row.preferred_move.weight),('e5',80))

    def test_deviations_owner_unknown_leaf_and_no_quality_judgments(self):
        for key,ply,owner in [('user_deviation',5,'user'),('opponent_deviation',6,'opponent')]:
            result=self.assess(key)
            self.assertEqual((result.first_deviation_ply,result.first_deviation.deviation_relation),(ply,owner))
            self.assertEqual(result.last_known_before_deviation.after_ply,ply-1)
            self.assertTrue(result.first_deviation.deviation)
        unknown=self.assess('user_deviation',None)
        self.assertIsNone(unknown.first_deviation.deviation_relation);self.assertIsNone(unknown.user_in_book_moves)
        leaf=self.assess('legal_outside');self.assertEqual(leaf.first_deviation.state,'continuation_not_authored')
        self.assertNotIn('mistake',opening_summary(leaf));self.assertNotIn('accuracy',asdict(leaf))

    def test_reentry_retains_unknown_interval_and_first_deviation(self):
        result=self.assess('reentry')
        self.assertEqual(result.reentry_count,1);self.assertTrue(result.moves[2].reentry)
        self.assertEqual([m.played_move_in_book for m in result.moves[:3]],[False,False,False])
        self.assertEqual(result.first_deviation_ply,1)
        self.assertEqual(result.final_named_variation,'Advance Variation')
        self.assertTrue(result.entered_book)
        self.assertGreater(result.last_known_position.after_ply,result.last_known_before_deviation.after_ply)

    def test_transposition_ambiguity_and_observed_route_preference(self):
        bid=transposed_book(self.service);lookup=OpeningBookLookup(self.repo.snapshot(bid))
        ambiguous=assess_game(lookup,ucis('Nc3 d5 d4 Nf6 Nf3'))
        self.assertTrue(ambiguous.final_variation.ambiguous)
        self.assertIsNone(ambiguous.final_named_variation)
        self.assertEqual({p[0].name for p in ambiguous.final_variation.paths},{'Pawn route','Knight route'})
        actual=assess_game(lookup,ucis('Nf3 d5 d4 Nf6 Nc3'))
        self.assertEqual(actual.final_named_variation,'Knight route')
        self.assertFalse(actual.final_variation.ambiguous)
        continuous=assess_game(lookup,ucis('d4 Nf6 Nf3 d5 Nc3'))
        self.assertEqual(continuous.final_named_variation,'Pawn route')

    def test_inferred_starting_context_cannot_resolve_later_ambiguity(self):
        bid=transposed_book(self.service);lookup=OpeningBookLookup(self.repo.snapshot(bid))
        board=chess.Board();board.push_san('d4')
        result=assess_game(lookup,ucis('d5 Nf3 Nf6',board.fen()),initial_fen=board.fen())
        self.assertEqual(result.initial_variation.deepest_name,'Pawn route')
        self.assertFalse(result.initial_variation.observed)
        self.assertTrue(result.final_variation.ambiguous)
        self.assertIsNone(result.final_named_variation)

    def test_meaningful_threshold_root_only_counts_and_policy(self):
        result=self.assess('never_entered');self.assertFalse(result.entered_book)
        self.assertGreaterEqual(len(result.known_book_positions),1)
        self.assertEqual(result.in_book_moves,0)
        quick=assess_game(self.lookup,ucis('e4 e6'))
        self.assertFalse(quick.entered_book)
        two=OpeningBookLookup(self.repo.snapshot(self.bid),policy=OpeningMatchPolicy(min_consecutive_plies=2))
        self.assertTrue(assess_game(two,ucis('e4 e6')).entered_book)
        self.assertNotEqual(two.provenance.policy_identity,self.lookup.provenance.policy_identity)

    def test_versioning_naming_weights_graph_and_snapshot_currentness(self):
        initial=self.assess('advance');edge=next(m for m in self.repo.snapshot(self.bid).moves if m.variation_name=='Advance Variation')
        details=MoveDetails(**{k:getattr(edge,k) for k in MoveDetails.__dataclass_fields__})
        self.service.edit_move(self.bid,edge.move_id,replace(details,variation_name='Renamed'))
        named=OpeningBookLookup.from_library(self.path,self.bid)
        self.assertFalse(initial.is_current(named.provenance))
        changes=named.provenance.changes_from(initial.provenance)
        self.assertIn('labels',changes);self.assertNotIn('membership',changes);self.assertNotIn('preferences',changes)
        self.service.edit_move(self.bid,edge.move_id,replace(details,weight=99))
        weighted=OpeningBookLookup.from_library(self.path,self.bid)
        self.assertIn('preferences',weighted.provenance.changes_from(initial.provenance))
        self.assertEqual(weighted.provenance.membership_identity,initial.provenance.membership_identity)
        self.service.edit_move(self.bid,edge.move_id,replace(details,active=False,preferred=False))
        graph=OpeningBookLookup.from_library(self.path,self.bid)
        self.assertIn('membership',graph.provenance.changes_from(initial.provenance))
        self.repo.update_book(self.bid,BookDetails('The French',version='2'))
        self.assertIn('version',OpeningBookLookup.from_library(self.path,self.bid).provenance.changes_from(graph.provenance))

    def test_read_only_legacy_without_migration_and_immutable_results(self):
        self.repo.connection.execute('ALTER TABLE book_moves DROP COLUMN variation_name')
        self.repo.connection.execute('ALTER TABLE book_moves DROP COLUMN variation_description')
        self.repo.connection.execute('PRAGMA user_version=1');self.repo.connection.commit()
        before=self.path.read_bytes();old=read_book(self.path,self.bid)
        self.assertTrue(all(not m.variation_name for m in old.moves));self.assertEqual(before,self.path.read_bytes())
        with self.assertRaises(FrozenInstanceError):self.assess('trunk').entered_book=False

    def test_context_bound_marks_uncertainty_without_affecting_played_membership(self):
        bid=transposed_book(self.service)
        lookup=OpeningBookLookup(self.repo.snapshot(bid),policy=OpeningMatchPolicy(max_variation_contexts=1))
        result=assess_game(lookup,ucis('Nc3 d5 d4 Nf6 Nf3'))
        self.assertFalse(result.final_variation.complete);self.assertTrue(result.final_variation.ambiguous)
        self.assertIsNone(result.final_named_variation)
        actual=assess_game(lookup,ucis('d4 Nf6 Nf3 d5 Nc3'))
        self.assertEqual(actual.in_book_moves,5);self.assertEqual(actual.final_named_variation,'Pawn route')

    def test_queries_and_portability(self):
        results=tuple(self.assess(k) for k in FRENCH_CASES)
        self.assertTrue(matches_opening(self.assess('advance'),OpeningQuery(variation_name='Advance Variation')))
        self.assertTrue(matches_opening(self.assess('opponent_deviation'),OpeningQuery(deviation_relation='opponent')))
        self.assertFalse(matches_opening(self.assess('never_entered')))
        self.assertIn('Advance Variation',variation_distribution(results));self.assertTrue(get_deviations(results))
        for path in Path('.').glob('opening_intelligence_*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.ImportFrom):self.assertFalse((node.module or '').startswith(('tkinter','merlin_ui','chess.engine')))


class StoredOpeningTests(TemporaryAnalysis):
    def setUp(self):
        super().setUp();self.library=Path(self.temp.name)/'opening.cwbook'
        self.repo=OpeningBookRepository.create(self.library);self.addCleanup(self.repo.close)
        self.bid=french_book(OpeningBookService(self.repo));self.lookup=OpeningBookLookup.from_library(self.library,self.bid)
        self.import_fixture(pgn(FRENCH_CASES['advance'],'opening1'))
        self.import_fixture(pgn(FRENCH_CASES['user_deviation'],'opening2'))
        self.service=OpeningIntelligenceService(self.path,self.lookup)

    def test_batch_scope_errors_explorer_and_zero_writes(self):
        before=self.digest();book=self.library.read_bytes()
        with patch.object(chess.engine.SimpleEngine,'popen_uci',side_effect=AssertionError('No engine')):
            batch=self.service.assess_games((1,2,1,9999))
            self.assertEqual(len(batch.assessments),2);self.assertEqual(len(batch.errors),1)
            self.assertEqual(batch.games_entered,2)
            from game_search_service import GameSearchService
            result=GameSearchService(self.path).search_openings(self.lookup,opening_query=OpeningQuery(variation_name='Advance Variation'))
            self.assertEqual([a.game_id for a in result.assessments],[1])
        self.assertEqual(before,self.digest());self.assertEqual(book,self.library.read_bytes())

    def test_corrupt_game_does_not_produce_completed_assessment(self):
        with closing(self.connect()) as db:
            db.execute("UPDATE moves SET fen_after=fen_before WHERE game_id=1 AND ply_number=1");db.commit()
        result=self.service.assess_games((1,2))
        self.assertEqual([a.game_id for a in result.assessments],[2]);self.assertEqual(result.errors[0].game_id,1)

    def test_review_refresh_book_rename_and_actual_proof_context(self):
        import tkinter as tk
        from merlin_ui.game_review_view import GameReviewView
        root=tk.Tk();root.withdraw();view=GameReviewView(root,database_path=self.path)
        before=self.digest()
        try:
            view.open_game_position(1,None);wait_for_opening(view);view.open_opening_facts()
            manager=view.opening_reference.service.library
            imported=manager.import_book(self.library,manager.preview_import(self.library),self.bid)
            for gid in (1,2):view.opening_reference.service.select(gid,imported.installation_id)
            view.opening_reference.refresh(force=True);wait_for_opening(view)
            panel=view.opening_panel;view._set_step(5)
            self.assertIn('Advance Variation',panel.summary.cget('text'))
            row=next(m for m in self.repo.snapshot(self.bid).moves if m.variation_name=='Advance Variation')
            managed=OpeningBookRepository.open(manager.get(imported.installation_id).path)
            try:OpeningBookService(managed).edit_move(self.bid,row.move_id,MoveDetails(variation_name='New authored name'))
            finally:managed.close()
            view.opening_reference.refresh(force=True);wait_for_opening(view);self.assertIn('New authored name',panel.summary.cget('text'))
            self.assertNotIn('Advance Variation',panel.summary.cget('text'))
            text=opening_summary(panel.assessment,5,proof=True)
            self.assertIn('actual game only',text)
            view.open_game_position(2,None);wait_for_opening(view);self.assertEqual(panel.assessment.game_id,2)
            self.assertEqual(self.digest(),before)
        finally:view.close()
