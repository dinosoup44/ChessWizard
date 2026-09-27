"""Current-board Studio handoff regressions with temporary games and libraries."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
import chess
from opening_book_models import BookDetails, position_identity
from opening_book_session import OpeningBookSession
from opening_studio_handoff import studio_source_step
from tests.opening_book_fixtures import add_line
from tests.opening_intelligence_fixtures import pgn
from tests.opening_ui_wait import wait_for_opening
from tests.test_opening_workspace import OpeningWorkspaceFixture


class CurrentPositionHandoffTests(OpeningWorkspaceFixture):
    def capture(self):
        receiver = Mock()
        with patch.object(self.view, 'open_opening_book_studio'), patch.object(
                self.view, 'opening_book_studio', SimpleNamespace(receive_handoff=receiver), create=True):
            self.view.open_opening_context()
        receiver.assert_called_once()
        return receiver.call_args.args[0]

    def assert_current(self, step):
        self.assertEqual(self.view.current_step, step)
        self.assertFalse(self.panel.studio_button.instate(['disabled']))
        handoff = self.capture()
        self.assertEqual(handoff.source_game_id, self.view.current_game['game_id'])
        self.assertEqual(handoff.source_ply, step)
        self.assertEqual(handoff.requested_position, position_identity(self.view.board_widget.board))
        self.assertEqual(handoff.anchor.library_identity, self.lib.library_id)
        self.assertEqual(handoff.anchor.book_id, self.bid)
        return handoff

    def test_moment_next_previous_and_actual_click_use_visible_cursor(self):
        self.analyze();self.space.games_grid.selection_set('1');self.root.update()
        before = self.digest(), self.repo.path.read_bytes()
        self.panel.select_moment(6)
        self.assertEqual(self.assert_current(5).candidate_moves, ())
        self.panel.forward.invoke()
        self.assertEqual(self.assert_current(6).candidate_moves, ('a7a6',))
        self.panel.back.invoke()
        self.assertEqual(self.assert_current(5).candidate_moves, ())
        self.view.actual_moves.on_jump(2)
        self.assert_current(2)
        for step in range(3, 7):
            self.view.next_move();self.assert_current(step)
        self.assertEqual((self.digest(), self.repo.path.read_bytes()), before)

    def test_stale_moment_and_browsed_game_cannot_override_board(self):
        self.analyze();self.view._set_step(6)
        self.space.games_grid.selection_set('2');self.root.update()
        self.assertEqual(self.panel.assessment.game_id, 2)
        self.panel.selected_ply = 5
        self.view.opening_anchor_ply = 999
        handoff = self.assert_current(6)
        self.assertEqual((handoff.source_game_id, handoff.candidate_moves), (1, ('a7a6',)))

    def test_all_tabs_summary_and_drilldown_keep_displayed_position(self):
        self.analyze();self.view._set_step(6)
        for tree in (self.space.games_grid, self.space.variations, self.space.deviations, self.space.gaps):
            with self.subTest(tab=tree):
                self.space.tabs.select(tree.master);self.root.update()
                tree.selection_set(tree.get_children()[0]);self.root.update()
                self.assert_current(6)
                if tree is not self.space.games_grid:
                    rows = self.space.affected.tree.get_children()
                    self.assertTrue(rows)
                    self.space.affected.tree.selection_set(rows[0]);self.root.update()
                    self.assert_current(6)
                self.view.previous_move();self.assert_current(5)
                self.view.next_move();self.assert_current(6)

    def test_be7_and_followup_stage_minimum_suffix_without_duplicate_authoring(self):
        # Representative owner-reported 4...Be7 route; all storage is temporary.
        author = OpeningBookSession(self.author, self.bid)
        add_line(author, 'e4 e6 d4 d5 Nc3 Nf6 Bg5')
        self.import_fixture(pgn('e4 e6 d4 d5 Nc3 Nf6 Bg5 Be7 e5 Nfd7 Bxe7 Qxe7', 'be7-cursor'))
        self.picker.refresh(force=True);wait_for_opening(self.view)
        self.view.open_game_position(8, None);wait_for_opening(self.view)
        before = self.digest(), self.repo.path.read_bytes()
        self.view.show_opening_moment(8)
        self.assertEqual(self.assert_current(7).candidate_moves, ())
        self.view.next_move()
        self.assertEqual(self.assert_current(8).candidate_moves, ('f8e7',))
        self.view.previous_move();self.assert_current(7)
        self.view.next_move();self.view.next_move()
        handoff = self.assert_current(9)
        self.assertEqual(handoff.candidate_moves, ('f8e7', 'e4e5'))
        self.assertEqual(handoff.anchor.path, tuple(author.history))
        self.view.open_opening_context();studio = self.view.opening_book_studio
        self.assertEqual(studio.staged_review.handoff, handoff)
        self.assertEqual((self.digest(), self.repo.path.read_bytes()), before)
        snapshot = self.repo.snapshot(self.bid)
        with patch('merlin_ui.opening_studio_handoff.confirm_book_line', return_value='Be7 game line'):
            studio.staged_review.confirm()
        after = self.repo.snapshot(self.bid)
        self.assertEqual(len(after.moves), len(snapshot.moves) + 2)
        self.assertTrue(set(snapshot.moves).issubset(set(after.moves)))
        wait_for_opening(self.view)
        self.assertEqual(self.assert_current(9).candidate_moves, ())
        saved = self.repo.path.read_bytes()
        for _ in range(2):
            self.view.open_opening_context()
            self.assertIsNone(studio.staged_review.handoff)
            self.assertEqual(position_identity(studio.session.board), handoff.requested_position)
        self.assertEqual(self.repo.path.read_bytes(), saved)
        self.assertEqual(self.digest(), before[0])

    def test_transposition_reuses_exact_authored_branch_without_staging(self):
        self.view.open_game_position(5, None);wait_for_opening(self.view)
        self.view._set_step(3)
        before = self.repo.path.read_bytes()
        handoff = self.assert_current(3)
        self.assertEqual(handoff.candidate_moves, ())
        self.view.open_opening_context()
        studio = self.view.opening_book_studio
        self.assertIsNone(studio.staged_review.handoff)
        self.assertEqual(position_identity(studio.session.board), handoff.requested_position)
        self.assertEqual(self.repo.path.read_bytes(), before)

    def test_authored_exploration_uses_its_anchor_and_return_restores_actual_cursor(self):
        self.view._set_step(6)
        row = self.picker.summary_session.assessment.moves[5]
        self.panel.explore(6, row.available_moves[0].move_id)
        self.assertEqual(self.view.current_step, 6)
        state = self.view.opening_exploration
        handoff = self.capture()
        self.assertEqual(handoff.source_ply, state.anchor_ply - 1)
        self.assertEqual(handoff.requested_position, position_identity(state.fen))
        self.assertEqual(handoff.candidate_moves, ())
        self.panel.return_button.invoke()
        self.assertEqual(self.assert_current(6).candidate_moves, ('a7a6',))

    def test_game_and_opening_changes_never_reuse_loading_or_old_context(self):
        self.view._set_step(6)
        self.view.open_game_position(2, None)
        self.assertTrue(self.panel.studio_button.instate(['disabled']))
        wait_for_opening(self.view)
        self.assert_current(0)
        self.view._set_step(5)
        self.assertEqual(self.assert_current(5).candidate_moves, ('h2h3',))
        self.picker.picker.current(0);self.picker.select()
        self.assertTrue(self.panel.studio_button.instate(['disabled']))
        with patch.object(self.view, 'open_opening_book_studio') as launch:
            self.view.open_opening_context();launch.assert_not_called()
        other = self.author.create_book(BookDetails('Different Opening'))
        self.picker.refresh(force=True)
        item = next(b for b in self.library.get_library(self.lib.library_id).books if b.snapshot.book.book_id == other)
        self.picker.service.select(2, item.installation_id);self.picker.refresh(force=True)
        self.assertTrue(self.panel.studio_button.instate(['disabled']))
        wait_for_opening(self.view)
        self.assertFalse(self.panel.studio_button.instate(['disabled']))
        handoff = self.capture()
        self.assertEqual(handoff.anchor.book_id, other)
        self.assertEqual(handoff.source_game_id, 2)
        self.assertEqual(handoff.candidate_moves, tuple(m['uci_played'] for m in self.view.moves[:5]))

    def test_invalid_board_proof_playback_and_empty_game_do_not_handoff(self):
        self.view._set_step(6)
        self.view.board_widget.board = chess.Board()
        self.picker.refresh_summary()
        self.assertTrue(self.panel.studio_button.instate(['disabled']))
        with patch.object(self.view, 'open_opening_book_studio') as launch:
            self.view.open_opening_context();launch.assert_not_called()
        self.view.refresh_all();self.assert_current(6)
        with patch.object(self.view, 'line_playback', object()):
            self.assertFalse(self.view.can_open_opening_studio())
        with patch.object(self.view, 'current_game', None):
            self.assertFalse(self.view.can_open_opening_studio())
        with patch.object(self.view, 'moves', []):
            self.assertFalse(self.view.can_open_opening_studio())

    def test_source_validation_rejects_stale_facts_and_route(self):
        self.view._set_step(5)
        session = self.picker.summary_session
        args = (session.lookup, session.assessment, self.view.moves, 1, 5, self.view.board_widget.board.fen())
        self.assertEqual(studio_source_step(*args), 5)
        for changes in ({'game_id': 2}, {'actual_step': 99}, {'actual_step': -1},
                        {'assessment': replace(session.assessment, game_id=2)},
                        {'displayed_fen': chess.STARTING_FEN},
                        {'moves': [dict(m, uci_played='a2a4') for m in self.view.moves]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                values = dict(zip(('lookup','assessment','moves','game_id','actual_step','displayed_fen'), args))
                studio_source_step(**(values | changes))

    def test_navigation_uses_loaded_facts_without_graph_reads_or_engine(self):
        self.view._set_step(1)
        with patch('opening_intelligence_review.read_book', side_effect=AssertionError('No graph reads')), \
             patch('opening_intelligence_review.OpeningIntelligenceService.assess_game', side_effect=AssertionError('No assessment reads')):
            for step in range(2, 7):
                self.view.next_move();self.assert_current(step)
            for step in range(5, -1, -1):
                self.view.previous_move();self.assert_current(step)
