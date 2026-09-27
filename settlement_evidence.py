"""Normalized legal proof evidence, distinct from unverified root-PV facts."""
from dataclasses import dataclass
import chess
from analysis_settings import MaterialValues, identity
from analysis_states import EvidenceState, proof_state
from board_analysis import capture_square, material_balance
from candidate_lines import LineScore, to_data
from tactical_proof import BoundedProof


@dataclass(frozen=True)
class CaptureEvent:
    ply: int
    actor: str
    move_uci: str
    captured_square: str
    captured_piece: str


@dataclass(frozen=True)
class SettlementEvidence:
    """Observed bounded settlement; material movement does not establish motif causality."""
    base_fen: str
    final_fen: str
    player: str
    branch_identity: str
    moves_uci: tuple[str, ...]
    moves_san: tuple[str, ...]
    material_before_cp: int
    material_after_cp: int
    observed_material_change_cp: int
    captures: tuple[CaptureEvent, ...]
    final_evaluation: LineScore | None
    state: EvidenceState
    reason: str
    proof_profile_identity: str
    evidence_requests: tuple[tuple[str, str], ...]
    material_profile: MaterialValues

    @property
    def settled(self):
        return self.state == EvidenceState.PROOF_STABLE

    @property
    def mate_winner(self):
        if self.final_evaluation is not None:
            return self.final_evaluation.mate_winner
        board = chess.Board(self.final_fen)
        if board.is_checkmate():
            return "black" if board.turn else "white"
        return None

    @property
    def branch_length(self):
        return len(self.moves_uci)


def settlement_evidence(base_fen, player, proof: BoundedProof, *, profile_identity,
                        evidence_requests=(), material=MaterialValues()):
    """Replay a supplied proof, validate its ledger and attach exact request provenance."""
    if not isinstance(proof, BoundedProof) or player not in {"white", "black"} or not profile_identity:
        raise ValueError("Explicit bounded proof, player and profile required")
    board, color = chess.Board(base_fen), player == "white"
    values = material.piece_values()
    initial = material_balance(board, color, values)
    captures, ucis, sans = [], [], []
    for ply, step in enumerate(proof.steps, 1):
        if board.fen() != step.before_fen or board.turn != step.actor:
            raise ValueError("Proof position/actor mismatch")
        move = board.parse_uci(step.uci)
        san, square = board.san(move), capture_square(board, move)
        victim = board.piece_at(square) if square is not None else None
        if san != step.san or square != step.captured_square or (victim.piece_type if victim else None) != step.captured_piece:
            raise ValueError("Proof SAN/capture ledger mismatch")
        if victim:
            captures.append(CaptureEvent(ply, "white" if board.turn else "black", step.uci,
                chess.square_name(square), chess.piece_name(victim.piece_type)))
        board.push(move)
        if board.fen() != step.after_fen or material_balance(board, color, values) != step.material_cp:
            raise ValueError("Proof replay/material mismatch")
        ucis.append(step.uci); sans.append(san)
    if board.fen() != proof.final_fen:
        raise ValueError("Proof final position mismatch")
    raw, final_score = proof.final_evidence, None
    # Terminal proof may retain a preceding evaluation. Never label it as endpoint evidence.
    if proof.state in {"stable", "unsettled", "mate"} and not board.is_game_over() and raw:
        if raw.get("score_pov") != "white":
            raise ValueError("Explicit White-POV proof evidence required")
        if raw.get("score_type") == "cp":
            final_score = LineScore(score_cp=raw["score_cp"]).pov(player)
        elif raw.get("score_type") == "mate":
            final_score = LineScore(mate_score=raw["mate"], mate_winner=raw.get("mate_winner")).pov(player)
    if proof.state == "stable" and final_score is None:
        raise ValueError("Stable settlement needs a fresh endpoint evaluation")
    final = material_balance(board, color, values)
    requests = tuple(tuple(request) for request in evidence_requests)
    branch_id = settlement_identity(base_fen, ucis, profile_identity, requests, proof.window, material)
    return SettlementEvidence(base_fen, board.fen(), player, branch_id, tuple(ucis), tuple(sans),
        initial, final, final-initial, tuple(captures), final_score, proof_state(proof), proof.state,
        profile_identity, requests, material)


def settlement_identity(base_fen, moves, profile_identity, requests, window, material):
    """One metadata identity for freshly computed and read-normalized settlement evidence."""
    return identity({"base_fen": base_fen, "moves": list(moves), "profile": profile_identity,
        "requests": tuple(tuple(key) for key in requests), "window": to_data(window), "material": to_data(material)})
