"""Shared fail-closed receipt selection and in-flight generation checks."""
from plugin_models import InstalledPlugin, PluginDescriptor, PluginState, RequestedState


def selected_installation(state: PluginState, plugin_id: str) -> InstalledPlugin:
    """Select only a unique explicitly indexed installation.

    Args:
        state: Validated plugin state.
        plugin_id: Stable plugin identity.

    Returns:
        Unique selected receipt.

    Raises:
        ValueError: Identity is absent or colliding; no filesystem-order winner exists.
    """
    matches = [receipt for receipt in state.installations.values() if receipt.plugin_id == plugin_id]
    if len(matches) != 1:
        raise ValueError("Duplicate or missing plugin ID; explicit resolution required")
    return matches[0]


def request_is_current(state: PluginState, receipt: InstalledPlugin, requested: RequestedState) -> bool:
    """Require the same enabled, trusted, unique generation before delivering work.

    Args:
        state: Current validated state.
        receipt: Invocation receipt.
        requested: Invocation generation and trust.

    Returns:
        Whether admission remains valid and no replacement is stopping this worker.
    """
    try:
        return (selected_installation(state, receipt.plugin_id) == receipt
                and state.requested.get(receipt.plugin_id) == requested
                and requested.installation_id == receipt.installation_id
                and requested.enabled and not requested.requires_reenable
                and requested.trusted_sha256 == receipt.artifact_sha256
                and not any(tx.stop_requested and tx.previous_id == receipt.installation_id
                            for tx in state.transactions.values()))
    except ValueError:
        return False


def descriptor_matches(receipt: InstalledPlugin, descriptor: PluginDescriptor) -> bool:
    """Compare all receipt-owned metadata with freshly inspected static metadata.

    Args:
        receipt: Immutable installed identity.
        descriptor: Metadata-only discovery result.

    Returns:
        Whether the claimed distribution and static contract match the receipt.
    """
    fields = ("plugin_id", "distribution_name", "version", "manifest_sha256", "api_version",
              "minimum_app_version", "plugin_type", "capabilities")
    return all(getattr(receipt, field) == getattr(descriptor, field) for field in fields)
