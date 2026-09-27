"""Shared result contract for single-position specialists; no I/O."""
from dataclasses import dataclass, field
from tactical_opportunities import TacticalOpportunity


@dataclass(frozen=True)
class HeavyResult:
    state: str  # candidate / analyzed_no_hit / error
    candidate: dict | None = None
    details: dict = field(default_factory=dict)
    opportunity: TacticalOpportunity | None = None
