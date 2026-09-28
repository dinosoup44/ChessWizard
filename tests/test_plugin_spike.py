"""Synthetic wheel and worker regressions; never use owner profiles or engines."""
from dataclasses import asdict, replace
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chesswizard_plugin_api import PositionContext
from plugin_discovery import discover
from plugin_models import PluginLimits
from plugin_repository import checked_path, inventory
from plugin_runtime import run_worker
from plugin_service import PluginService

from support.plugin_wheels import FEN, GOOD_CODE, PACKAGE, PLUGIN_ID, make_wheel


class PluginSpikeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.profile = self.root / "profile"
        self.profile.mkdir()
        for name in ("merlin.db", "settings.json", "opening_books/sentinel.cwbook"):
            path = self.profile / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic owner data must remain unchanged")
        self.before = {p: h for p, h in inventory(self.profile).items()}
        self.service = PluginService(self.profile)

    def receipt(self):
        state = self.service.repository.read()
        return state.installations[state.requested[PLUGIN_ID].installation_id]

    def tearDown(self):
        self.service.close()
        for name, digest in self.before.items():
            self.assertEqual(hashlib.sha256((self.profile / name).read_bytes()).hexdigest(), digest)
        self.temporary.cleanup()

    def install(self, **kwargs):
        wheel = make_wheel(self.root, **kwargs)
        return self.service.install(wheel)

    def test_end_to_end_and_idempotent_state(self):
        self.assertTrue(self.install()["inserted"])
        snapshot = inventory(self.profile)
        self.assertFalse(self.install()["inserted"])
        self.assertEqual(snapshot, inventory(self.profile))
        with self.assertRaisesRegex(ValueError, "trust"):
            self.service.set_enabled(PLUGIN_ID, True)
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        self.assertFalse(self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True))
        result = self.service.analyze(PLUGIN_ID, PositionContext("synthetic", FEN))
        self.assertEqual(len(result.squares), 32)
        self.assertEqual(sum(x.count for x in result.counts), 32)
        site = self.service.repository.verify(self.receipt())
        worker = run_worker({"operation": "analyze", "site": str(site),
                             "profile": str(self.profile), "plugin_id": PLUGIN_ID,
                             "context": asdict(PositionContext("pid-proof", FEN))}, PluginLimits())
        self.assertNotEqual(worker["worker_pid"], os.getpid())
        self.service.set_enabled(PLUGIN_ID, False)
        with patch.object(self.service.supervisor, "call", side_effect=AssertionError("must not execute")):
            with self.assertRaisesRegex(ValueError, "disabled"):
                self.service.analyze(PLUGIN_ID, PositionContext("disabled", FEN))
        with self.assertRaisesRegex(RuntimeError, "discovery"):
            run_worker({"operation": "analyze", "site": str(site),
                        "profile": str(self.profile), "plugin_id": PLUGIN_ID,
                        "context": asdict(PositionContext("direct-disabled", FEN))}, PluginLimits())
        self.service.remove(PLUGIN_ID)
        self.assertEqual(self.service.list_plugins(), [])

    def test_discovery_does_not_import_failing_plugin(self):
        self.install(code='raise RuntimeError("MUST NOT IMPORT DURING DISCOVERY")')
        plugins = self.service.list_plugins()
        self.assertFalse(plugins[0]["enabled"])
        site = self.service.repository.verify(self.receipt())
        response = run_worker({"operation": "discover", "site": str(site)}, PluginLimits())
        self.assertEqual(response["plugin_modules_loaded"], [])
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        with self.assertRaisesRegex(RuntimeError, "import"):
            self.service.analyze(PLUGIN_ID, PositionContext("error", FEN))
        self.assertTrue(self.service.list_plugins())

    def test_restart_retains_disabled_and_enabled_state(self):
        self.install()
        self.assertFalse(PluginService(self.profile).list_plugins()[0]["enabled"])
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        self.assertTrue(PluginService(self.profile).list_plugins()[0]["enabled"])

    def test_incompatible_api_retained_disabled(self):
        self.install(api="2.0.0", code='raise AssertionError("do not import")')
        self.assertFalse(self.service.list_plugins()[0]["descriptor"]["compatible"])
        with self.assertRaisesRegex(ValueError, "API"):
            self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)

    def test_minimum_application_version_checked(self):
        self.install(minimum="99.0.0")
        self.assertIn("Minimum", self.service.list_plugins()[0]["descriptor"]["reason"])

    def test_duplicate_id_rejected_existing_unchanged(self):
        self.install()
        snapshot = inventory(self.service.repository.location(self.receipt().installation_id))
        before = self.service.repository.read()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.install(code=GOOD_CODE + "\n# distinct artifact\n")
        self.assertEqual(snapshot, inventory(self.service.repository.location(self.receipt().installation_id)))
        after = self.service.repository.read()
        self.assertEqual(before.installations, after.installations)
        self.assertEqual(before.requested, after.requested)

    def test_changed_artifact_requires_new_trust(self):
        self.install()
        receipt = self.receipt()
        path = self.service.repository.location(receipt.installation_id) / PACKAGE / "__init__.py"
        path.write_text("raise AssertionError('changed')")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)

    def test_wrong_facts_rejected_by_core(self):
        self.install(code=GOOD_CODE.replace("tuple(squares), counts", "tuple(), counts"))
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        with self.assertRaisesRegex(ValueError, "Square evidence"):
            self.service.analyze(PLUGIN_ID, PositionContext("wrong", FEN))

    def test_hang_is_bounded(self):
        self.install(code="while True: pass")
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        self.service.limits = replace(PluginLimits(), timeout_seconds=0.5)
        with self.assertRaisesRegex(RuntimeError, "time limit"):
            self.service.analyze(PLUGIN_ID, PositionContext("hang", FEN))

    def test_output_flood_is_bounded(self):
        self.install(code='while True: print("x"*4096)')
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        with self.assertRaisesRegex(RuntimeError, "output limit"):
            self.service.analyze(PLUGIN_ID, PositionContext("flood", FEN))

    def test_unsafe_or_unrelated_wheel_paths_rejected(self):
        for name in ("../escape.py", "outside.py", "foo.pth", "pkg/CON", "/absolute.py", "pkg/file:stream"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.install(extra={name: b"unsafe"})
        self.assertEqual(self.service.list_plugins(), [])

    def test_metadata_does_not_mutate_files(self):
        self.install()
        before = inventory(self.profile)
        self.service.list_plugins()
        self.service.list_plugins()
        self.assertEqual(before, inventory(self.profile))

    def test_path_escape_and_no_default_profile(self):
        with self.assertRaises(ValueError):
            checked_path(self.profile, "../outside")
        self.assertFalse((self.profile / "plugins").exists())


if __name__ == "__main__":
    unittest.main()