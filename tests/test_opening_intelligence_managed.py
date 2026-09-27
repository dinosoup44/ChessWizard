"""Managed identities, live snapshots and reusable opening queries in temp profiles."""
from tests.opening_ui_wait import wait_for_opening
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import tkinter as tk
import chess.engine
from opening_book_models import BookDetails, MoveDetails
from opening_book_repository import OpeningBookRepository
from opening_book_service import OpeningBookService
from opening_intelligence_lookup import OpeningBookLookup
from opening_intelligence_application import assess_game
from opening_intelligence_managed import ManagedOpeningIntelligenceService
from opening_intelligence_models import OpeningQuery
from opening_intelligence_service import matches_opening
from opening_intelligence_presentation import compact_opening_summary
from opening_library_service import OpeningLibraryService
from tests.test_game_analysis import TemporaryAnalysis
from tests.opening_intelligence_fixtures import french_book, transposed_book, FRENCH_CASES, pgn, ucis


class ManagedIntelligenceTests(TemporaryAnalysis):
    def setUp(self):
        super().setUp()
        guard = patch.object(chess.engine.SimpleEngine, 'popen_uci', side_effect=AssertionError('No engine'))
        guard.start(); self.addCleanup(guard.stop)
        self.library = OpeningLibraryService()
        created = self.library.create_library('My Openings')
        self.library_id = created.library_id
        self.repo = OpeningBookRepository.open(created.path)
        self.addCleanup(self.repo.close)
        self.author = OpeningBookService(self.repo)
        self.book_id = french_book(self.author)
        self.service = ManagedOpeningIntelligenceService(self.path, self.library)
        for index, name in enumerate(('advance', 'user_deviation', 'reentry', 'never_entered'), 1):
            self.import_fixture(pgn(FRENCH_CASES[name], 'managed-french-'+str(index)))

    def assess(self, game_id=1):
        return self.service.assess_game_against_book(game_id, self.library_id, self.book_id)

    def test_fresh_managed_identity_draft_batch_queries_and_failure_visibility(self):
        before = self.digest(); book = self.repo.path.read_bytes()
        result = self.assess()
        self.assertTrue(result.meaningful_match)
        self.assertEqual(result.provenance.library_identity, self.library_id)
        self.assertEqual(self.repo.snapshot(self.book_id).book.status, 'draft')
        self.assertTrue(all(m.provenance == result.provenance for m in result.moves))
        batch = self.service.assess_games_against_book((1, 2, 1, 99999), self.library_id, self.book_id)
        self.assertEqual([a.game_id for a in batch.assessments], [1, 2])
        self.assertEqual([e.game_id for e in batch.errors], [99999])
        found = self.service.get_games_for_opening_book(self.library_id, self.book_id)
        self.assertEqual([a.game_id for a in found.assessments], [1, 2, 3])
        reentered = self.service.get_games_for_opening_book(self.library_id, self.book_id,
            query=OpeningQuery(reentered_book=True))
        self.assertEqual([a.game_id for a in reentered.assessments], [3])
        distribution = self.service.variation_distribution(self.library_id, self.book_id, (1, 2, 3, 4, 99999))
        self.assertEqual(dict(distribution.counts), {'Advance Variation': 2, 'Unnamed trunk': 1})
        self.assertEqual((distribution.assessed_games, distribution.meaningful_matches), (4, 3))
        self.assertEqual(len(distribution.errors), 1)
        deviations = self.service.get_deviations(self.library_id, self.book_id, (2, 99999))
        self.assertEqual([(d.game_id, d.ply, d.deviation_relation) for d in deviations.deviations], [(2, 5, 'user')])
        self.assertEqual(deviations.deviations[0].provenance, deviations.provenance)
        self.assertEqual(len(deviations.errors), 1)
        self.assertEqual(before, self.digest()); self.assertEqual(book, self.repo.path.read_bytes())

    def test_book_selection_is_library_scoped_and_query_validated(self):
        empty = self.library.create_library('Other')
        with self.assertRaises(ValueError):
            self.service.assess_game_against_book(1, empty.library_id, self.book_id)
        with self.assertRaises(ValueError):
            self.service.assess_game_against_book(1, self.library_id, True)
        with self.assertRaises(ValueError):
            self.service.get_games_for_opening_book(self.library_id, self.book_id, query=OpeningQuery(entered_book=False))
        with self.assertRaises(ValueError): OpeningQuery(reentered_book='yes')

    def test_same_service_refreshes_naming_preference_and_graph_edits(self):
        original = self.assess()
        edge = next(m for m in self.repo.snapshot(self.book_id).moves if m.variation_name == 'Advance Variation')
        details = MoveDetails(**{key: getattr(edge, key) for key in MoveDetails.__dataclass_fields__})
        self.author.edit_move(self.book_id, edge.move_id, replace(details, variation_name='Advance renamed'))
        named = self.assess()
        self.assertEqual(named.final_named_variation, 'Advance renamed')
        self.assertEqual(named.provenance.membership_identity, original.provenance.membership_identity)
        self.assertIn('labels', named.provenance.changes_from(original.provenance))
        self.author.edit_move(self.book_id, edge.move_id, replace(details, weight=91, preferred=False))
        weighted = self.assess()
        self.assertEqual(weighted.moves[4].played_weight, 91)
        self.assertIsNone(weighted.moves[4].preferred_move)
        self.assertIn('preferences', weighted.provenance.changes_from(original.provenance))
        self.author.edit_move(self.book_id, edge.move_id, replace(details, active=False, preferred=False))
        changed = self.assess()
        self.assertEqual(changed.first_deviation_ply, 5)
        self.assertIn('membership', changed.provenance.changes_from(original.provenance))
        self.assertEqual(changed.provenance.library_identity, self.library_id)

    def test_explicit_fixture_expectations_every_ply_and_both_player_colors(self):
        lookup = OpeningBookLookup(self.repo.snapshot(self.book_id), library_identity=self.library_id)
        expected = {
            'trunk': '1111', 'advance': '111111111', 'exchange': '1111111',
            'tarrasch': '111111', 'nested': '11111111', 'user_deviation': '11110',
            'opponent_deviation': '111110', 'legal_outside': '1111110',
            'reentry': '000111111', 'never_entered': '0000', 'nonpreferred': '111111',
        }
        for name, bits in expected.items():
            result = assess_game(lookup, ucis(FRENCH_CASES[name]), user_color='black')
            self.assertEqual(''.join(str(int(m.played_move_in_book)) for m in result.moves), bits, name)
            for row in result.moves:
                self.assertEqual(row.deviation, row.position_in_book and not row.played_move_in_book)
                if row.deviation:
                    self.assertEqual(row.deviation_relation, 'user' if row.actor_color == 'black' else 'opponent')
        exact_end = assess_game(lookup, ucis('e4 e6 d4 d5 Nc3 Nf6'))
        self.assertIsNone(exact_end.first_deviation)
        self.assertEqual(exact_end.final_named_variation, 'Classical Variation')
        bid = transposed_book(self.author)
        ambiguous = assess_game(OpeningBookLookup(self.repo.snapshot(bid)), ucis('Nc3 d5 d4 Nf6 Nf3'))
        self.assertEqual([m.played_move_in_book for m in ambiguous.moves], [False]*5)
        self.assertTrue(ambiguous.final_variation.ambiguous)
        self.assertTrue(matches_opening(ambiguous, OpeningQuery(entered_book=False, reentered_book=True)))
        unknown = assess_game(lookup, ucis('e4 e6 d4 d5 a3'))
        self.assertIsNone(unknown.first_deviation.deviation_relation)
        self.assertIn('unknown owner', compact_opening_summary(unknown, 5))

    def test_inline_review_navigation_live_edits_and_none_clear(self):
        from merlin_ui.game_review_view import GameReviewView
        before = self.digest()
        root = tk.Tk(); root.withdraw()
        view = GameReviewView(root, database_path=self.path)
        try:
            view.open_game_position(1, None);wait_for_opening(view)
            item = self.library.get_library(self.library_id).books[0]
            picker = view.opening_reference
            picker.service.select(1, item.installation_id); picker.refresh(force=True);wait_for_opening(view)
            view._set_step(5)
            self.assertIn('Advance Variation', view.opening_panel.summary.cget('text'))
            self.assertEqual(view.opening_panel.assessment.total_plies,9)
            edge = next(m for m in self.repo.snapshot(self.book_id).moves if m.variation_name == 'Advance Variation')
            details = MoveDetails(**{key: getattr(edge, key) for key in MoveDetails.__dataclass_fields__})
            self.author.edit_move(self.book_id, edge.move_id, replace(details, variation_name='Live name'))
            picker.library_changed();wait_for_opening(view)
            self.assertIn('Live name', view.opening_panel.summary.cget('text'))
            self.assertNotIn('Advance Variation', view.opening_panel.summary.cget('text'))
            view._set_step(0)
            self.assertNotIn('Live name', view.opening_panel.summary.cget('text'))
            view.open_game_position(2, None);wait_for_opening(view)
            picker.service.select(2, item.installation_id); picker.refresh(force=True);wait_for_opening(view); view._set_step(5)
            self.assertEqual(view.opening_panel.assessment.first_deviation.played_san,'a3')
            self.assertIsNotNone(view.opening_panel.assessment.first_deviation.preferred_move)
            self.assertIn('proof line is separate', compact_opening_summary(picker.summary_session.assessment, 5, proof=True))
            if getattr(self, 'artifact_directory', None):
                from PIL import ImageGrab
                root.deiconify(); root.update()
                ImageGrab.grab(window=root.winfo_id()).save(Path(self.artifact_directory)/'inline_review.png')
            picker.service.select(2, None); picker.refresh(force=True);wait_for_opening(view)
            self.assertIn('Choose an Opening',view.opening_panel.summary.cget('text'))
            self.assertIsNone(picker.summary_session.assessment)
            self.assertEqual(self.digest(), before)
        finally:
            view.close()
