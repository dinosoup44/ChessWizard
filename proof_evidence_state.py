"""Proof facts and escalation attempts have independent lifetimes.

Legacy status strings remain readable; a denied request is not new chess evidence.
"""
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal
import chess

ProofState = Literal["stable", "unsettled", "incomplete", "terminal", "deferred", "error"]
AttemptState = Literal["not_needed", "completed", "branch_limit_denied", "request_limit_denied", "child_depth_denied", "deferred", "error"]


def proof_state(state: str, fen: str | None = None) -> ProofState:
    if state in {"stable", "unsettled", "incomplete", "terminal", "deferred", "error"}:
        return state
    if state == "mate":
        return "terminal" if fen and chess.Board(fen).is_game_over() else "deferred"
    if state in {"draw", "terminal_after_reply"}:
        return "terminal"
    if state == "mate_baseline":
        return "deferred"
    return "incomplete"


def attempt_state(status: str, reason: str) -> AttemptState:
    if status == "budget_exhausted":
        return {"branch_limit": "branch_limit_denied", "verification_request_limit": "request_limit_denied",
                "child_depth_limit": "child_depth_denied"}[reason]
    if status in {"not_needed", "deferred", "error"}:
        return status
    return "completed"


def retained_branches(details):
    """Adapt historical overwritten states without mutating the stored payload.

    Only attempts with no replacement proof restore normal evidence. Successful
    rechecks retain their own proof even if it did not settle.
    """
    branches = deepcopy(details.get("branches", []))
    normal = details.get("normal_branches", branches)
    for attempt in details.get("escalation_attempts", []):
        index = attempt["branch_index"]
        if not attempt.get("proof") and attempt["status"] not in {"complete", "not_needed"}:
            branches[index] = deepcopy(normal[index])
        branches[index]["escalation_attempt_state"] = attempt_state(attempt["status"], attempt["reason"])
    return branches


@dataclass(frozen=True)
class TerminalFacts:
    terminal_state: str = "none"
    ownership: str = "not_applicable"
    complete: bool = False
    result: str | None = None


def terminal_facts(board: chess.Board, *, role: str = "endpoint") -> TerminalFacts:
    """Terminal completeness comes from board rules, without an engine continuation."""
    outcome = board.outcome()
    if outcome is None:
        return TerminalFacts()
    if board.is_checkmate():
        state = {"played": "played_checkmate", "candidate": "candidate_checkmate"}.get(role, "other_terminal")
        owner = "played_move_terminal" if role == "played" else "mate"
    else:
        state = "stalemate" if board.is_stalemate() else "draw_terminal"
        owner = "played_move_terminal" if role == "played" else "deferred"
    return TerminalFacts(state, owner, True, outcome.result())
