"""Frontend-independent lifecycle and factual invocation for trusted external plugins."""
from dataclasses import asdict, replace
from pathlib import Path
from chesswizard_plugin_api import MaterialFacts, PositionContext
from plugin_admission import request_is_current, selected_installation
from plugin_diagnostics import PluginDiagnostics
from plugin_inspection import inspect_installation
from plugin_installation import PluginInstaller
from plugin_locking import PluginBusyError
from plugin_models import (CompatibilityCode, DiscoverySnapshot, InstalledPlugin, PluginLimits,
                           PluginView, RequestedState, RuntimeState)
from plugin_protocol import material_result, validate_context
from plugin_repository import PluginRepository
from plugin_runtime import PluginCancelledError, PluginWorkerError, supervisor_for


class PluginService:
    """Coordinate plugin-only state and workers without a chess database or UI.

    Args:
        profile: Explicit writable user profile outside application files.
        limits: Typed package/state/execution limits.
    """
    def __init__(self, profile: Path, limits: PluginLimits | None = None) -> None:
        """Select collaborators without starting workers or writing files.

        Args:
            profile: Explicit managed user-data directory.
            limits: Optional operational bounds.
        """
        self.limits = limits or PluginLimits()
        self.repository = PluginRepository(profile, self.limits)
        self.supervisor = supervisor_for(self.repository.root)
        self.diagnostics = PluginDiagnostics(self.repository.root, self.limits)

    def _installer(self) -> PluginInstaller:
        return PluginInstaller(self.repository, self.supervisor, self.diagnostics, self.limits)

    def install(self, wheel: Path) -> dict:
        """Install one validated artifact disabled, reusing an exact healthy install.

        Args:
            wheel: Local independently built restricted wheel.

        Returns:
            Metadata, installation identity, and inserted flag.

        Raises:
            ValueError: Package is unsafe or conflicts with a published identity.
            RuntimeError: A bounded helper or lifecycle operation fails.
        """
        return self._installer().install(wheel)

    def replace(self, plugin_id: str, wheel: Path) -> dict:
        """Explicitly replace an artifact atomically and require new code trust.

        Args:
            plugin_id: Unique current installation's stable ID.
            wheel: Compatible independently built replacement.

        Returns:
            Replacement identity, descriptor, and publication flag.

        Raises:
            ValueError: Replacement identity, compatibility, or package is invalid.
            RuntimeError: Work cannot be stopped or staging fails.
        """
        return self._installer().install(wheel, replacing=plugin_id)

    def _block(self, receipt: InstalledPlugin, *, revoke_trust: bool) -> None:
        with self.repository.exclusive():
            state = self.repository.read()
            requested = state.requested.get(receipt.plugin_id)
            if requested is None:
                return
            updated = replace(requested, requires_reenable=True,
                              enabled=False if revoke_trust else requested.enabled,
                              trusted_sha256="" if revoke_trust else requested.trusted_sha256)
            if updated != requested:
                state.requested[receipt.plugin_id] = replace(updated, generation=requested.generation + 1)
                self.repository.save(state)
        self.supervisor.cancel(receipt.installation_id)

    def scan(self) -> DiscoverySnapshot:
        """Discover deterministic static views while isolating malformed installations.

        Returns:
            Typed installation views and bounded recovery diagnostics. Existing
            malformed state is preserved and reported without preventing core startup.
        """
        try:
            state = self.repository.read()
            findings = self.repository.recovery_findings(state)
        except (OSError, ValueError, RuntimeError):
            message = "Plugin state/path requires explicit recovery; core startup may continue"
            self.diagnostics.record(None, "discovery", "state_invalid", message)
            return DiscoverySnapshot(diagnostics=(message,))
        counts = {}
        for receipt in state.installations.values():
            counts[receipt.plugin_id] = counts.get(receipt.plugin_id, 0) + 1
        views = []
        for receipt in sorted(state.installations.values(), key=lambda r: (r.plugin_id, r.distribution_name, r.version, r.installation_id)):
            requested = state.requested[receipt.plugin_id]
            descriptor, reason, code = None, "", CompatibilityCode.COMPATIBLE
            runtime = RuntimeState.BLOCKED
            try:
                if counts[receipt.plugin_id] > 1:
                    code, reason = CompatibilityCode.DUPLICATE, "Duplicate plugin ID; every colliding installation is blocked"
                    self._block(receipt, revoke_trust=False)
                elif self.supervisor.running(receipt.installation_id):
                    runtime = RuntimeState.RUNNING
                else:
                    with self.repository.invocation(receipt.installation_id):
                        self.repository.verify(receipt)
                        descriptor = inspect_installation(self.repository, receipt, self.supervisor, self.limits)
                    code, reason = descriptor.compatibility_code, descriptor.reason
                    if not descriptor.compatible:
                        if requested.enabled:
                            self._block(receipt, revoke_trust=False)
                    elif self.supervisor.failure(receipt.installation_id):
                        runtime, reason = RuntimeState.FAILED, "Session failure; explicit re-enable is required"
                    elif request_is_current(state, receipt, requested):
                        runtime = RuntimeState.READY
                    elif not requested.enabled:
                        runtime = RuntimeState.DISABLED
                    else:
                        reason = "Explicit re-enable is required after a compatibility/conflict change"
            except PluginBusyError:
                reason = "Plugin is busy; rescan explicitly after active work finishes"
            except PluginWorkerError as error:
                code, reason = CompatibilityCode.METADATA, "Static metadata helper failed; implementation was not imported"
                self.diagnostics.record(receipt, error.phase, error.kind, reason)
            except (OSError, ValueError, RuntimeError):
                code, reason = CompatibilityCode.INTEGRITY, "Installation identity/files changed; explicit reinstall and trust review required"
                try:
                    self._block(receipt, revoke_trust=True)
                except (OSError, ValueError, RuntimeError):
                    pass
            if code != CompatibilityCode.COMPATIBLE:
                self.diagnostics.record(receipt, "discovery", code.value, reason)
            try:
                requested = self.repository.read().requested.get(receipt.plugin_id, requested)
            except (OSError, ValueError):
                runtime, reason = RuntimeState.BLOCKED, "State changed during discovery; rescan required"
            views.append(PluginView(receipt, requested, descriptor, code, runtime, reason))
        return DiscoverySnapshot(tuple(views), findings)

    def list_plugins(self) -> list[dict]:
        """Expose a compact CLI-compatible projection of typed discovery.

        Returns:
            Deterministically sorted metadata and independent intent/runtime states.
            Use scan() when startup/recovery diagnostics are also required.
        """
        return [{"plugin_id": view.installed.plugin_id, "installation_id": view.installed.installation_id,
                 "descriptor": asdict(view.descriptor) if view.descriptor else None,
                 "enabled": view.requested.enabled, "effective_enabled": (view.requested.enabled and not view.requested.requires_reenable
                                       and view.requested.trusted_sha256 == view.installed.artifact_sha256
                                       and view.runtime_state in (RuntimeState.READY, RuntimeState.RUNNING)),
                 "runtime_state": view.runtime_state.value, "compatibility": view.compatibility.value,
                 "error": view.reason} for view in self.scan().plugins]

    def set_enabled(self, plugin_id: str, enabled: bool, *, acknowledge_trust: bool = False,
                    expected_artifact_sha256: str | None = None) -> bool:
        """Persist explicit intent; disable cancels and drains existing invocations.

        Args:
            plugin_id: Stable installed plugin identity.
            enabled: Desired requested state.
            acknowledge_trust: Explicit acknowledgement for newly encountered artifact bytes.
            expected_artifact_sha256: Artifact shown by a frontend trust review;
                a replacement since that review must be reviewed again.

        Returns:
            Whether persisted intent changed; exact no-op writes preserve timestamps.

        Raises:
            ValueError: Trust, integrity, compatibility, or uniqueness prevents admission.
            RuntimeError: Worker cancellation or a bounded lock cannot complete.
        """
        if type(enabled) is not bool or type(acknowledge_trust) is not bool:
            raise ValueError("Enable/trust flags must be boolean")
        if not enabled:
            with self.repository.exclusive():
                state = self.repository.read()
                requested = state.requested[plugin_id]
                state.requested[plugin_id] = replace(requested, enabled=False, generation=requested.generation + int(requested.enabled))
                changed = self.repository.save(state)
                receipts = [r for r in state.installations.values() if r.plugin_id == plugin_id]
            for receipt in receipts:
                self.supervisor.cancel(receipt.installation_id)
                with self.repository.invocation(receipt.installation_id, self.limits.shutdown_timeout_seconds + self.limits.lock_timeout_seconds):
                    pass
            return changed
        receipt = selected_installation(self.repository.read(), plugin_id)
        if expected_artifact_sha256 is not None and receipt.artifact_sha256 != expected_artifact_sha256:
            raise ValueError("Plugin changed since review; refresh and review the new artifact")
        with self.repository.invocation(receipt.installation_id):
            try:
                descriptor = inspect_installation(self.repository, receipt, self.supervisor, self.limits)
            except (OSError, ValueError):
                self._block(receipt, revoke_trust=True)
                raise
            if not descriptor.compatible:
                self._block(receipt, revoke_trust=False)
                raise ValueError(descriptor.reason)
            with self.repository.exclusive():
                state = self.repository.read()
                if selected_installation(state, plugin_id) != receipt:
                    raise ValueError("Selected installation changed")
                requested = state.requested[plugin_id]
                if requested.trusted_sha256 != receipt.artifact_sha256 and not acknowledge_trust:
                    raise ValueError("Explicit code trust acknowledgement is required")
                updated = RequestedState(receipt.installation_id, True, receipt.artifact_sha256, requested.generation)
                if updated != requested:
                    updated = replace(updated, generation=requested.generation + 1)
                state.requested[plugin_id] = updated
                changed = self.repository.save(state)
            self.supervisor.failure(receipt.installation_id, clear=True)
            return changed

    def analyze(self, plugin_id: str, context: PositionContext) -> MaterialFacts:
        """Invoke a current trusted installation and independently validate its facts.

        Args:
            plugin_id: Unique stable plugin identity.
            context: Bounded position; no database or UI handle is exposed.

        Returns:
            Core-validated factual material inventory for the same current request.

        Raises:
            ValueError: Admission or factual/context validation fails.
            PluginWorkerError: Bounded worker fails; retry requires explicit re-enable.
            PluginCancelledError: Work is disabled, removed, superseded, or cancelled.
        """
        validate_context(context)
        state = self.repository.read()
        receipt = selected_installation(state, plugin_id)
        requested = state.requested[plugin_id]
        if not request_is_current(state, receipt, requested):
            raise ValueError("Plugin is disabled, untrusted, or blocked")
        if self.supervisor.failure(receipt.installation_id):
            raise ValueError("Plugin failed for this session; explicitly re-enable before retry")

        def current() -> bool:
            try:
                return request_is_current(self.repository.read(), receipt, requested)
            except (OSError, ValueError):
                return False

        with self.repository.invocation(receipt.installation_id):
            try:
                descriptor = inspect_installation(self.repository, receipt, self.supervisor, self.limits)
                if not descriptor.compatible:
                    self._block(receipt, revoke_trust=False)
                    raise ValueError(descriptor.reason)
                if not current():
                    raise PluginCancelledError("discovery", "cancelled", "Plugin work cancelled before import")
                response = self.supervisor.call(receipt.installation_id,
                    {"operation": "analyze", "site": str(self.repository.location(receipt.installation_id)),
                     "profile": str(self.repository.root.parent), "plugin_id": plugin_id,
                     "installation_id": receipt.installation_id, "generation": requested.generation,
                     "context": asdict(context)}, self.limits, current)
                facts = material_result(context, response["result"])
                if not current():
                    raise PluginCancelledError("invoke", "stale_result", "Plugin result was superseded")
                return facts
            except PluginCancelledError:
                raise
            except PluginBusyError:
                raise
            except PluginWorkerError as error:
                self.supervisor.failure(receipt.installation_id, error)
                self.diagnostics.record(receipt, error.phase, error.kind, str(error))
                raise
            except (ValueError, KeyError, OSError) as error:
                failure = PluginWorkerError("invoke", "validation_failed", "Core rejected plugin identity or factual evidence")
                self.supervisor.failure(receipt.installation_id, failure)
                self.diagnostics.record(receipt, failure.phase, failure.kind, str(failure))
                try:
                    self.repository.verify(receipt)
                except (OSError, ValueError):
                    self._block(receipt, revoke_trust=True)
                raise error

    def remove(self, plugin_id: str, *, installation_id: str | None = None) -> bool:
        """Remove one owned installation after disabling and draining its work.

        Args:
            plugin_id: Stable plugin identity.
            installation_id: Explicit selection when duplicate IDs require resolution.

        Returns:
            Whether owned physical cleanup succeeded; failure remains visible/disabled.

        Raises:
            ValueError: Selection or containment is invalid.
            RuntimeError: Work cannot be stopped within the bounded deadline.
        """
        return self._installer().remove(plugin_id, installation_id=installation_id)

    def cleanup(self, installation_id: str) -> bool:
        """Explicitly retry a retired installation's owned cleanup, never a scan retry.

        Args:
            installation_id: Unpublished installation identity.

        Returns:
            Whether cleanup succeeded.
        """
        return self._installer().cleanup(installation_id)

    def close(self) -> None:
        """Cancel profile workers at application shutdown without changing user intent."""
        self.supervisor.close(self.limits.shutdown_timeout_seconds + self.limits.lock_timeout_seconds)
