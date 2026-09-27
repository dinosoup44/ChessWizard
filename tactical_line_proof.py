"""Shared line-participant tracking and conservative exchange accounting.

No engine, database, selection, or tactic labels. Policies decide whether the
observed resolution is compelling enough for their particular line motif.
"""
from dataclasses import dataclass
import chess
from board_analysis import direction, line_relationship, material_balance


@dataclass(frozen=True)
class BlockerResolution:
    resolution: str | None
    resolution_ply: int | None
    concrete_resolution: bool
    rear_captured: bool
    payoff_user_move: int | None
    related_material_cp: int
    attacker_exchanged: bool
    relationship_survived: bool


def trace_blocker_resolution(line, proof, values):
    """Track a resolved blocker and retained rear capture on the original ray.

    Unlike front-target compulsion, resolution can be another piece's capture,
    or a friendly blocker's capture/check. Quiet displacement is recorded but
    is not causal proof. Rear escape is rejected except an immediate rear-for-
    blocker exchange recaptured by the original slider. All own losses are
    charged; unrelated captures offset only loss of the same capturing piece.
    This helper does not assign a tactic or a candidate state.
    """
    color = line.attacker.color
    squares = {name:getattr(line, name).square for name in ("attacker", "front", "rear")}
    resolution, resolution_ply, payoff = None, None, None
    concrete = rear_captured = exchanged = survived = False
    gains = losses = 0
    incidental = {}
    intercepted_rear = attacker_exchange = None
    for ply, step in enumerate(proof.steps, 1):
        board = chess.Board(step.before_fen)
        move = chess.Move.from_uci(step.uci)
        a, f, r = (squares[name] for name in ("attacker", "front", "rear"))
        roles = {name for name, sq in squares.items() if sq is not None and sq == step.captured_square}
        mover = next((name for name, sq in squares.items() if sq == move.from_square), None)
        clear = (a is not None and r is not None and direction(a, r) == line.step
                 and line_relationship(board, a, r).clear)
        rear_on_line = r == line.rear.square or (r == intercepted_rear and intercepted_rear is not None)
        direct_rear = (step.actor == color and mover == "attacker" and "rear" in roles
                       and clear and rear_on_line and concrete)
        recapture_rear = (step.actor == color and "rear" in roles and attacker_exchange is not None
                          and step.captured_square == attacker_exchange and concrete)
        if step.actor == color:
            credit = incidental.pop(move.from_square, 0)
            if step.captured_piece:
                if direct_rear or recapture_rear or "front" in roles:
                    gains += values[step.captured_piece]
                else:
                    credit += values[step.captured_piece]
            if credit:
                incidental[move.to_square] = credit
            if (direct_rear or recapture_rear) and step.in_payoff_window and step.user_move_number <= proof.window.user_moves:
                rear_captured = True
                payoff = payoff or step.user_move_number
                survived = survived or clear or recapture_rear
            intercepted_rear = attacker_exchange = None
        elif step.captured_piece:
            losses += max(0, values[step.captured_piece] - incidental.pop(step.captured_square, 0))
            if "attacker" in roles:
                exchanged = True
                if mover == "rear" and clear and rear_on_line and concrete:
                    attacker_exchange = move.to_square
        if "front" in roles and resolution is None:
            resolution_ply = ply
            resolution = ("captured_by_rear" if mover == "rear" else
                          "captured_by_attacker" if mover == "attacker" else "removed_by_other_piece")
            concrete = True
            if mover == "rear" and a is not None and direction(a, move.to_square) == line.step:
                intercepted_rear = move.to_square
        elif mover == "front" and resolution is None:
            resolution_ply = ply
            concrete = step.actor == color and (step.captured_piece is not None or board.gives_check(move))
            resolution = "forcing_blocker_move" if concrete else "quiet_blocker_move"
        for role in roles:
            squares[role] = None
        if mover:
            squares[mover] = move.to_square
        if mover == "attacker" and squares["rear"] is not None and move.to_square != squares["rear"]:
            if direction(move.to_square, squares["rear"]) != line.step:
                squares["attacker"] = None
    return BlockerResolution(resolution, resolution_ply, concrete, rear_captured, payoff,
                             gains-losses if rear_captured else 0, exchanged, survived)


