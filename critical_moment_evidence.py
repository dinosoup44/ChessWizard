"""Toolkit-backed material facts for context consumers, with no engine or DB access."""
from dataclasses import dataclass
import chess
from position_range_evidence import LegalReplay
from critical_moment_context import ContextPolicy


@dataclass(frozen=True)
class ObservedMaterialLoss:
    supported: bool
    victim_type: str | None
    loss_cp: int | None
    capture_san: str | None
    facts: tuple[str, ...]


def observe_material_loss(fen: str, moves_uci: tuple[str, ...], policy=ContextPolicy()) -> ObservedMaterialLoss:
    """Describe an actual capture plus recorded reply, not hypothetical best play."""
    if len(moves_uci) < 2:
        return ObservedMaterialLoss(False,None,None,None,("No recorded reply window.",))
    replay = LegalReplay(fen,moves_uci[:policy.observation_plies])
    first = replay.events[0]
    capture = first.capture
    if capture is None or capture.victim_type not in (chess.QUEEN,chess.ROOK,chess.BISHOP,chess.KNIGHT):
        return ObservedMaterialLoss(False,None,None,first.san,("No immediate major-piece capture at this anchor.",))
    start = replay.position_evidence(ply=0,squares=(capture.square,))
    evidence = replay.evidence(track_squares=(capture.square,))
    fate = evidence.get_piece_fate(capture.victim)
    delta = evidence.material_transition.delta
    loss = delta.for_color(not capture.victim_color) - delta.for_color(capture.victim_color)
    recaptures = replay.relevant_recaptures(ply=1,track_squares=(capture.square,))
    capturer_can_be_taken = any(r.capture.victim == first.actor for r in recaptures)
    losing_side_mates = evidence.terminal_state.state == "checkmate" and evidence.terminal_state.winner == capture.victim_color
    supported = bool(start.attack_states[0].legal_capture_available and fate.capture_ply == 1 and
                     loss >= policy.major_loss_cp and not capturer_can_be_taken and not losing_side_mates)
    facts = (f"Legal recorded capture: {first.san}; victim {chess.piece_name(capture.victim_type)} ({capture.value} cp).",
             f"TargetFate capture ply {fate.capture_ply}; observed net loss {loss} cp over {evidence.ply_count} plies.",
             f"Immediate legal recapture of capturer available: {capturer_can_be_taken}.")
    return ObservedMaterialLoss(supported,chess.piece_name(capture.victim_type),loss,first.san,facts)
