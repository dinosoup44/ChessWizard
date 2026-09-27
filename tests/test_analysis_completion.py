"""Completion diagnostics and run progress must not manufacture durable truth."""
from dataclasses import replace
from contextlib import closing
import sqlite3
import threading
import tkinter as tk
import unittest
from unittest.mock import patch
from analysis_completion import (CompletionState, assess_preflight_completion,
                                 assess_decision_completion, assess_failure_completion)
from analysis_failures import classify_failure
from analysis_preflight import PreflightResult
from evidence_errors import IncompleteLineEvidence
from game_analysis_models import AnalysisProgress, GameAnalysisResult
from merlin_ui.analyze_games_dialog import AnalyzeGamesDialog
from tests.test_game_analysis import TemporaryAnalysis, candidate_definition
from tests.test_game_import import pgn


class CompletionPolicyTests(unittest.TestCase):
    def test_current_positive_and_negative_decisions(self):
        for status in ('candidate','rejected','screened_out','scouted_out','analyzed_no_hit'):
            with self.subTest(status=status):
                self.assertEqual(assess_decision_completion(status,current=True).state,CompletionState.COMPLETE_DECISION)
                self.assertEqual(assess_decision_completion(status,current=False).state,CompletionState.INCOMPLETE_RETRYABLE)

    def test_error_absent_and_unknown_coverage_never_complete(self):
        for status in ('error','','deferred','unknown'):
            self.assertEqual(assess_decision_completion(status,current=True).state,CompletionState.INCOMPLETE_RETRYABLE)

    def test_exact_approved_preflight_predicates_are_conservative_completion(self):
        cases=(('cached_quick_rejected','every_geometric_alternative_fails_current_cached_quick_policy'),
               ('mate_deferred','current_quick_baseline_requires_material_mate_deferral'),
               ('played_checkmate','actual_played_move_delivered_checkmate'),
               ('already_owned','every_geometric_alternative_has_another_canonical_owner'))
        for disposition,reason in cases:
            with self.subTest(disposition=disposition):
                value=assess_preflight_completion(disposition,reason)
                self.assertEqual(value.state,CompletionState.COMPLETE_DEFERRED)
                self.assertEqual(value.reason,reason)
                self.assertTrue(value.invalidation)

    def test_unknown_mixed_missing_failed_predicates_remain_retryable(self):
        for disposition,reason in (('heavy_required','unresolved_alternatives'),('heavy_required','preflight_error'),
                                  ('mate_deferred','fixture'),('already_owned','one_alternative_owned'),
                                  ('cached_quick_rejected','partial_evidence'),('','')):
            self.assertEqual(assess_preflight_completion(disposition,reason).state,CompletionState.INCOMPLETE_RETRYABLE)

    def test_bounded_evidence_is_not_terminal_from_exception_alone(self):
        value=assess_failure_completion(classify_failure(IncompleteLineEvidence('bound')))
        self.assertEqual(value.state,CompletionState.INCOMPLETE_RETRYABLE)

    def test_cancellation_stays_retryable(self):
        self.assertEqual(assess_failure_completion().state,CompletionState.INCOMPLETE_RETRYABLE)

    def test_recoverable_error_and_fatal_error_stay_distinct(self):
        self.assertEqual(assess_failure_completion(classify_failure(ValueError('local'))).state,CompletionState.FAILED_RECOVERABLE)
        self.assertEqual(assess_failure_completion(classify_failure(sqlite3.DatabaseError('unsafe'))).state,CompletionState.FAILED_FATAL)

    def test_progress_measures_inspected_not_completed(self):
        result=GameAnalysisResult(scope_total=50,games_inspected=50,games_completed=0,games_skipped=6,
            games_remaining=44,games_waiting_deferred_coverage=44,stable_deferred_checks=145)
        self.assertEqual(result.progress_percent,100)
        self.assertIn('Games inspected: 50 / 50',result.summary())
        self.assertIn('Still needing retryable work: 0',result.summary())
        self.assertIn('await durable coverage',result.remaining_explanation)

    def test_partial_and_empty_run_progress(self):
        self.assertEqual(GameAnalysisResult(scope_total=50,games_inspected=12,cancelled=True).progress_percent,24)
        self.assertEqual(GameAnalysisResult(scope_total=50,games_inspected=1,fatal_errors=1).progress_percent,2)
        self.assertEqual(GameAnalysisResult().progress_percent,100)
        self.assertEqual(GameAnalysisResult(queue_complete=False,fatal_errors=1).progress_percent,0)


