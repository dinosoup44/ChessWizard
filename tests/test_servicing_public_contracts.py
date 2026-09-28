"""Public-safe servicing inputs retain privacy and explicit-root boundaries."""
from pathlib import Path
import tempfile
import unittest
from tools.public_source import scan_text
from tools.servicing_fixture import initialize_fixture


class ServicingPublicContracts(unittest.TestCase):
    def test_inno_system_symbol_import_is_not_an_email(self):
        findings=scan_text('packaging/windows/ChessWizard.iss', "  external '" + "@".join(("CreateMutexW", "kernel32.dll")) + " stdcall';")
        self.assertEqual({f.category for f in findings},{'public-safe reference'})

    def test_arbitrary_email_and_non_import_context_still_require_review(self):
        for path,text in [('script.iss',"external '"+"@".join(("Person","private.invalid"))+" stdcall';"),
                          ('script.iss','Contact: '+ '@'.join(('Person','kernel32.dll'))),
                          ('script.py',"external '"+"@".join(("Person","kernel32.dll"))+" stdcall';")]:
            with self.subTest(path=path,text=text):
                self.assertTrue(any(f.category=='requires owner decision' for f in scan_text(path,text)))

    def test_fixture_requires_new_explicit_temporary_child(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'chesswizard-servicing-nested'
            with self.assertRaises(ValueError): initialize_fixture(root,root/'profile')
        with self.assertRaises(ValueError): initialize_fixture(Path.home(),Path.home()/'profile')
