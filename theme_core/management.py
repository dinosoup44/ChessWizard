"""Delete only validated, privately owned theme packages under the managed root."""
from dataclasses import dataclass, replace
import hashlib
import shutil
from .assets import reject_links
from .active import DEFAULT_THEME


@dataclass(frozen=True)
class ThemeDeletionPlan:
    theme_id: str
    name: str
    asset_count: int
    total_bytes: int
    active: bool
    fingerprint: str


class ThemeManagementService:
    def __init__(self, active_service):
        self.active = active_service

    def _files(self, theme_id):
        if theme_id == DEFAULT_THEME.theme.theme_id:
            raise ValueError("The built-in fallback theme cannot be deleted")
        repo = self.active.repository
        loaded = repo.load(theme_id)
        folder = repo.managed_directory(theme_id)
        if folder.resolve().parent != repo.root.resolve():
            raise ValueError("Theme must be a direct managed child")
        files = []
        for path in sorted(folder.rglob("*")):
            reject_links(path)
            if path.is_file():
                if path.stat().st_nlink != 1:
                    raise ValueError("Shared/hard-linked theme assets cannot be deleted")
                files.append((path.relative_to(folder), path.read_bytes()))
        return loaded, folder, files

    def plan(self, theme_id):
        loaded, folder, files = self._files(theme_id)
        digest = hashlib.sha256()
        for name, data in files:
            digest.update(str(name).encode()); digest.update(data)
        return ThemeDeletionPlan(theme_id, loaded.theme.name, len(files)-1,
            sum(len(data) for _, data in files),
            self.active.settings.load().active_theme_id == theme_id, digest.hexdigest())

    def themes(self):
        result = []
        for theme in self.active.repository.list_themes():
            if theme.theme_id != "default":
                result.append(self.plan(theme.theme_id))
        return tuple(result)

    def delete(self, plan):
        if self.plan(plan.theme_id) != plan:
            raise ValueError("Theme changed since preview; refresh and confirm again")
        loaded, folder, files = self._files(plan.theme_id)
        if plan.active:
            # Persist fallback before touching assets. On deletion failure fallback is
            # still valid; never roll settings back to a potentially missing package.
            settings = self.active.settings.load()
            self.active.settings.save(replace(settings, active_theme_id="default"))
            self.active.refresh()
        try:
            reject_links(folder)
            if folder.resolve().parent != self.active.repository.root.resolve():
                raise ValueError("Unsafe theme deletion target")
            shutil.rmtree(folder)
        except OSError:
            # Keep the package recoverable after a partial filesystem failure.
            for relative, data in files:
                target = folder / relative
                reject_links(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            raise
        self.active.refresh(notify=True)
