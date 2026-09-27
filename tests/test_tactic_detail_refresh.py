from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
import chess
from feedback import FeedbackContextBuilder, FeedbackGenerator
from merlin_ui.game_review_view import GameReviewView
from stored_line import StoredLine
from tactical_opportunities import (TacticalOpportunity, TacticalOutcome, TacticalMotif,
    TacticalPresentation, opportunity_to_dict)
from test_game_review_tactics import fixture_db, add


class SelectionRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "review.db"
        with closing(fixture_db()) as fixture, closing(sqlite3.connect(self.path)) as saved:
            op = TacticalOpportunity(TacticalOutcome("win_pawn"),
                (TacticalMotif("pin", True, "supported", "Abstract legacy proof description"),),
                presentation=TacticalPresentation("strong_callout"))
            self.a = add(fixture,"missed_pin",metadata=json.dumps({"tactical_opportunity":opportunity_to_dict(op)}))
            op = replace(op, primary_outcome=TacticalOutcome("win_rook"),
                motifs=(TacticalMotif("skewer", True, "supported", "Other abstract proof"),
                        TacticalMotif("pin",False,"context_only","Context")),
                presentation=TacticalPresentation("secondary_motif"))
            self.b = add(fixture,"missed_skewer",metadata=json.dumps({"tactical_opportunity":opportunity_to_dict(op)}))
            fixture.execute("UPDATE tactic_candidates SET solution_move_uci='e2e4',solution_move_san='e4',solution_line='e4 e5 Nf3' WHERE candidate_id=?",(self.b,))
            self.c = add(fixture,"missed_fork")
            fixture.execute("UPDATE tactic_candidates SET solution_move_uci=NULL,solution_move_san=NULL,solution_line=NULL WHERE candidate_id=?",(self.c,))
            fixture.commit(); fixture.backup(saved)
        self.before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        guard = patch("chess.engine.SimpleEngine.popen_uci",side_effect=AssertionError("No engine"))
        guard.start(); self.addCleanup(guard.stop)
        self.root = tk.Tk()
        self.view = GameReviewView(self.root,self.path)
        self.addCleanup(self.view.close)
        self.view.show_game(next(i for i,g in enumerate(self.view.games) if g["game_id"]==1))
        self.root.update()

    def select(self, candidate_id):
        p = self.view.tactics_panel
        index = next(i for i,m in enumerate(p.moments) if m.candidate_id==candidate_id)
        p.listbox.selection_clear(0,"end"); p.listbox.selection_set(index)
        p.listbox.event_generate("<<ListboxSelect>>"); self.root.update()
        self.assertEqual(p.selected_candidate_id,candidate_id)
        self.assertEqual(self.view.board_widget.board.fen(),p.selected.fen_before)
        return p

    def test_a_b_empty_a_rebuilds_every_field_and_resets_proof(self):
        for cid,title,motifs,solution in ((self.a,"Win a pawn","Motifs: Pin","d4"),
                                         (self.b,"Win the rook","Motifs: Skewer\nContext only: Pin","e4"),
                                         (self.c,"Missed Fork","","Not recorded"),
                                         (self.a,"Win a pawn","Motifs: Pin","d4")):
            p = self.select(cid)
            f = p.selected.feedback
            self.assertEqual(p.title_label["text"],title)
            self.assertEqual(p.motifs_label["text"],motifs)
            text = p.detail.get("1.0","end")
            self.assertIn("Merlin found: " + solution,text)
            self.assertIn(f.played_move_label,text)
            self.assertIn(f.explanation,text)
            self.assertFalse(p.show_line)
            self.assertFalse(p.proof_frame.winfo_ismapped())
            self.assertEqual(p.line_button["text"],"Show Line")
            if cid==self.c:
                for stale in ("Outcome:","Attribution:","Skewer","Win the rook","Context"):
                    self.assertNotIn(stale,text)
                self.assertEqual(p.proof_text.get("1.0","end").strip(),"")
                self.assertEqual(str(p.line_button["state"]),"disabled")
            else:
                self.assertIn("Outcome: " + title,text)
                self.assertIn("Attribution:",text)
                p.line_button.invoke(); self.root.update()
                self.assertTrue(p.proof_frame.winfo_ismapped())
                self.assertIsNotNone(p.proof_text.bbox("1.0"))
                self.assertEqual(p.line_button["text"],"Hide Line")
                self.assertIn("Move\tWhite\tBlack",p.proof_text.get("1.0","end"))
                for san in p.selected.stored_line.moves:
                    self.assertIn(san,p.proof_text.get("1.0","end"))
                p.line_button.invoke(); self.root.update()
                self.assertFalse(p.proof_frame.winfo_ismapped())
                p.line_button.invoke(); self.root.update()
        self.assertEqual(self.view.connection.total_changes,0)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.before)

    def test_arrow_updates_clears_and_preserves_last_move_setting(self):
        self.select(self.a)
        self.assertEqual(self.view.board_widget.arrows,[{"from":chess.D2,"to":chess.D4}])
        self.select(self.b)
        self.assertEqual(self.view.board_widget.arrows,[{"from":chess.E2,"to":chess.E4}])
        self.select(self.c); self.assertEqual(self.view.board_widget.arrows,[])
        self.select(self.a)
        self.view.next_move(); self.root.update()
        self.assertEqual(self.view.board_widget.arrows,[])
        self.assertIsNone(self.view.tactics_panel.selected_candidate_id)
        self.assertEqual(self.view.board_widget.last_move,chess.Move.from_uci("e2e4"))

    def test_selection_reloads_result_instead_of_reusing_game_list_snapshot(self):
        self.select(self.a)
        with closing(sqlite3.connect(self.path)) as fixture:
            fixture.execute("UPDATE tactic_candidates SET metadata_json=NULL,solution_line=NULL WHERE candidate_id=?",(self.a,))
            fixture.commit()
        p = self.select(self.a)
        self.assertEqual(p.title_label["text"],"Missed Pin")
        self.assertEqual(p.motifs_label["text"],"")
        self.assertEqual(p.proof_text.get("1.0","end").strip(),"")
        self.assertEqual(self.view.connection.total_changes,0)

    def test_optional_feedback_fields_clear_through_same_renderer(self):
        p = self.select(self.a)
        f = replace(p.selected.feedback, teaching_note="Example teaching note", warning_note="Example warning",
                    relationship_labels=("Example relationship",))
        p.selected = replace(p.selected,feedback=f)
        p.render_feedback_result()
        self.assertIn("Example relationship",p.detail.get("1.0","end"))
        p = self.select(self.c)
        self.assertNotIn("Example",p.detail.get("1.0","end"))
        self.assertEqual(p.title_label["fg"],p.skin["text"])


