"""Temporary-only repertoire analysis contracts; no engine or owner data access."""
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import chess.engine
from candidate_line_repository import CandidateLineRepository
from move_quality_repository import MoveQualityRepository
from opening_analysis_service import OpeningAnalysisService
from opening_analysis_settings import OpeningAnalysisSettings
from opening_analysis_query import OpeningAnalysisQuery, filter_opening_games
from opening_analysis_accessors import (get_games_for_opening_book, get_variation_distribution,
    get_user_deviation_summary, get_opponent_deviation_summary, get_repertoire_gap_candidates,
    get_opening_accuracy_summary, get_variation_accuracy_summary)
from opening_analysis_statistics import summarize_gaps
from opening_book_models import BookDetails, MoveDetails
from opening_book_repository import OpeningBookRepository
from opening_book_service import OpeningBookService
from opening_book_session import OpeningBookSession
from opening_intelligence_lookup import OpeningBookLookup
from opening_library_service import OpeningLibraryService
from opening_repertoire import RepertoireSide, read_repertoire_side, with_repertoire_side
from tests.test_game_analysis import TemporaryAnalysis
from tests.opening_intelligence_fixtures import french_book, pgn
from tests.opening_book_fixtures import add_line
from tests.test_opening_accuracy import evidence


class OpeningAnalysisTests(TemporaryAnalysis):
    def setUp(self):
        super().setUp()
        guard = patch.object(chess.engine.SimpleEngine, 'popen_uci', side_effect=AssertionError('No engine'))
        guard.start(); self.addCleanup(guard.stop)
        self.library = OpeningLibraryService()
        self.lib = self.library.create_library('Analysis fixture')
        self.repo = OpeningBookRepository.open(self.lib.path)
        self.addCleanup(self.repo.close)
        self.author = OpeningBookService(self.repo)
        self.bid = french_book(self.author)
        self.author.set_repertoire_side(self.bid, RepertoireSide.WHITE)
        self.analysis = OpeningAnalysisService(self.path, self.library)

    def add_game(self, line, *, color='white', result='1-0'):
        index = self.count('games') + 1
        self.import_fixture(pgn(line, 'analysis-' + str(index)))
        with closing(self.connect()) as db:
            db.execute('UPDATE games SET user_color=?,result=? WHERE game_id=?', (color, result, index))
            db.commit()
        return index

    def run_scope(self, ids=None):
        return self.analysis.analyze_opening_book(self.lib.library_id, self.bid, ids)

    def store_evidence(self, gid, *, steps=None, losses=None):
        with closing(self.connect()) as db:
            for move in MoveQualityRepository(db).moves(gid):
                if steps is not None and move.step not in steps:
                    continue
                root, played = evidence(move, (losses or {}).get(move.step, 0))
                CandidateLineRepository(db).put(root)
                if played is not None:
                    CandidateLineRepository(db).put(played)
            db.commit()

    def test_side_metadata_legacy_validation_and_idempotent_author_edit(self):
        self.assertIsNone(read_repertoire_side('{}'))
        for side in RepertoireSide:
            metadata = with_repertoire_side('{"owner_note":"keep"}', side)
            details = BookDetails('Named arbitrarily', metadata_json=metadata)
            self.assertEqual(details.repertoire_side, side)
            self.assertEqual(json.loads(metadata)['owner_note'], 'keep')
        for invalid in ('red', None, 1, True):
            with self.assertRaises(ValueError):
                BookDetails('Bad', metadata_json=json.dumps({'repertoire_side': invalid}))
        before = self.repo.snapshot(self.bid)
        self.author.set_repertoire_side(self.bid, 'white')
        self.assertEqual(before, self.repo.snapshot(self.bid))
        self.author.set_repertoire_side(self.bid, 'black')
        after = self.repo.snapshot(self.bid)
        self.assertEqual(before.moves, after.moves)
        self.assertEqual(before.book.book_id, after.book.book_id)
        self.assertGreater(after.book.revision, before.book.revision)
        reopened = OpeningBookLookup.from_library(self.lib.path, self.bid)
        self.assertEqual(reopened.snapshot.book.repertoire_side, 'black')

    def test_unspecified_side_requires_explicit_choice_not_name_inference(self):
        self.repo.update_book(self.bid, BookDetails('The French'))
        with self.assertRaisesRegex(ValueError, 'repertoire side'):
            self.run_scope()

    def test_white_black_both_and_wrong_side_do_not_load_quality(self):
        a = self.add_game('e4 e6 d4 d5', color='white')
        b = self.add_game('e4 e6 d4 d5 e5', color='black')
        for side, expected in (('white', (a,)), ('black', (b,)), ('both', (a, b))):
            self.author.set_repertoire_side(self.bid, side)
            result = self.run_scope()
            self.assertFalse(result.matching_set.errors)
            self.assertEqual(result.matching_set.game_ids, expected)
            self.assertEqual(result.matching_set.meaningful_before_side, 2)
        self.author.set_repertoire_side(self.bid, 'black')
        with patch('opening_analysis_service.assess_opening_evidence', side_effect=AssertionError('Wrong-side read')):
            result = self.run_scope((a,))
        self.assertEqual(result.matching_set.exclusions[0].reason, 'wrong_repertoire_side')

    def test_meaningful_trunk_nested_and_nonmatching_initial_position(self):
        trunk = self.add_game('e4 e6 d4 d5')
        nested = self.add_game('e4 e6 d4 d5 Nc3 Bb4 e5 c5')
        other = self.add_game('e4 c5 Nf3 Nc6')
        result = self.run_scope()
        self.assertEqual(result.matching_set.game_ids, (trunk, nested))
        self.assertEqual(result.matching_set.exclusions[0].game_id, other)
        self.assertEqual(result.variations[0].context.path, ())
        self.assertEqual(tuple(node.name for node in result.variations[1].context.path),
                         ('Nc3 branches', 'Winawer Variation', 'Advance structure'))
        self.assertEqual(result.games[1].meaningful_match_depth, 8)

    def test_full_evidence_and_out_of_book_engine_best_are_independent(self):
        gid = self.add_game('e4 e6 d4 d5 a3')
        self.store_evidence(gid)
        result = self.run_scope()
        game = result.games[0]
        self.assertEqual((game.adherence.in_book_moves, game.adherence.opportunities), (2, 3))
        first = game.first_user_deviation
        self.assertEqual((first.book.ply, first.book.played_san), (5, 'a3'))
        self.assertEqual((first.quality.eval_loss_cp, first.quality.accuracy), (0, 100))
        self.assertTrue(first.quality.best_move_match)
        self.assertNotEqual(first.quality.best_move, first.book.preferred_move.move_uci)
        self.assertEqual(result.accuracy.status, 'complete')
        self.assertEqual((result.accuracy.quality.total_moves, result.accuracy.coverage_percentage), (3, 100))
        self.assertEqual(result.accuracy.quality.accuracy, 100)

    def test_partial_evidence_is_missing_not_zero_or_perfect(self):
        gid = self.add_game('e4 e6 d4 d5 a3')
        self.store_evidence(gid, steps={1})
        result = self.run_scope()
        self.assertEqual((result.accuracy.status, result.accuracy.missing_evidence), ('partial', 2))
        self.assertEqual(result.accuracy.quality.accuracy, 100)
        self.assertAlmostEqual(result.accuracy.coverage_percentage, 100/3)
        self.assertEqual(filter_opening_games(result, OpeningAnalysisQuery(accuracy_min=99, require_complete_accuracy=False)), result.games)
        self.assertFalse(filter_opening_games(result, OpeningAnalysisQuery(accuracy_min=99)))

    def test_black_user_only_accuracy(self):
        self.author.set_repertoire_side(self.bid, 'black')
        gid = self.add_game('e4 e6 d4 d5 e5', color='black')
        self.store_evidence(gid, losses={1:1000})
        result = self.run_scope()
        self.assertEqual(result.accuracy.quality.accuracy, 100)
        self.assertEqual(result.accuracy.quality.total_moves, 2)

    def test_opponent_departure_does_not_penalize_unknown_user_moves(self):
        gid = self.add_game('e4 e6 d4 d5 e5 a6 Nf3 h6 Bd3 g6')
        game = self.run_scope((gid,)).games[0]
        self.assertEqual((game.adherence.in_book_moves, game.adherence.opportunities), (3, 3))
        self.assertIsNone(game.first_user_deviation)
        self.assertEqual(game.first_opponent_deviation.book.ply, 6)
        self.assertEqual(game.accuracy.user.quality.total_moves, 5)
        self.assertFalse(game.book.moves[6].position_in_book)

    def test_late_reentry_resumes_adherence_but_does_not_reopen_expired_accuracy(self):
        gid = self.add_game('e4 e6 d4 d5 Nf3 Nf6 Ng5 Ng4 Nf3 Nf6 Ng1 Ng8 e5 c5')
        result = self.run_scope((gid,))
        game = result.games[0]
        self.assertEqual(game.accuracy.phase.end_ply, 8)
        self.assertEqual((game.adherence.in_book_moves, game.adherence.opportunities), (3, 4))
        self.assertEqual(game.book.moves[12].state, 'in_book')
        self.assertFalse(game.book.moves[10].position_in_book)
        self.assertTrue(any(not row.within_accuracy_window for row in result.reentries))
        self.assertEqual(result.variations[0].context.deepest_name, 'Advance Variation')
        self.assertIsNone(result.variation_accuracy[0].context.deepest_name)

    def test_active_nonpreferred_counts_and_first_departures_are_separate(self):
        a = self.add_game('e4 e6 d4 d5 exd5 exd5 Nf3')
        b = self.add_game('e4 e6 d4 d5 e5 a6')
        result = self.run_scope((a, b))
        game = result.games[0]
        self.assertEqual(game.adherence.percentage, 100)
        self.assertFalse(game.book.moves[4].available_moves[1].preferred)
        self.assertIsNone(game.first_user_deviation)
        self.assertEqual(result.games[1].first_opponent_deviation.book.played_san, 'a6')

    def test_user_position_groups_actual_moves_and_quality_distribution(self):
        a = self.add_game('e4 e6 d4 d5 a3')
        b = self.add_game('e4 e6 d4 d5 h3')
        self.store_evidence(a, losses={5:100})
        self.store_evidence(b, losses={5:300})
        result = self.run_scope()
        group = result.user_deviations[0]
        self.assertEqual((group.count, len(group.game_ids), len(group.moves)), (2, 2, 2))
        self.assertEqual(group.quality.average_loss_cp, 200)
        self.assertEqual(group.quality.median_loss_cp, 200)
        self.assertEqual(sorted(v for move in group.moves for v in move.accuracies), [10, 50])
        self.assertEqual(result.games[0].first_user_deviation.fen_before,
                         result.games[0].first_user_deviation.quality.move.fen)

    def test_gap_requires_distinct_games_and_no_resulting_continuation(self):
        a = self.add_game('e4 e6 d4 d5 e5 a6')
        b = self.add_game('e4 e6 d4 d5 e5 a6 Nf3')
        result = self.run_scope()
        self.assertEqual(len(result.repertoire_gaps), 1)
        gap = result.repertoire_gaps[0]
        self.assertEqual((gap.signal, gap.count, gap.game_ids), ('repertoire_gap_candidate', 2, (a, b)))
        self.assertFalse(summarize_gaps((result.games[0], result.games[0])))
        self.assertFalse(summarize_gaps(result.games, OpeningAnalysisSettings(gap_minimum_games=3)))
        with_continuation = replace(result.games[0].deviations[0], continuations=(result.games[0].book.moves[0].available_moves[0],))
        self.assertFalse(summarize_gaps(tuple(replace(game, deviations=(replace(with_continuation,
            book=game.deviations[0].book),)) for game in result.games)))

    def test_pooled_accuracy_not_mean_of_game_means(self):
        a = self.add_game('e4 e6 d4 d5')
        b = self.add_game('e4 e6 d4 d5 a3')
        self.store_evidence(a)
        self.store_evidence(b, losses={5:100})
        result = self.run_scope()
        self.assertEqual(result.accuracy.quality.accuracy, 90)
        summary = result.variation_accuracy[0]
        self.assertEqual(summary.accuracy.quality.accuracy, 90)
        self.assertAlmostEqual(summary.average_game_accuracy, (100 + 250/3)/2)
        self.assertEqual(summary.scored_games, 2)
        self.assertEqual(summary.complete_games, 2)

    def test_query_hooks_accessors_and_descriptive_context(self):
        a = self.add_game('e4 e6 d4 d5 a3', result='0-1')
        b = self.add_game('e4 e6 d4 d5 exd5 exd5', result='1/2-1/2')
        self.store_evidence(a, losses={5:300})
        result = self.run_scope()
        self.assertEqual(get_games_for_opening_book(result), result.games)
        self.assertEqual(get_variation_distribution(result), result.variations)
        self.assertEqual(get_user_deviation_summary(result), result.user_deviations)
        self.assertEqual(get_opponent_deviation_summary(result), result.opponent_deviations)
        self.assertEqual(get_repertoire_gap_candidates(result), result.repertoire_gaps)
        self.assertEqual(get_opening_accuracy_summary(result), result.accuracy)
        self.assertEqual(get_variation_accuracy_summary(result), result.variation_accuracy)
        self.assertEqual(dict(result.contexts.results), {'draw':1, 'loss':1})
        self.assertEqual(tuple(g.context.game_id for g in filter_opening_games(result,
            OpeningAnalysisQuery(minimum_deviation_loss_cp=200, user_deviated=True, adherence_max=90))), (a,))
        self.assertEqual(tuple(g.context.game_id for g in filter_opening_games(result,
            OpeningAnalysisQuery(variation_name='Exchange Variation'))), (b,))
        self.assertFalse(filter_opening_games(result, OpeningAnalysisQuery(library_identity='elsewhere')))
        self.assertEqual(tuple(g.context.game_id for g in filter_opening_games(result,
            OpeningAnalysisQuery(accuracy_min=0, user_deviated=False, require_complete_accuracy=False))), (b,))
        self.assertEqual(result.games[1].accuracy.user.status, 'partial')
        for args in ({'accuracy_min':101}, {'adherence_min':90,'adherence_max':80}, {'minimum_deviation_loss_cp':float('nan')}):
            with self.assertRaises(ValueError): OpeningAnalysisQuery(**args)

    def test_readonly_stable_rerun_and_result_currentness(self):
        gid = self.add_game('e4 e6 d4 d5 a3')
        before_db = self.digest()
        before_book = hashlib.sha256(Path(self.lib.path).read_bytes()).hexdigest()
        a = self.run_scope((gid, gid))
        b = self.run_scope((gid,))
        self.assertEqual(a, b)
        self.assertEqual(before_db, self.digest())
        self.assertEqual(before_book, hashlib.sha256(Path(self.lib.path).read_bytes()).hexdigest())
        self.assertEqual(self.count('game_collections'), 0)
        self.store_evidence(gid)
        c = self.run_scope((gid,))
        self.assertNotEqual(c.result_identity, a.result_identity)
        self.author.set_repertoire_side(self.bid, 'both')
        self.assertNotEqual(c.result_identity, self.run_scope((gid,)).result_identity)
        changed = OpeningAnalysisService(self.path, self.library, settings=OpeningAnalysisSettings(gap_minimum_games=3))
        self.assertNotEqual(changed.analyze_opening_book(self.lib.library_id, self.bid).result_identity,
                            self.run_scope().result_identity)

    def test_empty_invalid_and_unknown_user_scope(self):
        self.assertFalse(self.run_scope(()).games)
        with self.assertRaises(ValueError): self.run_scope((True,))
        gid = self.add_game('e4 e6 d4 d5', color=None)
        result = self.run_scope((gid, 999))
        self.assertEqual(result.matching_set.exclusions[0].reason, 'unknown_user_color')
        self.assertEqual(result.matching_set.errors[0].game_id, 999)
        with closing(self.connect()) as db:
            db.execute("INSERT INTO users(lichess_username) VALUES('SecondOwner')")
            owner = db.execute('SELECT max(user_id) FROM users').fetchone()[0]
            db.commit()
        other = self.add_game('e4 e6 d4 d5 e5')
        with closing(self.connect()) as db:
            db.execute('UPDATE games SET user_id=? WHERE game_id=?', (owner, other)); db.commit()
        with self.assertRaisesRegex(ValueError, 'multiple owners'): self.run_scope()
        selected = self.analysis.analyze_opening_book(self.lib.library_id, self.bid, (gid, other), user_id=owner)
        self.assertEqual(selected.matching_set.game_ids, (other,))

    def test_metadata_survives_export_import_and_clone(self):
        from opening_library_package import write_package
        export = Path(self.temp.name) / 'side-preserved.cwbook'
        write_package(self.repo.snapshot(self.bid), export)
        self.assertEqual(OpeningBookLookup.from_library(export, 1).snapshot.book.repertoire_side, 'white')
        preview = self.library.preview_import(export)
        imported = self.library.import_book(export, preview, 1)
        cloned = self.library.clone_book(imported.installation_id, 'Explicit side clone')
        self.assertEqual(self.library.get(cloned.installation_id).snapshot.book.repertoire_side, 'white')

    def test_equal_named_anchors_remain_distinct_groups(self):
        snapshot = self.repo.snapshot(self.bid)
        move = next(edge for edge in snapshot.moves if edge.variation_name == 'Exchange Variation')
        self.author.edit_move(self.bid, move.move_id, MoveDetails(variation_name='Advance Variation'))
        self.add_game('e4 e6 d4 d5 e5 c5')
        self.add_game('e4 e6 d4 d5 exd5 exd5')
        result = self.run_scope()
        self.assertEqual(len(result.variations), 2)
        self.assertEqual(result.variations[0].context.deepest_name, result.variations[1].context.deepest_name)
        self.assertNotEqual(result.variations[0].context.path, result.variations[1].context.path)
        self.assertEqual(len(result.variation_accuracy), 2)
        anchor = result.variations[0].context.path[0].move_id
        self.assertEqual(len(filter_opening_games(result, OpeningAnalysisQuery(variation_move_id=anchor))), 1)

    def test_public_core_can_import_without_tk_or_engine_start(self):
        script = "import sys; import opening_analysis_service, opening_analysis_accessors; assert 'tkinter' not in sys.modules"
        completed = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
