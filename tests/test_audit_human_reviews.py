"""Audit-only QA anchors coexist with canonical candidate reviews without DB writes."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

from game_review_sets import ALL_GAMES, ReviewSet, ReviewSetEntry, load_review_sets
from human_analyzer_reviews import HumanReviewCase, HumanReviewRecord, ReviewVerdict, audit_cases_for_game, case_for_moment, summarize_reviews
from human_analyzer_review_repository import HumanReviewRepository
import test_game_review_tactics as fixtures


def audit_entry(game_id=3, move_id=301, key="case:a2a4", proposed="a2a4", reason="new deferral"):
    return ReviewSetEntry(game_id,"deferral",reason,"audit.json",key,move_id,None,
                          1 if move_id else None,"white",proposed,tactic_type="missed_fork")


def audit_set(*entries):
    return ReviewSet("questionable","Questionable audit", "", entries)


class AuditReviewContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.repo = HumanReviewRepository(Path(self.tmp.name)/"reviews.jsonl")

    def test_synthetic_anchor_save_reload_and_set_independent_identity(self):
        item=replace(audit_entry(21,201,'synthetic:21:201','a5a3'),move_number=30,color='black')
        sets={'questionable':audit_set(item),'selective_12':ReviewSet('selective_12','Selective','',(item,))}
        case = audit_cases_for_game(sets["questionable"],21)[0]
        self.assertEqual((case.move_id,case.move_number,case.color,case.candidate_id),(201,30,"black",None))
        self.assertEqual(case.proposed_move,"a5a3")
        self.assertEqual(case.tactic_type,"missed_fork")
        self.assertTrue(case.identity.startswith("audit:"))
        other = audit_cases_for_game(sets["selective_12"],21)[0]
        self.assertEqual(case.identity,other.identity)
        for verdict in ReviewVerdict:
            saved = self.repo.save(case,verdict,"Audit feedback")
            self.assertEqual(self.repo.get(case),saved)
            self.assertEqual(len(self.repo.load()),1)
        self.assertEqual(summarize_reviews(self.repo.load())["reviewed_total"],1)

    def test_duplicate_reasons_merge_but_different_moves_and_cases_do_not(self):
        first=audit_entry()
        cases=audit_cases_for_game(audit_set(first,replace(first,reason_label="rank 2"),
                            replace(first,case_key="different"),replace(first,proposed_move="h2h4")),3)
        self.assertEqual(len(cases),3)
        self.assertEqual(cases[0].review_reason,("new deferral","rank 2"))
        self.assertEqual(len({c.identity for c in cases}),3)
        self.assertNotEqual(cases[0].identity,replace(cases[0],game_id=4).identity)
        self.assertNotEqual(cases[0].identity,replace(cases[0],move_id=302).identity)
        self.assertEqual(cases[0].identity,replace(cases[0],review_reason=("new label",)).identity)

    def test_move_zero_is_non_chess_anchor_and_requires_explicit_id(self):
        case=audit_cases_for_game(audit_set(audit_entry(move_id=None,key="opening-observation",proposed=None)),3)[0]
        self.assertIsNone(case.move_id); self.assertIsNone(case.candidate_id)
        self.assertEqual(case.move_number,0)
        self.assertIn("not a chess move",case.label)
        self.repo.save(case,ReviewVerdict.INVESTIGATE)
        self.assertEqual(self.repo.get(case).case,case)
        with self.assertRaises(ValueError): replace(case,audit_case_id=None)
        with self.assertRaises(ValueError): replace(case,move_id=301)
        with self.assertRaises(ValueError): replace(case,candidate_id=1)
        with self.assertRaises(ValueError): replace(case,move_number=2)
        with self.assertRaises(ValueError): audit_cases_for_game(audit_set(replace(audit_entry(),case_key="")),3)

    def test_audit_summary_names_case_and_non_chess_anchor(self):
        case=audit_cases_for_game(audit_set(audit_entry(move_id=None,proposed=None)),3)[0]
        self.repo.save(case,ReviewVerdict.NOT_IMPORTANT,"Conditional on neutral payoff")
        before=self.repo.path.read_bytes()
        run=subprocess.run([sys.executable,"-B","tools/summarize_human_reviews.py","--path",str(self.repo.path)],
                           capture_output=True,text=True,encoding="utf-8")
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn("Audit audit.json#",run.stdout)
        self.assertIn("game-level anchor (not a chess move)",run.stdout)
        self.assertIn("NOT IMPORTANT: 1",run.stdout)
        self.assertIn("Conditional on neutral payoff",run.stdout)
        self.assertNotIn("Candidate None",run.stdout)
        self.assertEqual(self.repo.path.read_bytes(),before)

    def test_old_candidate_records_remain_readable_and_identity_unchanged(self):
        old={"schema_version":1,"case":{"game_id":3,"move_id":301,"candidate_id":9,"tactic_type":"missed_fork","review_set":"questionable"},
             "verdict":"PASS","note":"Original", "reviewed_at":"2026-09-10T12:00:00+00:00"}
        record=HumanReviewRecord.from_dict(old)
        self.repo.path.write_text(json.dumps(old)+"\n")
        before=self.repo.path.read_bytes()
        self.assertEqual(record.case.identity,"candidate:9")
        self.assertEqual(self.repo.save(record.case,ReviewVerdict.PASS,"Original"),record)
        self.assertEqual(self.repo.path.read_bytes(),before)
        audit=audit_cases_for_game(audit_set(audit_entry()),3)[0]
        self.repo.save(audit,ReviewVerdict.WORDING)
        self.assertEqual(self.repo.get(record.case),record)
        self.assertEqual(len(self.repo.load()),2)


class AuditReviewWidgetTests(unittest.TestCase):
    select_game = fixtures.GameReviewWidgetTests.select_game

    def setUp(self):
        fixtures.GameReviewWidgetTests.setUp(self)
        self.repo=HumanReviewRepository(Path(self.tmp.name)/"audit-feedback.jsonl")
        self.view.open_human_review()
        self.view.human_review_panel.repository=self.repo

    def configure_set(self,*entries):
        review=audit_set(*entries)
        self.view.review_sets=(ALL_GAMES,review)
        self.view.review_set_picker.configure(values=[s.label for s in self.view.review_sets])
        self.view.review_set_var.set(review.label); self.view.load_games(); self.root.update()

    def test_audit_only_game_enables_logger_without_tactical_moments(self):
        self.configure_set(audit_entry())
        v=self.view; panel=v.human_review_panel
        self.assertEqual(v.current_game["game_id"],3)
        self.assertEqual(v.moments,[])
        self.assertIsNone(panel.case.candidate_id)
        self.assertEqual(str(panel.save_button["state"]),"normal")
        fen=v.board_widget.board.fen()
        panel.verdict_var.set("NOT IMPORTANT"); panel.note_var.set("Conditional on neutral continuation")
        panel.save_button.invoke()
        self.assertEqual(self.repo.load()[0].verdict,ReviewVerdict.NOT_IMPORTANT)
        self.assertEqual(v.board_widget.board.fen(),fen)
        self.assertEqual(v.connection.total_changes,0)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.before)
        v.review_set_var.set("All Games"); v.load_games()
        self.configure_set(audit_entry())
        self.assertEqual(panel.verdict_var.get(),"NOT IMPORTANT")
        self.assertEqual(panel.note_var.get(),"Conditional on neutral continuation")

    def test_multiple_cases_require_choice_and_do_not_share_reviews(self):
        self.configure_set(audit_entry(),audit_entry(move_id=303,key="other",proposed="g1f3"))
        panel=self.view.human_review_panel
        self.assertIsNone(panel.case)
        self.assertEqual(str(panel.save_button["state"]),"disabled")
        panel.target_picker.current(0); panel._choose_target()
        panel.verdict_var.set("PASS"); panel.note_var.set("First case"); panel.save_button.invoke()
        panel.target_picker.current(1); panel._choose_target()
        self.assertEqual(panel.verdict_var.get(),""); self.assertEqual(panel.note_var.get(),"")
        panel.verdict_var.set("INVESTIGATE"); panel.save_button.invoke()
        panel.target_picker.current(0); panel._choose_target()
        self.assertEqual(panel.note_var.get(),"First case")
        self.assertEqual(len(self.repo.load()),2)

    def test_visible_candidate_keeps_original_identity_without_duplicate_audit_choice(self):
        self.select_game(1)
        moment=self.view.moments[0]
        exact=audit_entry(1,moment.move_id,proposed=moment.solution_uci)
        other=audit_entry(1,101,key="audit_only")
        self.configure_set(exact,other)
        panel=self.view.tactics_panel
        panel.listbox.selection_set(0); panel._select()
        qa=self.view.human_review_panel
        self.assertEqual(qa.case.identity,f"candidate:{moment.candidate_id}")
        self.assertEqual(len(qa.targets),2)
        self.assertEqual(sum(c.candidate_id is None for c in qa.targets),1)
        self.assertEqual(qa.case.review_reason,("new deferral",))

    def test_audit_draft_survives_actual_navigation_but_not_game_change(self):
        self.configure_set(audit_entry(),audit_entry(2,201))
        self.select_game(3)
        panel=self.view.human_review_panel
        panel.verdict_var.set("WORDING"); panel.note_var.set("Unfinished")
        self.view.next_move()
        self.assertEqual(panel.note_var.get(),"Unfinished")
        self.select_game(2)
        self.assertEqual(panel.note_var.get(),"")
        self.assertEqual(panel.case.game_id,2)

    def test_unlocated_case_does_not_create_real_move_or_change_board(self):
        self.configure_set(audit_entry(move_id=None,proposed=None))
        panel=self.view.human_review_panel
        self.assertEqual(panel.case.move_number,0)
        self.assertIsNone(panel.case.move_id)
        self.assertEqual(len(self.view.moves),4)
        self.assertEqual(self.view.current_step,0)
        panel.verdict_var.set("INVESTIGATE");panel.save_button.invoke()
        self.assertEqual(self.view.current_step,0)
        self.assertEqual(self.view.connection.total_changes,0)
