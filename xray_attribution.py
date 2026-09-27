"""Conservative X-ray causality policy over shared line-resolution evidence."""
from dataclasses import dataclass
from tactical_line_proof import BlockerResolution, trace_blocker_resolution
from xray_geometry import PIECE_VALUES


@dataclass(frozen=True)
class XrayAttribution:
    kind: str
    rationale: str
    resolution: BlockerResolution


def attribute_xray(line, proof):
    resolution = trace_blocker_resolution(line, proof, PIECE_VALUES)
    supported = resolution.concrete_resolution and resolution.rear_captured and resolution.related_material_cp >= 100
    rationale = ("Resolving the intervening piece opens the original slider line to a rear-target capture; related material remains after recaptures."
                 if supported else "The line lacks a concrete blocker resolution and retained rear-target payoff; geometry alone is context.")
    return XrayAttribution("supported" if supported else "context_only", rationale, resolution)
