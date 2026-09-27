"""Public adapter to the shared position-analysis service."""
from analyze_xrays import analyze_single_move


def xray_adapter(row, positions):
    return analyze_single_move(row, positions.position)
