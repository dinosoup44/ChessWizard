"""Desktop navigation shares one owner and preserves view close contracts."""
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
from merlin_ui.application import ChessWizardApplication
from merlin_ui.game_review_view import GameReviewView


class DesktopApplicationTests(unittest.TestCase):
    def make_owner(self):
        review = object.__new__(GameReviewView)
        review.root = MagicMock()
        review.database_path = Path("isolated.db")
        review.training = None
        review.opening_book_window = None
        review.explorer_window = None
        review.connection = MagicMock()
        review.opening_workspace = MagicMock()
        review.stop_analysis_for_close = MagicMock(return_value=True)
        return review

    def test_training_reuses_profile_and_existing_window(self):
        review = self.make_owner()
        with patch("merlin_ui.game_review_view.tk.Toplevel"), \
             patch("merlin_ui.game_review_view.application_menu"), \
             patch("merlin_ui.candidate_viewer.CandidateViewer") as training:
            first = review.open_training()
            self.assertIs(review.open_training(), first)
            training.assert_called_once()
            self.assertEqual(training.call_args.kwargs["database_path"], review.database_path)
            first.root.lift.assert_called_once()

    def test_destroyed_training_window_can_reopen(self):
        review = self.make_owner()
        with patch("merlin_ui.game_review_view.tk.Toplevel"), \
             patch("merlin_ui.game_review_view.application_menu"), \
             patch("merlin_ui.candidate_viewer.CandidateViewer") as training:
            first = review.open_training()
            first.root.winfo_exists.return_value = False
            review.open_training()
            self.assertEqual(training.call_count, 2)

    def test_shutdown_uses_training_lifecycle_before_review(self):
        review = self.make_owner()
        review.training = MagicMock()
        order = MagicMock()
        order.attach_mock(review.training.close, "training")
        order.attach_mock(review.connection.close, "connection")
        review.close()
        self.assertEqual([c[0] for c in order.mock_calls], ["training", "connection"])
        review.root.destroy.assert_called_once()

    def test_unsaved_opening_book_can_veto_parent_close(self):
        review = self.make_owner()
        review.opening_book_window = MagicMock()
        review.opening_book_studio = MagicMock()
        review.opening_book_studio.close.return_value = False
        review.close()
        review.connection.close.assert_not_called()
        review.root.destroy.assert_not_called()

    def test_shutdown_closes_explorer_before_parent_connection(self):
        review = self.make_owner()
        review.explorer_window = MagicMock()
        review.explorer = MagicMock()
        order = MagicMock()
        order.attach_mock(review.explorer.close, "explorer")
        order.attach_mock(review.connection.close, "connection")
        review.close()
        self.assertEqual([c[0] for c in order.mock_calls], ["explorer", "connection"])

    def test_shutdown_with_no_training(self):
        review = self.make_owner()
        review.close()
        review.connection.close.assert_called_once()
        review.opening_workspace.close.assert_called_once()
        review.root.destroy.assert_called_once()

    def test_application_delegates_to_review_owner(self):
        with patch("merlin_ui.application.GameReviewView") as review, \
             patch("merlin_ui.application_menu.application_menu"):
            app = ChessWizardApplication(MagicMock(), Path("isolated.db"))
            self.assertIs(app.open_training(), review.return_value.open_training.return_value)
            app.close()
            review.return_value.close.assert_called_once()
