"""Bounded approved-PV replay with fresh endpoint checks; no motif or storage policy."""
from dataclasses import dataclass
import chess
from tactical_proof import BoundedProof, ProofStep, ProofWindow, play_proof_move
from candidate_lines import freeze


def _raw(line):
    score = line.score.pov("white")
    return {"score_pov": "white", "score_type": "cp" if score.score_cp is not None else "mate",
            "score_cp": score.score_cp, "mate": score.mate_score, "mate_winner": score.mate_winner,
            "principal_variation": " ".join(line.pv_san), "engine_identity": line.engine_identity}


def _quiet_pv(board, line, count):
    if len(line.pv_uci) < count:
        return False
    copy = board.copy(stack=False)
    for uci in line.pv_uci[:count]:
        move = copy.parse_uci(uci)
        if copy.is_check() or copy.is_capture(move) or move.promotion or copy.gives_check(move):
            return False
        copy.push(move)
    return not copy.is_check()


@dataclass(frozen=True)
class SettlementContinuation:
    """Resume state before the old cap's extra endpoint probe; raw PV is preserved."""
    after_tactic_fen: str
    player: bool
    prefix_uci: tuple[str, ...]
    steps: tuple[ProofStep, ...]
    pending_uci: tuple[str, ...]
    quiet_plies: int
    user_moves: int
    last_evidence: dict
    window: ProofWindow

    def __post_init__(self):
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "pending_uci", tuple(self.pending_uci))
        object.__setattr__(self, "prefix_uci", tuple(self.prefix_uci))
        object.__setattr__(self, "last_evidence", freeze(self.last_evidence))


def verify_candidate_line_settlement(after_tactic, player, prefix, best_line, piece_values, window,
                                    *, checkpoint_sink=None, resume=None):
    """Keep approved entry plies fixed, then replay deep PVs and refresh settlement endpoints.

    Scores belong to their requested FEN, never to every intervening PV position.
    A short PV or an unfinished endpoint requests only that exact new position.
    This is linear bounded evidence, not an exhaustive tree or per-ply deep search.
    """
    board = after_tactic.copy(stack=False)
    if board.turn == player:
        raise ValueError("Expected a position after the player's tactical move")
    payoff_plies = 2 * window.user_moves + 1
    maximum_plies = payoff_plies + window.settlement_plies
    steps, pending, quiet, user_moves, raw = [], [], 0, 0, {}
    if resume is not None:
        if (resume.after_tactic_fen != after_tactic.fen() or resume.player != player
                or resume.prefix_uci != tuple(entry.move_uci for entry in prefix)
                or resume.window.user_moves != window.user_moves
                or resume.window.quiet_plies != window.quiet_plies
                or resume.window.version != window.version
                or resume.window.settlement_plies >= window.settlement_plies
                or len(resume.steps) != 2 * resume.window.user_moves + 1 + resume.window.settlement_plies):
            raise ValueError("Incompatible settlement continuation")
        for step in resume.steps:
            if board.fen() != step.before_fen:
                raise ValueError("Continuation proof prefix differs")
            board.push_uci(step.uci)
            if board.fen() != step.after_fen:
                raise ValueError("Continuation proof endpoint differs")
        steps, pending = list(resume.steps), list(resume.pending_uci)
        quiet, user_moves, raw = resume.quiet_plies, resume.user_moves, dict(resume.last_evidence)
    while True:
        if board.is_game_over():
            return BoundedProof("mate" if board.is_checkmate() else "draw", tuple(steps), board.fen(), raw, window)
        ply = len(steps)
        if ply < len(prefix):
            move = board.parse_uci(prefix[ply].move_uci)
        else:
            inspect_endpoint = ply >= payoff_plies and quiet >= window.quiet_plies and not board.is_check()
            if inspect_endpoint or ply == maximum_plies or not pending:
                if ply == maximum_plies and checkpoint_sink is not None:
                    checkpoint_sink(SettlementContinuation(after_tactic.fen(), player,
                        tuple(entry.move_uci for entry in prefix), tuple(steps), tuple(pending), quiet,
                        user_moves, dict(raw), window))
                line = best_line(board.fen())
                raw = _raw(line)
                if line.score.mate_score is not None:
                    return BoundedProof("mate", tuple(steps), board.fen(), raw, window)
                if inspect_endpoint and _quiet_pv(board, line, window.quiet_plies):
                    return BoundedProof("stable", tuple(steps), board.fen(), raw, window)
                if ply == maximum_plies:
                    return BoundedProof("unsettled", tuple(steps), board.fen(), raw, window)
                pending = list(line.pv_uci)
            move = board.parse_uci(pending.pop(0))
        step, forcing = play_proof_move(board, move, player, piece_values,
            ply=ply, user_moves=user_moves, payoff_plies=payoff_plies)
        steps.append(step)
        user_moves = step.user_move_number
        quiet = 0 if forcing else quiet + 1
