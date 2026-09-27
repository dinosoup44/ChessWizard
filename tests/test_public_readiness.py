"""Public-source boundaries and documentation tooling; no owner data or engine."""
from dataclasses import asdict
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from tools.pydoc_support import public_modules, render_modules
from tools.public_source import ROOT, ignored_paths, scan_text, source_manifest


class PublicReadinessTests(unittest.TestCase):
    def test_git_ignore_keeps_exact_public_defaults_and_synthetic_fixtures(self):
        public = ['assets/openings/ChessWizard Default Openings.cwbook',
            'assets/openings/ChessWizard Default Openings.bin', 'assets/openings/manifest.json',
            'data/default_openings/source/a.tsv', 'data/default_openings/source/bin/gen.py',
            'tests/fixtures/see_synthetic.json', 'tests/test_opening_book.py', 'README.md',
            '.github/ISSUE_TEMPLATE/bug_report.md',
            'packaging/windows/assets/ChessWizard.png', 'packaging/windows/assets/ChessWizard.ico',
            'packaging/windows/assets/LICENSE.txt', 'packaging/windows/assets/provenance.json']
        private = ['merlin.db', 'merlin.db-wal', 'cache/position.sqlite3-shm',
            'opening_books/catalog.sqlite', 'opening_books/mine.cwbook', 'assets/openings/mine.cwbook',
            'reports/private.json', 'backups/full/source.py', '.venv/Lib/site.py',
            'build/pydoc/index.html', 'dist/ChessWizard.exe', 'Engines/stockfish.exe',
            'settings.json', '.env', '.env.production', 'screenshots/owner.png',
            'reviews/notes.jsonl', 'review_data/builtin_review_sets.json',
            'tests/fixtures/fork_pass_2.json', 'packaging/windows/assets/owner-private.png',
            'packaging/windows/assets/other.ico', 'tests/local_history/test_private.py',
            'build/release.privacy.json', 'release.privacy.json']
        ignored = ignored_paths(ROOT, [Path(p) for p in public + private])
        self.assertTrue(set(private) <= ignored)
        self.assertFalse(set(public) & ignored)

    def test_public_default_assets_match_pinned_source_and_curation(self):
        assets = ROOT / 'assets/openings'
        manifest = json.loads((assets / 'manifest.json').read_text())
        source = ROOT / 'data/default_openings/source'
        pinned = json.loads((source / 'manifest.json').read_text())
        self.assertEqual(manifest['source'], pinned)
        self.assertEqual(pinned['commit'], 'c67912be581f0793dbaa776be5ccf111e01f88d9')
        self.assertEqual(pinned['license'], 'CC0-1.0')
        for name, entry in pinned['files'].items():
            self.assertEqual(hashlib.sha256((source / name).read_bytes()).hexdigest(), entry['sha256'])
        for name, expected in [('ChessWizard Default Openings.cwbook', manifest['cwbook_sha256']),
                               ('ChessWizard Default Openings.bin', manifest['polyglot']['sha256'])]:
            self.assertEqual(hashlib.sha256((assets / name).read_bytes()).hexdigest(), expected)
        self.assertEqual(hashlib.sha256((ROOT / 'data/default_openings/curation.json').read_bytes()).hexdigest(),
                         manifest['curation_sha256'])
        self.assertEqual((assets / 'COPYING.txt').read_bytes(), (source / 'COPYING.txt').read_bytes())

    def test_public_manifest_does_not_include_runtime_or_held_data(self):
        manifest = source_manifest(ROOT)
        paths = {entry['path'] for entry in manifest['files']}
        self.assertIn('run_chesswizard.py', paths)
        self.assertIn('assets/openings/ChessWizard Default Openings.cwbook', paths)
        for name in paths:
            self.assertFalse(name.startswith(('reports/', 'review_data/', 'reviews/', 'backups/', 'build/', '.venv/', 'Engines/', 'tests/local_history/')))
            self.assertNotIn(Path(name).suffix, {'.db', '.sqlite', '.sqlite3', '.exe', '.dll'})
            if name.endswith('.cwbook'):
                self.assertEqual(name, 'assets/openings/ChessWizard Default Openings.cwbook')

    def test_secret_findings_never_contain_values(self):
        secret = 'ghp_' + 'a' * 36
        result = scan_text('example.txt', 'credential=' + secret)
        self.assertTrue(any(r.category == 'potential secret' for r in result))
        self.assertNotIn(secret, json.dumps([asdict(r) for r in result]))
        self.assertTrue(all(r.line == 1 for r in result))
        self.assertEqual(scan_text('licenses/example.txt', 'author@example.org')[0].category, 'public-safe reference')

    def test_api_index_unique_and_no_launchers_or_test_modules(self):
        names = public_modules()
        self.assertGreaterEqual(len(names), 80)
        self.assertEqual(len(names), len(set(names)))
        self.assertFalse(any(n.startswith(('tests.', 'merlin_ui.', 'run_', 'migrate_', 'reports.')) for n in names))
        result = render_modules(['opening_studio_handoff', 'board_analysis', 'no_such_chesswizard_module'])
        self.assertEqual([bool(r.error) for r in result], [False, False, True])
        self.assertIn('studio_source_step', result[0].text)
        self.assertNotIn(str(ROOT), result[0].html)

    def test_documentation_guard_blocks_runtime_side_effects(self):
        worker = ROOT / 'tools/_pydoc_worker.py'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'tools').mkdir()
            (root / 'tools/_pydoc_worker.py').write_bytes(worker.read_bytes())
            scripts = {
                'write_probe': "open('must_not_exist.txt', 'w')",
                'db_probe': "import sqlite3; sqlite3.connect('must_not_exist.db')",
                'process_probe': "import subprocess; subprocess.run(['must_not_launch_engine'])",
                'network_probe': "import socket; socket.socket()",
                'gui_probe': "import tkinter",
            }
            for name, body in scripts.items():
                (root / (name + '.py')).write_text(body)
            run = subprocess.run([sys.executable, '-I', '-B', str(root / 'tools/_pydoc_worker.py')],
                input=json.dumps(list(scripts)), capture_output=True, text=True, encoding='utf-8',
                cwd=root, timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertTrue(all(r['error'] for r in json.loads(run.stdout)))
            self.assertFalse((root / 'must_not_exist.txt').exists())
            self.assertFalse((root / 'must_not_exist.db').exists())

    def test_doc_cli_failure_returns_nonzero(self):
        from tools.check_pydoc import main
        from tools.pydoc_support import ModuleDocumentation
        with patch('tools.check_pydoc.render_modules', return_value=(ModuleDocumentation('failed', error='ImportError'),)):
            self.assertEqual(main(), 1)

    def test_public_setup_uses_portable_profile_and_no_owner_path(self):
        for name in ['README.md', 'CONTRIBUTING.md', 'docs/DEVELOPMENT.md', 'docs/FIRST_PUBLIC_RELEASE_CHECKLIST.md']:
            value = (ROOT / name).read_text(encoding='utf-8')
            self.assertNotRegex(value, r'(?i)[A-Z]:[\\/]+Users[\\/]')
        self.assertIn('CHESSWIZARD_DATA_DIR', (ROOT / 'docs/DEVELOPMENT.md').read_text())

    def test_public_tests_do_not_import_private_audit_modules(self):
        for path in (ROOT / 'tests').rglob('*.py'):
            if 'local_history' in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            imported = [n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            imported += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
            self.assertFalse(any(n == 'reports' or n.startswith(('reports.', 'tests.local_history'))
                                 for n in imported), str(path.relative_to(ROOT)))

    def test_reserved_example_addresses_do_not_hide_real_address_findings(self):
        self.assertEqual(scan_text('sample.py', 'tester@example.org')[0].category, 'safe/example')
        self.assertEqual(scan_text('sample.py', 'tester' + '@' + 'private.invalid')[0].category, 'requires owner decision')
