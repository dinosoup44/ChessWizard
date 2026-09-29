"""Synthetic acceptance-tool regressions; never invoke consumer installers."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.acceptance.console import Console, run_wizard
from tools.acceptance.records import RunRecord, previous_result, checked_path
from tools.acceptance.workflow import ConsumerRun, consumer_workflow
from tools.release_acceptance import acceptance_blockers


class MemoryConsole(Console):
    def __init__(self, answers):
        self.output=[]
        self.answers=iter(answers)
        super().__init__(self.answer,self.output.append)

    def answer(self, prompt):
        self.output.append(prompt)
        value=next(self.answers)
        if isinstance(value,BaseException):raise value
        return value

    def key(self,prompt):
        self.output.append(prompt)
        self.answer('')


def simulated_pass(wizard):
    wizard.step(1,'Synthetic environment only')
    wizard.ask('installer_ui','Inspect synthetic UI',True)
    for gate in wizard.record.data['gates'].values():
        gate.update(status='PASS',evidence_kind='simulation',notes='Synthetic harness only; no human acceptance')
    wizard.record.data['children_drained']=True


class AcceptanceWizardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_starts_incomplete_before_first_key(self):
        record=RunRecord(self.root)
        self.assertEqual(previous_result(self.root)['status'],'INCOMPLETE')
        self.assertIn(str(record.path),(self.root/'VIEW-RESULT.txt').read_text())

    def test_pass_waits_at_start_checkpoint_and_final_key(self):
        console=MemoryConsole(['','Y','Synthetic observation',''])
        self.assertEqual(run_wizard(self.root,simulated_pass,console,'simulation'),0)
        receipt=previous_result(self.root)
        self.assertEqual(receipt['status'],'PASS')
        self.assertEqual(receipt['scope'],'simulation')
        self.assertTrue(acceptance_blockers(receipt))
        self.assertEqual(receipt['answers'][0]['answer'],'Y')
        self.assertIn('Press any key to begin.',console.output)
        self.assertIn('Press any key to close.',console.output)
        self.assertIn('VALIDATION COMPLETE - PASS',console.output)
        self.assertFalse(receipt['release_approved'])

    def test_no_checkpoint_fails_without_continuing(self):
        console=MemoryConsole(['','N','Button missing',''])
        self.assertEqual(run_wizard(self.root,simulated_pass,console,'simulation'),1)
        receipt=previous_result(self.root)
        self.assertEqual(receipt['status'],'FAIL')
        self.assertEqual(receipt['gates']['installer_ui']['status'],'FAIL')
        self.assertIn('VALIDATION FAILED',console.output)

    def test_ctrl_c_is_incomplete_and_previous_view_quit_preserves_bytes(self):
        console=MemoryConsole([KeyboardInterrupt(),''])
        self.assertEqual(run_wizard(self.root,simulated_pass,console,'simulation'),2)
        record=previous_result(self.root)
        pointer=(self.root/'receipts/latest.json').read_bytes()
        console=MemoryConsole(['V','Q'])
        self.assertEqual(run_wizard(self.root,simulated_pass,console,'simulation'),2)
        self.assertIn('Previous validation run was incomplete.',console.output)
        self.assertEqual((self.root/'receipts/latest.json').read_bytes(),pointer)
        self.assertEqual(previous_result(self.root),record)

    def test_restart_archives_prior_run_and_begins_from_first_step(self):
        prior=RunRecord(self.root).path
        console=MemoryConsole(['R','','Y','Synthetic again',''])
        self.assertEqual(run_wizard(self.root,simulated_pass,console,'simulation'),0)
        self.assertTrue(prior.exists())
        self.assertEqual(json.loads(prior.read_text())['status'],'INCOMPLETE')
        self.assertEqual(len(list((self.root/'receipts').glob('acceptance-*.json'))),2)

    def test_missing_observations_never_pass(self):
        console=MemoryConsole(['',''])
        self.assertEqual(run_wizard(self.root,lambda wizard:None,console,'simulation'),2)
        self.assertIn('Unobserved',previous_result(self.root)['reason'])

    def test_pending_children_never_pass(self):
        def work(wizard):
            for gate in wizard.record.data['gates'].values():gate['status']='PASS'
        console=MemoryConsole(['',''])
        self.assertEqual(run_wizard(self.root,work,console,'simulation'),1)

    def test_invalid_answer_reprompts_and_no_is_durable(self):
        console=MemoryConsole(['','maybe','N','not observed',''])
        self.assertEqual(run_wizard(self.root,simulated_pass,console,'simulation'),1)
        self.assertIn('Please enter Y or N. No answer has been recorded.',console.output)

    def test_path_traversal_and_outside_result_pointer_refused(self):
        for value in ('../outside','C:/outside','/absolute','a\\b'):
            with self.subTest(value=value),self.assertRaises(ValueError):checked_path(self.root,value)
        (self.root/'receipts').mkdir()
        (self.root/'receipts/latest.json').write_text('{"receipt":"../outside.json"}')
        with self.assertRaises(ValueError):previous_result(self.root)

    def test_existing_profile_guard_prevents_any_child_or_installer(self):
        local=self.root/'synthetic-local';(local/'ChessWizard').mkdir(parents=True)
        kit=self.root/'kit';kit.mkdir()
        console=MemoryConsole(['',''])
        with patch('tools.acceptance.workflow.local_app_data',return_value=local),patch.dict(os.environ,{'LOCALAPPDATA':str(local)},clear=False),patch.object(ConsumerRun,'process') as process:
            run_wizard(kit,consumer_workflow,console)
        process.assert_not_called()
        self.assertEqual(previous_result(kit)['status'],'FAIL')

    def test_hash_drift_refused_before_execution(self):
        record=RunRecord(self.root)
        from tools.acceptance.console import Wizard
        run=ConsumerRun(Wizard(record,MemoryConsole([])))
        (self.root/'input.exe').write_bytes(b'synthetic')
        run.manifest={'input.exe':'0'*64}
        with self.assertRaises(ValueError):run.package('input.exe')

    def test_heartbeat_is_visible_and_logged(self):
        from tools.acceptance.console import Wizard
        record=RunRecord(self.root);console=MemoryConsole([]);wizard=Wizard(record,console)
        with patch('tools.acceptance.console.time.monotonic',return_value=wizard.last_pulse+6):wizard.pulse()
        self.assertTrue(any('Still working...' in line for line in console.output))
        self.assertIn('Still working...',record.log.read_text())

    def test_environment_override_cannot_bypass_real_known_folder(self):
        actual=self.root/'actual';override=self.root/'override'
        actual.mkdir();override.mkdir();kit=self.root/'kit';kit.mkdir()
        console=MemoryConsole(['',''])
        with patch('tools.acceptance.workflow.local_app_data',return_value=actual),patch.dict(os.environ,{'LOCALAPPDATA':str(override)},clear=False),patch.object(ConsumerRun,'process') as process:
            run_wizard(kit,consumer_workflow,console)
        process.assert_not_called()
        self.assertEqual(previous_result(kit)['status'],'FAIL')

    def test_receipt_write_failure_stops_before_work(self):
        console=MemoryConsole([''])
        with patch('tools.acceptance.records.atomic_text',side_effect=OSError('synthetic read-only media')),patch('tools.acceptance.workflow.consumer_workflow') as work:
            self.assertEqual(run_wizard(self.root,work,console),3)
        work.assert_not_called()

    def test_malformed_prior_receipt_is_not_overwritten(self):
        folder=self.root/'receipts';folder.mkdir()
        (folder/'latest.json').write_text('{"receipt":"receipts/bad.json"}')
        (folder/'bad.json').write_text('[]')
        console=MemoryConsole([''])
        self.assertEqual(run_wizard(self.root,simulated_pass,console,'simulation'),3)
        self.assertEqual((folder/'bad.json').read_text(),'[]')
