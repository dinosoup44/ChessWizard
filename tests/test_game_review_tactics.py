"""Read/query/presentation contracts and real Tk replay integration."""
from dataclasses import replace
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock,patch
import chess
import chess.engine
from game_review_repository import GameReviewRepository
from tactic_query import TacticQuery
from tactic_presentation import TacticReadService,present_candidate,decision_step
from tactical_opportunities import TacticalOpportunity,TacticalOutcome,TacticalMotif,TacticalPresentation
from tactical_opportunity_repository import prepare_opportunity_payload
from merlin_ui.game_review_view import GameReviewView
from merlin_ui.candidate_viewer import CandidateViewer
from feedback import FeedbackResult


def fixture_db():
    c=sqlite3.connect(":memory:")
    c.executescript("""
      CREATE TABLE games(game_id INTEGER PRIMARY KEY,source,source_game_id,white_username,black_username,user_color,result,played_at);
      CREATE TABLE moves(move_id INTEGER PRIMARY KEY,game_id,ply_number,move_number,color,san_played,uci_played,fen_before,fen_after);
      CREATE TABLE tactic_candidates(candidate_id INTEGER PRIMARY KEY,move_id,tactic_type,candidate_status,
        solution_move_uci,solution_move_san,solution_line,notes,metadata_json,detector_version DEFAULT 1);
      CREATE TABLE tactic_episodes(episode_id INTEGER PRIMARY KEY,primary_candidate_id,tactic_type,episode_status);
      CREATE TABLE analysis_coverage(move_id,analysis_type,coverage_status,candidate_id);
    """)
    for gid in range(1,5):
        c.execute("INSERT INTO games(game_id,source,source_game_id,white_username,black_username,user_color,result) VALUES (?,?,?,?,?,?,?)",(gid,"dev" if gid==4 else "test",str(gid),"White","Black","black" if gid==1 else "white","1-0"))
        b=chess.Board()
        for ply,uci in enumerate(("e2e4","e7e5","g1f3","b8c6"),1):
            before=b.fen(); move=b.parse_uci(uci); san=b.san(move); color="white" if b.turn else "black"; number=b.fullmove_number
            b.push(move)
            c.execute("INSERT INTO moves VALUES (?,?,?,?,?,?,?,?,?)",(gid*100+ply,gid,ply,number,color,san,uci,before,b.fen()))
    c.commit()
    return c


def add(c,kind,*,game=1,ply=1,status="candidate",episode=False,metadata=None):
    cursor=c.execute("INSERT INTO tactic_candidates(move_id,tactic_type,candidate_status,solution_move_uci,solution_move_san,solution_line,notes,metadata_json) VALUES (?,?,?,?,?,?,?,?)",
        (game*100+ply,kind,status,"d2d4","d4","d4 d5 c4","Legacy notes",metadata))
    cid=cursor.lastrowid
    if episode: c.execute("INSERT INTO tactic_episodes(primary_candidate_id,tactic_type,episode_status) VALUES (?,?,'candidate')",(cid,kind))
    c.commit(); return cid


