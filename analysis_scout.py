"""Cheap engine hypotheses. A scout miss is not proof that no tactic exists.

No candidates or coverage are written here. Engine evidence uses the shared
White-POV cache. Both analyzers reuse the same before-position search.
"""
from collections import Counter
from dataclasses import dataclass
import json

import chess

from engine_cache import ENGINE_NAME, ENGINE_VERSION, get_profile, get_or_analyze, score_for_color


SCOUT_PROFILE = "tactic_scout_v1"
SCOUT_VERSION = "1"
MATE_LIMIT = 3
FORK_MIN_LOSS_CP = 80  # Deliberately looser than Fork V2's 120 cp quick threshold.
SCOUT_ENGINE_OPTIONS = {"Threads": 1, "Hash": 64}


def scout_config(**thresholds):
    """Canonical, inspectable identity of evidence and decision configuration.

    Logic changes still require a scout_version bump. Configuration changes
    invalidate negative coverage even if someone forgets that version bump.
    """
    return json.dumps({
        "engine_name": ENGINE_NAME,
        "engine_version": ENGINE_VERSION,
        "profile_name": SCOUT_PROFILE,
        "profile": get_profile(SCOUT_PROFILE),
        "engine_options": SCOUT_ENGINE_OPTIONS,
        "thresholds": thresholds,
    }, sort_keys=True, separators=(",", ":"))


def fork_scout_config():
    return scout_config(min_loss_cp=FORK_MIN_LOSS_CP)


def mate_scout_config():
    return scout_config(mate_limit=MATE_LIMIT)


@dataclass(frozen=True)
class ScoutResult:
    send_to_heavy: bool
    reason: str


def validate_stored_move(row):
    """Invalid imported data must never become completed negative coverage."""
    if row["color"] not in {"white", "black"}:
        raise ValueError("Unknown player color")
    board = chess.Board(row["fen_before"])
    if not board.is_valid() or board.turn != (row["color"] == "white"):
        raise ValueError("Invalid position or player turn")
    move = chess.Move.from_uci(row["uci_played"])
    if move not in board.legal_moves:
        raise ValueError("Stored played move is illegal")
    board.push(move)
    if board.fen() != row["fen_after"]:
        raise ValueError("Stored before/after positions disagree")


class ScoutEvidence:
    def __init__(self, connection, engine):
        self.connection = connection
        self.engine = engine
        self.positions = {}
        self.stats = Counter()

    def position(self, fen):
        if fen in self.positions:
            self.stats["memory_hits"] += 1
            return self.positions[fen]
        result = get_or_analyze(self.connection, self.engine, fen, SCOUT_PROFILE)
        if result["score_pov"] != "white":
            raise ValueError("Scout requires White-POV cache evidence.")
        self.positions[fen] = result
        self.stats["database_hits" if result["cache_hit"] else "engine_searches"] += 1
        return result

    def for_player(self, row, after=False):
        if row["color"] not in {"white", "black"}:
            raise ValueError("Unknown player color")
        color = row["color"] == "white"
        if not after:
            validate_stored_move(row)
        result = score_for_color(self.position(row["fen_after" if after else "fen_before"]), color)
        field = "mate" if result["score_type"] == "mate" else "score_cp"
        if result[field] is None:
            raise ValueError("Engine returned no usable score")
        return result


def scout_mate(row, evidence):
    before = evidence.for_player(row)
    # python-chess/UCI mate distance is in moves, not a raw ply count.
    found = before["score_type"] == "mate" and 0 < before["mate"] <= MATE_LIMIT
    return ScoutResult(found, "mate_within_limit" if found else "no_shallow_mate")


def scout_fork(row, evidence):
    before = evidence.for_player(row)
    actual = evidence.for_player(row, after=True)
    # Keep ambiguous mate scores for the specialist: shallow mate findings
    # must not discard a saving/equalizing fork or assign motif ownership.
    if before["score_type"] == "mate" or actual["score_type"] == "mate":
        return ScoutResult(True, "mate_score_needs_specialist")
    loss = before["score_cp"] - actual["score_cp"]
    found = loss >= FORK_MIN_LOSS_CP
    return ScoutResult(found, "possible_missed_gain" if found else "small_shallow_loss")
