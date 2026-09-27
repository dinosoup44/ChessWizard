"""Proposal lifecycle regressions using an isolated Review/Studio library."""
from contextlib import closing
from dataclasses import replace
from unittest.mock import patch
import chess
from opening_book_models import MoveDetails, position_identity
from opening_book_repository import OpeningBookRepository
from opening_studio_handoff import handoff_disposition
from tests.test_opening_workspace import OpeningWorkspaceFixture
from tests.opening_ui_wait import wait_for_opening


class StudioHandoffCleanupTests(OpeningWorkspaceFixture):
    def stage(self):
        self.analyze()
        self.view.show_opening_moment(6)
        self.view.next_move()
        wait_for_opening(self.view)
        self.view.open_opening_context()
        studio = self.view.opening_book_studio
        return studio, studio.staged_review.handoff

    def test_automatic_whole_route_atomic_once(self):
        studio, handoff = self.stage()
        before = studio.session.snapshot
        game_before = self.digest()
        board = chess.Board(handoff.anchor.fen)
        moves = ('a7a6', 'g1f3', 'b8c6')
        for move in moves:board.push_uci(move)
        handoff = replace(handoff, candidate_moves=moves, requested_position=position_identity(board))
        staged = studio.staged_review
        staged.show(handoff)
        self.assertEqual(staged.create_button['text'], 'Create Variation from Game')
        with patch('merlin_ui.opening_studio_handoff.confirm_book_line', return_value='Game continuation'):
            staged.confirm()
        after = studio.repository.snapshot(studio.session.book_id)
        self.assertEqual(len(after.moves), len(before.moves) + 3)
        self.assertTrue(set(before.moves).issubset(set(after.moves)))
        self.assertIsNone(staged.handoff)
        stable = studio.repository.path.read_bytes()
        staged.confirm()
        staged.show(handoff)
        staged.confirm()
        self.assertEqual(studio.repository.path.read_bytes(), stable)
        self.assertIn('already exists', staged.message['text'])
        self.assertEqual(self.digest(), game_before)

    def test_manual_save_rename_reopen_retains_ids_notes_and_no_second_commit(self):
        studio, handoff = self.stage()
        before = studio.session.snapshot
        game_before = self.digest()
        studio.session.stage(handoff.candidate_moves[0])
        details = MoveDetails(variation_name='Working line', move_note='Owner annotation',
                              instructional_note='Watch the fork', metadata_json='{"source":"game fixture"}')
        studio.set_details(details)
        studio.save_pending()
        new_id = studio.session.history[-1]
        self.assertIsNone(studio.staged_review.handoff)
        self.assertIn('already exists', studio.staged_review.message['text'])
        with patch('merlin_ui.opening_studio_workflow.simpledialog.askstring', return_value='Fork Alert'):
            studio.rename_line()
        after = studio.repository.snapshot(studio.session.book_id)
        added = next(m for m in after.moves if m.move_id == new_id)
        self.assertEqual(added.variation_name, 'Fork Alert')
        self.assertEqual(added.move_note, details.move_note)
        self.assertEqual(added.instructional_note, details.instructional_note)
        self.assertEqual(added.metadata_json, details.metadata_json)
        self.assertTrue(set(before.moves).issubset(set(after.moves)))
        stable = studio.repository.path.read_bytes()
        studio.staged_review.show(handoff)
        studio.staged_review.confirm()
        self.assertEqual(studio.repository.path.read_bytes(), stable)
        path, bid = studio.repository.path, studio.session.book_id
        self.assertTrue(studio.close())
        with closing(OpeningBookRepository.open(path)) as reopened:
            self.assertEqual(reopened.snapshot(bid), after)
        self.view.open_opening_book_studio()
        reopened_studio = self.view.opening_book_studio
        self.assertIsNone(reopened_studio.staged_review.handoff)
        self.assertEqual(self.digest(), game_before)

    def test_stale_callback_checks_fresh_graph_before_anchor_or_dialog(self):
        studio, handoff = self.stage()
        # Another author commits the route while this Studio still holds the old snapshot.
        self.author.save_move(self.bid, handoff.anchor.fen, handoff.candidate_moves[0], MoveDetails(variation_name='Other save'))
        stable = studio.repository.path.read_bytes()
        with patch('merlin_ui.opening_studio_handoff.confirm_book_line', side_effect=AssertionError('No duplicate confirmation')):
            studio.staged_review.confirm()
        self.assertIsNone(studio.staged_review.handoff)
        self.assertEqual(studio.repository.path.read_bytes(), stable)
        self.assertIn('already exists', studio.staged_review.message['text'])

    def test_partial_manual_path_retires_without_claiming_completion(self):
        studio, handoff = self.stage()
        board = chess.Board(handoff.anchor.fen)
        moves = ('a7a6', 'g1f3')
        for move in moves:board.push_uci(move)
        handoff = replace(handoff, candidate_moves=moves, requested_position=position_identity(board))
        studio.staged_review.show(handoff)
        studio.session.stage(moves[0]);studio.save_pending()
        self.assertIsNone(studio.staged_review.handoff)
        self.assertIn('normal Save Move', studio.staged_review.message['text'])
        self.assertNotIn('already exists', studio.staged_review.message['text'])
        studio.session.stage(moves[1]);studio.save_pending()
        self.assertEqual(handoff_disposition(studio.session.snapshot, self.lib.library_id, handoff), 'satisfied')

    def test_different_library_or_inactive_edge_is_not_satisfied(self):
        studio, handoff = self.stage()
        self.assertEqual(handoff_disposition(studio.session.snapshot, 'other-library', handoff), 'superseded')
        mid = self.author.save_move(self.bid, handoff.anchor.fen, handoff.candidate_moves[0], MoveDetails(active=False))
        snapshot = self.repo.snapshot(self.bid)
        self.assertEqual(handoff_disposition(snapshot, self.lib.library_id, handoff), 'superseded')
        studio.staged_review.confirm()
        self.assertFalse(next(m for m in self.repo.snapshot(self.bid).moves if m.move_id == mid).active)

    def test_proposal_retired_while_confirmation_open_is_harmless(self):
        studio, handoff = self.stage()
        def authored_elsewhere(*args):
            self.author.save_move(self.bid, handoff.anchor.fen, handoff.candidate_moves[0], MoveDetails())
            studio.session.refresh();studio.render()
            return 'Do not duplicate'
        before=len(studio.session.snapshot.moves)
        with patch('merlin_ui.opening_studio_handoff.confirm_book_line',side_effect=authored_elsewhere):
            studio.staged_review.confirm()
        self.assertEqual(len(self.repo.snapshot(self.bid).moves),before+1)
        self.assertIsNone(studio.staged_review.handoff)
