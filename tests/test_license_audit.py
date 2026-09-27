"""License-audit failure contracts; isolated files only, no application execution."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from tools.license_audit import safe_file, check_hashes, check_release_files, external_imports


class LicenseAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_changed_or_missing_notice_is_reported(self):
        path = self.root/'LICENSE'; path.write_bytes(b'original')
        entries = [{'root':'project','path':'LICENSE','sha256':hashlib.sha256(b'original').hexdigest()}]
        self.assertEqual(check_hashes(entries,{'project':self.root}),[])
        path.write_bytes(b'changed'); self.assertIn('Changed input',check_hashes(entries,{'project':self.root})[0])
        path.unlink(); self.assertIn('unavailable',check_hashes(entries,{'project':self.root})[0])

    def test_manifest_cannot_escape_root(self):
        for path in ('../secret','/secret','C:/secret','folder/../../secret'):
            with self.subTest(path=path), self.assertRaises(ValueError): safe_file(self.root,path)

    def test_private_file_cannot_be_added_to_notice_manifest(self):
        path = self.root/'merlin.db';path.write_bytes(b'private')
        entry = {'root':'project','path':'merlin.db','sha256':hashlib.sha256(b'private').hexdigest()}
        self.assertIn('Private/data',check_release_files([entry],self.root)[0])

    def test_import_scan_follows_local_modules_without_executing_them(self):
        (self.root/'app.py').write_text('import shared\nraise RuntimeError("must not execute")\n')
        (self.root/'shared.py').write_text('import newly_added_dependency\nimport json\n')
        self.assertEqual(external_imports(self.root,['app']),{'newly_added_dependency'})

    def test_relative_package_imports_are_not_unknown_dependencies(self):
        (self.root/'theme_core').mkdir()
        (self.root/'app.py').write_text('from theme_core import helper\n')
        (self.root/'theme_core/__init__.py').write_text('from . import helper\n')
        (self.root/'theme_core/helper.py').write_text('from PIL import Image\n')
        self.assertEqual(external_imports(self.root,['app']),{'PIL'})
