"""Connect Pin V2 to the shared position-analysis service."""
from analyze_pins_v2 import analyze_single_move


def pin_adapter(row, positions):
    return analyze_single_move(row, positions.position)
