"""Tactic-agnostic, read-only chess primitives for analyzers and patterns.

Public functions accept a python-chess Board and return immutable observations.
No database, engine, UI, tactic registry, or persistence dependencies.
"""
from .geometry import DIRECTIONS, ORTHOGONAL_DIRECTIONS, DIAGONAL_DIRECTIONS, direction, ray_squares, between_squares, neighborhood
from .attacks import PieceRef, AttackMap, attacked_squares, attackers, attack_map, attacked_pieces
from .lines import LineRelationship, RayContact, SliderLine, SliderMoveLines, new_slider_move_lines, line_relationship, ray_contacts, slider_directions, direct_slider_lines
from .safety import PieceSafety, piece_safety
from .mobility import Mobility, legal_mobility, capture_square
from .king_safety import KingSafety, king_safety
from .material import material_balance

__all__ = [
    "DIRECTIONS", "ORTHOGONAL_DIRECTIONS", "DIAGONAL_DIRECTIONS", "direction", "ray_squares", "between_squares", "neighborhood",
    "PieceRef", "AttackMap", "attacked_squares", "attackers", "attack_map", "attacked_pieces",
    "LineRelationship", "RayContact", "line_relationship", "ray_contacts", "PieceSafety", "piece_safety",
    "Mobility", "legal_mobility", "capture_square", "KingSafety", "king_safety",
    "material_balance",
    "SliderLine", "slider_directions", "direct_slider_lines",
    "SliderMoveLines", "new_slider_move_lines",
]
