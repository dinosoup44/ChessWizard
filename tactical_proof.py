"""Bounded best-line verification shared by tactical specialists.

No selection, database, engine lifecycle, or motif policy. The caller supplies
position evaluation and material values; board inputs are never modified.
"""
from dataclasses import dataclass
import chess
from board_analysis import capture_square, material_balance
from proof_evidence_state import proof_state


@dataclass(frozen=True)
class ProofWindow:
    version: str = "bounded_best_line_v1"
    user_moves: int = 4
    settlement_plies: int = 4
    quiet_plies: int = 2

    def __post_init__(self):
        if not 1 <= self.user_moves <= 4 or not 0 <= self.settlement_plies <= 16 or self.quiet_plies != 2:
            raise ValueError("Unsupported bounded proof window")


@dataclass(frozen=True)
class ProofStep:
    before_fen: str
    after_fen: str
    uci: str
    san: str
    actor: bool
    captured_square: int | None
    captured_piece: int | None
    material_cp: int
    user_move_number: int
    in_payoff_window: bool


@dataclass(frozen=True)
class BoundedProof:
    state: str
    steps: tuple[ProofStep, ...]
    final_fen: str
    final_evidence: dict
    window: ProofWindow

    @property
    def evidence_state(self):
        """Canonical fact state while preserving historical serialized solver states."""
        return proof_state(self.state, self.final_fen)


def validate_evaluation(raw):
    if raw.get("score_pov") != "white":
        raise ValueError("Tactical proof requires White-POV evidence")
    field = {"cp": "score_cp", "mate": "mate"}.get(raw.get("score_type"))
    if field is None or type(raw.get(field)) is not int:
        raise ValueError("Missing or invalid tactical evaluation")
    return raw


def _quiet_lookahead(board, pv, count):
    copy = board.copy(stack=False)
    tokens = (pv or "").split()
    if len(tokens) < count:
        return False
    for token in tokens[:count]:
        move = copy.parse_san(token)
        if copy.is_check() or copy.is_capture(move) or move.promotion or copy.gives_check(move):
            return False
        copy.push(move)
    return not copy.is_check()


def play_proof_move(board, move, color, piece_values, *, ply, user_moves, payoff_plies):
    """Advance the caller-owned board and record consistent capture/material evidence."""
    san, before, actor = board.san(move), board.fen(), board.turn
    square = capture_square(board, move)
    captured = board.piece_at(square) if square is not None else None
    forcing = bool(board.is_check() or board.is_capture(move) or move.promotion or board.gives_check(move))
    board.push(move)
    step = ProofStep(before, board.fen(), move.uci(), san, actor, square,
                     captured.piece_type if captured else None,
                     material_balance(board, color, piece_values), user_moves + int(actor == color),
                     ply < payoff_plies)
    return step, forcing


def verify_bounded_line(after_tactic, color, evaluate, piece_values, window=ProofWindow()):
    """Re-evaluate each ply; follow the selected depth/profile best reply.

Always inspect the full payoff window and following defense, then the configured
extra plies for settlement (four by default). Stable means two quiet actual plies, no check, and
two quiet best-PV lookahead plies at the freshly evaluated endpoint. This is
bounded best-line evidence, not exhaustive search or a mathematical proof.
"""
    board = after_tactic.copy(stack=False)
    if board.turn == color:
        raise ValueError("Proof must begin after the user's tactical move")
    payoff_plies = 2 * window.user_moves + 1
    steps, quiet, user_moves = [], 0, 0
    raw = {}
    for ply in range(payoff_plies + window.settlement_plies + 1):
        if board.is_game_over():
            return BoundedProof("mate" if board.is_checkmate() else "draw", tuple(steps), board.fen(), raw, window)
        raw = validate_evaluation(evaluate(board.fen()))
        if raw["score_type"] == "mate":
            return BoundedProof("mate", tuple(steps), board.fen(), raw, window)
        if (ply >= payoff_plies and quiet >= window.quiet_plies and not board.is_check()
                and _quiet_lookahead(board, raw.get("principal_variation"), window.quiet_plies)):
            return BoundedProof("stable", tuple(steps), board.fen(), raw, window)
        if ply == payoff_plies + window.settlement_plies:
            break
        tokens = (raw.get("principal_variation") or "").split()
        if not tokens:
            return BoundedProof("missing_continuation", tuple(steps), board.fen(), raw, window)
        move = board.parse_san(tokens[0])
        step, forcing = play_proof_move(board, move, color, piece_values,
            ply=ply, user_moves=user_moves, payoff_plies=payoff_plies)
        user_moves = step.user_move_number
        quiet = 0 if forcing else quiet + 1
        steps.append(step)
    return BoundedProof("unsettled", tuple(steps), board.fen(), raw, window)
