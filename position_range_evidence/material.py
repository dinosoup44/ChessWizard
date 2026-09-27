"""Configured material accounting, independent of evaluations and tactic ownership."""
from collections.abc import Mapping
import chess
from analysis_settings import MaterialValues
from .models import MaterialTransition, MoveEvent, SideMaterial


def configured_values(values: Mapping[int, int] | None) -> dict[int, int]:
    result = dict(MaterialValues().piece_values() if values is None else values)
    if set(result) != set(chess.PIECE_TYPES) or any(type(v) is not int or v < 0 for v in result.values()):
        raise ValueError("Provide nonnegative integer values for all six piece types")
    return result


def material_totals(board: chess.Board, values: Mapping[int, int]) -> SideMaterial:
    return SideMaterial(*(sum(len(board.pieces(t, c)) * values[t] for t in chess.PIECE_TYPES)
                          for c in (chess.WHITE, chess.BLACK)))


def material_transition(before: SideMaterial, events: tuple[MoveEvent, ...],
                        values: Mapping[int, int], *, snapshots: bool = False) -> MaterialTransition:
    """Reconcile loss and promotion separately; captures by a side are positive totals."""
    lost = {True: 0, False: 0}
    promoted = {True: 0, False: 0}
    timeline = [before] if snapshots else None
    captures, promotions = [], []
    for event in events:
        if event.capture:
            captures.append(event.capture)
            lost[event.capture.victim_color] += event.capture.value
        if event.promotion:
            promotions.append(event.promotion)
            promoted[event.promotion.piece.color] += event.promotion.material_delta
        if timeline is not None:
            timeline.append(SideMaterial(before.white - lost[True] + promoted[True],
                                         before.black - lost[False] + promoted[False]))
    delta = SideMaterial(promoted[True] - lost[True], promoted[False] - lost[False])
    return MaterialTransition(before, SideMaterial(before.white + delta.white, before.black + delta.black),
        delta, SideMaterial(lost[False], lost[True]), SideMaterial(lost[True], lost[False]),
        SideMaterial(promoted[True], promoted[False]), tuple(captures), tuple(promotions),
        tuple(timeline) if timeline is not None else None, tuple(sorted(values.items())))
