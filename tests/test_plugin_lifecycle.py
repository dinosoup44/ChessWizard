"""Synthetic durable-state, recovery, compatibility, and ownership regressions."""
from dataclasses import asdict, replace
import json
import os
import subprocess
import unittest
from pathlib import Path
import shutil
import uuid
from unittest.mock import patch
from chesswizard_plugin_api import PositionContext
from plugin_compatibility import assess_compatibility
from plugin_models import CompatibilityCode, HostVersions, InstallPhase, InstallTransaction, PluginLimits, RuntimeState
from plugin_repository import PluginRepository, checked_path, inventory
from plugin_state import PluginStateError, decode_json
from plugin_service import PluginService
from support.plugin_fixture import PluginFixture
from support.plugin_wheels import FEN, GOOD_CODE, PACKAGE, PLUGIN_ID, make_wheel


class PluginLifecycleTests(PluginFixture):
    def test_atomic_failure_preserves_prior_state(self):
        self.install()
        path = self.repository.root / "state.json"
        before = path.read_bytes()
        state = self.repository.read()
        state.requested[PLUGIN_ID] = replace(state.requested[PLUGIN_ID], generation=7)
        with patch("plugin_repository.os.replace", side_effect=OSError("synthetic atomic failure")):
            with self.assertRaises(OSError):
                with self.repository.exclusive():
                    self.repository.save(state)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(list(path.parent.glob(".atomic-*.tmp")))

    def test_noop_rescan_enable_and_reinstall_preserve_bytes_and_timestamps(self):
        self.install()
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        before = {p.relative_to(self.profile).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.profile.rglob("*") if p.is_file()}
        self.assertEqual(self.service.scan().plugins[0].runtime_state, RuntimeState.READY)
        self.assertFalse(self.service.set_enabled(PLUGIN_ID, True))
        self.assertFalse(self.install()["inserted"])
        after = {p.relative_to(self.profile).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in self.profile.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_corrupt_state_preserved_without_startup_failure(self):
        self.install()
        path = self.repository.root / "state.json"
        for raw in (b"not json", b'{"schema_version":2,"schema_version":2}', b'{"schema_version":1}', b'{"x":NaN}'):
            with self.subTest(raw=raw):
                path.write_bytes(raw)
                self.assertFalse(self.service.scan().plugins)
                self.assertTrue(self.service.scan().diagnostics)
                self.assertEqual(path.read_bytes(), raw)
                with self.assertRaises(PluginStateError):
                    self.install()

    def test_restart_persists_intent_without_importing(self):
        self.install(code="raise SystemExit('should never import during rescan')")
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        self.service.close()
        self.service = PluginService(self.profile)
        with patch.object(self.service.supervisor, "failure", return_value=None):
            view = self.service.scan().plugins[0]
        self.assertTrue(view.requested.enabled)
        self.assertEqual(view.runtime_state, RuntimeState.READY)

    def test_duplicates_block_all_without_metadata_or_import(self):
        self.install(code="raise AssertionError('no collision imports')")
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        self.publish_collision()
        files = inventory(self.repository.root / "installations")
        with patch.object(self.service.supervisor, "call", side_effect=AssertionError("no worker for conflicts")):
            snapshot = self.service.scan()
            self.assertEqual(len(snapshot.plugins), 2)
            self.assertTrue(all(v.compatibility == CompatibilityCode.DUPLICATE and v.runtime_state == RuntimeState.BLOCKED for v in snapshot.plugins))
            with self.assertRaises(ValueError):
                self.service.analyze(PLUGIN_ID, PositionContext("duplicate", FEN))
        self.assertEqual(inventory(self.repository.root / "installations"), files)
        self.assertEqual(snapshot, self.service.scan())

    def test_resolved_collision_stays_disabled_until_explicit_enable(self):
        self.install()
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        collision = self.publish_collision()
        self.service.scan()
        self.assertTrue(self.service.remove(PLUGIN_ID, installation_id=collision.installation_id))
        with self.assertRaises(ValueError):
            self.service.analyze(PLUGIN_ID, PositionContext("no-auto", FEN))
        self.service.set_enabled(PLUGIN_ID, True)
        self.assertEqual(self.service.scan().plugins[0].runtime_state, RuntimeState.READY)

    def test_remove_selected_duplicate_does_not_choose_implicit_winner(self):
        self.install()
        original = self.receipt()
        collision = self.publish_collision()
        self.service.remove(PLUGIN_ID, installation_id=original.installation_id)
        self.assertEqual(self.repository.read().requested[PLUGIN_ID].installation_id, "")
        self.assertEqual(len(self.service.scan().plugins), 1)
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        self.assertEqual(self.receipt(), collision)

    def test_changed_site_bytes_revoke_trust_and_do_not_run(self):
        self.install()
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        path = self.repository.location(self.receipt().installation_id) / PACKAGE / "__init__.py"
        path.write_text("raise AssertionError('modified')")
        with patch.object(self.service.supervisor, "call", side_effect=AssertionError("no import")):
            view = self.service.scan().plugins[0]
        self.assertEqual(view.compatibility, CompatibilityCode.INTEGRITY)
        self.assertFalse(view.requested.enabled)
        self.assertEqual(view.requested.trusted_sha256, "")
        self.assertTrue(view.requested.requires_reenable)

    def test_retained_wheel_change_revokes_trust(self):
        self.install()
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        path = self.repository.location(self.receipt().installation_id).parent / "artifact.whl"
        path.write_bytes(b"changed wheel")
        self.assertFalse(self.service.scan().plugins[0].requested.enabled)
        self.assertEqual(self.repository.read().requested[PLUGIN_ID].trusted_sha256, "")

    def test_receipt_identity_change_blocks_execution(self):
        self.install()
        path = self.repository.location(self.receipt().installation_id).parent / "receipt.json"
        data = json.loads(path.read_text()); data["version"] = "9.9"
        path.write_text(json.dumps(data))
        self.assertEqual(self.service.scan().plugins[0].compatibility, CompatibilityCode.INTEGRITY)

    def test_interrupted_and_unindexed_installations_never_publish(self):
        self.install()
        identity = uuid.uuid4().hex
        self.repository.location(identity, staged=True).mkdir(parents=True)
        with self.repository.exclusive():
            state = self.repository.read()
            state.transactions[identity] = InstallTransaction(identity, InstallPhase.STAGED)
            self.repository.save(state)
        self.repository.location(uuid.uuid4().hex).mkdir(parents=True)
        before = inventory(self.profile)
        snapshot = self.service.scan()
        self.assertEqual(len(snapshot.plugins), 1)
        self.assertGreaterEqual(len(snapshot.diagnostics), 3)
        self.assertEqual(before, inventory(self.profile))

    def test_malformed_manifest_fails_before_publication_and_import(self):
        for extra in ({PACKAGE+"/chesswizard-plugin.json": b"bad json"},
                      {PACKAGE+"/chesswizard-plugin.json": b'{"schema_version":99}'}):
            with self.subTest(extra=extra):
                with self.assertRaises(RuntimeError):
                    self.install(extra=extra, code="raise AssertionError('no import')")
                self.assertFalse(self.repository.read().installations)
                self.assertTrue(self.service.scan().diagnostics)
        with self.assertRaises(RuntimeError):
            self.install(omit=(PACKAGE+"/chesswizard-plugin.json",))

    def test_static_compatibility_categories_and_proper_version_order(self):
        host = HostVersions("2.0.0", "1.2.0", "3.14.7")
        defaults = dict(required_api="1.0", minimum_app="1.9", python_requirement=">=3.14,<3.15",
                        dependencies=("chesswizard-plugin-api>=1,<2",), host=host)
        cases = [(dict(required_api="2"), CompatibilityCode.API),
                 (dict(minimum_app="10.0"), CompatibilityCode.APP),
                 (dict(python_requirement="<3.14"), CompatibilityCode.PYTHON),
                 (dict(dependencies=("requests",)), CompatibilityCode.DEPENDENCY),
                 (dict(dependencies=("chesswizard-plugin-api[extra]>=1",)), CompatibilityCode.DEPENDENCY),
                 (dict(required_api="garbage"), CompatibilityCode.METADATA)]
        self.assertEqual(assess_compatibility(**defaults)[0], CompatibilityCode.COMPATIBLE)
        for changed, expected in cases:
            with self.subTest(changed=changed):
                self.assertEqual(assess_compatibility(**(defaults | changed))[0], expected)

    def test_dependency_python_and_capability_checks_are_preimport(self):
        info = "chesswizard_plugin_test-1.0.0.dist-info/METADATA"
        base = "Metadata-Version: 2.4\nName: chesswizard-plugin-test\nVersion: 1.0.0\nAuthor: Test\nLicense: MIT\n"
        for fields, code in (("Requires-Python: <3\nRequires-Dist: chesswizard-plugin-api>=1,<2\n", CompatibilityCode.PYTHON),
                             ("Requires-Python: >=3.14\nRequires-Dist: other-package\n", CompatibilityCode.DEPENDENCY)):
            with self.subTest(code=code):
                result = self.install(extra={info: (base+fields).encode()}, code="raise AssertionError('no import')")
                self.assertEqual(result["descriptor"]["compatibility_code"], code)
                with self.assertRaises(ValueError):
                    self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
                self.service.remove(PLUGIN_ID)
        manifest = dict(schema_version=1, plugin_id=PLUGIN_ID, display_name="Synthetic", minimum_app_version="1",
                        api_version="1", type="position_facts", capabilities=["arbitrary_tactics"])
        with self.assertRaises(RuntimeError):
            self.install(extra={PACKAGE+"/chesswizard-plugin.json": json.dumps(manifest).encode()})

    def test_successful_replacement_requires_new_artifact_trust(self):
        self.install()
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        old = self.receipt()
        result = self.service.replace(PLUGIN_ID, make_wheel(self.root, code=GOOD_CODE+"\n# new artifact\n"))
        new = self.receipt()
        self.assertNotEqual(old.installation_id, new.installation_id)
        self.assertNotEqual(old.artifact_sha256, new.artifact_sha256)
        self.assertFalse(self.repository.location(old.installation_id).exists())
        self.assertFalse(self.repository.read().requested[PLUGIN_ID].enabled)
        self.assertEqual(self.repository.read().requested[PLUGIN_ID].trusted_sha256, "")
        with self.assertRaises(ValueError):
            self.service.set_enabled(PLUGIN_ID, True)
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        self.assertEqual(len(self.service.analyze(PLUGIN_ID, PositionContext("new", FEN)).squares), 32)

    def test_incompatible_replacement_preserves_old_receipt_and_trust(self):
        self.install(); self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        before = self.repository.read()
        files = inventory(self.repository.root / "installations")
        with self.assertRaises(ValueError):
            self.service.replace(PLUGIN_ID, make_wheel(self.root, api="99"))
        after = self.repository.read()
        self.assertEqual(before.installations, after.installations)
        self.assertEqual(before.requested, after.requested)
        self.assertEqual(files, inventory(self.repository.root / "installations"))
        self.assertEqual(len(self.service.analyze(PLUGIN_ID, PositionContext("old", FEN)).squares), 32)

    def test_failed_atomic_replacement_switch_preserves_working_old_plugin(self):
        self.install(); self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        before = self.repository.read()
        old = self.receipt()
        save = self.repository.save
        def fail_switch(state):
            if old.installation_id not in state.installations:
                raise OSError("synthetic publication failure")
            return save(state)
        with patch.object(self.repository, "save", side_effect=fail_switch):
            with self.assertRaises(OSError):
                self.service.replace(PLUGIN_ID, make_wheel(self.root, code=GOOD_CODE+"\n# replacement\n"))
        after = self.repository.read()
        self.assertEqual(before.installations, after.installations)
        self.assertEqual(before.requested, after.requested)
        self.assertFalse(any(tx.stop_requested for tx in after.transactions.values()))
        self.assertTrue(self.service.scan().diagnostics)
        self.assertEqual(len(self.service.analyze(PLUGIN_ID, PositionContext("rollback", FEN)).squares), 32)

    def test_removal_never_runs_hooks_or_touches_other_plugin(self):
        self.install(code="raise AssertionError('no uninstall hook')")
        self.install(plugin_id="org.example.other")
        other = self.receipt("org.example.other")
        before = inventory(self.repository.location(other.installation_id))
        self.assertTrue(self.service.remove(PLUGIN_ID))
        self.assertEqual(before, inventory(self.repository.location(other.installation_id)))
        self.assertEqual([v.installed.plugin_id for v in self.service.scan().plugins], ["org.example.other"])

    def test_failed_cleanup_unpublishes_without_automatic_retry(self):
        self.install()
        old = self.receipt()
        with patch("plugin_repository.shutil.rmtree", side_effect=PermissionError("busy file")) as delete:
            self.assertFalse(self.service.remove(PLUGIN_ID))
            state = self.repository.read()
            self.assertFalse(state.installations)
            self.assertIn(old.installation_id, state.retired)
            self.assertIn(old.installation_id, state.cleanup_failures)
            self.service.scan(); self.service.scan()
            self.assertEqual(delete.call_count, 1)
        self.assertTrue(self.service.cleanup(old.installation_id))
        self.assertFalse(self.repository.read().retired)

    def test_forged_removal_receipt_and_unsafe_paths_refused(self):
        self.install()
        receipt = self.receipt()
        for relative in ("../escape", "/absolute", "C:/escape", "file:stream", "CON.txt", "name.", "folder/../other"):
            with self.subTest(relative=relative):
                with self.assertRaises(ValueError):
                    checked_path(self.repository.root, relative)
        with self.assertRaises(ValueError):
            self.repository.delete_installation(replace(receipt, managed_path="../outside"))
        with self.assertRaises(ValueError):
            PluginRepository(Path(__file__).resolve().parents[1])
        self.assertTrue(self.repository.location(receipt.installation_id).exists())

    def test_file_directory_conflicts_and_noncanonical_archive_paths(self):
        for extra in ({PACKAGE+"/folder": b"file", PACKAGE+"/folder/nested.py": b"code"},
                      {PACKAGE+"//alias.py": b"code"}, {PACKAGE+"/./alias.py": b"code"},
                      {PACKAGE+"/UPPER.py": b"code", PACKAGE+"/upper.py": b"code"}):
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError):
                    self.install(extra=extra)
        self.assertFalse(self.repository.read().installations)

    @unittest.skipUnless(os.name == "nt", "Windows junction containment")
    def test_junction_refuses_discovery_and_removal_without_touching_external_files(self):
        self.install()
        receipt = self.receipt()
        external = self.root / "external"
        external.mkdir()
        sentinel = external / "keep.txt"
        sentinel.write_bytes(b"external must survive")
        junction = self.repository.location(receipt.installation_id) / "junction"
        command = Path(os.environ["SystemRoot"]) / "System32/cmd.exe"
        result = subprocess.run([str(command), "/d", "/c", "mklink", "/J", str(junction), str(external)],
                                capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            self.assertEqual(self.service.scan().plugins[0].compatibility, CompatibilityCode.INTEGRITY)
            self.assertFalse(self.service.remove(PLUGIN_ID))
            self.assertEqual(sentinel.read_bytes(), b"external must survive")
            self.assertIn(receipt.installation_id, self.repository.read().retired)
        finally:
            junction.rmdir()
        self.assertTrue(self.service.cleanup(receipt.installation_id))

    def test_public_plugin_modules_have_no_tk_or_chess_storage_dependency(self):
        import ast
        root = Path(__file__).resolve().parents[1]
        forbidden = {"tkinter", "sqlite3", "database", "application_settings", "tactic_repository", "analysis_coverage"}
        for path in (*root.glob("plugin_*.py"), *root.glob("chesswizard_plugin_api/*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.add(node.module.split(".")[0])
            self.assertFalse(names & forbidden, path.name)
