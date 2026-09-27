"""Connect Skewer V1 to the shared position-analysis service."""
from analyze_skewers import analyze_single_move


def skewer_adapter(row, positions):
    return analyze_single_move(row,positions.position)
