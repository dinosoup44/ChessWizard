"""Local QA identity, atomic persistence, failure safety and desktop selection."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from game_review_sets import ALL_GAMES, ReviewSet, ReviewSetEntry
from human_analyzer_reviews import HumanReviewCase, HumanReviewRecord, ReviewVerdict, case_for_moment, summarize_reviews
from human_analyzer_review_repository import HumanReviewRepository, ReviewStorageError
import test_game_review_tactics as fixtures


def review_case(candidate_id=1, **changes):
    return replace(HumanReviewCase(10, 100, candidate_id, "missed_fork", "questionable"), **changes)


class HumanReviewStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "reviews" / "human_analyzer_review.jsonl"
        self.repo = HumanReviewRepository(self.path)

    def test_missing_file_load_is_read_only(self):
        self.assertEqual(self.repo.load(), ())
        self.assertFalse(self.path.parent.exists())

    def test_each_verdict_optional_note_roundtrip_and_summary(self):
        for index, verdict in enumerate(ReviewVerdict, 1):
            record = self.repo.save(review_case(index), verdict, "" if index == 1 else "  Why? â™ž\nCheck wording.  ")
            self.assertEqual(record.verdict, verdict)
            self.assertEqual(record.note, "" if index == 1 else "Why? â™ž\nCheck wording.")
            self.assertEqual(HumanReviewRecord.from_dict(json.loads(json.dumps(record.to_dict()))), record)
        records = self.repo.load()
        summary = summarize_reviews(records)
        self.assertEqual(summary["reviewed_total"], 6)
        self.assertEqual(set(summary["verdicts"].values()), {1})
        self.assertEqual(summary["by_tactic_type"], {"missed_fork":6})
        self.assertEqual(summary["by_review_set"], {"questionable":6})
        self.assertEqual(len(summary["non_pass"]), 5)
        self.assertTrue(all(row["note"] for row in summary["non_pass"]))

    def test_identical_save_has_no_timestamp_or_byte_churn(self):
        old = self.repo.save(review_case(), ReviewVerdict.PASS)
        before = self.path.read_bytes(); modified = self.path.stat().st_mtime_ns
        self.assertEqual(self.repo.save(review_case(), ReviewVerdict.PASS), old)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mtime_ns, modified)

    def test_change_verdict_updates_one_logical_record_across_sets(self):
        self.repo.save(review_case(), ReviewVerdict.PASS)
        new_case = review_case(review_set="all_games")
        saved = self.repo.save(new_case, ReviewVerdict.INVESTIGATE, "Revisit")
        self.assertEqual(self.repo.load(), (saved,))
        self.assertEqual(saved.case.identity, "candidate:1")
        self.assertEqual(saved.case.review_set, "all_games")

    def test_malformed_files_refuse_save_and_remain_unchanged(self):
        valid = self.repo.save(review_case(), ReviewVerdict.PASS)
        invalid_schema = valid.to_dict(); invalid_schema["schema_version"] = 2
        for payload in (b"{broken", b"null", b"\xff", json.dumps(invalid_schema).encode(),
                        (json.dumps(valid.to_dict()) + "\n") .encode() * 2):
            self.path.write_bytes(payload)
            with self.assertRaises(ReviewStorageError): self.repo.load()
            with self.assertRaises(ReviewStorageError): self.repo.save(review_case(), ReviewVerdict.WORDING)
            self.assertEqual(self.path.read_bytes(), payload)
            self.assertFalse(self.path.with_name(self.path.name + ".lock").exists())

    def test_replace_failure_preserves_previous_file_and_cleans_owned_files(self):
        self.repo.save(review_case(), ReviewVerdict.PASS)
        before = self.path.read_bytes()
        with patch("human_analyzer_review_repository.os.replace", side_effect=PermissionError("busy")):
            with self.assertRaises(ReviewStorageError): self.repo.save(review_case(), ReviewVerdict.WRONG_PAYOFF)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_competing_writer_lock_does_not_get_removed(self):
        self.path.parent.mkdir()
        lock = self.path.with_name(self.path.name + ".lock"); lock.write_text("owner")
        with self.assertRaises(ReviewStorageError): self.repo.save(review_case(), ReviewVerdict.PASS)
        self.assertEqual(lock.read_text(), "owner")
        self.assertFalse(self.path.exists())

    def test_independent_repositories_merge_under_lock(self):
        other = HumanReviewRepository(self.path)
        self.repo.save(review_case(1), ReviewVerdict.PASS)
        other.save(review_case(2), ReviewVerdict.WORDING)
        self.repo.save(review_case(1), ReviewVerdict.INVESTIGATE)
        self.assertEqual({r.case.candidate_id for r in other.load()}, {1,2})

    def test_identity_conflict_and_invalid_notes_do_not_modify_file(self):
        self.repo.save(review_case(), ReviewVerdict.PASS)
        before = self.path.read_bytes()
        with self.assertRaises(ReviewStorageError): self.repo.get(review_case(move_id=200))
        self.assertEqual(self.repo.get(review_case()).verdict, ReviewVerdict.PASS)
        with self.assertRaises(ReviewStorageError):
            self.repo.save(review_case(move_id=200), ReviewVerdict.PASS)
        with self.assertRaises(ValueError): self.repo.save(review_case(), ReviewVerdict.PASS, "x" * 501)
        with self.assertRaises(ValueError): review_case(candidate_id=None)
        self.assertEqual(self.path.read_bytes(), before)

    def test_summary_cli_is_read_only_and_reports_non_pass_notes(self):
        self.repo.save(review_case(), ReviewVerdict.WRONG_MOTIF, "Looks like a double attack â™ž")
        before = self.path.read_bytes()
        run = subprocess.run([sys.executable,"-B","tools/summarize_human_reviews.py","--path",str(self.path)],capture_output=True,text=True,encoding="utf-8")
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn("Reviewed total: 1",run.stdout)
        self.assertIn("WRONG MOTIF: 1",run.stdout)
        self.assertIn("Looks like a double attack â™ž",run.stdout)
        self.assertEqual(self.path.read_bytes(),before)
        self.path.write_text("broken")
        run = subprocess.run([sys.executable,"-B","tools/summarize_human_reviews.py","--path",str(self.path)],capture_output=True,text=True,encoding="utf-8")
        self.assertEqual(run.returncode,2)
        self.assertIn("File left unchanged",run.stderr)
        self.assertEqual(self.path.read_text(),"broken")

    def test_core_imports_without_database_ui_or_analyzers(self):
        code = """
