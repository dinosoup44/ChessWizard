"""Temporary plugin-only service fixtures with protected chess-data sentinels."""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
from plugin_models import InstalledPlugin
from plugin_repository import inventory
from plugin_service import PluginService
from support.plugin_wheels import PLUGIN_ID, make_wheel


class PluginFixture(unittest.TestCase):
    """Keep every lifecycle test isolated from real profiles and core files."""
    def setUp(self) -> None:
        """Create a disposable profile with unrelated-data sentinels."""
        self.temporary = tempfile.TemporaryDirectory(prefix="plugin-lifecycle-test-")
        self.root = Path(self.temporary.name)
        self.profile = self.root / "profile"
        self.profile.mkdir()
        self.sentinels = {}
        for name in ("merlin.db", "settings.json", "opening_books/test.cwbook", "themes/test/theme.json", "reviews/test.json"):
            path = self.profile / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic protected user data")
            self.sentinels[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.service = PluginService(self.profile)
        self.repository = self.service.repository

    def tearDown(self) -> None:
        """Stop synthetic workers and prove unrelated data stayed byte-identical."""
        self.service.close()
        for name, expected in self.sentinels.items():
            self.assertEqual(hashlib.sha256((self.profile / name).read_bytes()).hexdigest(), expected)
        self.temporary.cleanup()

    def install(self, **kwargs: object) -> dict:
        """Install a synthetic wheel into the disposable managed profile.

        Args:
            kwargs: Synthetic wheel parameters.

        Returns:
            Lifecycle installation summary.
        """
        return self.service.install(make_wheel(self.root, **kwargs))

    def receipt(self, plugin_id: str = PLUGIN_ID) -> InstalledPlugin:
        """Read the uniquely selected temporary receipt.

        Args:
            plugin_id: Synthetic stable identity.

        Returns:
            Typed installed receipt.
        """
        state = self.repository.read()
        return state.installations[state.requested[plugin_id].installation_id]

    def publish_collision(self) -> InstalledPlugin:
        """Simulate two indexed distributions without executing either implementation.

        Returns:
            Second immutable synthetic receipt for duplicate-discovery tests.
        """
        original = self.receipt()
        identity = uuid.uuid4().hex
        copied = replace(original, installation_id=identity, managed_path=f"installations/{identity}/site-packages")
        site = self.repository.location(identity)
        shutil.copytree(self.repository.location(original.installation_id).parent, site.parent)
        (site.parent / "receipt.json").write_text(json.dumps(asdict(copied), sort_keys=True, indent=2)+"\n", encoding="utf-8")
        with self.repository.exclusive():
            state = self.repository.read()
            state.installations[identity] = copied
            self.repository.save(state)
        return copied
