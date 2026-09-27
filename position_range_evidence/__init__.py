"""Pure board/range facts for frontend-independent consumers; no tactical verdicts."""
from .models import (PieceIdentity, SideMaterial, MoveEvent, CaptureEvent, PromotionEvent,
    CheckEvent, PieceIdentityTransition, MaterialTransition, TargetFate, AttackerSurvival,
    LegalCapture, RelevantRecapture, AttackState, TerminalState, PositionEvidence, RangeEvidence)
from .replay import LegalReplay, IllegalRangeError, analyze_position, analyze_range
from .terminal import terminal_state

__all__ = ["PieceIdentity", "SideMaterial", "MoveEvent", "CaptureEvent", "PromotionEvent",
    "CheckEvent", "PieceIdentityTransition", "MaterialTransition", "TargetFate", "AttackerSurvival",
    "LegalCapture", "RelevantRecapture", "AttackState", "TerminalState", "PositionEvidence",
    "RangeEvidence", "LegalReplay", "IllegalRangeError", "analyze_position", "analyze_range", "terminal_state"]