import builtins
original=builtins.__import__
def guard(name,*args,**kwargs):
    if name.startswith(('tkinter','sqlite3','chess','analysis_','analyze_','tactic_presentation')): raise AssertionError(name)
    return original(name,*args,**kwargs)
builtins.__import__=guard
import human_analyzer_reviews, human_analyzer_review_repository
"""
        run = subprocess.run([sys.executable,"-B","-c",code],capture_output=True,text=True,encoding="utf-8")
        self.assertEqual(run.returncode,0,run.stderr)


class HumanReviewWidgetTests(unittest.TestCase):
    select_game = fixtures.GameReviewWidgetTests.select_game

    def setUp(self):
        fixtures.GameReviewWidgetTests.setUp(self)
        self.review_path = Path(self.tmp.name) / "qa.jsonl"
        self.repo = HumanReviewRepository(self.review_path)
        from game_review_sets import ALL_GAMES, ReviewSet
        self.view.review_sets=(ALL_GAMES, ReviewSet("synthetic", "Synthetic QA", "Test-owned optional catalog"))
        self.view.open_human_review()
        self.view.human_review_panel.repository = self.repo

    def select_tactic(self):
        self.select_game(1)
        panel = self.view.tactics_panel
        panel.listbox.selection_set(0); panel._select(); self.root.update()
        return self.view.human_review_panel

    def test_save_reload_change_and_database_unchanged(self):
        panel = self.select_tactic()
        self.assertIn("Not reviewed",panel.status["text"])
        panel.verdict_var.set("WRONG PAYOFF"); panel.note_var.set("Check the recapture")
        panel.save_button.invoke()
        self.assertIn("Saved: WRONG PAYOFF",panel.status["text"])
        self.view.next_game(); self.select_tactic()
        self.assertEqual(panel.verdict_var.get(),"WRONG PAYOFF")
        self.assertEqual(panel.note_var.get(),"Check the recapture")
        panel.verdict_var.set("PASS"); panel.save_button.invoke()
        self.assertEqual(len(self.repo.load()),1)
        self.assertEqual(self.repo.load()[0].verdict,ReviewVerdict.PASS)
        self.assertEqual(self.view.connection.total_changes,0)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.before)

    def test_selection_clear_prevents_stale_save_and_playback_preserves_draft(self):
        panel = self.select_tactic()
        panel.verdict_var.set("WORDING"); panel.note_var.set("Draft")
        self.view.tactics_panel.line_button.invoke(); self.view.next_move()
        self.view.tactics_panel.line_button.invoke()
        self.assertEqual(panel.note_var.get(),"Draft")
        self.view.next_move()
        self.assertIsNone(panel.case)
        self.assertEqual(panel.note_var.get(),"")
        self.assertEqual(str(panel.save_button["state"]),"disabled")
        panel.save_review(); self.assertFalse(self.review_path.exists())

    def test_malformed_file_shows_error_without_breaking_game_review(self):
        self.review_path.write_text("bad JSON")
        panel = self.select_tactic()
        self.assertIn("Cannot read human reviews",panel.status["text"])
        self.assertEqual(str(panel.save_button["state"]),"disabled")
        self.view.next_move(); self.assertEqual(self.view.current_step,3)
        self.assertEqual(self.review_path.read_text(),"bad JSON")

    def test_only_exact_audit_case_provenance_is_attached(self):
        panel = self.select_tactic(); moment = self.view.tactics_panel.selected
        entries = (
            ReviewSetEntry(1,"matching","exact reason","audit.json","a",moment.move_id,None,2,"white",moment.solution_uci),
            ReviewSetEntry(1,"other","wrong move","audit.json","b",moment.move_id,None,2,"white","a2a3"),
        )
        review_set = ReviewSet("questionable","Q","",entries)
        case = case_for_moment(moment,review_set)
        self.assertEqual(case.review_reason,("exact reason",))
        self.assertEqual(case.source_artifacts,("audit.json",))
        self.assertEqual(case.identity,case_for_moment(moment,ALL_GAMES).identity)
        self.assertIsNone(case_for_moment(None,review_set))
        self.select_game(3)
        self.assertIsNone(panel.case)
        self.assertIn("Choose an audit case",panel.status["text"])
