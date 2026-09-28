"""Strict data-only encoding for durable plugin state and receipts."""
from dataclasses import asdict
import json
import re
from typing import Any
from plugin_models import InstalledPlugin, InstallPhase, InstallTransaction, PluginLimits, PluginState, RequestedState


class PluginStateError(ValueError):
    """Report malformed state without authorizing an automatic reset."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise PluginStateError("Duplicate JSON key")
        result[key] = value
    return result


def decode_json(payload: bytes) -> Any:
    """Parse data without allowing duplicate keys or nonfinite numbers.

    Args:
        payload: Already size-bounded UTF-8 JSON.

    Returns:
        Parsed JSON values.

    Raises:
        PluginStateError: JSON is malformed or ambiguous.
    """
    try:
        return json.loads(payload, object_pairs_hook=_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(PluginStateError("Nonfinite JSON")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise PluginStateError("Invalid plugin JSON data") from error


def _text(value: Any, maximum: int = 256) -> str:
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise PluginStateError("Invalid bounded receipt text")
    return value


def valid_id(value: str) -> str:
    """Validate a core-generated installation UUID hex.

    Args:
        value: Candidate installation identity.

    Returns:
        The validated identity.

    Raises:
        PluginStateError: Identity is not a UUID hex value.
    """
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise PluginStateError("Invalid installation identity")
    return value


def _sha(value: Any, *, empty: bool = False) -> str:
    if empty and value == "":
        return ""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise PluginStateError("Invalid SHA256 identity")
    return value


def receipt_from_data(data: dict[str, Any], limits: PluginLimits) -> InstalledPlugin:
    """Validate an immutable installation receipt without trusting filesystem paths.

    Args:
        data: Decoded receipt object.
        limits: Host inventory bounds.

    Returns:
        Typed installation provenance.

    Raises:
        PluginStateError: Fields, identities, or inventory are invalid.
    """
    try:
        data = dict(data)
        data["capabilities"] = tuple(data["capabilities"])
        receipt = InstalledPlugin(**data)
        valid_id(receipt.installation_id)
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{2,100}", receipt.plugin_id):
            raise PluginStateError("Invalid plugin identity")
        if receipt.managed_path != f"installations/{receipt.installation_id}/site-packages":
            raise PluginStateError("Receipt path does not match installation identity")
        for name in ("distribution_name", "version", "installed_at", "source_description", "api_version", "minimum_app_version"):
            if not _text(getattr(receipt, name)):
                raise PluginStateError("Missing receipt metadata")
        _sha(receipt.artifact_sha256); _sha(receipt.manifest_sha256)
        if receipt.plugin_type != "position_facts" or receipt.capabilities != ("material_inventory",):
            raise PluginStateError("Unsupported receipt contract")
        if not isinstance(receipt.inventory, dict) or not 1 <= len(receipt.inventory) <= limits.max_files + 8:
            raise PluginStateError("Invalid receipt inventory")
        for name, digest in receipt.inventory.items():
            _text(name, 512); _sha(digest)
            if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name or ".." in name.split("/"):
                raise PluginStateError("Unsafe receipt inventory path")
        return receipt
    except (TypeError, KeyError, AttributeError, ValueError) as error:
        raise PluginStateError("Invalid installation receipt") from error


def state_from_data(data: dict[str, Any], limits: PluginLimits) -> PluginState:
    """Decode the host state contract and reject dangling or ambiguous ownership.

    Args:
        data: Bounded JSON object.
        limits: Maximum record counts.

    Returns:
        Validated state; colliding plugin IDs remain representable for safe diagnosis.

    Raises:
        PluginStateError: State is corrupt, unsupported, or exceeds bounds.
    """
    try:
        expected = {"schema_version", "installations", "requested", "transactions", "retired", "cleanup_failures"}
        if not isinstance(data, dict) or set(data) != expected or data["schema_version"] != 2:
            raise PluginStateError("Unsupported plugin state; explicit recovery is required")
        if any(not isinstance(data[key], dict) or len(data[key]) > limits.max_installations for key in expected - {"schema_version"}):
            raise PluginStateError("Plugin state exceeds record bounds")
        installations = {valid_id(key): receipt_from_data(value, limits) for key, value in data["installations"].items()}
        retired = {valid_id(key): receipt_from_data(value, limits) for key, value in data["retired"].items()}
        if set(installations) & set(retired):
            raise PluginStateError("Installation cannot be both published and retired")
        for key, receipt in {**installations, **retired}.items():
            if key != receipt.installation_id:
                raise PluginStateError("Receipt key mismatch")
        requested = {}
        for plugin_id, value in data["requested"].items():
            request = RequestedState(**value)
            receipt = installations[valid_id(request.installation_id)] if request.installation_id else None
            if receipt is None and (request.enabled or request.trusted_sha256):
                raise PluginStateError("Unselected state cannot be enabled/trusted")
            if receipt is not None and receipt.plugin_id != plugin_id or any(type(getattr(request, flag)) is not bool for flag in ("enabled", "requires_reenable")):
                raise PluginStateError("Requested identity or flags are invalid")
            if type(request.generation) is not int or not 0 <= request.generation < 2**63:
                raise PluginStateError("Invalid state generation")
            _sha(request.trusted_sha256, empty=True)
            if request.trusted_sha256 and (receipt is None or request.trusted_sha256 != receipt.artifact_sha256):
                raise PluginStateError("Trust is not bound to the selected artifact")
            requested[plugin_id] = request
        if {r.plugin_id for r in installations.values()} != set(requested):
            raise PluginStateError("Missing requested state")
        transactions = {}
        for key, value in data["transactions"].items():
            value = dict(value); value["phase"] = InstallPhase(value["phase"])
            transaction = InstallTransaction(**value)
            if valid_id(key) != valid_id(transaction.installation_id):
                raise PluginStateError("Transaction identity mismatch")
            if transaction.previous_id:
                valid_id(transaction.previous_id)
            if type(transaction.stop_requested) is not bool:
                raise PluginStateError("Invalid transaction stop flag")
            _text(transaction.message)
            transactions[key] = transaction
        failures = {valid_id(key): _text(value) for key, value in data["cleanup_failures"].items()}
        return PluginState(installations, requested, transactions, retired, failures)
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise PluginStateError("Invalid or unsupported plugin state; preserved for review") from error


def state_payload(state: PluginState, limits: PluginLimits) -> bytes:
    """Encode a validated deterministic state without timestamp changes.

    Args:
        state: Typed plugin-only state.
        limits: State size/count bounds.

    Returns:
        Canonical UTF-8 JSON bytes.

    Raises:
        PluginStateError: State violates the storage contract.
    """
    data = asdict(state)
    state_from_data(data, limits)
    payload = (json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if len(payload) > limits.max_state_bytes:
        raise PluginStateError("Plugin state exceeds byte limit")
    return payload
