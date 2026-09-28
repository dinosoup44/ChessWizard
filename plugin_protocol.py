"""Bounded host transport and independent reconstruction of Plugin API V1 facts."""
from dataclasses import asdict
import json
from typing import Any
from chesswizard_plugin_api import MaterialCount, MaterialFacts, PositionContext, SquareFact
from plugin_result_validation import validate_material_facts

PROTOCOL_VERSION = 1
MAX_REQUEST_ID = 128
MAX_FEN = 256


def validate_context(context: PositionContext) -> None:
    """Reject oversized or invalid caller context before it reaches plugin code.

    Args:
        context: Immutable SDK position request.

    Raises:
        ValueError: Request identity or standard-chess position is invalid.
    """
    import chess
    if not isinstance(context, PositionContext) or not isinstance(context.request_id, str) or not 1 <= len(context.request_id) <= MAX_REQUEST_ID:
        raise ValueError("Invalid bounded request identity")
    if not isinstance(context.fen, str) or len(context.fen) > MAX_FEN or len(context.fen.split()) != 6 or not chess.Board(context.fen).is_valid():
        raise ValueError("Invalid bounded standard-chess position")


def material_result(context: PositionContext, data: dict[str, Any]) -> MaterialFacts:
    """Reconstruct and independently validate factual data from an untrusted response.

    Args:
        context: Exact original context retained by core.
        data: Bounded JSON result object.

    Returns:
        Core-verified immutable material facts.

    Raises:
        ValueError: Fields, counts, squares, or context identity are wrong.
    """
    try:
        if not isinstance(data, dict) or set(data) != {"request_id", "fen", "squares", "counts"}:
            raise ValueError("Unexpected result fields")
        if not isinstance(data["squares"], list) or len(data["squares"]) > 64 or not isinstance(data["counts"], list) or len(data["counts"]) != 12:
            raise ValueError("Unbounded/invalid fact inventory")
        facts = MaterialFacts(data["request_id"], data["fen"], tuple(SquareFact(**row) for row in data["squares"]),
                              tuple(MaterialCount(**row) for row in data["counts"]))
        validate_material_facts(context, facts)
        return facts
    except (TypeError, KeyError, AttributeError) as error:
        raise ValueError("Malformed material facts") from error


def encode_message(value: dict[str, Any], maximum: int) -> bytes:
    """Serialize one finite, bounded protocol message.

    Args:
        value: Plain data-only message.
        maximum: Allowed UTF-8 byte count.

    Returns:
        Encoded JSON bytes.

    Raises:
        ValueError: Message is nonfinite or oversized.
    """
    raw = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
    if len(raw) > maximum:
        raise ValueError("Plugin message exceeds limit")
    return raw