def capture_balance_floor(board, source, target, color, values):
    """Material gain after a hypothetical legal capture and every immediate recapture.

This is a local threat observation, not SEE, a forced-line proof or evaluation.
The caller supplies the color because the threatened side is normally to move.
"""
    copy = board.copy(stack=False)
    copy.turn = color
    move = chess.Move(source, target)
    if move not in copy.legal_moves or not copy.is_capture(move):
        return None
    before = material_balance(copy, color, values)
    copy.push(move)
    floor = material_balance(copy, color, values) - before
    for reply in copy.legal_moves:
        if reply.to_square == target and copy.is_capture(reply):
            after = copy.copy(stack=False)
            after.push(reply)
            floor = min(floor, material_balance(after, color, values) - before)
    return floor


@dataclass(frozen=True)
class LineResolution:
    front_resolution: str | None
    front_captured_by_attacker: bool
    rear_exposed: bool
    rear_captured: bool
    payoff_user_move: int | None
    related_material_cp: int
    attacker_exchanged: bool
    relationship_survived: bool


def trace_line_resolution(line, proof, values):
    """Follow identities, not stationary squares, through a bounded legal proof.

Rear credit requires the original attacker to capture along the original ray,
or immediate recapture of the rear target after it exchanges that attacker.
Front credit requires capture by that attacker. Unrelated wins cannot fund a
line claim: they offset only a later loss of the same capturing piece.
All own losses through settlement are charged, including later recaptures.
"""
    color = line.attacker.color
    squares = {name:getattr(line,name).square for name in ("attacker","front","rear")}
    front_resolution, exposed, rear_captured, front_captured = None, False, False, False
    payoff, related, losses, exchanged, survived = None, 0, 0, False, False
    incidental = {}
    exchange_target = None
    for step in proof.steps:
        board = chess.Board(step.before_fen)
        move = chess.Move.from_uci(step.uci)
        roles = {name for name,square in squares.items() if square is not None and square == step.captured_square}
        mover = next((name for name,square in squares.items() if square == move.from_square), None)
        a, r = squares["attacker"], squares["rear"]
        open_ray = (front_resolution is not None and a is not None and r == line.rear.square
                    and direction(a,r) == line.step and line_relationship(board,a,r).clear)
        exposed = exposed or open_ray
        is_exchange = (step.actor == color and step.captured_square == exchange_target
                       and "rear" in roles and exchange_target is not None)
        direct_rear = step.actor == color and mover == "attacker" and "rear" in roles and open_ray
        direct_front = step.actor == color and mover == "attacker" and "front" in roles
        if step.actor != color and step.captured_piece:
            losses += max(0, values[step.captured_piece] - incidental.pop(step.captured_square,0))
            exchanged = exchanged or "attacker" in roles
            if "attacker" in roles and mover == "rear" and open_ray:
                exchange_target = move.to_square
        elif step.actor == color:
            credit = incidental.pop(move.from_square,0)
            if step.captured_piece:
                if direct_front or direct_rear or is_exchange:
                    related += values[step.captured_piece]
                else:
                    credit += values[step.captured_piece]
            if credit:
                incidental[move.to_square] = credit
            if (direct_rear or is_exchange) and step.in_payoff_window and step.user_move_number <= proof.window.user_moves:
                rear_captured = True
                payoff = payoff or step.user_move_number
                exchanged = exchanged or is_exchange
                survived = survived or open_ray
            exchange_target = None
        if direct_front:
            front_captured = True
            front_resolution = front_resolution or "captured_by_attacker"
        elif mover == "front" and front_resolution is None:
            front_resolution = "captured_attacker" if "attacker" in roles else "moved"
        for role in roles:
            squares[role] = None
        if mover:
            squares[mover] = move.to_square
        # Moving the attacker off its original ray ends this line's identity.
        if mover == "attacker" and squares["rear"] == line.rear.square and move.to_square != line.rear.square:
            if direction(move.to_square,line.rear.square) != line.step:
                squares["attacker"] = None
    return LineResolution(front_resolution, front_captured, exposed, rear_captured, payoff,
                          related-losses if rear_captured else 0, exchanged, survived)
