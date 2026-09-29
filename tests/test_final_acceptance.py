"""Final acceptance scope stays narrow while unknown observations remain open."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.acceptance.console import Console, Wizard, run_wizard
from tools.acceptance.records import RunRecord, previous_result
from tools.acceptance.observations import record_review, record_security
from tools.acceptance.workflow import ConsumerRun
from tools.release_acceptance import FINAL_PLAN, acceptance_blockers, receipt_template, required_gates


class FinalAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def wizard(self, answers):
        values = iter(answers)
        return Wizard(RunRecord(self.root), Console(lambda prompt: next(values), lambda text: None))

    def test_final_scope_does_not_relabel_original_full_removal_or_upgrade_gates(self):
        legacy = receipt_template()
        final = receipt_template(FINAL_PLAN)
        self.assertIn('upgrade_api2', legacy['gates'])
        self.assertIn('confirmed_full_removal', legacy['gates'])
        self.assertNotIn('upgrade_api2', final['gates'])
        self.assertNotIn('confirmed_full_removal', final['gates'])
        self.assertIn('optional_removal_review', final['gates'])
        self.assertEqual(final['schema_version'], 2)
        self.assertEqual(legacy['schema_version'], 1)

    def test_unknown_plan_cannot_drop_required_gates(self):
        with self.assertRaises(ValueError):
            receipt_template('arbitrary-shortcut')
        self.assertEqual(acceptance_blockers({'schema_version': 2, 'plan_id': 'unknown'}), ('Unsupported receipt',))

    def test_usb_no_warning_does_not_close_download_gate(self):
        w = self.wizard(['U', *(['N']*5), 'USB only; no warnings', 'U', 'No browser test'])
        record_security(w)
        self.assertEqual(w.record.data['gates']['security_prompts']['status'], 'PENDING')
        self.assertEqual(w.record.data['security_observation']['transfer'], 'usb')
        self.assertTrue(any('USB' in item for item in acceptance_blockers(w.record.data)))

    def test_observed_browser_warnings_are_recorded_without_automatic_failure(self):
        w = self.wizard(['B', 'Y', 'Y', 'N', 'Y', 'N', 'Known publisher warning reviewed', 'A', 'Observed manageable warning'])
        record_security(w)
        self.assertEqual(w.record.data['gates']['security_prompts']['status'], 'PASS')
        self.assertEqual(w.record.data['security_observation']['smartscreen_warning'], 'Y')
        self.assertFalse(w.record.data['release_approved'])

    def test_defender_or_execution_block_is_not_silently_passed(self):
        for index in (2, 4):
            with self.subTest(index=index):
                answers = ['N']*5
                answers[index] = 'Y'
                w = self.wizard(['B', *answers, 'Observed alert/block', 'B', 'Requires investigation'])
                record_security(w)
                self.assertEqual(w.record.data['gates']['security_prompts']['status'], 'FAIL')

    def test_unobserved_security_field_stays_pending(self):
        w = self.wizard(['B', 'N', 'U', 'N', 'N', 'N', 'Prompt not observed', 'U', 'Wait for evidence'])
        record_security(w)
        self.assertEqual(w.record.data['gates']['security_prompts']['status'], 'PENDING')

    def test_unobserved_dpi_is_preserved_for_supplemental_review(self):
        w = self.wizard(['U', 'Windows requires sign-out'])
        record_review(w, 'dpi_125', 'Inspect at effective 125%')
        self.assertEqual(w.record.data['gates']['dpi_125']['status'], 'PENDING')
        self.assertEqual(w.record.data['answers'][-1]['answer'], 'U')

    def test_final_receipt_needs_structured_security_even_with_pass_label(self):
        receipt = receipt_template(FINAL_PLAN)
        for gate in receipt['gates'].values():
            gate.update(status='PASS', evidence_kind='human_observed', notes='Synthetic')
        self.assertTrue(any('Security observations incomplete' in x for x in acceptance_blockers(receipt)))

    def test_consumer_flow_only_repairs_candidate_and_inspects_full_removal(self):
        kit = self.root/'kit'; kit.mkdir()
        local = self.root/'local'; local.mkdir()
        files = ['candidate/ChessWizard-1.0.0-beta-Windows-x64-Setup.exe',
                 'ChessWizard-Final-Acceptance-Source.zip',
                 'plugins/chesswizard_example_plugin-1.0.0-py3-none-any.whl']
        (kit/'KIT-MANIFEST.json').write_text(json.dumps({'plan_id': FINAL_PLAN, 'files': [{'path': n, 'sha256': 'a'*64} for n in files]}))
        calls = []
        class FakeRun(ConsumerRun):
            def quiet(self): pass
            def package(self, relative): return kit/relative
            def setup(self, case, preserve=True): calls.append(('setup', case, preserve))
            def desktop(self, instructions): calls.append(('desktop',))
            def host(self, *args, failure=False):
                calls.append(('host', args[0], failure))
                return {'error': 'Disabled'} if failure else {}
            def uninstall(self, label, full=False, cancel=False): calls.append(('uninstall', full, cancel))
        class Owner:
            def stop_children(self): pass
            def children(self): return ()
        def answer(prompt):
            if 'transfer:' in prompt or 'effective now?' in prompt or 'signing recommendation:' in prompt: return 'U'
            if 'Y/N/U' in prompt: return 'N'
            if 'Did this pass?' in prompt: return 'Y'
            return 'Synthetic observation'
        class HeadlessConsole(Console):
            def key(self, prompt): self.read(prompt)
        with patch('tools.acceptance.workflow.local_app_data', return_value=local), patch.dict(os.environ, {'LOCALAPPDATA': str(local), 'CHESSWIZARD_DATA_DIR': ''}, clear=False), patch('tools.acceptance.workflow.JobOwner', Owner):
            code = run_wizard(kit, lambda w: FakeRun(w).run(), HeadlessConsole(answer, lambda text: None), 'simulation')
        self.assertEqual(code, 2)
        self.assertEqual([c for c in calls if c[0]=='setup'], [('setup','candidate',False),('setup','candidate',True),('setup','candidate',True)])
        self.assertEqual([c for c in calls if c[0]=='uninstall'], [('uninstall',False,False),('uninstall',False,True)])
        self.assertFalse(any(c[:2]==('host','enable') for c in calls))
        self.assertEqual(previous_result(kit)['status'], 'INCOMPLETE')
