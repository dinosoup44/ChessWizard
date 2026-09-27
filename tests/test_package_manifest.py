"""Fail-closed packaging provenance and private-file contracts, using temporary files."""
from pathlib import Path
import tempfile
import unittest
from tools.package_manifest import owner, validate_member, code_strings


class PackageManifestTests(unittest.TestCase):
    def test_private_artifacts_rejected(self):
        for name in ("_internal/merlin.db", "reports/a.json", "reviews/private.jsonl", "tests/test_core.py", ".venv/python.exe"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_member(name)

    def test_public_notice_and_runtime_allowed(self):
        for name in ("_internal/licenses/python/LICENSE.txt", "ChessWizard.exe", "_internal/database_schema.py"):
            validate_member(name)

    def test_unknown_dependency_cannot_be_labeled_as_python(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"project";base=Path(temp)/"python";env=root/"build/venv"
            with self.assertRaises(ValueError):
                owner(env/"Lib/site-packages/unknown/native.dll",root,base,env)

    def test_external_native_origin_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"project";base=Path(temp)/"python";env=root/"build/venv"
            with self.assertRaises(ValueError):
                owner(Path(temp)/"unrelated/native.dll",root,base,env)

    def test_known_pillow_and_hook_licenses(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"project";base=Path(temp)/"python";env=root/"build/venv"
            self.assertIn("Pillow", owner(env/"Lib/site-packages/PIL/_imaging.pyd",root,base,env)[0])
            self.assertEqual(owner(env/"Lib/site-packages/PyInstaller/hooks/rthooks/pyi_rth.py",root,base,env)[1],"Apache-2.0")

    def test_privacy_scan_visits_nested_code(self):
        code=compile("def nested():\n    return 'private-marker'\n", "source.py", "exec")
        self.assertIn(("constant","private-marker"),list(code_strings(code)))

    def test_only_public_default_library_is_allowed(self):
        validate_member('_internal/assets/openings/ChessWizard Default Openings.cwbook')
        for name in ('owner.cwbook', '_internal/opening_books/private.cwbook', '_internal/assets/openings/My Repertoire.cwbook'):
            with self.assertRaises(ValueError):validate_member(name)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'project'
            result=owner(root/'assets/openings/ChessWizard Default Openings.cwbook',root,Path(temp)/'python',root/'venv')
            self.assertIn('CC0',result[1])
