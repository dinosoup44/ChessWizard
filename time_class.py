"""Provider-aware time classes shared by migrations and PGN importers.

Explicit labels take priority. Clock fallback uses base + 40 * increment,
with each provider's own rating boundaries (see docs/analysis_pipeline.md).
Unknown providers and unsupported multi-stage clocks stay unknown.
"""
import io
import re

import chess.pgn


TIME_CLASSES = ("bullet", "blitz", "rapid", "classical", "correspondence", "unknown")
ALIASES = {"daily": "correspondence", "ultrabullet": "bullet", "ultra-bullet": "bullet"}


def normalize_time_class(value):
    value = str(value or "").strip().lower()
    value = ALIASES.get(value, value)
    return value if value in TIME_CLASSES else "unknown"


def classify_time_control(source, time_control=None, headers=None, provider_class=None):
    headers = headers or {}
    for value in (provider_class, headers.get("TimeClass"), headers.get("time_class"),
                  headers.get("Speed")):
        label = normalize_time_class(value)
        if label != "unknown":
            return label

    # Match actual provider event labels, not arbitrary tournament names.
    event = str(headers.get("Event", "")).strip().lower()
    match = re.fullmatch(
        r"(?:rated|casual|unrated) (ultrabullet|bullet|blitz|rapid|classical|correspondence) game",
        event,
    )
    if match:
        return normalize_time_class(match[1])

    source = str(source or "").lower()
    if source not in {"lichess", "chesscom"}:
        return "unknown"
    clock = str(time_control if time_control is not None else headers.get("TimeControl", "")).strip()
    daily = re.fullmatch(r"1/(\d+)", clock)
    if daily and int(daily[1]) >= 86400:
        return "correspondence"
    match = re.fullmatch(r"(\d+)(?:\+(\d+))?", clock)
    if not match:
        return "unknown"
    seconds = int(match[1]) + 40 * int(match[2] or 0)
    if seconds <= 0:
        return "unknown"
    if source == "lichess":
        if seconds < 180:
            return "bullet"
        if seconds < 480:
            return "blitz"
        return "rapid" if seconds < 1500 else "classical"
    if seconds < 180:
        return "bullet"
    return "blitz" if seconds < 600 else "rapid"


def classify_stored_game(source, time_control, raw_pgn):
    # Read only headers; backfilling must not parse or rewrite stored moves.
    headers = chess.pgn.read_headers(io.StringIO(raw_pgn or "")) or {}
    return classify_time_control(source, time_control, headers)


def require_time_class_schema(connection):
    if "time_class" not in {row[1] for row in connection.execute("PRAGMA table_info(games)")}:
        raise RuntimeError("Run migrate_games_time_class.py before importing or filtering games.")
