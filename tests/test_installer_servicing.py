"""Synthetic servicing contracts: no owner profile, registry, UI, or engine use."""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from application_lifetime import mutex_prefix, windows_api
from servicing_inventory import INVENTORY_NAME, REQUIRED_FILES, create_inventory, load_inventory, verify_payload
from servicing_paths import FIXTURE_MARKER, relative_file, tree_files, validate_roots
from servicing_profile import CONFIRMATION, removal_preview, remove_profile
from servicing_transaction import prepare, rollback, validate_and_prune

ROOT = Path(__file__).resolve().parents[1]


class ServicingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="chesswizard-servicing-")
        self.root = Path(self.tmp.name)
        self.marker = self.root / FIXTURE_MARKER
        self.marker.write_text(json.dumps({"schema_version": 1, "root": str(self.root), "purpose": "disposable-servicing-test"}))
        self.app, self.profile = self.root / "app", self.root / "profile"
        self.profile.mkdir()
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"CHESSWIZARD_DATA_DIR":str(self.profile)}).start()
        self.sentinels = {}
        for name in ("merlin.db", "settings.json", "opening_books/edited.cwbook", "reviews/test.json", "plugins/state.json", "cache/test.sqlite"):
            path = self.profile / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic user bytes: " + name.encode())
            self.sentinels[name] = path.read_bytes()
        self.source = self.payload("A", "1.5.0", {"old_module.py": b"old module", "stale.dll": b"synthetic owned DLL"})
        self.txn = self.root / "transaction"

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self, name, version, extra=None):
        root = self.root / name
        root.mkdir()
        for relative in REQUIRED_FILES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((version + relative).encode())
        for relative, content in (extra or {}).items():
            (root / relative).write_bytes(content)
        create_inventory(root, version)
        return root

    def start(self, source=None, transaction=None, **kwargs):
        return prepare(source or self.source, self.app, self.profile, transaction or self.txn, self.marker, **kwargs)

    def copy_payload(self, source=None):
        shutil.copytree(source or self.source, self.app, dirs_exist_ok=True)

    def assert_profile(self):
        self.assertEqual({p.relative_to(self.profile).as_posix(): p.read_bytes() for p in tree_files(self.profile)}, self.sentinels)

    def install(self):
        self.start()
        self.copy_payload()
        validate_and_prune(self.txn)

    def test_clean_install_and_profile_separation(self):
        self.install()
        verify_payload(self.app, load_inventory(self.app / INVENTORY_NAME), exact=True)
        self.assert_profile()

    def test_repair_corrupt_and_missing_files_without_reset(self):
        self.install()
        (self.app / 'ChessWizard.exe').write_bytes(b'corrupt')
        (self.app / 'stale.dll').unlink()
        self.start(transaction=self.root / 'repair')
        self.copy_payload()
        validate_and_prune(self.root / 'repair')
        verify_payload(self.app, load_inventory(self.app / INVENTORY_NAME), exact=True)
        self.assert_profile()

    def test_upgrade_removes_stale_owned_files_preserves_unknown(self):
        self.install()
        (self.app / 'unknown.txt').write_bytes(b'not installer-owned')
        new = self.payload('B', '1.5.1')
        plan = self.start(new, self.root / 'upgrade')
        self.assertEqual(plan['stale_files'], ['old_module.py', 'stale.dll'])
        self.copy_payload(new)
        result = validate_and_prune(self.root / 'upgrade')
        self.assertEqual(result['removed'], plan['stale_files'])
        self.assertEqual((self.app / 'unknown.txt').read_bytes(), b'not installer-owned')
        self.assert_profile()

    def test_downgrade_refused_before_mutation(self):
        self.install()
        before = (self.app / INVENTORY_NAME).read_bytes()
        with self.assertRaisesRegex(ValueError, 'Downgrade'):
            self.start(self.payload('old', '1.4.0'), self.root / 'old-txn')
        self.assertEqual((self.app / INVENTORY_NAME).read_bytes(), before)
        self.assert_profile()

    def test_cancel_before_mutation_needs_no_rollback(self):
        self.start()
        self.assertFalse(self.app.exists())
        self.assert_profile()

    def test_reversible_partial_copy_and_failed_validation_restore_app_only(self):
        self.install()
        before = {p.relative_to(self.app):p.read_bytes() for p in tree_files(self.app)}
        new = self.payload('B', '1.5.1', {'new.txt':b'new'})
        txn = self.root / 'upgrade'
        self.start(new, txn)
        self.copy_payload(new)
        (self.app / 'ChessWizard.exe').write_bytes(b'broken after copy')
        with self.assertRaisesRegex(ValueError, 'verification'):
            validate_and_prune(txn)
        rollback(txn)
        self.assertEqual({p.relative_to(self.app):p.read_bytes() for p in tree_files(self.app)}, before)
        self.assert_profile()

    def test_invalid_inventory_refused_before_snapshot(self):
        (self.source / 'ChessWizard.exe').write_bytes(b'changed input')
        with self.assertRaisesRegex(ValueError, 'verification'):
            self.start()
        self.assertFalse(self.txn.exists())
        self.assertFalse(self.app.exists())

    def test_insufficient_space_is_pre_mutation(self):
        with self.assertRaisesRegex(OSError, 'Insufficient'):
            self.start(available_bytes=1)
        self.assertFalse(self.txn.exists())
        self.assert_profile()

    def test_unknown_collision_and_legacy_directory_fail_closed(self):
        self.app.mkdir()
        (self.app / 'ChessWizard.exe').write_text('legacy')
        with self.assertRaisesRegex(ValueError, 'no valid ownership'):
            self.start()
        (self.app / 'ChessWizard.exe').unlink()
        self.install()
        (self.app / 'new.txt').write_text('keep')
        with self.assertRaisesRegex(ValueError, 'Unknown file'):
            self.start(self.payload('B', '1.5.1', {'new.txt':b'new'}), self.root / 'upgrade')
        self.assertEqual((self.app / 'new.txt').read_text(), 'keep')

    def test_inventory_traversal_duplicates_and_missing_requirements(self):
        for name in ('../escape', '/absolute', 'C:/absolute', 'file:stream', 'CON', 'a/../b', 'a//b', 'a./b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                relative_file(name)
        target = self.source / INVENTORY_NAME
        original = json.loads(target.read_text())
        for row in (original['files'][0], dict(original['files'][0], path=original['files'][0]['path'].upper())):
            data = dict(original, files=original['files']+[row]); target.write_text(json.dumps(data))
            with self.assertRaises(ValueError): load_inventory(target)
        target.write_text(json.dumps(dict(original, files=original['files'][1:])))
        with self.assertRaises(ValueError): load_inventory(target)

    def test_root_home_system_overlap_and_unmarked_fixture_refused(self):
        for app, profile in ((Path(self.root.anchor),self.profile), (Path.home(),self.profile),
                (Path(os.environ.get('SystemRoot', '/bin')),self.profile), (self.app,self.app),
                (self.app,self.app/'profile'), (self.profile/'app',self.profile)):
            with self.subTest(app=app), self.assertRaises(ValueError):
                validate_roots(app,profile,self.marker)
        self.marker.write_text('{}')
        with self.assertRaises(ValueError): self.start()

    def test_full_removal_requires_confirmation_and_unchanged_inventory(self):
        with patch.dict(os.environ, {'CHESSWIZARD_DATA_DIR':str(self.profile)}):
            preview=removal_preview(self.app,self.profile,self.marker)
            with self.assertRaisesRegex(ValueError,'confirmation'):
                remove_profile(self.app,self.profile,preview['identity'],'',self.marker)
            (self.profile/'new.txt').write_text('new user write')
            with self.assertRaisesRegex(ValueError,'changed'):
                remove_profile(self.app,self.profile,preview['identity'],CONFIRMATION,self.marker)
            self.assertTrue((self.profile/'merlin.db').exists())
            current=removal_preview(self.app,self.profile,self.marker)
            result=remove_profile(self.app,self.profile,current['identity'],CONFIRMATION,self.marker)
            self.assertEqual(result['removed_files'],len(self.sentinels)+1)
            self.assertFalse(self.profile.exists())
            self.profile.mkdir()
            self.assertFalse(any(self.profile.iterdir()))

    def test_custom_profile_environment_refused(self):
        with patch.dict(os.environ, {'CHESSWIZARD_DATA_DIR':str(self.root/'external')}):
            with self.assertRaisesRegex(ValueError,'Custom'):
                removal_preview(self.app,self.profile,self.marker)
        self.assert_profile()

    @unittest.skipUnless(os.name=='nt','Windows kernel lock contract')
    def test_locked_owned_file_refuses_preflight(self):
        self.install()
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p]
        api.CreateFileW.restype=ctypes.c_void_p
        api.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=api.CreateFileW(str(self.app/'ChessWizard.exe'),0x80000000,0,None,3,0,None)
        try:
            with self.assertRaisesRegex(OSError,'Close ChessWizard'):
                self.start(transaction=self.root/'repair')
        finally:
            api.CloseHandle(handle)
        self.assert_profile()

    @unittest.skipUnless(os.name=='nt','Windows junction contract')
    def test_junction_never_followed_or_deleted(self):
        external=self.root/'external';external.mkdir();(external/'keep.txt').write_text('external')
        link=self.profile/'linked'
        # mklink creates only this explicit test junction; deletion uses native unlink/rmdir.
        result=subprocess.run(['cmd','/c','mklink','/J',str(link),str(external)],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        try:
            with self.assertRaisesRegex(ValueError,'Links'):
                removal_preview(self.app,self.profile,self.marker)
            self.assertEqual((external/'keep.txt').read_text(),'external')
        finally:
            link.rmdir()

    @unittest.skipUnless(os.name=='nt','Windows lifetime contract')
    def test_service_guard_refuses_new_desktop_or_host_lifetime(self):
        api=windows_api()
        handle=api.CreateMutexW(None,False,mutex_prefix(self.app)+'-servicing')
        try:
            script='from application_lifetime import retain_application_lifetime; from pathlib import Path; retain_application_lifetime(Path(__import__("sys").argv[1]))'
            result=subprocess.run([sys.executable,'-B','-c',script,str(self.app)],cwd=ROOT,capture_output=True,timeout=10)
            self.assertNotEqual(result.returncode,0)
            self.assertIn(b'being installed or removed',result.stderr)
        finally:
            api.CloseHandle(handle)

    def test_reinstall_into_unknown_only_directory_preserves_unknown(self):
        self.app.mkdir()
        (self.app/'unknown.txt').write_text('keep')
        self.install()
        self.assertEqual((self.app/'unknown.txt').read_text(),'keep')
        self.assert_profile()

    def test_changed_prepared_inventory_cannot_bypass_verification(self):
        self.start(); self.copy_payload()
        data=json.loads((self.app/INVENTORY_NAME).read_text())
        data['files'][0]['category']='runtime' if data['files'][0]['category']!='runtime' else 'application'
        (self.app/INVENTORY_NAME).write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'inventory changed'):
            validate_and_prune(self.txn)

    def test_full_removal_checks_all_known_locks_before_any_deletion(self):
        preview=removal_preview(self.app,self.profile,self.marker)
        from servicing_transaction import probe_replaceable
        def probe(path):
            if path.name=='settings.json': raise OSError('synthetic lock')
            probe_replaceable(path)
        with patch('servicing_profile.probe_replaceable',side_effect=probe), self.assertRaisesRegex(OSError,'synthetic lock'):
            remove_profile(self.app,self.profile,preview['identity'],CONFIRMATION,self.marker)
        self.assert_profile()
