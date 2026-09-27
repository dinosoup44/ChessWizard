"""Synthetic Fork positions and legal scripted proof, without historical recordings."""
import chess
from analyze_forks_v3 import PIECE_VALUES
from board_analysis import material_balance, capture_square
from tactical_proof import BoundedProof, ProofStep, ProofWindow
from tests.test_heavy_services import move_row


def candidate(fen: str = "r3k3/8/8/3N4/8/8/8/4K3 w - - 0 1", played: str = "e1f1", solution: str = "d5c7") -> dict:
    """Build an in-memory candidate for a supplied synthetic position.

    Args:
        fen: Hand-authored initial position.
        played: Legal actual move in UCI notation.
        solution: Legal tactical alternative in UCI notation.

    Returns:
        A detached candidate dictionary with a synthetic identity.

    Raises:
        ValueError: Position or moves are invalid.
    """
    row = move_row(fen,played)
    board = chess.Board(fen)
    row.update(candidate_id=42,tactic_type="missed_fork",candidate_status="candidate",detector_version=2,
               solution_move_uci=solution,solution_move_san=board.san(chess.Move.from_uci(solution)),
               solution_line="Nc7+ Kf7 Nxa8",metadata_json="{}",confidence=0.9)
    return row


def proof_for(after: chess.Board, line: str, state: str = "stable") -> BoundedProof:
    """Replay supplied legal moves with factual material accounting and a test proof state.

    Args:
        after: Board after the proposed tactical move; never modified.
        line: Scripted SAN continuation, not generated engine evidence.
        state: Explicit fixture completeness state.

    Returns:
        Bounded proof with factual per-move material totals.

    Raises:
        ValueError: The supplied SAN cannot be replayed legally.
    """
    b = after.copy();color=not b.turn;steps=[];user=0
    for token in line.split():
        move=b.parse_san(token);before=b.fen();actor=b.turn;square=capture_square(b,move)
        captured=b.piece_at(square) if square is not None else None
        user+=int(actor==color);san=b.san(move);b.push(move)
        steps.append(ProofStep(before,b.fen(),move.uci(),san,actor,square,
            captured.piece_type if captured else None,material_balance(b,color,PIECE_VALUES),user,True))
    return BoundedProof(state,tuple(steps),b.fen(),{},ProofWindow())
