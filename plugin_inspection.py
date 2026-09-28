"""Bounded metadata inspection shared by lifecycle and runtime admission."""
from dataclasses import asdict
from pathlib import Path
from plugin_admission import descriptor_matches
from plugin_models import CompatibilityCode, InstalledPlugin, PluginDescriptor, PluginLimits
from plugin_repository import PluginRepository
from plugin_runtime import WorkerSupervisor


def inspect_site(site: Path, installation_id: str, supervisor: WorkerSupervisor, limits: PluginLimits) -> PluginDescriptor:
    """Inspect one contained site using an import-free bounded helper process.

    Args:
        site: Staged or owned site-packages directory.
        installation_id: Opaque identity for cancellation.
        supervisor: Shared profile worker controller.
        limits: Finite runtime limits.

    Returns:
        Typed static descriptor.

    Raises:
        RuntimeError: Metadata helper fails or times out.
        ValueError: Descriptor shape is invalid.
    """
    data = supervisor.call(installation_id, {"operation": "discover", "site": str(site)}, limits)["descriptor"]
    data["capabilities"] = tuple(data["capabilities"])
    data["compatibility_code"] = CompatibilityCode(data["compatibility_code"])
    return PluginDescriptor(**data)


def inspect_installation(repository: PluginRepository, receipt: InstalledPlugin,
                         supervisor: WorkerSupervisor, limits: PluginLimits) -> PluginDescriptor:
    """Verify immutable ownership and static metadata before any implementation import.

    Args:
        repository: Managed plugin repository.
        receipt: Published installation identity.
        supervisor: Profile worker controller.
        limits: Inspection limits.

    Returns:
        Verified static descriptor.

    Raises:
        ValueError: Artifact, installed files, or metadata identity changed.
        RuntimeError: Bounded discovery fails.
    """
    descriptor = inspect_site(repository.verify(receipt), receipt.installation_id, supervisor, limits)
    if not descriptor_matches(receipt, descriptor):
        raise ValueError("Installation receipt metadata changed")
    return descriptor
