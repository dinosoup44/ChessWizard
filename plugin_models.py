"""Typed host lifecycle values; separate from plugin SDK facts and analyzer truth."""
from dataclasses import dataclass, field
from enum import StrEnum


class CompatibilityCode(StrEnum):
    """Classify static admission without importing installed plugin code."""
    COMPATIBLE = "compatible"
    API = "unsupported_plugin_api"
    APP = "minimum_app_version_unmet"
    PYTHON = "python_version_mismatch"
    METADATA = "invalid_metadata"
    DEPENDENCY = "unsupported_dependency_contract"
    DUPLICATE = "duplicate_plugin_id"
    INTEGRITY = "installation_integrity_failure"
    RECEIPT = "receipt_identity_failure"


class RuntimeState(StrEnum):
    """Describe session availability independently of persisted user intent."""
    DISABLED = "disabled"
    BLOCKED = "blocked"
    READY = "ready"
    RUNNING = "running"
    FAILED = "failed"


class InstallPhase(StrEnum):
    """Record the durable boundary reached by an installation transaction."""
    STAGED = "staged"
    VALIDATED = "validated"
    PUBLISHED = "published"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PluginLimits:
    """Bound host work using the approved operational defaults.

    Args:
        timeout_seconds: Maximum analysis call time; also caps other phases.
        metadata_timeout_seconds: Maximum static discovery time.
        import_timeout_seconds: Maximum entry-point import/initialization time.
        shutdown_timeout_seconds: Maximum close or cancellation grace.
        max_message_bytes: Maximum transport payload, including phase frames.
        max_diagnostic_bytes: Maximum captured worker stderr.
        max_workers: Maximum concurrent helpers/workers per profile.
        max_wheel_bytes: Maximum compressed wheel size.
        max_expanded_bytes: Maximum expanded installation payload.
        max_files: Maximum files in one installation.
        max_installations: Maximum published and retired receipts.
        max_state_bytes: Maximum persisted state file.
        max_diagnostics: Maximum retained diagnostic records.
        max_diagnostic_message: Maximum safe diagnostic message characters.
        poll_seconds: Cancellation/phase observation interval.
        lock_timeout_seconds: Bound waiting for a short repository transaction.
    """
    timeout_seconds: float = 10.0
    metadata_timeout_seconds: float = 3.0
    import_timeout_seconds: float = 5.0
    shutdown_timeout_seconds: float = 1.0
    max_message_bytes: int = 1048576
    max_diagnostic_bytes: int = 65536
    max_workers: int = 2
    max_wheel_bytes: int = 4194304
    max_expanded_bytes: int = 8388608
    max_files: int = 128
    max_installations: int = 64
    max_state_bytes: int = 4194304
    max_diagnostics: int = 100
    max_diagnostic_message: int = 512
    poll_seconds: float = 0.025
    lock_timeout_seconds: float = 1.0

    def __post_init__(self) -> None:
        """Reject nonfinite or unbounded operational settings."""
        import math
        for name in ("timeout_seconds", "metadata_timeout_seconds", "import_timeout_seconds",
                     "shutdown_timeout_seconds", "poll_seconds", "lock_timeout_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 120:
                raise ValueError("Invalid plugin time limit: " + name)
        if type(self.max_workers) is not int or not 1 <= self.max_workers <= 4:
            raise ValueError("Plugin worker count must be between one and four")
        for name in ("max_message_bytes", "max_diagnostic_bytes", "max_wheel_bytes", "max_expanded_bytes",
                     "max_files", "max_installations", "max_state_bytes", "max_diagnostics", "max_diagnostic_message"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 16777216:
                raise ValueError("Invalid plugin size limit: " + name)


@dataclass(frozen=True, slots=True)
class HostVersions:
    """Keep application, SDK API, and Python compatibility independently versioned.

    Args:
        application: PEP 440 application version.
        api: Public SDK version.
        python: Interpreter version used by the worker.
    """
    application: str
    api: str
    python: str


@dataclass(frozen=True, slots=True)
class PluginDescriptor:
    """Describe one statically inspected distribution and its compatibility.

    Args:
        plugin_id: Stable entry-point identity.
        name: Display name.
        version: Distribution version.
        author: Declared author.
        license: Declared license.
        entry_point: Selected regular-package factory.
        minimum_app_version: Required application minimum.
        api_version: Required SDK minimum.
        compatible: Whether static admission succeeds.
        reason: Safe explanation of the first blocking condition.
        distribution_name: Normalized distribution identity.
        python_requirement: Declared Python specifier.
        manifest_sha256: Identity of the static manifest bytes.
        compatibility_code: Machine-readable static decision.
        plugin_type: Supported contract category.
        capabilities: Supported factual capabilities.
    """
    plugin_id: str
    name: str
    version: str
    author: str
    license: str
    entry_point: str
    minimum_app_version: str
    api_version: str
    compatible: bool
    reason: str
    distribution_name: str = ""
    python_requirement: str = ""
    manifest_sha256: str = ""
    compatibility_code: CompatibilityCode = CompatibilityCode.COMPATIBLE
    plugin_type: str = "position_facts"
    capabilities: tuple[str, ...] = ("material_inventory",)


@dataclass(frozen=True, slots=True)
class InstalledPlugin:
    """Retain immutable installation provenance and exact owned file identity.

    Args:
        installation_id: Core-generated UUID hex.
        plugin_id: Stable plugin identity.
        distribution_name: Distribution metadata name.
        version: Distribution version.
        artifact_sha256: Exact retained wheel identity, not publisher authenticity.
        managed_path: Canonical path relative to the plugin root.
        installed_at: UTC installation timestamp.
        source_description: Bounded local provenance description.
        manifest_sha256: Static manifest byte identity.
        api_version: Required public API minimum.
        minimum_app_version: Required application minimum.
        plugin_type: Contract category.
        capabilities: Declared capabilities.
        inventory: Site-relative file SHA256 values.
    """
    installation_id: str
    plugin_id: str
    distribution_name: str
    version: str
    artifact_sha256: str
    managed_path: str
    installed_at: str
    source_description: str
    manifest_sha256: str
    api_version: str
    minimum_app_version: str
    plugin_type: str
    capabilities: tuple[str, ...]
    inventory: dict[str, str]


@dataclass(frozen=True, slots=True)
class RequestedState:
    """Persist user intent and artifact-specific trust separately from availability.

    Args:
        installation_id: Explicitly selected installation.
        enabled: Requested enablement.
        trusted_sha256: Acknowledged artifact, or an empty untrusted identity.
        generation: Monotonic revision invalidating in-flight results.
        requires_reenable: Compatibility/conflict changes require an explicit decision.
    """
    installation_id: str
    enabled: bool = False
    trusted_sha256: str = ""
    generation: int = 0
    requires_reenable: bool = False


@dataclass(frozen=True, slots=True)
class InstallTransaction:
    """Make interrupted staging distinguishable from published installations.

    Args:
        installation_id: Staged installation UUID.
        phase: Last durable transaction boundary.
        previous_id: Selected installation being replaced, when applicable.
        stop_requested: Whether old work must stop before a state switch.
        message: Bounded core-authored recovery explanation.
    """
    installation_id: str
    phase: InstallPhase
    previous_id: str = ""
    stop_requested: bool = False
    message: str = ""


@dataclass(slots=True)
class PluginState:
    """Own typed plugin-only state without a connection to chess storage.

    Args:
        installations: Published receipts by installation UUID.
        requested: User intent by stable plugin ID.
        transactions: Durable staging/replacement records.
        retired: Unpublished owned receipts awaiting explicit/successful cleanup.
        cleanup_failures: Bounded cleanup errors by installation UUID.
        schema_version: Persistent host-state contract, independent of SDK API V1.
    """
    installations: dict[str, InstalledPlugin] = field(default_factory=dict)
    requested: dict[str, RequestedState] = field(default_factory=dict)
    transactions: dict[str, InstallTransaction] = field(default_factory=dict)
    retired: dict[str, InstalledPlugin] = field(default_factory=dict)
    cleanup_failures: dict[str, str] = field(default_factory=dict)
    schema_version: int = 2


@dataclass(frozen=True, slots=True)
class PluginView:
    """Expose one installation's intent, compatibility, and session state.

    Args:
        installed: Immutable installation receipt.
        requested: Persisted requested state for the plugin ID.
        descriptor: Metadata when valid.
        compatibility: Static blocking category.
        runtime_state: Effective session availability.
        reason: Bounded core-authored explanation.
    """
    installed: InstalledPlugin
    requested: RequestedState
    descriptor: PluginDescriptor | None
    compatibility: CompatibilityCode
    runtime_state: RuntimeState
    reason: str = ""


@dataclass(frozen=True, slots=True)
class DiscoverySnapshot:
    """Return startup-safe discovery and recovery findings without raising for bad plugins.

    Args:
        plugins: Deterministically ordered installation views.
        diagnostics: Bounded core-authored startup/recovery explanations.
    """
    plugins: tuple[PluginView, ...] = ()
    diagnostics: tuple[str, ...] = ()
