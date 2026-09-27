"""Generic packaging privacy rules use synthetic identities and temporary files."""
from pathlib import Path
import json
import tempfile
import unittest
from tools.package_privacy import PrivacyPolicy, content_findings, load_privacy_policy, validate_package_path
from tools.package_manifest import validate_member
from packaging.windows.assemble_beta import validate_sources


class PackagePrivacyTests(unittest.TestCase):
    def test_private_artifacts_and_sidecars_at_any_depth(self):
        for path in ('cache/foo.json','appdata/profile.json','Settings.json','analysis_settings.json',
                     'opening_books/catalog.sqlite','backups/snapshot.py','reports/result.txt',
                     'x/moves.db-wal','x/moves.sqlite3-shm','x/data.db.backup','x/run.analysis-lock',
                     '.env.private','x/secret.key','x/profile.privacy.json'):
            with self.subTest(path=path), self.assertRaises(ValueError):validate_member(path)

    def test_path_escapes_and_case_changes_fail_closed(self):
        for path in ('../private.json','/absolute.txt','C:/temp/file.txt',r'\\server\share\a.txt',
                     r'_internal\RePoRtS\a.json','x/../assets/safe.txt'):
            with self.subTest(path=path), self.assertRaises(ValueError):validate_package_path(path)

    def test_only_exact_default_book_is_public(self):
        validate_member('_internal/assets/openings/ChessWizard Default Openings.cwbook')
        for path in ('assets/openings/personal.cwbook','x/ChessWizard Default Openings.cwbook'):
            with self.assertRaises(ValueError):validate_member(path)

    def test_home_paths_utf8_utf16_and_credentials_are_redacted(self):
        private='C:' + '/Users/' + 'SyntheticPerson/private.db'
        for encoding in ('utf-8','utf-16le'):
            findings=content_findings(private.encode(encoding))
            self.assertIn('user-home path',findings)
            self.assertNotIn(private,str(findings))
        token='ghp_'+'a'*36
        self.assertIn('credential-like token',content_findings(token.encode()))
        self.assertNotIn(token,str(content_findings(token.encode())))

    def test_local_extra_identifiers_without_public_identity_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'distribution.privacy.json'
            path.write_text(json.dumps({'private_literals':['SyntheticPlayer','synthetic-session-42']}))
            policy=load_privacy_policy(path)
            self.assertEqual(content_findings(b'SYNTHETICPLAYER',policy),('configured private literal',))
            self.assertEqual(content_findings(b'SYNTHETICPLAYER'),())
            with self.assertRaises(ValueError):
                validate_member('data/SyntheticPlayer.txt', policy)
            for data in ({'unknown':[]},{'private_literals':['']},{'private_literals':'bad'}):
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):load_privacy_policy(path)

    def test_source_companion_checks_members_before_archiving(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fixture.txt';path.write_text('public source')
            validate_sources({'ChessWizard/docs/fixture.txt':path})
            with self.assertRaises(ValueError):validate_sources({'ChessWizard/reports/a.txt':path})
            path.write_text('synthetic-secret-identifier')
            with self.assertRaises(ValueError):
                validate_sources({'ChessWizard/docs/a.txt':path},PrivacyPolicy(('synthetic-secret-identifier',)))
            self.assertEqual(path.read_text(),'synthetic-secret-identifier')