class CompletionReportingTests(TemporaryAnalysis):
    def definition(self, reason='current_quick_baseline_requires_material_mate_deferral'):
        return replace(candidate_definition(),preflight_existing_evidence=lambda row,context:
            PreflightResult('mate_deferred',reason,{'evidence':[{'cache_id':123}]}))

    def test_stable_planning_outcome_is_reported_without_false_coverage(self):
        self.import_fixture(pgn(moves='1. e4 1-0'))
        service=self.service(self.definition());before=self.digest();events=[]
        first=service.run(progress=events.append);second=service.run()
        self.assertEqual((first.games_inspected,first.games_waiting_deferred_coverage,first.stable_deferred_checks),(1,1,1))
        self.assertEqual((first.games_completed,first.games_remaining,first.database_changes),(0,1,0))
        self.assertEqual((second.checks_processed,second.engine_searches,second.database_changes),(1,0,0))
        self.assertEqual(first.details,second.details)
        self.assertIn('current_quick_baseline_requires_material_mate_deferral',first.details[0])
        self.assertEqual(self.count('analysis_coverage'),0)
        self.assertEqual(before,self.digest())
        self.assertEqual(events[-1].games_inspected,1)

    def test_rolled_back_planning_diagnostics_are_not_reported_as_retained(self):
        self.import_fixture(pgn())
        definition=self.definition()
        def preflight(row,context):
            if row['ply_number']==1:
                return definition.preflight_existing_evidence(row,context)
            return PreflightResult('heavy_required','unresolved_alternatives',{})
        def failed(row,positions):
            raise ValueError('fixture failure after a provisional defer')
        result=self.service(replace(definition,preflight_existing_evidence=preflight,heavy=failed)).run()
        self.assertEqual((result.stable_deferred_checks,result.deferred,result.games_waiting_deferred_coverage),(0,0,0))
        self.assertEqual(result.recoverable_errors,1)
        self.assertFalse(any('complete_deferred' in detail for detail in result.details))

    def test_unclassified_defer_is_not_reported_as_stable(self):
        self.import_fixture(pgn(moves='1. e4 1-0'))
        result=self.service(self.definition('unknown_future_predicate')).run()
        self.assertEqual((result.games_waiting_deferred_coverage,result.stable_deferred_checks,result.retryable_deferred_checks),(0,0,1))
        self.assertIn('1 games need retryable work',result.remaining_explanation)

    def test_fully_settled_game_skips_without_engine_or_writes(self):
        self.import_fixture(pgn(moves='1. e4 1-0'))
        service=self.service();first=service.run();before=self.digest();second=service.run()
        self.assertEqual((first.games_completed,first.games_inspected),(1,1))
        self.assertEqual((second.games_inspected,second.games_skipped,second.checks_processed,second.engine_searches,second.database_changes),(1,1,0,0,0))
        self.assertEqual(before,self.digest())

    def test_progress_after_cancel_does_not_claim_unvisited_games(self):
        self.import_fixture(''.join(pgn(identity=str(i),moves='1. e4 1-0') for i in range(3)))
        cancel=threading.Event()
        def progress(event):
            if event.games_visited==1:cancel.set()
        result=self.service().run(cancel=cancel,progress=progress)
        self.assertEqual(result.games_inspected,1)
        self.assertLess(result.progress_percent,100)

    def test_fatal_stop_does_not_claim_inspection_of_later_games(self):
        self.import_fixture(pgn(identity='1')+pgn(identity='2'))
        with patch('game_analysis_service.refresh_mate_episodes',side_effect=sqlite3.DatabaseError('unsafe')):
            result=self.service().run()
        self.assertEqual((result.games_inspected,result.fatal_errors),(1,1))
        self.assertEqual(result.progress_percent,50)

    def test_ui_finished_fifty_keeps_full_bar_with_unresolved_games(self):
        root=tk.Tk();root.withdraw();self.addCleanup(root.destroy)
        dialog=AnalyzeGamesDialog(root,self.path,service=self.service());dialog._cancel_preview()
        event=AnalysisProgress('Batch done',phase='Batch completed',scope_total=50,games_inspected=50,
            games_visited=44,games_queued=44,overall_completed=6,batch_index=1,batch_count=1,batch_start=1,batch_end=50)
        dialog._progress(event)
        self.assertEqual(dialog.progress_bar['value'],100)
        self.assertIn('Games inspected this run: 50 / 50',dialog.output.get('1.0','end'))
        result=GameAnalysisResult(scope_total=50,games_inspected=50,games_remaining=44,
            games_waiting_deferred_coverage=44,stable_deferred_checks=145)
        dialog.events.put(('result',result,None));dialog.poll()
        self.assertEqual(dialog.progress_bar['value'],100)
        self.assertIn('await durable coverage',dialog.status.get())
        self.assertNotIn('some work remains',dialog.status.get())

    def test_batch_readiness_does_not_reset_run_bar_to_batch_percentage(self):
        root=tk.Tk();root.withdraw();self.addCleanup(root.destroy)
        dialog=AnalyzeGamesDialog(root,self.path,service=self.service());dialog._cancel_preview()
        dialog._progress(AnalysisProgress('Checking',phase='Checking analysis coverage',scope_total=100,
            games_inspected=50,coverage_checked=50,coverage_total=50))
        self.assertEqual(dialog.progress_bar['value'],50)
