"""Small direct-exposure queries over the shared legal evidence ledger."""
import chess

from position_range_evidence import LegalReplay
from major_material_blunder_models import DirectEscape

MAJOR_PIECES = (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT)


def legal_recoveries(replay, ply):
    """All actual-side captures, including equivalent recovery away from the capturer."""
    board = replay.board_at(ply)
    squares = tuple(s for s, p in board.piece_map().items() if p.color != board.turn)
    return tuple(c for state in replay.position_evidence(ply=ply, squares=squares).attack_states
                 for c in state.legal_captures_against)


def forcing_moves(board):
    """Unproved checks/promotions are compensation uncertainty, never a positive proof."""
    return tuple(sorted(board.san(m) for m in board.legal_moves if m.promotion or board.gives_check(m)))


def direct_escape(before, target_square, played_uci, values):
    """Find one nonforcing escape without substituting another immediately hanging major piece.

    This is a one-ply legal witness, not minimax, engine analysis or proof that an
    already trapped piece can survive indefinitely. Failure to find one is unknown.
    """
    for move in sorted(before.legal_moves, key=lambda m: m.uci()):
        if move.uci() == played_uci or before.gives_check(move) or move.promotion:
            continue
        replay = LegalReplay(before, (move.uci(),), piece_values=values)
        evidence = replay.evidence(track_squares=(target_square,))
        fate = evidence.get_piece_fate(replay.identity_at_start(target_square))
        if not fate.alive or fate.attack_state.geometric_attackers:
            continue
        board = replay.board_at()
        own = tuple(s for s, p in board.piece_map().items()
                    if p.color == before.turn and p.piece_type in MAJOR_PIECES)
        if any(s.legal_capture_available for s in replay.position_evidence(squares=own).attack_states):
            continue
        return DirectEscape(move.uci(), replay.events[0].san, board.fen(), fate)
    return None


def exposure_cause(replay, target, before_attack, after_attack):
    event = replay.events[0]
    if any(t.piece == target and t.to_square != t.from_square for t in event.transitions):
        return "moved_target_into_capture"
    if event.from_square in before_attack.geometric_defenders and event.from_square not in after_attack.geometric_defenders:
        return "abandoned_defender"
    if before_attack.geometric_attackers:
        return "ignored_existing_direct_threat"
    return "opened_capture_line"
