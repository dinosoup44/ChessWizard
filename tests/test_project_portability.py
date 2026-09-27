from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from backup_merlin import copy_project_files, validate_backup_location


class ProjectPortabilityTests(unittest.TestCase):
    def test_nested_backup_is_rejected_before_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            destination = source / "backups" / "snapshot"
            with self.assertRaises(ValueError):
                copy_project_files(source, destination, True)
            self.assertFalse(destination.exists())

    def test_sibling_backup_does_not_traverse_backup_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, backups = root / "ChessWizard", root / "Merlin_Backups"
            source.mkdir()
            backups.mkdir()
            (source / "module.py").write_text("value = 1")
            (backups / "previous.txt").write_text("historical backup")
            count, _ = copy_project_files(source, backups / "new", True)
            self.assertEqual(count, 1)
            self.assertEqual((backups / "new/module.py").read_text(), "value = 1")
            self.assertFalse((backups / "new/previous.txt").exists())

    def test_resolved_destination_cannot_alias_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            with self.assertRaises(ValueError):
                validate_backup_location(source, source / "folder" / "..")

    def test_game_review_entry_uses_shared_startup(self):
        import merlin_ui.game_review_view as view
        window = Mock()
        path = Path("isolated.db").resolve()
        with patch.object(view.tk, "Tk", return_value=window), patch.object(view, "GameReviewView") as create, patch.object(view, "prepare_database", return_value=path) as prepare:
            view.main()
        prepare.assert_called_once_with(window)
        create.assert_called_once_with(window, database_path=path)
        window.mainloop.assert_called_once_with()
