"""Admin orchestration and explicit aggregate export, independent of desktop widgets."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
from admin_database import database_status
from admin_capabilities import capability_status, profile_status
from admin_engine import engine_status, test_engine
from admin_models import AdminSnapshot
from application_paths import resolve_database_path
from chesswizard_version import PRODUCT_NAME, VERSION, DISPLAY_VERSION
from application_settings import application_data_directory
from theme_core.active import get_active_theme_service

BUILD_SOURCES = ("analysis_registry.py","analysis_settings.py","application_settings.py",
                 "admin_service.py","admin_models.py","admin_database.py","admin_capabilities.py","admin_engine.py",
                 "merlin_ui/admin_console.py","chesswizard_version.py","database_schema.py","database_bootstrap.py","application_paths.py")


def path_status(path):
    path = Path(path)
    ancestor = path
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    return dict(path=str(path),exists=path.exists(),
                writable_hint=os.access(ancestor,os.W_OK),writable_hint_basis="os.access on nearest existing ancestor; no write probe")


class AdminService:
    def __init__(self, root=None, database_path=None, theme_service=None):
        self.root = Path(root) if root is not None else Path(__file__).resolve().parent
        self.database_path = resolve_database_path(database_path,root=self.root)
        self.themes = theme_service if theme_service is not None else get_active_theme_service()

    def snapshot(self, *, diagnostics=False):
        database = database_status(self.database_path,diagnostics=diagnostics)
        theme = self.themes.resolve()
        try:
            settings = asdict(self.themes.settings.load())
            settings_error = ""
        except (ValueError,OSError) as error:
            settings,settings_error = {},str(error)
        try:
            repository = path_status(self.themes.repository.root)
        except (ValueError,OSError) as error:
            repository = dict(error=str(error))
        app = dict(settings=settings,settings_error=settings_error,theme_requested_id=theme.requested_id,
                   theme_resolved_id=theme.loaded.theme.theme_id,theme_error=theme.error,
                   theme_repository=repository,settings_path=path_status(self.themes.settings.path),
                   application_data=path_status(application_data_directory()),project=path_status(self.root))
        hashes = {name:hashlib.sha256((self.root/name).read_bytes()).hexdigest()
                  for name in BUILD_SOURCES if (self.root/name).is_file()}
        build = dict(product_name=PRODUCT_NAME,version=VERSION,release_version=DISPLAY_VERSION,
                     installation="frozen executable" if getattr(sys,"frozen",False) else "source checkout",
                     source_fingerprint=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest(),
                     fingerprint_scope=list(hashes),python=platform.python_version(),sqlite=__import__("sqlite3").sqlite_version,
                     project_root=str(self.root))
        occurrence = dict(database.occurrence)
        manifest = self.database_path.parent/"occurrence_storage_lineage.json"
        if occurrence.get("bootstrap"):
            occurrence["activation"] = "Current clean-user schema; Tactic Occurrence Storage V1 initialized"
        else:
            try:
                with manifest.open("rb") as stream:
                    raw = stream.read(65537)
                if len(raw)>65536:
                    raise ValueError("Migration manifest too large")
                data = json.loads(raw)
                if (not isinstance(data,dict) or data.get("migration_id") != "tactic_occurrence_storage_v1"
                        or type(data.get("storage_contract_version")) is not int
                        or not isinstance(data.get("schema_sha256"),str)
                        or not re.fullmatch(r"[0-9a-f]{64}",data["schema_sha256"])
                        or not isinstance(data.get("identity_versions"),list)
                        or any(type(v) is not int for v in data["identity_versions"])):
                    raise ValueError("Invalid migration metadata")
                # Lineage UUIDs, backup locations and legacy identities are not diagnostic exports.
                occurrence["manifest"] = {k:data.get(k) for k in (
                    "migration_id","storage_contract_version","schema_sha256","identity_versions")}
                occurrence["activation"] = "Tables present; manifest version is declarative, not a full migration replay" if occurrence.get("schema_state")=="present" else "Occurrence schema absent or incomplete"
            except (ValueError,OSError) as error:
                occurrence["manifest_error"] = type(error).__name__+": migration metadata unavailable"
        database = replace(database, occurrence=occurrence)
        return AdminSnapshot(datetime.now(timezone.utc).isoformat(),build,database,
                             engine_status(self.root),capability_status(self.root,database.candidate_counts if database.counts.get("tactic_candidates") is not None else None),
                             profile_status(),app)

    def test_engine(self):
        return test_engine(self.root)

    def export(self, snapshot: AdminSnapshot, destination):
        """Write aggregate JSON only, exclusively to a new explicit .json report file."""
        path = Path(destination)
        if path.suffix.lower() != ".json":
            raise ValueError("Choose a .json report path")
        payload = dict(report_version=1,privacy="Aggregates/settings/versions and necessary local paths only; no game rows, candidate IDs, cache payloads, themes or credentials.",
                       **asdict(snapshot))
        # Exclusive creation prevents an export from overwriting an existing user file.
        with path.open("x",encoding="utf-8") as stream:
            json.dump(payload,stream,indent=2)
            stream.write("\n")
        return path
