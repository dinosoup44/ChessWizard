"""Explicit repertoire ownership stored in existing book metadata, without inference."""
from enum import StrEnum
import json


class RepertoireSide(StrEnum):
    """Identify an authored repertoire's intended side, or an explicit reference book."""
    WHITE = 'white'
    BLACK = 'black'
    BOTH = 'both'


def read_repertoire_side(metadata_json: str) -> RepertoireSide | None:
    """Read explicit side metadata without treating a legacy book as Both.

    Args:
        metadata_json: Existing book-level JSON object.

    Returns:
        The declared side, or None when the legacy metadata has no side key.

    Raises:
        ValueError: JSON is malformed or a declared side is unsupported.
    """
    metadata = json.loads(metadata_json)
    if not isinstance(metadata, dict):
        raise ValueError('Book metadata must be a JSON object.')
    if 'repertoire_side' not in metadata:
        return None
    return RepertoireSide(metadata['repertoire_side'])


def with_repertoire_side(metadata_json: str, side: RepertoireSide | str) -> str:
    """Return metadata with an explicit side, retaining unrelated author fields.

    Args:
        metadata_json: Existing book metadata; no file is opened.
        side: White, Black or Both/Reference, using the canonical enum values.

    Returns:
        Canonical JSON ready for the normal ID-preserving book update path.

    Raises:
        ValueError: Metadata or the requested side is invalid.
    """
    metadata = json.loads(metadata_json)
    if not isinstance(metadata, dict):
        raise ValueError('Book metadata must be a JSON object.')
    metadata['repertoire_side'] = RepertoireSide(side).value
    return json.dumps(metadata, sort_keys=True, separators=(',', ':'), allow_nan=False)
