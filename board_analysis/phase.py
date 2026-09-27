"""Deterministic board-state phase heuristic, independent of opening theory."""
from dataclasses import dataclass
from enum import StrEnum
import chess
from analysis_settings import Settings, setting


class GamePhase(StrEnum):
    OPENING = "Opening"
    MIDDLEGAME = "Middlegame"
    ENDGAME = "Endgame"


@dataclass(frozen=True)
class PhaseSettings(Settings):
    endgame_units: int = setting(8, "Endgame at or below this total non-pawn phase weight (N/B=1, R=2, Q=4).", minimum=0, maximum=24)
    opening_units: int = setting(20, "Minimum remaining phase weight for opening.", minimum=0, maximum=24)
    home_minors: int = setting(4, "Minimum knights/bishops on their original squares for opening.", minimum=0, maximum=8)


def game_phase(board, settings=PhaseSettings()):
    """Classify the position before a move; material takes precedence over development."""
    weights = {chess.KNIGHT: 1, chess.BISHOP: 1, chess.ROOK: 2, chess.QUEEN: 4}
    units = sum(weights.get(piece.piece_type, 0) for piece in board.piece_map().values())
    if units <= settings.endgame_units:
        return GamePhase.ENDGAME
    home = sum(board.piece_at(square) == chess.Piece(kind, color)
               for color, rank in ((chess.WHITE, 0), (chess.BLACK, 7))
               for file, kind in ((1, chess.KNIGHT), (2, chess.BISHOP), (5, chess.BISHOP), (6, chess.KNIGHT))
               for square in (chess.square(file, rank),))
    return GamePhase.OPENING if units >= settings.opening_units and home >= settings.home_minors else GamePhase.MIDDLEGAME
