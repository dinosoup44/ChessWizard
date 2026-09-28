"""Durable staged publication, explicit replacement, and receipt-owned cleanup."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import uuid
from plugin_admission import selected_installation
from plugin_diagnostics import PluginDiagnostics
from plugin_inspection import inspect_installation, inspect_site
from plugin_locking import file_lease
from plugin_models import InstalledPlugin, InstallPhase, InstallTransaction, PluginLimits, RequestedState
from plugin_package import install_wheel
from plugin_repository import PluginRepository, atomic_bytes, checked_path, inventory
from plugin_runtime import WorkerSupervisor


class PluginInstaller:
    """Publish only validated disabled installations through an atomic state switch.

    Args:
        repository: Plugin-only owned storage.
        supervisor: Shared cancellation and worker bounds.
        diagnostics: Bounded local diagnostic sink.
        limits: Package and runtime bounds.
    """
    def __init__(self, repository: PluginRepository, supervisor: WorkerSupervisor,
                 diagnostics: PluginDiagnostics, limits: PluginLimits) -> None:
        """Bind lifecycle collaborators without performing work.

        Args:
            repository: Managed storage.
            supervisor: Worker controller.
            diagnostics: Local diagnostics.
            limits: Operational limits.
        """
        self.repository, self.supervisor, self.diagnostics, self.limits = repository, supervisor, diagnostics, limits

    def install(self, wheel: Path, *, replacing: str | None = None) -> dict:
        """Install or explicitly replace one artifact; exact bytes are idempotent.

        Args:
            wheel: Independently built restricted wheel.
            replacing: Stable ID explicitly selected for replacement, if any.

        Returns:
            Descriptor, installation identity, and whether publication changed.

        Raises:
            ValueError: Package, compatibility, or duplicate identity is invalid.
            RuntimeError: Another lifecycle operation or bounded worker prevents completion.
        """
        if wheel.suffix != ".whl" or wheel.stat().st_size > self.limits.max_wheel_bytes:
            raise ValueError("Expected a bounded local wheel")
        payload = wheel.read_bytes()
        if len(payload) > self.limits.max_wheel_bytes:
            raise ValueError("Wheel exceeds compressed size limit")
        digest = hashlib.sha256(payload).hexdigest()
        with file_lease(checked_path(self.repository.root, "install.lock")):
            state = self.repository.read()
            old = selected_installation(state, replacing) if replacing else None
            for receipt in state.installations.values():
                if receipt.artifact_sha256 == digest and (old is None or old == receipt):
                    selected_installation(state, receipt.plugin_id)
                    descriptor = inspect_installation(self.repository, receipt, self.supervisor, self.limits)
                    return {"inserted": False, "installation_id": receipt.installation_id, "descriptor": asdict(descriptor)}
            return self._publish(payload, wheel.name, digest, old)

    def _publish(self, payload: bytes, filename: str, digest: str, old: InstalledPlugin | None) -> dict:
        repository = self.repository
        identity = uuid.uuid4().hex
        transaction = InstallTransaction(identity, InstallPhase.STAGED, old.installation_id if old else "")
        with repository.exclusive():
            state = repository.read()
            # Published transaction history is already represented by immutable receipts.
            state.transactions = {key: value for key, value in state.transactions.items() if value.phase != InstallPhase.PUBLISHED}
            state.transactions[identity] = transaction
            repository.save(state)
        published = False
        try:
            site = repository.location(identity, staged=True)
            source = checked_path(site.parent, filename)
            atomic_bytes(source, payload)
            install_wheel(source, site, self.limits)
            descriptor = inspect_site(site, identity, self.supervisor, self.limits)
            if old and (descriptor.plugin_id != old.plugin_id or not descriptor.compatible):
                raise ValueError("Replacement must retain the plugin ID and be compatible")
            receipt = InstalledPlugin(identity, descriptor.plugin_id, descriptor.distribution_name, descriptor.version,
                        digest, f"installations/{identity}/site-packages", datetime.now(timezone.utc).isoformat(),
                        filename, descriptor.manifest_sha256, descriptor.api_version, descriptor.minimum_app_version,
                        descriptor.plugin_type, descriptor.capabilities, inventory(site, self.limits))
            artifact = checked_path(site.parent, "artifact.whl")
            source.replace(artifact)
            repository.write_receipt(receipt)
            with repository.exclusive():
                state = repository.read()
                matches = [r for r in state.installations.values() if r.plugin_id == descriptor.plugin_id]
                if old is None and matches:
                    raise ValueError("Duplicate plugin ID; existing plugin unchanged")
                if old and (len(matches) != 1 or matches[0] != old):
                    raise ValueError("Replacement selection changed")
                state.transactions[identity] = replace(transaction, phase=InstallPhase.VALIDATED, stop_requested=bool(old))
                repository.save(state)
            if old:
                self.supervisor.cancel(old.installation_id)
            with repository.invocation(old.installation_id if old else identity,
                                       self.limits.shutdown_timeout_seconds + self.limits.lock_timeout_seconds):
                destination = repository.location(identity).parent
                destination.parent.mkdir(parents=True, exist_ok=True)
                site.parent.replace(destination)
                with repository.exclusive():
                    state = repository.read()
                    if old and state.installations.get(old.installation_id) != old:
                        raise ValueError("Replacement selection changed before commit")
                    generation = state.requested[old.plugin_id].generation + 1 if old else 0
                    if old:
                        state.retired[old.installation_id] = state.installations.pop(old.installation_id)
                    state.installations[identity] = receipt
                    state.requested[receipt.plugin_id] = RequestedState(identity, generation=generation)
                    state.transactions[identity] = replace(transaction, phase=InstallPhase.PUBLISHED)
                    repository.save(state)
                    published = True
            if old:
                self.cleanup(old.installation_id)
            return {"inserted": True, "installation_id": identity, "descriptor": asdict(descriptor)}
        except BaseException:
            if not published:
                try:
                    with repository.exclusive():
                        state = repository.read()
                        state.transactions[identity] = replace(transaction, phase=InstallPhase.FAILED,
                                                               message="Unpublished transaction retained for review")
                        repository.save(state)
                except (OSError, ValueError, RuntimeError):
                    pass
                self.diagnostics.record(old, "installation", "publication_failed", "Installation failed; unpublished files retained for review")
            raise

    def remove(self, plugin_id: str, *, installation_id: str | None = None) -> bool:
        """Disable, cancel, unpublish, then clean one explicitly owned installation.

        Args:
            plugin_id: Stable plugin identity.
            installation_id: Required to resolve a duplicate-ID installation explicitly.

        Returns:
            Whether physical cleanup succeeded; failures remain retired and disabled.

        Raises:
            ValueError: Selected identity is missing, ambiguous, or not owned.
            RuntimeError: Active work cannot be stopped within the deadline.
        """
        repository = self.repository
        with file_lease(checked_path(repository.root, "install.lock")):
            with repository.exclusive():
                state = repository.read()
                receipt = state.installations[installation_id] if installation_id else selected_installation(state, plugin_id)
                if receipt.plugin_id != plugin_id:
                    raise ValueError("Removal identity mismatch")
                requested = state.requested[plugin_id]
                state.requested[plugin_id] = replace(requested, enabled=False, generation=requested.generation + int(requested.enabled), requires_reenable=True)
                repository.save(state)
            self.supervisor.cancel(receipt.installation_id)
            with repository.invocation(receipt.installation_id, self.limits.shutdown_timeout_seconds + self.limits.lock_timeout_seconds):
                with repository.exclusive():
                    state = repository.read()
                    state.retired[receipt.installation_id] = state.installations.pop(receipt.installation_id)
                    remaining = [r for r in state.installations.values() if r.plugin_id == plugin_id]
                    if not remaining:
                        state.requested.pop(plugin_id)
                    elif state.requested[plugin_id].installation_id == receipt.installation_id:
                        # An unresolved collision has no implicit first/last winner.
                        state.requested[plugin_id] = RequestedState("", generation=requested.generation + 1, requires_reenable=True)
                    repository.save(state)
            return self.cleanup(receipt.installation_id)

    def cleanup(self, installation_id: str) -> bool:
        """Explicitly retry cleanup of an unpublished receipt-owned directory.

        Args:
            installation_id: Retired installation identity.

        Returns:
            True when cleanup and receipt removal succeed; otherwise False.
        """
        repository = self.repository
        state = repository.read()
        receipt = state.retired.get(installation_id)
        if receipt is None:
            return False
        try:
            with repository.invocation(installation_id, self.limits.shutdown_timeout_seconds):
                repository.delete_installation(receipt)
            with repository.exclusive():
                state = repository.read()
                state.retired.pop(installation_id, None)
                state.cleanup_failures.pop(installation_id, None)
                repository.save(state)
            return True
        except (OSError, ValueError, RuntimeError):
            with repository.exclusive():
                state = repository.read()
                state.cleanup_failures[installation_id] = "Cleanup failed; retired installation stays disabled; explicit review required"
                repository.save(state)
            self.diagnostics.record(receipt, "removal", "cleanup_failed", "Owned cleanup failed; installation remains unpublished and disabled")
            return False