class StoredLineTests(unittest.TestCase):
    def test_legal_replay_positions_and_identity(self):
        line = StoredLine.from_san(chess.STARTING_FEN,"e4 e5 Nf3",1847)
        self.assertEqual(line.source_candidate_id,1847)
        self.assertEqual(line.moves_uci,("e2e4","e7e5","g1f3"))
        self.assertEqual(len(line.positions),4)
        board = chess.Board(); board.push_san("e4")
        self.assertEqual(line.position_at(1),board.fen())
        self.assertEqual(line.display_text,"e4 → e5 → Nf3")
        with self.assertRaises(IndexError): line.position_at(-1)

    def test_bad_or_missing_line_has_no_partial_replay(self):
        for raw in ("e4 not-a-move", ""):
            line = StoredLine.from_san(chess.STARTING_FEN,raw)
            self.assertEqual(line.positions,())
            self.assertEqual(line.display_text,raw)
            with self.assertRaises(ValueError): line.position_at(0)

    def test_concrete_continuation_precedes_abstract_rationale(self):
        op = TacticalOpportunity(TacticalOutcome("win_pawn"),
            (TacticalMotif("pin",True,"supported","The proof wins a pin participant."),))
        row = {"solution_move_san":"Qb6", "solution_line":"Qb6 a4 axb3", "tactic_type":"missed_pin"}
        c = FeedbackContextBuilder().build(row,op)
        result = FeedbackGenerator().generate(c)
        self.assertIn("Qb6 wins a pawn",result.explanation)
        self.assertIn("Qb6 → a4 → axb3",result.explanation)
        self.assertNotIn("pin participant",result.explanation)
        self.assertNotIn("creates the pin",result.explanation)