class TacticReadTests(unittest.TestCase):
    def setUp(self):
        self.c=fixture_db(); self.addCleanup(self.c.close)
        self.query=TacticQuery(self.c); self.service=TacticReadService(self.c)
        blocker=patch("chess.engine.SimpleEngine.popen_uci",side_effect=AssertionError("No engine in review"))
        blocker.start(); self.addCleanup(blocker.stop)

    def test_no_tactics_and_one_fork(self):
        self.assertEqual(self.service.moments_for_game(1),[])
        cid=add(self.c,"missed_fork")
        moments=self.service.moments_for_game(1)
        self.assertEqual([(m.candidate_id,m.title,m.played_move,m.suggested_move) for m in moments],[(cid,"Missed Fork","e4","d4")])
        self.assertFalse(moments[0].has_opportunity)

    def test_confirmed_mate_episode_primary_only(self):
        primary=add(self.c,"missed_mate",status="confirmed",episode=True)
        add(self.c,"missed_mate",ply=2,status="confirmed")
        add(self.c,"missed_mate",ply=3,status="confirmed")
        self.assertEqual([r["candidate_id"] for r in self.query.candidates()], [primary])
        self.c.execute("INSERT INTO tactic_episodes(primary_candidate_id,tactic_type,episode_status) VALUES (?,'missed_mate','candidate')",(primary,))
        self.assertEqual(len(self.query.candidates()),1)

    def test_rejected_candidate_coverage_and_episode_hidden(self):
        add(self.c,"missed_fork",status="rejected")
        add(self.c,"missed_mate",status="rejected",episode=True)
        pin=add(self.c,"missed_pin")
        self.c.execute("INSERT INTO analysis_coverage VALUES (101,'missed_pin','rejected',?)",(pin,))
        self.assertEqual(self.query.candidates(),[])
        self.c.execute("UPDATE tactic_candidates SET candidate_status='confirmed' WHERE tactic_type='missed_mate'")
        self.c.execute("UPDATE tactic_episodes SET episode_status='rejected'")
        self.assertEqual(self.query.candidates(),[])

    def test_all_tactic_types_and_future_type_appear_generically(self):
        for kind in ("missed_fork","missed_pin","missed_skewer","missed_xray","missed_deflection"):
            add(self.c,kind)
        add(self.c,"missed_mate",status="confirmed",episode=True)
        self.assertEqual(len(self.service.moments_for_game(1)),6)
        self.assertIn(("missed_deflection","Deflection"),self.query.filter_options())

    def test_any_specific_and_composable_scope_filters_are_read_only(self):
        add(self.c,"missed_fork"); add(self.c,"missed_pin",game=2); add(self.c,"missed_skewer",game=4)
        before=self.c.total_changes,tuple(self.c.iterdump())
        self.c.execute("PRAGMA query_only=ON")
        self.assertEqual(self.query.game_ids("any",within=[1,2,3]),{1,2})
        self.assertEqual(self.query.game_ids("missed_pin"),{2})
        self.assertEqual(self.query.game_ids("any",within=[]),set())
        repo=GameReviewRepository(self.c)
        self.assertEqual([g["game_id"] for g in repo.games("any")],[2,1])
        self.assertEqual([g["game_id"] for g in repo.games("missed_fork")],[1])
        self.assertEqual([g["game_id"] for g in repo.games()],[3,2,1])
        self.assertEqual(before,(self.c.total_changes,tuple(self.c.iterdump())))

    def test_ambiguous_canonical_rows_are_not_arbitrarily_selected(self):
        add(self.c,"missed_fork"); add(self.c,"missed_fork")
        self.assertEqual(self.query.candidates(),[])

    def test_opportunity_outcome_context_and_levels(self):
        cid=add(self.c,"missed_pin")
        row=self.query.candidates()[0]
        opportunity=TacticalOpportunity(TacticalOutcome("win_rook"),
            (TacticalMotif("pin",True,"context_only","A line exists"),TacticalMotif("fork",False,"supported","The double attack wins material")),
            presentation=TacticalPresentation("secondary_motif","Pin","A double attack wins the rook"))
        moment=present_candidate(row,opportunity)
        self.assertEqual(moment.title,"Win the rook")
        self.assertEqual(moment.motifs,("Fork",)); self.assertEqual(moment.context_motifs,("Pin",))
        self.assertNotIn("Pin",moment.list_label)
        self.assertEqual(moment.presentation_level,"secondary_motif")
        positional=replace(opportunity,presentation=TacticalPresentation("positional_note","A note","Context"))
        self.assertIn("Note:",present_candidate(row,positional).list_label)
        payload=prepare_opportunity_payload({"solution_move_uci":"d2d4","solution_line":"d4 d5 c4","metadata_json":None},opportunity,{"uci_played":"e2e4"})
        self.c.execute("UPDATE tactic_candidates SET metadata_json=? WHERE candidate_id=?",(payload["metadata_json"],cid))
        loaded=self.service.moments_for_game(1)[0]
        self.assertTrue(loaded.has_opportunity); self.assertEqual(loaded.title,"Win the rook")
        self.assertEqual(loaded.proof_line,"d4 d5 c4")

    def test_invalid_optional_metadata_uses_canonical_fallback(self):
        add(self.c,"missed_skewer",metadata='{"tactical_opportunity":{"schema_version":999}}')
        self.assertEqual(self.service.moments_for_game(1)[0].title,"Missed Skewer")

    def test_jump_resolves_move_id_not_assumed_ply_offset(self):
        add(self.c,"missed_fork",ply=3)
        moment=self.service.moments_for_game(1)[0]
        moves=GameReviewRepository(self.c).moves(1)[1:]
        self.assertEqual(decision_step(moves,moment),1)
        with self.assertRaises(ValueError): decision_step([],moment)
        with self.assertRaises(ValueError): decision_step(moves,replace(moment,fen_before=chess.STARTING_FEN))

    def test_candidate_viewer_uses_shared_visibility_and_original_filters(self):
        fork=add(self.c,"missed_fork")
        mate=add(self.c,"missed_mate",status="confirmed",episode=True)
        add(self.c,"missed_mate",ply=2,status="confirmed"); add(self.c,"missed_pin")
        viewer=CandidateViewer.__new__(CandidateViewer)
        viewer.connection=self.c; viewer.filter_var=Mock(); viewer.filter_var.get.return_value="All"
        viewer.show_candidate=Mock()
        viewer.load_candidates()
        self.assertEqual([r["candidate_id"] for r in viewer.candidates],[fork,mate])
        viewer.show_candidate.assert_called_once_with(0)
        viewer.filter_var.get.return_value="Missed Mate"; viewer.load_candidates()
        self.assertEqual([r["candidate_id"] for r in viewer.candidates],[mate])
        self.assertIsNotNone(viewer.candidates[0]["episode_id"])


class GameReviewWidgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"review.db"
        with closing(fixture_db()) as fixture, closing(sqlite3.connect(self.path)) as saved:
            add(fixture,"missed_fork",ply=3)
            add(fixture,"missed_mate",game=2,status="confirmed",episode=True)
            fixture.backup(saved)
        self.before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.root=tk.Tk(); self.root.withdraw()
        blocker=patch("chess.engine.SimpleEngine.popen_uci",side_effect=AssertionError("No engine in UI"))
        blocker.start(); self.addCleanup(blocker.stop)
        self.view=GameReviewView(self.root,self.path)
        self.addCleanup(self.view.close)

    def select_game(self,gid):
        self.view.show_game(next(i for i,g in enumerate(self.view.games) if g["game_id"]==gid))
        self.root.deiconify()
        self.root.update()

    def test_click_jump_orientation_highlight_and_navigation(self):
        self.select_game(1); v=self.view
        v.tactics_panel.listbox.selection_set(0)
        v.tactics_panel.listbox.event_generate("<<ListboxSelect>>")
        self.root.update()
        self.assertEqual(v.current_step,2)
        self.assertEqual(v.board_widget.board.fen(),v.moments[0].fen_before)
        self.assertEqual(v.board_widget.orientation,chess.BLACK)
        self.assertEqual(v.board_widget.last_move,chess.Move.from_uci("e7e5"))
        self.assertIn("Merlin found: d4",v.tactics_panel.detail.get("1.0","end"))
        self.assertIsInstance(v.moments[0].feedback, FeedbackResult)
        self.assertIn(v.moments[0].feedback.explanation,v.tactics_panel.detail.get("1.0","end"))
        self.assertNotIn("d4 d5 c4",v.tactics_panel.detail.get("1.0","end"))
        v.tactics_panel.line_button.invoke()
        self.root.update()
        self.assertTrue(v.tactics_panel.proof_frame.winfo_ismapped())
        self.assertIn("2\td4\td5",v.tactics_panel.proof_text.get("1.0","end"))
        self.assertEqual(v.navigation_mode,"merlin_line")
        v.next_move(); self.assertEqual(v.current_step,2)
        self.assertEqual(v.line_playback.ply,1)
        v.tactics_panel.line_button.invoke()
        self.assertEqual(v.navigation_mode,"game")
        v.next_move(); self.assertEqual(v.current_step,3); self.assertTrue(v.board_widget.board.is_valid())
        self.assertIsNone(v.tactics_panel.selected)
        v.previous_move(); self.assertEqual(v.current_step,2)
        v.go_to_start(); self.assertEqual(v.current_step,0); self.assertIsNone(v.get_last_move())
        self.assertEqual(v.connection.total_changes,0)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.before)

    def test_filters_empty_state_restore_games_and_controls(self):
        v=self.view; self.select_game(1)
        original=[g["game_id"] for g in v.games]
        v.filter_var.set("Any missed tactic"); v.load_games()
        self.assertEqual([g["game_id"] for g in v.games],[2,1])
        self.assertEqual(v.current_game["game_id"],1)
        v.filter_var.set("Mate"); v.load_games()
        self.assertEqual([g["game_id"] for g in v.games],[2])
        self.assertEqual(v.board_widget.orientation,chess.WHITE)
        v.filter_var.set("Skewer"); v.load_games()
        self.assertIsNone(v.current_game); self.assertEqual(v.moves,[])
        self.assertTrue(v.board_widget.board.is_valid())
        self.assertEqual(str(v.navigation.step_forward_button['state']),"disabled")
        v.filter_var.set("All games"); v.load_games()
        self.assertEqual([g["game_id"] for g in v.games],original)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.before)

    def test_full_replay_end_start_and_last_move_toggle(self):
        self.select_game(1); v=self.view
        for step in range(1,5):
            v.next_move(); self.assertEqual(v.current_step,step); self.assertTrue(v.board_widget.board.is_valid())
        v.next_move(); self.assertEqual(v.current_step,4)
        self.assertEqual(v.get_board_for_current_step().fen(),v.moves[-1]['fen_after'])
        v.show_last_move_var.set(False); v.refresh_board(); self.assertIsNone(v.board_widget.last_move)
        v.go_to_start(); v.previous_move(); self.assertEqual(v.current_step,0)
        self.assertIsNone(v.tactics_panel.train_button)
        with self.assertRaises(sqlite3.OperationalError): v.connection.execute("DELETE FROM tactic_candidates")
