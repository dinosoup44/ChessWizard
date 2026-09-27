"""Audit disposition stays explicit, portable and separate from saved human judgment."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from game_review_sets import load_review_sets
from human_analyzer_reviews import HumanReviewCase, HumanReviewRecord, ReviewVerdict, audit_cases_for_game
from human_analyzer_review_repository import HumanReviewRepository
from merlin_ui.human_review_panel import HumanReviewPanel
from review_audit_status import audit_status_for_case


def audit_case(classification="confirmed"):
    return HumanReviewCase(10, 100, None, "hung_queen", "future_audit",
                           audit_case_id="fixture:100",
                           analyzer_provenance=(("checker_classification", classification),))


class ReviewAuditStatusTests(unittest.TestCase):
    def test_exact_classifications_preserve_metadata_and_identity(self):
        for classification, label in (("confirmed", "CONFIRMED BLUNDER"),
                                      ("unresolved", "UNRESOLVED"),
                                      ("not_blunder", "CONTROL — NOT BLUNDER")):
            with self.subTest(classification=classification):
                case = audit_case(classification)
                before = asdict(case), case.identity
                result = audit_status_for_case(case)
                self.assertEqual(result.classification, classification)
                self.assertEqual(result.label, label)
                self.assertEqual((asdict(case), case.identity), before)
                self.assertIsNone(case.candidate_id)

    def test_missing_unknown_conflicting_metadata_never_infers_a_status(self):
        for metadata in ((), (("checker_classification", "error"),),
                         (("checker_classification", "CONFIRMED"),),
                         (("checker_classification", "confirmed"), ("checker_classification", "unresolved"))):
            case = replace(audit_case(), analyzer_provenance=metadata,
                           review_reason=("Confirmed blunder",), review_reason_codes=("material_blunder_confirmed",))
            self.assertIsNone(audit_status_for_case(case))
        self.assertIsNone(audit_status_for_case(None))
        self.assertIsNone(audit_status_for_case(replace(audit_case(), candidate_id=1, audit_case_id=None)))

    def test_older_sets_without_status_remain_unlabeled(self):
        for review in load_review_sets():
            if review.id not in ("questionable", "verified", "selective_12"):
                continue
            for game_id in {entry.game_id for entry in review.entries}:
                for case in audit_cases_for_game(review, game_id):
                    self.assertIsNone(audit_status_for_case(case))

    def test_core_does_not_load_desktop_database_or_chess_modules(self):
        code = "import review_audit_status, sys; assert not any(m in sys.modules for m in ('tkinter', 'sqlite3', 'chess'))"
        subprocess.run([sys.executable, "-B", "-c", code], check=True, capture_output=True)


class ReviewAuditStatusWidgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = HumanReviewRepository(Path(self.temp.name) / "reviews.jsonl")
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.panel = HumanReviewPanel(self.root, repository=self.repo,
                                     ui_skin={"panel_bg": "white", "text": "black", "muted_text": "gray"})
        self.panel.pack(fill="both", expand=True)

    def test_selection_changes_and_clears_status_without_io(self):
        with patch('sqlite3.connect', side_effect=AssertionError('No DB access')), \
             patch('subprocess.Popen', side_effect=AssertionError('No engine/process')), \
             patch.object(self.repo, 'save', side_effect=AssertionError('No implicit save')):
            for classification in ("confirmed", "unresolved", "not_blunder", "confirmed"):
                case = audit_case(classification)
                self.panel.set_case(case)
                self.assertEqual(self.panel.audit_status['text'], audit_status_for_case(case).label)
                self.assertEqual(self.panel.audit_status.winfo_manager(), "grid")
            for case in (replace(audit_case(), analyzer_provenance=()),
                         HumanReviewCase(10, 100, 1, "missed_fork", "questionable"), None):
                self.panel.set_case(case)
                self.assertEqual(self.panel.audit_status['text'], "")
                self.assertEqual(self.panel.audit_explanation['text'], "")
                self.assertEqual(self.panel.audit_status.winfo_manager(), "")
        self.assertFalse(self.repo.path.exists())

    def test_old_saved_verdicts_and_bytes_stay_independent(self):
        control = audit_case("not_blunder")
        legacy = HumanReviewCase(10, 101, 1, "missed_fork", "questionable")
        records = [HumanReviewRecord(control, ReviewVerdict.WRONG_MOTIF, "ordinary trade", "2026-09-10T12:00:00+00:00"),
                   HumanReviewRecord(legacy, ReviewVerdict.PASS, "old review", "2026-09-09T12:00:00+00:00")]
        self.repo.path.write_text("".join(json.dumps(r.to_dict()) + "\n" for r in records), encoding="utf-8")
        before = self.repo.path.read_bytes(), self.repo.path.stat().st_mtime_ns
        for case in (control, legacy, control):
            self.panel.set_case(case)
            saved = self.repo.get(case)
            self.assertEqual(self.panel.verdict_var.get(), saved.verdict.value)
            self.assertEqual(self.panel.note_var.get(), saved.note)
        for verdict in ReviewVerdict:
            self.panel.verdict_var.set(verdict.value)
            self.assertEqual(self.panel.audit_status['text'], "CONTROL — NOT BLUNDER")
        self.assertEqual(self.panel.verdict_picker['values'], tuple(v.value for v in ReviewVerdict))
        self.assertEqual((self.repo.path.read_bytes(), self.repo.path.stat().st_mtime_ns), before)
        self.assertEqual(self.repo.load(), tuple(records))
