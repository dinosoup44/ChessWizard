"""Pin-specific attribution policy over a verified line; no I/O or engines."""
from dataclasses import dataclass
import chess
from board_analysis import attacked_squares, between_squares, capture_square, legal_mobility, material_balance, piece_safety
from pin_geometry import PIECE_VALUES, pins_from


@dataclass(frozen=True)
class PinAttribution:
    kind: str
    rationale: str
    constraint: str
    payoff_move: int | None
    related_material_cp: int
    captured_piece: str | None
    relationship_survived: bool
    pinner_exchanged: bool
    defender_removed: bool = False


def _active(board, squares):
    if any(squares[k] is None for k in ("attacker", "pinned", "behind")):
        return False
    return any(p.pinned.square == squares["pinned"] and p.behind.square == squares["behind"]
               for p in pins_from(board, squares["attacker"]))


def _relative_concession(after_pin, pin):
    """Observe an escape exposing a higher-value rear target to a winning capture.

This supports a material constraint, not a counterfactual engine theorem.
Allow every immediate legal recapture when conservatively pricing that capture.
"""
    color = pin.attacker.color
    for escape in after_pin.legal_moves:
        if escape.from_square != pin.pinned.square or after_pin.is_capture(escape):
            continue
        moved = after_pin.copy(stack=False)
        moved.push(escape)
        capture = chess.Move(pin.attacker.square, pin.behind.square)
        if capture not in moved.legal_moves or capture_square(moved, capture) != pin.behind.square:
            continue
        baseline = material_balance(moved, color, PIECE_VALUES)
        moved.push(capture)
        gain = material_balance(moved, color, PIECE_VALUES) - baseline
        for reply in moved.legal_moves:
            if capture_square(moved, reply) == pin.behind.square:
                recaptured = moved.copy(stack=False)
                recaptured.push(reply)
                gain = min(gain, material_balance(recaptured, color, PIECE_VALUES) - baseline)
        if gain >= 100:
            return True
    return False


def attribute_pin(after_pin, pin, proof):
    color = pin.attacker.color
    squares = {k: getattr(pin, k).square for k in ("attacker", "pinned", "behind")}
    mobility = legal_mobility(after_pin, pin.pinned.square).move_count
    safety = piece_safety(after_pin, pin.pinned.square)
    absolute = bool(safety and safety.absolutely_pinned)
    concession = pin.pin_type == "relative" and _relative_concession(after_pin, pin)
    constraint = "fully_constrained" if absolute and mobility == 0 else "partially_constrained" if absolute or concession else "not_established"
    related_value, losses, payoff, captured_piece = 0, 0, None, None
    supported, check_led, exchanged, survived = False, False, False, False
    recapture_target = None
    incidental_credit = {}
    removed_defenders = False
    captured_value = 0
    original_ray = {pin.attacker.square, *between_squares(pin.attacker.square, pin.behind.square)}
    for step in proof.steps:
        board = chess.Board(step.before_fen)
        move = chess.Move.from_uci(step.uci)
        active = _active(board, squares)
        captured_role = next((k for k, square in squares.items()
                              if square is not None and square == step.captured_square), None)
        if step.actor != color and step.captured_piece:
            # An unrelated capture may offset only the later loss of that same
            # capturing piece (e.g. Bxh3 gxh3), never another piece's sacrifice.
            credit = incidental_credit.pop(step.captured_square, 0)
            losses += max(0, PIECE_VALUES[step.captured_piece] - credit)
            if captured_role == "attacker" and move.from_square in (squares["pinned"], squares["behind"]):
                recapture_target = move.to_square
        if step.actor == color:
            exchange = recapture_target is not None and step.captured_square == recapture_target
            exposed = (captured_role == "behind" and move.from_square == squares["attacker"]
                       and move.from_square in original_ray and step.captured_square == pin.behind.square)
            related = bool(step.captured_piece and ((captured_role == "pinned" and active) or exposed or exchange))
            if related and step.in_payoff_window and step.user_move_number <= proof.window.user_moves:
                related_value += PIECE_VALUES[step.captured_piece]
                payoff = payoff or step.user_move_number
                if PIECE_VALUES[step.captured_piece] > captured_value:
                    captured_piece, captured_value = chess.piece_name(step.captured_piece), PIECE_VALUES[step.captured_piece]
                survived = survived or active
                exchanged = exchanged or exchange
                supported = supported or (active and (absolute or concession)) or exposed or (exchange and (absolute or concession))
                check_led = check_led or (after_pin.is_check() and step.user_move_number == 1
                                          and captured_role == "pinned")
            recapture_target = None
            credit = incidental_credit.pop(move.from_square, 0)
            if step.captured_piece and not related:
                credit += PIECE_VALUES[step.captured_piece]
                defender = piece_safety(board, step.captured_square)
                if (step.in_payoff_window and active and squares["pinned"] in attacked_squares(board, step.captured_square)
                        and defender and not defender.absolutely_pinned):
                    removed_defenders = True
            if credit:
                incidental_credit[move.to_square] = credit
        for role, square in tuple(squares.items()):
            if square is not None:
                if square == step.captured_square:
                    squares[role] = None
                elif square == move.from_square:
                    squares[role] = move.to_square
    # Credit only related captures and neutral same-piece preparatory exchanges.
    # An unrelated gain by a surviving piece cannot fund another piece's loss.
    retained = related_value - losses
    if check_led:
        kind, reason = "check_led", "The forcing check supplies the tempo to capture the attacked piece; pin geometry is secondary context."
    elif supported:
        kind, reason = "supported", ("Exchanging the pinner wins a related target after recapture." if exchanged else
            "The proof wins a pin participant while the absolute restriction or a concrete rear-target exposure constrains defense.")
    else:
        kind, reason = "context_only", "Pin geometry is present, but a material role in the observed gain is not established."
    return PinAttribution(kind, reason, constraint, payoff, retained, captured_piece, survived, exchanged,
                          removed_defenders and payoff is not None)
