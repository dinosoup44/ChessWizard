"""Release gates stay blocked without human clean-machine evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from tools.release_acceptance import CLEAN_GATES, HUMAN_GATES, acceptance_blockers, receipt_template
from tools.build_installer import build_installer


class AcceptanceTests(unittest.TestCase):
    def complete(self):
        receipt = receipt_template()
        receipt['status'] = 'PASS'
        receipt['environment'].update(genuinely_clean_windows=True, windows_build='Synthetic Windows build',
            reviewer='Synthetic reviewer', source_checkout_absent=True, developer_tools_not_required=True)
        receipt['artifacts'] = {key:'a'*64 for key in receipt['artifacts']}
        for key,gate in receipt['gates'].items():
            gate.update(status='PASS', evidence_kind='clean_windows_observed' if key in CLEAN_GATES else 'human_observed', notes='Synthetic observed result')
        receipt.update(signing_decision='unsigned_with_documentation', signing_reason='Synthetic observed warning and documented decision')
        return receipt

    def test_pending_never_passes(self):
        self.assertTrue(acceptance_blockers(receipt_template()))

    def test_complete_attestation_is_distinct_from_pending(self):
        self.assertEqual(acceptance_blockers(self.complete()), ())

    def test_automated_dpi_or_same_host_cannot_certify(self):
        for key in (*CLEAN_GATES, *HUMAN_GATES):
            with self.subTest(key=key):
                receipt=self.complete();receipt['gates'][key]['evidence_kind']='automated_same_host'
                self.assertTrue(acceptance_blockers(receipt))
        receipt=self.complete();receipt['environment']['genuinely_clean_windows']=False
        self.assertTrue(acceptance_blockers(receipt))

    def test_fail_missing_notes_hash_or_signing_keeps_blocked(self):
        for change in ('failure','notes','hash','signing'):
            receipt=self.complete()
            if change=='failure': receipt['gates']['clean_install']['status']='FAIL'
            if change=='notes': receipt['gates']['dpi_150']['notes']=''
            if change=='hash': receipt['artifacts']['installer_sha256']='wrong'
            if change=='signing': receipt['signing_decision']='sign_before_release'
            self.assertTrue(acceptance_blockers(receipt))

    def test_malformed_receipts_fail_closed(self):
        for receipt in (None, [], {}, {'schema_version':1,'environment':None,'gates':None,'artifacts':None}):
            self.assertTrue(acceptance_blockers(receipt))


class ConsumerAcceptanceBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'packaging/windows').mkdir(parents=True)
        (self.root/'packaging/windows/installer-toolchain.json').write_text(json.dumps({'compiler_sha256':'synthetic'}))
        self.addCleanup(patch.stopall)
        patch('tools.build_installer.ROOT',self.root).start()
        patch('tools.build_installer.file_hash',return_value='synthetic').start()
        patch('tools.build_installer.verify_payload').start()
        patch('tools.build_installer.load_inventory',return_value=SimpleNamespace(version='1.5.0')).start()

    def invoke(self, identity=None, **kwargs):
        identity = identity if identity is not None else {'application_version':'1.5.0','api_version':'1.0.0','frozen':True,'plugin_packages_loaded':[]}
        with patch('tools.build_installer.subprocess.run', side_effect=[SimpleNamespace(returncode=0,stdout=json.dumps(identity)),SimpleNamespace(returncode=0)]) as run:
            result=build_installer(self.root/'payload',self.root/'output',**kwargs)
            return result,run.call_args_list

    def test_normal_build_still_rejects_changed_public_version(self):
        with self.assertRaisesRegex(ValueError,'canonical'):
            self.invoke()

    def test_acceptance_uses_consumer_paths_and_records_exact_identity(self):
        result,calls=self.invoke(acceptance_only=True)
        compiler_args=calls[-1].args[0]
        self.assertFalse(any('Fixture' in item for item in compiler_args))
        self.assertIn('/DAppVersion=1.5.0',compiler_args)
        receipt=json.loads((result.parent/'acceptance-build.json').read_text())
        self.assertTrue(receipt['consumer_paths']);self.assertFalse(receipt['fixture_switches'])
        self.assertEqual(receipt['frozen_identity']['application_version'],'1.5.0')

    def test_wrong_unfrozen_loaded_or_incomplete_identity_refused(self):
        for identity in ({}, {'application_version':'2.0.0'}, {'application_version':'1.5.0','frozen':False},
                {'application_version':'1.5.0','api_version':'1.0.0','frozen':True,'plugin_packages_loaded':['unapproved']}):
            with self.subTest(identity=identity),self.assertRaises(ValueError):
                self.invoke(identity,acceptance_only=True)

    def test_fixture_mode_cannot_masquerade_as_consumer(self):
        with self.assertRaisesRegex(ValueError,'fixture'):
            self.invoke(acceptance_only=True,fixture=self.root/'fixture')
