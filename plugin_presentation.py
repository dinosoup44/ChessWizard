"""Frontend-independent plugin status, trust, and validated-fact presentation."""
from dataclasses import dataclass
import unicodedata
from chesswizard_plugin_api import MaterialFacts
from plugin_diagnostics import PluginDiagnostic
from plugin_models import CompatibilityCode, PluginView, RuntimeState

TRUST_DISCLOSURE = ("Plugins are executable Python code and run with your user permissions. "
                    "They are not sandboxed.")
MAX_DISPLAY_TEXT = 512
MAX_VISIBLE_DIAGNOSTICS = 8


def display_text(value: str) -> str:
    """Bound metadata for plain-text controls and remove invisible control characters.

    Args:
        value: Declared metadata or core-authored explanation.

    Returns:
        Readable bounded text without control or bidirectional override characters.
    """
    return "".join(c if not unicodedata.category(c).startswith("C") else " "
                   for c in value[:MAX_DISPLAY_TEXT])


@dataclass(frozen=True, slots=True)
class PluginRow:
    """Project a typed installation into labels without changing lifecycle truth.

    Args:
        view: Original rich service state used for actions.
        values: Name, version, author, capability, intent, status, compatibility, trust.
        details: Bounded sanitized details including artifact provenance.
        trust_details: Metadata displayed before acknowledging executable code.
        can_enable: Whether an explicit enable action can be offered.
        needs_approval: Whether this artifact has not been acknowledged.
        can_run: Whether the service considers this installation ready.
    """
    view: PluginView
    values: tuple[str, ...]
    details: str
    trust_details: str
    can_enable: bool
    needs_approval: bool
    can_run: bool


def present_plugin(view: PluginView, diagnostics: tuple[PluginDiagnostic, ...] = ()) -> PluginRow:
    """Translate existing service decisions into consistent frontend labels.

    Args:
        view: Service-owned compatibility, requested state, and runtime state.
        diagnostics: Already sanitized diagnostic records for the same artifact.

    Returns:
        One read-only presentation, retaining its full typed source view.
    """
    receipt, requested, descriptor = view.installed, view.requested, view.descriptor
    name = display_text(descriptor.name if descriptor else receipt.distribution_name)
    author = display_text(descriptor.author if descriptor else "Unavailable")
    license_name = display_text(descriptor.license if descriptor else "Unavailable")
    compatible = view.compatibility == CompatibilityCode.COMPATIBLE
    approval = requested.trusted_sha256 != receipt.artifact_sha256
    status = "Disabled"
    if view.compatibility == CompatibilityCode.DUPLICATE:
        status = "Conflict"
    elif view.compatibility in (CompatibilityCode.METADATA, CompatibilityCode.INTEGRITY, CompatibilityCode.RECEIPT):
        status = "Failed"
    elif not compatible:
        status = "Incompatible"
    elif view.runtime_state == RuntimeState.FAILED:
        status = "Failed"
    elif view.runtime_state == RuntimeState.RUNNING:
        status = "Running"
    elif approval:
        status = "Needs approval"
    elif view.runtime_state == RuntimeState.READY:
        status = "Ready"
    capability = display_text(receipt.plugin_type + " / " + ", ".join(receipt.capabilities))
    trust = "Needs approval" if approval else "Acknowledged"
    intent = "Enabled" if requested.enabled else "Disabled"
    compatibility = "Compatible" if compatible else status
    trust_details = (f"Name: {name}\nVersion: {display_text(receipt.version)}\nAuthor: {author}\n"
        f"License: {license_name}\nSource: {display_text(receipt.source_description)}\n"
        f"Artifact SHA256: {receipt.artifact_sha256}\nCapabilities: {capability}")
    lines = [trust_details, f"Plugin ID: {display_text(receipt.plugin_id)}",
             f"Installation: {receipt.installation_id}", f"Requested: {intent} | Status: {status} | Trust: {trust}",
             f"Compatibility: {view.compatibility.value}", display_text(view.reason)]
    if requested.requires_reenable:
        lines.append("Explicit re-enable is required after a state or compatibility change.")
    for record in diagnostics[-MAX_VISIBLE_DIAGNOSTICS:]:
        lines.append(f"{record.timestamp} | {record.phase}: {record.message}")
    return PluginRow(view, (name, display_text(receipt.version), author, capability, intent, status,
                     compatibility, trust), "\n".join(lines), trust_details,
                     compatible and descriptor is not None and view.runtime_state != RuntimeState.RUNNING,
                     approval, view.runtime_state == RuntimeState.READY)


def present_material(facts: MaterialFacts) -> str:
    """Format only material facts that have already passed core validation.

    Args:
        facts: Validated response from PluginService.analyze.

    Returns:
        Bounded factual inventory without tactical conclusions or persistence.
    """
    lines = ["Material Inventory"]
    for color in ("white", "black"):
        counts = [f"{item.piece}: {item.count}" for item in facts.counts if item.color == color]
        lines.append(color.title() + ": " + ", ".join(counts))
    lines.append("Occupied squares: " + ", ".join(
        f"{item.square} {item.color} {item.piece}" for item in facts.squares))
    return "\n".join(lines)
