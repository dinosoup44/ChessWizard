"""Advisory SEE V1: one legal LVA chain, not move evaluation or tactic proof.

Negative estimates never authorize rejection. Optional stopping is not a legal
pass, a harmless alternative, or a guaranteed lower bound. No production analyzer
consumes this API yet; see docs/STATIC_EXCHANGE_EVALUATION.md.
"""
import chess
from analysis_settings import MaterialValues
from .attacks import attackers
from .mobility import capture_square
from .static_exchange_models import (
    ExchangeCompleteness, ExchangeLimitation, ExchangeStep, ExchangeUncertainty,
    ExchangeVerdict, StaticExchangePolicy, StaticExchangeResult,
)

__all__ = ["evaluate_static_exchange", "StaticExchangePolicy", "StaticExchangeResult",
           "ExchangeStep", "ExchangeCompleteness", "ExchangeVerdict",
           "ExchangeUncertainty", "ExchangeLimitation"]


def _attacker_cost(board: chess.Board, move: chess.Move, values: dict[int, int]) -> tuple[bool, int, int, str]:
    piece = board.piece_type_at(move.from_square)
    # Kings have zero accounting value but must never be treated as cheap victims.
    return (piece == chess.KING, values[piece], -values.get(move.promotion, 0), move.uci())


def _select_prefix(steps: list[ExchangeStep], stops: list[bool]) -> tuple[int, int]:
    """Compare stop/continue along the fixed chain, without exploring sibling moves."""
    value, prefix = steps[-1].cumulative_net_cp, len(steps)
    for i in range(len(steps)-2, -1, -1):
        if not stops[i]:
            continue
        stop = steps[i].cumulative_net_cp
        initiating_side_to_move = (i + 1) % 2 == 0
        if (stop >= value if initiating_side_to_move else stop <= value):
            value, prefix = stop, i+1
    return value, prefix


def evaluate_static_exchange(source: chess.Board | str, capture: chess.Move | str, *,
                             material: MaterialValues = MaterialValues(),
                             policy: StaticExchangePolicy = StaticExchangePolicy()) -> StaticExchangeResult:
    """Force one legal capture, then estimate optional LVA recaptures on its destination.

    Each recapture is legal in its updated position. Equal-cost choices use UCI
    order; recapture promotions prefer highest configured value. Unsearched
    alternatives remain explicit uncertainty. Check evasions outside the square,
    terminal states and capped chains suppress the numerical estimate.
    """
    if not isinstance(source, (chess.Board, str)) or not isinstance(capture, (chess.Move, str)):
        raise TypeError("Expected a standard board/FEN and a move/UCI")
    if not isinstance(material, MaterialValues) or not isinstance(policy, StaticExchangePolicy):
        raise TypeError("Expected shared MaterialValues and StaticExchangePolicy")
    if isinstance(source, chess.Board) and (type(source) is not chess.Board or source.chess960):
        raise ValueError("Only standard chess is supported")
    board = chess.Board(source) if isinstance(source, str) else source.copy(stack=False)
    if not board.is_valid():
        raise ValueError("Invalid standard chess position")
    move = chess.Move.from_uci(capture) if isinstance(capture, str) else capture
    if not board.is_legal(move) or not board.is_capture(move):
        raise ValueError("A legal initiating capture is required")
    values = material.piece_values()
    start, side, target = board.fen(), board.turn, move.to_square
    steps, notes, geometry, promotions, hazards, stops = [], [], [], [], [], []
    original_attackers = {c: set(attackers(board, target, c)) for c in chess.COLORS}
    total = 0
    # A capture resets the halfmove clock; preserve an already terminal source.
    if board.is_insufficient_material() or board.is_seventyfive_moves():
        hazards.append(ExchangeUncertainty.TERMINAL_MATERIAL_NOT_GAME_OUTCOME)
    while True:
        victim_square = capture_square(board, move)
        victim = board.piece_at(victim_square)
        mover = board.piece_at(move.from_square)
        alternatives = tuple(sorted(m.uci() for m in board.generate_legal_captures()
                                    if m.to_square == target))
        promotion_gain = values[move.promotion] - values[chess.PAWN] if move.promotion else 0
        if move.promotion:
            promotions.append(f"ply {len(steps)+1}: {move.uci()} adds {promotion_gain} cp")
        if board.is_en_passant(move):
            notes.append(f"en passant removes victim on {chess.square_name(victim_square)}")
        total += (1 if board.turn == side else -1) * (values[victim.piece_type] + promotion_gain)
        steps.append(ExchangeStep(board.fen(), move.uci(), board.san(move), mover.piece_type,
            victim.piece_type, victim_square, values[victim.piece_type], promotion_gain,
            total, alternatives))
        board.push(move)
        geometric = set(attackers(board, target, board.turn))
        legal = tuple(m for m in board.generate_legal_captures() if m.to_square == target)
        legal_sources = {m.from_square for m in legal}
        for square in sorted(geometric - legal_sources):
            why = "absolute pin" if board.is_pinned(board.turn, square) else "king/check legality"
            geometry.append(f"ply {len(steps)}: excluded {chess.square_name(square)} ({why})")
        for square in sorted(legal_sources - original_attackers[board.turn]):
            geometry.append(f"ply {len(steps)}: newly available attacker {chess.square_name(square)}")
        all_legal = tuple(board.legal_moves)
        outside = any(m not in legal for m in all_legal)
        stops.append(outside and not board.is_check())
        if board.is_check() and outside:
            hazards.append(ExchangeUncertainty.OFF_SQUARE_CHECK_EVASION_REQUIRED)
        if not all_legal or board.is_insufficient_material() or board.is_seventyfive_moves():
            hazards.append(ExchangeUncertainty.TERMINAL_MATERIAL_NOT_GAME_OUTCOME)
        if not legal:
            break
        if len(steps) >= policy.max_plies:
            hazards.append(ExchangeUncertainty.EXCHANGE_BOUND_EXHAUSTED)
            break
        if len(legal) > 1:
            notes.append(f"ply {len(steps)}: {len(legal)} legal recaptures; only LVA choice followed")
        move = min(legal, key=lambda m: _attacker_cost(board, m, values))
    value, prefix = _select_prefix(steps, stops)
    estimate = None if hazards else value
    completeness = ExchangeCompleteness.INCOMPLETE if hazards else ExchangeCompleteness.COMPLETE_LVA_CHAIN_ONLY
    verdict = (ExchangeVerdict.UNKNOWN if estimate is None else ExchangeVerdict.FAVORABLE if estimate > 0
               else ExchangeVerdict.UNFAVORABLE if estimate < 0 else ExchangeVerdict.NEUTRAL)
    return StaticExchangeResult(
        source_fen=start, initiating_move=steps[0].move_uci, target_square=target,
        initiating_side=side, captured_piece_type=steps[0].captured_type,
        captured_piece_value=steps[0].captured_value_cp, exchange_sequence=tuple(steps),
        participant_piece_types=tuple(step.attacker_type for step in steps) + (steps[0].captured_type,),
        estimated_net_cp=estimate, provisional_net_cp=value, selected_prefix_plies=prefix,
        verdict=verdict, completeness=completeness,
        legality_notes=tuple(notes + sorted(set(hazards))), pin_xray_notes=tuple(geometry),
        promotion_notes=tuple(promotions), limitations=tuple(ExchangeLimitation),
        material_values=material, policy=policy, uncertainty_reasons=tuple(sorted(set(hazards))),
    )
