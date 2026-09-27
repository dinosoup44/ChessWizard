"""Strict read-only cache access. This service has no engine/fallback interface."""
from dataclasses import dataclass
from typing import Any
import sqlite3
from collections import Counter
import chess
import engine_cache
from analysis_scout import SCOUT_ENGINE_OPTIONS

# Existing cache rows do not encode engine options separately. Only the
# established immutable profile/options contract is usable without migration.
# A configuration change cannot silently reuse that evidence in this preflight.
ESTABLISHED_OPTIONS = {"Threads":1, "Hash":64}


@dataclass(frozen=True)
class ExistingEvidence:
    available: bool
    reason: str
    key: dict
    record: dict | None = None


class ExistingPositionEvidence:
    """Read compatible existing engine rows without fallback searches.

    Args:
        connection: Caller-owned connection to the shared position cache.
    """
    def __init__(self, connection: sqlite3.Connection) -> None:
        """Bind a read-only evidence capability.

        Args:
            connection: Caller-owned position-cache connection.
        """
        self._connection = connection
        self.stats = Counter()

    def identity(self, profile: str) -> dict[str, Any]:
        """Return the established exact raw request identity.

        Args:
            profile: Shared engine profile name.

        Returns:
            Engine/version, budget and options used by existing evidence.

        Raises:
            ValueError: The profile is unknown.
        """
        return position_evidence_identity(profile)

    def position(self, fen, profile):
        identity = self.identity(profile)
        key = {"fen":fen, **identity}
        if SCOUT_ENGINE_OPTIONS != ESTABLISHED_OPTIONS:
            self.stats["incompatible"] += 1
            return ExistingEvidence(False, "unverifiable_engine_configuration", key)
        raw = engine_cache.get_cached_position(self._connection, fen, profile)
        if raw is None:
            self.stats["missing"] += 1
            return ExistingEvidence(False, "missing_current_cache_key", key)
        expected = {k:v for k,v in key.items() if k != "engine_options"}
        valid = all(raw.get(k) == v for k,v in expected.items())
        valid = valid and raw.get("score_pov") == "white" and type(raw.get("cache_id")) is int
        field = {"cp":"score_cp", "mate":"mate"}.get(raw.get("score_type"))
        valid = valid and field is not None and type(raw.get(field)) is int
        valid = valid and raw.get("side_to_move") == ("white" if chess.Board(fen).turn else "black")
        if not valid:
            self.stats["incompatible"] += 1
            return ExistingEvidence(False, "incompatible_or_invalid_cache_record", key)
        self.stats["hits"] += 1
        return ExistingEvidence(True, "current_cache_hit", key, raw)


def position_evidence_identity(profile: str) -> dict[str, Any]:
    """Describe the established raw request without opening a database or engine.

    Args:
        profile: Shared engine profile name.

    Returns:
        Exact engine/version, profile budget and established options.

    Raises:
        ValueError: The profile is unknown.
    """
    return {"engine_name":engine_cache.ENGINE_NAME, "engine_version":engine_cache.ENGINE_VERSION,
            "analysis_profile":profile, **engine_cache.get_profile(profile),
            "engine_options":dict(SCOUT_ENGINE_OPTIONS)}
