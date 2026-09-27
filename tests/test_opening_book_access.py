"""Studio access-mode regressions use isolated profiles and never start an engine."""
import os
from pathlib import Path
import stat
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

import chess
from opening_book_models import BookDetails, MoveDetails
from opening_book_reader import open_readonly_library
from opening_book_repository import OpeningBookRepository, ReadOnlyLibraryError
from opening_book_service import OpeningBookService
from opening_library_service import OpeningLibraryService
from merlin_ui.opening_book_studio import OpeningBookStudio

UI = "merlin_ui.opening_book_studio."


class StudioAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio-access-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        for guard in (patch.dict(os.environ, CHESSWIZARD_DATA_DIR=str(self.folder / "profile")),
                      patch("theme_core.active._default_service", None),
                      patch("chess.engine.SimpleEngine.popen_uci", side_effect=AssertionError("No engine")),
                      patch(UI + "messagebox.showerror", side_effect=AssertionError("Unexpected Studio error"))):
            guard.start(); self.addCleanup(guard.stop)
        self.library = OpeningLibraryService()
        self.root = tk.Tk(); self.root.withdraw()
        self.studio = OpeningBookStudio(self.root)
        self.addCleanup(self.close_studio)

    def close_studio(self):
        if self.studio:
            self.studio.dirty = False
            if self.studio.session:self.studio.session.discard()
            self.studio.close(); self.studio = None

    def new_book(self, name="Test book"):
        self.studio.new_book()
        self.studio.draft_title.set(name)
        self.studio.save_editor()

    def open_file(self, path):
        with patch(UI + "filedialog.askopenfilename", return_value=str(path)):self.studio.open_library()

    def new_library(self):
        self.new_book()
        return self.studio.repository.path

    def external(self):
        path = self.folder / "JL_Rep.cwbook"
        repo = OpeningBookRepository.create(path)
        try:OpeningBookService(repo).create_book(BookDetails("The French"))
        finally:repo.close()
        return path

    def assert_writable(self):
        self.assertFalse(self.studio.repository.read_only)
        self.assertEqual(self.studio.repository.connection.execute("PRAGMA query_only").fetchone()[0], 0)
        self.assertFalse(self.studio.library_buttons["New book"].instate(["disabled"]))

    def test_managed_new_book_save_rename_delete_and_metadata(self):
        path = self.new_library(); self.assert_writable()
        self.assertEqual(path.parent, self.folder / "profile" / "opening_books")
        self.studio.stage("e4"); self.studio.save_editor()
        move_id = self.studio.session.snapshot.moves[0].move_id
        self.studio.edit_move()
        field = self.studio.fields["variation_name"]
        field.delete("1.0", "end"); field.insert("1.0", "King pawn")
        self.studio.save_editor()
        move = self.studio.session.snapshot.moves[0]
        self.assertEqual((move.move_id, move.variation_name), (move_id, "King pawn"))
        with patch("merlin_ui.opening_studio_workflow.edit_fields", return_value=dict(name="Renamed", description="", version="1.1", status="active")):
            self.studio.edit_book()
        self.assertEqual(self.studio.session.snapshot.book.name, "Renamed")
        plan = self.studio.service.preview_deletion(self.studio.session.book_id, move_id, subtree=True)
        with patch(UI + "choose_deletion", return_value=plan):self.studio.delete_branch()
        self.assertEqual(self.studio.session.snapshot.moves, ())
        self.new_book("Another book")
        self.assertEqual(len(self.studio.repository.books()), 2)
        self.assertFalse(self.studio.repository.connection.execute("PRAGMA foreign_key_check").fetchall())

    def test_managed_path_reopened_through_file_dialog_is_not_preview(self):
        path = self.new_library()
        self.open_file(path); self.assert_writable(); self.new_book("Second")
        self.assertEqual(len(self.studio.repository.books()), 2)
        self.assertNotIn(str(path), self.studio.library_context.cget("text"))

    def test_restart_keeps_canonical_library_writable(self):
        path = self.new_library(); self.close_studio()
        self.root = tk.Tk(); self.root.withdraw(); self.studio = OpeningBookStudio(self.root)
        self.open_file(path); self.assert_writable(); self.new_book("After restart")
        self.assertEqual(len(self.studio.repository.books()), 2)

    def test_readonly_import_source_produces_writable_managed_copy(self):
        source = self.external(); before = source.read_bytes()
        source.chmod(stat.S_IREAD)
        try:
            imported = self.library.import_library(source, self.library.preview_import(source))
            self.open_file(imported.path); self.assert_writable(); self.new_book("Imported addition")
            self.studio.stage("d4"); self.studio.save_editor()
            self.assertEqual(len(self.studio.session.snapshot.moves), 1)
            self.assertEqual(source.read_bytes(), before)
            self.assertNotEqual(source, self.studio.repository.path)
            self.assertTrue(imported.path.stat().st_mode & stat.S_IWRITE)
        finally:source.chmod(stat.S_IREAD | stat.S_IWRITE)

    def test_clone_is_editable_and_original_unchanged(self):
        original = self.new_library(); before = original.read_bytes()
        item = self.library.list_books()[0]
        clone = self.library.clone_book(item.installation_id, "Clone")
        self.open_file(self.library.get(clone.installation_id).path)
        self.assert_writable(); self.studio.stage("d4"); self.studio.save_editor()
        self.assertEqual(original.read_bytes(), before)

    def test_external_controls_and_callbacks_never_attempt_writes(self):
        source = self.external(); before = source.read_bytes(); self.open_file(source)
        self.assertTrue(self.studio.repository.read_only)
        self.assertEqual(self.studio.repository.connection.execute("PRAGMA query_only").fetchone()[0], 1)
        for control in (self.studio.library_buttons["New book"], self.studio.library_buttons["Book details"],
                        self.studio.edit_button, self.studio.delete_button, self.studio.preview_button,
                        self.studio.save_button, *self.studio.note_buttons):
            self.assertTrue(control.instate(["disabled"]))
        statements = []; self.studio.repository.connection.set_trace_callback(statements.append)
        with patch(UI + "messagebox.showinfo") as info, patch(UI + "edit_fields", side_effect=AssertionError("No editing dialog")):
            for callback in (self.studio.new_book, self.studio.edit_book, self.studio.edit_move,
                             self.studio.save_editor, self.studio.save_pending, self.studio.update_selected,
                             self.studio.delete_branch, self.studio.position_note, self.studio.advanced_metadata,
                             lambda:self.studio.sources(False), lambda:self.studio.stage("e4")):
                callback()
            self.assertIn("My ChessWizard Library", str(info.call_args))
        self.assertEqual(statements, [])
        self.assertEqual(source.read_bytes(), before)

    def test_preview_repository_rejects_all_mutations_before_sql(self):
        source = self.external(); before = source.read_bytes()
        repo = open_readonly_library(source)
        self.addCleanup(repo.close)
        statements = []; repo.connection.set_trace_callback(statements.append)
        mutations = ((repo.create_book, (None, None)), (repo.update_book, (None, None)),
                     (repo.save_branch, (None,) * 6), (repo.set_position_note, (None,) * 3),
                     (repo.delete_branch, (None, None)), (repo.apply_deletion, (None,)),
                     (repo.save_source, (None,) * 4), (repo.delete_source, (None, None)))
        for method, args in mutations:
            with self.subTest(method=method.__name__), self.assertRaises(ReadOnlyLibraryError):method(*args)
        self.assertEqual(statements, [])
        self.assertEqual(before, source.read_bytes())

    def test_adoption_switches_to_editable_copy_and_leaves_source_unchanged(self):
        source = self.external(); before = source.read_bytes(); self.open_file(source)
        with patch("merlin_ui.opening_studio_workflow.choose_books", return_value=(1,)):self.studio.import_books(source)
        self.assert_writable(); self.new_book("Adopted addition")
        self.studio.stage("e4"); self.studio.save_editor()
        self.assertEqual(source.read_bytes(), before)
        self.assertNotEqual(self.studio.repository.path, source)

    def test_genuine_sqlite_readonly_error_explains_editable_copy(self):
        self.new_library()
        self.studio.repository.connection.execute("PRAGMA query_only=ON")
        self.studio.stage("e4")
        with patch(UI + "messagebox.showerror") as error:self.studio.save_editor()
        self.studio.session.discard()
        self.assertIn("This library is read-only", str(error.call_args))
        self.assertIn("My ChessWizard Library", str(error.call_args))
        self.assertEqual(len(self.studio.repository.books()), 1)
