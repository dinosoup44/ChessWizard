"""Connect the Pin V1 calculator to the shared position service."""
from analyze_pins import analyze_single_move


def pin_adapter(row, positions):
    return analyze_single_move(row, positions.position)
