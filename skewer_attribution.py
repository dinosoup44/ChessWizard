"""Skewer-specific causality policy over shared line-resolution evidence."""
from dataclasses import dataclass
import chess
from tactical_line_proof import capture_balance_floor, trace_line_resolution, LineResolution
from skewer_geometry import PIECE_VALUES


@dataclass(frozen=True)
class SkewerAttribution:
    kind: str
    rationale: str
    front_threat_cp: int | None
    resolution: LineResolution


def attribute_skewer(after_tactic, skewer, proof):
    line = skewer.line
    resolution = trace_line_resolution(line,proof,PIECE_VALUES)
    king_front = line.front.piece_type == chess.KING
    threat = None if king_front else capture_balance_floor(after_tactic,line.attacker.square,line.front.square,
                                                          line.attacker.color,PIECE_VALUES)
    compelled = after_tactic.is_check() if king_front else threat is not None and threat > 0
    supported = compelled and resolution.rear_captured and resolution.related_material_cp >= 100
    rationale = ("The attacked front target resolves and exposes the rear target along the original line; the related gain survives settlement."
                 if supported else "Alignment alone does not establish a retained rear-target gain caused by a meaningful front-target response.")
    return SkewerAttribution("supported" if supported else "context_only",rationale,threat,resolution)
