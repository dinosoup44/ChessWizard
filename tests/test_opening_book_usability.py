"""V1.1 authoring, graph deletion and explicit-library upgrade regressions."""
from dataclasses import replace
from pathlib import Path
import sqlite3
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
import chess
from candidate_lines import LineScore
from position_evaluation import GamePosition, PositionEvaluation
from opening_book_models import BookDetails, MoveDetails, SourceDetails
from opening_book_repository import OpeningBookRepository
from opening_book_service import OpeningBookService, branch_browser
from opening_book_session import OpeningBookSession
from opening_book_polyglot import export_polyglot
from opening_book_application import apply_book
from tests.test_opening_book import LibraryFixture, ucis
from tests.test_game_analysis import TemporaryAnalysis
from tests.opening_book_fixtures import author_french_book, add_line, FRENCH_LINES


def details(move, **changes):
    return replace(MoveDetails(**{k:getattr(move,k) for k in MoveDetails.__dataclass_fields__}), **changes)


class VariationTests(LibraryFixture):
    def test_names_nested_navigation_rename_remove_reload_export_and_application(self):
        bid = author_french_book(self.service, named=False)
        initial = self.repo.snapshot(bid)
        before = export_polyglot(initial, Path(self.temp.name)/"before.bin")
        application = apply_book(initial, ucis("e4 e6 d4 d5 Nc3 Bb4"))
        session = OpeningBookSession(self.service, bid)
        for line, name in FRENCH_LINES.items():
            add_line(session, line)
            edge = next(m for m in session.snapshot.moves if m.move_id == session.history[-1])
            self.service.edit_move(bid, edge.move_id, details(edge, variation_name=name, variation_description="Original description"))
            session.refresh()
        # An optional named parent demonstrates nested breadcrumbs, without a second hierarchy.
        nc3 = next(m for m in session.snapshot.moves if m.san == "Nc3")
        self.service.edit_move(bid, nc3.move_id, details(nc3, variation_name="Knight branches"))
        session.refresh()
        entries = branch_browser(session.snapshot, compact=True)
        self.assertIn("1. e4", entries[0].label)
        for name in FRENCH_LINES.values():
            entry = next(e for e in entries if e.label.startswith(name))
            session.go_to(entry.path)
            self.assertEqual(session.position_id, entry.position_id)
            self.assertIn(name, session.breadcrumb())
        winawer = next(e for e in entries if e.label.startswith("Winawer"))
        session.go_to(winawer.path)
        self.assertIn("The French > Knight branches > Winawer Variation", session.breadcrumb())
        self.assertIn("1.e4 e6 2.d4 d5 3.Nc3 Bb4", session.breadcrumb())
        for name in ("Renamed parent", ""):
            self.service.edit_move(bid, nc3.move_id, details(nc3, variation_name=name))
        after = self.repo.snapshot(bid)
        self.assertEqual([m.move_id for m in initial.moves], [m.move_id for m in after.moves])
        self.assertEqual(initial.positions, after.positions)
        self.assertEqual(before.sha256, export_polyglot(after, Path(self.temp.name)/"after.bin").sha256)
        updated = apply_book(after, ucis("e4 e6 d4 d5 Nc3 Bb4"))
        self.assertEqual(application.moves, tuple(replace(row, available_moves=tuple(replace(m, variation_name="", variation_description="") for m in row.available_moves)) for row in updated.moves))
        self.repo.close();self.repo = OpeningBookRepository.open(self.path)
        self.assertEqual(after, self.repo.snapshot(bid))

    def test_subtree_counts_notes_sources_siblings_and_global_position_preservation(self):
        self.save("e4 e6 d4 d5 e5 c5 Nf3")
        snap = self.save("e4 e6 d4 d5 exd5 exd5")
        edge = next(m for m in snap.moves if m.san == "e5")
        self.service.edit_move(self.bid, edge.move_id, details(edge, variation_name="Advance", move_note="Move", instructional_note="Lesson", variation_description="Description"))
        self.repo.set_position_note(self.bid, edge.to_position_id, "Position")
        self.repo.save_source(self.bid, edge.from_position_id, edge.move_id, SourceDetails(title="Move source"))
        self.repo.save_source(self.bid, edge.to_position_id, None, SourceDetails(title="Position source"))
        other = self.service.create_book(BookDetails("Another repertoire"), snap.position(edge.to_position_id).canonical_fen)
        protected = self.repo.snapshot(other)
        plan = self.service.preview_deletion(self.bid, edge.move_id, subtree=True)
        self.assertEqual((len(plan.move_ids), plan.downstream_move_count, plan.note_count, len(plan.source_ids)), (3,2,4,2))
        self.assertIn('Delete "Advance"', plan.summary())
        self.service.delete(plan)
        after = self.repo.snapshot(self.bid)
        self.assertEqual(len(after.moves), 6)
        self.assertEqual(self.repo.snapshot(other), protected)
        self.assertFalse(self.repo.connection.execute("PRAGMA foreign_key_check").fetchall())
        self.assertNotIn(edge.to_position_id, [p.position_id for p in after.positions])

    def test_transposition_continuation_and_notes_survive_subtree_deletion(self):
        self.save("d4 Nf6 Nf3 d5 c4")
        snap = self.save("Nf3 Nf6 d4")
        root_move = next(m for m in snap.branches(snap.book.root_position_id) if m.san == "d4")
        shared = self.session.position_id
        self.repo.set_position_note(self.bid, shared, "Shared original note")
        self.repo.save_source(self.bid, shared, None, SourceDetails(title="Shared source"))
        before = self.repo.snapshot(self.bid)
        plan = self.service.preview_deletion(self.bid, root_move.move_id, subtree=True)
        self.assertEqual(len(plan.move_ids), 3)
        self.assertGreater(plan.shared_position_count, 0)
        self.service.delete(plan)
        after = self.repo.snapshot(self.bid)
        self.assertEqual(after.position(shared), before.position(shared))
        self.assertEqual(after.sources, before.sources)
        self.assertTrue(all(m in after.moves for m in before.moves if m.san in ("d5","c4")))

    def test_move_only_retains_descendants_and_leaf_subtree_cleans_orphan(self):
        snap = self.save("e4 e5")
        first, leaf = snap.moves
        plan = self.service.preview_deletion(self.bid, first.move_id)
        self.assertEqual(plan.move_ids, (first.move_id,))
        self.service.delete(plan)
        self.assertIn(leaf, self.repo.snapshot(self.bid).moves)
        self.assertEqual(snap.positions, self.repo.snapshot(self.bid).positions)
        leaf_plan = self.service.preview_deletion(self.bid, leaf.move_id, subtree=True)
        self.assertEqual(leaf_plan.position_ids, (leaf.to_position_id,))
        self.service.delete(leaf_plan)
        self.assertEqual(self.repo.snapshot(self.bid).moves, ())

    def test_cycle_preserves_root_and_surviving_references(self):
        snap = self.save("Nf3 Nf6 Ng1 Ng8")
        plan = self.service.preview_deletion(self.bid, snap.moves[-1].move_id, subtree=True)
        self.assertEqual(plan.position_ids, ())
        self.assertEqual(len(plan.move_ids), 1)
        self.service.delete(plan)
        self.assertEqual(len(self.repo.snapshot(self.bid).positions), 4)

    def test_disconnected_external_branch_still_protects_shared_content(self):
        self.save("d4 Nf6 Nf3 d5")
        snap = self.save("Nf3 Nf6 d4")
        root_moves = snap.branches(snap.book.root_position_id)
        self.repo.delete_branch(self.bid, next(m.move_id for m in root_moves if m.san == "Nf3"))
        plan = self.service.preview_deletion(self.bid, next(m.move_id for m in root_moves if m.san == "d4"), subtree=True)
        self.service.delete(plan)
        self.assertIn("d5", [m.san for m in self.repo.snapshot(self.bid).moves])

    def test_stale_confirmation_rejected_without_writes(self):
        snap = self.save("e4 e5")
        plan = self.service.preview_deletion(self.bid, snap.moves[0].move_id, subtree=True)
        self.repo.set_position_note(self.bid, snap.book.root_position_id, "Intervening edit")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "changed"):
            self.service.delete(plan)
        self.assertEqual(self.path.read_bytes(), before)

    def test_failed_delete_rolls_back_every_change(self):
        snap = self.save("e4 e5")
        self.repo.connection.execute("CREATE TRIGGER prevent_cleanup BEFORE DELETE ON book_positions BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        self.repo.connection.commit()
        before = self.path.read_bytes()
        plan = self.service.preview_deletion(self.bid, snap.moves[0].move_id, subtree=True)
        with self.assertRaises(sqlite3.IntegrityError): self.service.delete(plan)
        self.assertEqual(self.path.read_bytes(), before)

    def test_v1_upgrade_preserves_all_data_export_and_reopen_is_byte_identical(self):
        bid = author_french_book(self.service, named=False)
        before = self.repo.snapshot(bid)
        export = export_polyglot(before, Path(self.temp.name)/"old.bin")
        self.repo.connection.execute("ALTER TABLE book_moves DROP COLUMN variation_name")
        self.repo.connection.execute("ALTER TABLE book_moves DROP COLUMN variation_description")
        self.repo.connection.execute("PRAGMA user_version=1")
        self.repo.connection.commit();self.repo.close()
        self.repo = OpeningBookRepository.open(self.path)
        self.assertEqual(self.repo.connection.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(before, self.repo.snapshot(bid))
        self.assertEqual(export.sha256, export_polyglot(self.repo.snapshot(bid), Path(self.temp.name)/"new.bin").sha256)
        self.repo.close();raw = self.path.read_bytes()
        self.repo = OpeningBookRepository.open(self.path)
        self.assertEqual(raw, self.path.read_bytes())

    def test_invalid_partial_upgrade_rolls_back(self):
        self.repo.connection.execute("ALTER TABLE book_moves DROP COLUMN variation_name")
        self.repo.connection.execute("PRAGMA user_version=1")
        self.repo.connection.commit();self.repo.close()
        before = self.path.read_bytes()
        with self.assertRaises(sqlite3.OperationalError): OpeningBookRepository.open(self.path)
        self.assertEqual(before, self.path.read_bytes())


class StudioUsabilityTests(TemporaryAnalysis):
    def test_click_named_branch_edit_context_and_pending_guard(self):
        from merlin_ui.opening_book_studio import OpeningBookStudio
        root=tk.Tk();root.withdraw()
        studio=OpeningBookStudio(root, game_database_path=self.path)
        repo=OpeningBookRepository.create(Path(self.temp.name)/"french.cwbook")
        bid=author_french_book(OpeningBookService(repo))
        studio.use_repository(repo);root.update()
        try:
            for name in FRENCH_LINES.values():
                key=next(k for k,(b,i) in studio.branch_nodes.items() if k.startswith("b") and b.label==name)
                path=studio.paths[key]
                studio.activate_node(key);root.update()
                self.assertEqual(studio.session.history, path)
                self.assertIn(name, studio.position_label.cget("text"))
                self.assertEqual(studio.selected_move,path[-1])
                self.assertEqual(studio.fields["variation_name"].get("1.0","end-1c"),name)
                studio.edit_move()
                self.assertIn("EDITING SAVED MOVE",studio.editor.cget("text"))
                studio.discard()
            studio.book_start();studio.stage("d4");root.update()
            self.assertIn("UNSAVED",studio.position_label.cget("text"))
            key=next(iter(studio.paths))
            with patch("merlin_ui.opening_studio_workflow.choose_action",return_value="cancel"):
                studio.activate_node(key);root.update()
            self.assertEqual(studio.session.pending,"d2d4")
        finally:studio.discard();studio.close()

    def test_terminal_styles_and_layout_at_three_scales(self):
        from merlin_ui.opening_book_studio import OpeningBookStudio
        from merlin_ui.information_panel import BACKGROUND, FOREGROUND
        for percent in (100,125,150):
            root=tk.Tk();root.withdraw();root.tk.call("tk","scaling",percent/100*96/72)
            studio=OpeningBookStudio(root,game_database_path=self.path)
            try:
                root.update_idletasks()
                style=ttk.Style(root)
                for tree in (studio.tree,):
                    self.assertEqual(style.lookup(tree.cget("style"),"background"),BACKGROUND)
                    self.assertEqual(style.lookup(tree.cget("style"),"foreground"),FOREGROUND)
                self.assertEqual(studio.guide.cget("background"),BACKGROUND)
                self.assertEqual(studio.guide.cget("foreground"),FOREGROUND)
                self.assertTrue(studio.tree.bind("<ButtonRelease-1>"))
            finally:studio.close()


class ConciseEvaluationTests(unittest.TestCase):
    def test_white_black_equal_mate_and_unknown_labels(self):
        position=GamePosition(1,None,0,chess.STARTING_FEN,"Start")
        cases=[(LineScore(score_cp=69),"+0.69 White"), (LineScore(score_cp=-124),"-1.24 Black"),
               (LineScore(score_cp=0),"+0.00 Equal"), (LineScore(mate_score=3),"M3 White"),
               (LineScore(mate_score=0,mate_winner="black"),"-M0 Black"), (None,"—")]
        for score,expected in cases:
            value=PositionEvaluation(position,score,complete=score is not None)
            self.assertEqual(value.advantage_label(),expected)
