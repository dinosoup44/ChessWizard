"""Portable factual checker. No persistence, engine, UI or analyzer entry points."""
from dataclasses import replace
import chess

from analysis_settings import MaterialValues, identity
from position_range_evidence import LegalReplay
from major_material_blunder_models import MajorMaterialBlunderResult, MaterialBlunderPolicy
from major_material_blunder_evidence import (MAJOR_PIECES, direct_escape, exposure_cause,
    forcing_moves, legal_recoveries)


def check_major_material_blunder(before, played_move, after, continuation=(), *,
        move_id=None, target_square=None, material_values=MaterialValues(),
        policy=MaterialBlunderPolicy(), eval_before=None, eval_after=None, provenance=()):
    """Check one actual move and at most four following legal plies.

    `confirmed` means avoidable direct loss retained within this bounded factual
    window. It never proves a forced game outcome or excludes distant quiet
    compensation. Possible forcing compensation is unresolved, not searched.
    `target_square`, when supplied, is the target's square BEFORE the played move.
    Scores must already use player POV; they cannot establish admission.
    """
    result = MajorMaterialBlunderResult("error", "invalid_input", None, None, move_id,
        played_move, provenance=tuple(provenance),
        policy_identity=identity((identity(policy), identity(material_values))))
    try:
        return _check(result, before, played_move, after, tuple(continuation), target_square,
                      material_values.piece_values(), policy, eval_before, eval_after)
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return replace(result, explanation_facts=(str(exc),))


def _finish(result, classification, reason, *facts, complete=False):
    return replace(result, classification=classification, reason=reason,
        evidence_completeness="bounded_complete" if complete else "incomplete",
        explanation_facts=result.explanation_facts + tuple(facts))


def _check(result, before, played, after, continuation, target_square, values, policy, eb, ea):
    if len(continuation) > policy.continuation_plies:
        raise ValueError("Continuation exceeds the configured bounded window")
    initial = LegalReplay(before, (), piece_values=values)
    root = initial.board_at()
    player = root.turn
    result = replace(result, player_color=player, terminal_state=initial.evidence().terminal_state)
    if result.terminal_state.is_terminal:
        return _finish(result, "not_blunder", "terminal_source", "No move is assessed from a terminal source.", complete=True)
    replay = LegalReplay(before, (played,) + continuation, piece_values=values)
    after_board = after if isinstance(after, chess.Board) else chess.Board(after)
    if replay.board_at(1).fen() != after_board.fen():
        raise ValueError("Supplied after-position does not match the legal played move")
    for score, fen in ((eb, root.fen()), (ea, after_board.fen())):
        if score is not None and score.fen != fen:
            raise ValueError("Cached evaluation belongs to a different position")
    delta = ea.player_cp-eb.player_cp if (eb and ea and eb.request_identity == ea.request_identity
        and eb.player_cp is not None and ea.player_cp is not None) else None
    result = replace(result, eval_before=eb, eval_after=ea, eval_delta=delta)
    if not continuation:
        return _finish(result, "unresolved", "missing_capture_evidence")
    capture = replay.events[1].capture
    if target_square is None:
        if capture is None or capture.victim_type not in MAJOR_PIECES:
            return _finish(result, "not_blunder", "no_immediate_major_capture", complete=True)
        target_square = capture.victim.initial_square
    target = replay.identity_at_start(target_square)
    if target.color != player:
        raise ValueError("Target must belong to the player who made the actual move")
    evidence = replay.evidence(track_squares=(target_square,), material_snapshots=True)
    fate = evidence.get_piece_fate(target)
    material = evidence.material_transition
    lost = material.lost_by_side.for_color(player)
    recovered = material.captured_by_side.for_color(player)
    net = material.delta.for_color(not player) - material.delta.for_color(player)
    result = replace(result, target_piece_id=target, target_start_square=target.initial_square,
        target_piece_type=target.initial_piece_type, target_fate=fate,
        material_transition=material, range_evidence=evidence, material_loss_cp=lost,
        material_recovered_cp=recovered, net_loss_cp=net, terminal_state=evidence.terminal_state)
    post_square = next((t.to_square for t in replay.events[0].transitions if t.piece == target), target.initial_square)
    result = replace(result, attack_before=replay.position_evidence(ply=0, squares=(target.initial_square,)).attack_states[0],
        attack_after=replay.position_evidence(ply=1, squares=(post_square,)).attack_states[0])
    if fate.alive:
        return _finish(result, "not_blunder", "target_survived", "Attack alone is not a demonstrated material loss.", complete=True)
    if not capture or capture.victim != target or fate.capture_ply != 2:
        return _finish(result, "unresolved", "loss_not_immediate", "Delayed losses need a separate causal proof.")
    if capture.victim_type not in MAJOR_PIECES:
        return _finish(result, "not_blunder", "unsupported_target_type", complete=True)
    kind = "hung_queen" if capture.victim_type == chess.QUEEN else "hung_rook" if capture.victim_type == chess.ROOK else "hung_minor_piece"
    before_attack = replay.position_evidence(ply=0, squares=(target.initial_square,)).attack_states[0]
    after_attack = replay.position_evidence(ply=1, squares=(capture.square,)).attack_states[0]
    recaptures = replay.relevant_recaptures(ply=2, track_squares=(target.initial_square,))
    recoveries = legal_recoveries(replay, 2)
    result = replace(result, blunder_type=kind, target_piece_type=capture.victim_type,
        capture_square=capture.square, capturing_piece=capture.capturer,
        attack_before=before_attack, attack_after=after_attack, recapture_options=recaptures,
        immediate_recovery_options=recoveries,
        immediate_recapture_available=any(r.capture.victim == capture.capturer for r in recaptures),
        exposure_cause=exposure_cause(replay, target, before_attack, after_attack),
        explanation_facts=(f"{replay.events[0].san} was followed by legal {replay.events[1].san}.",
            f"Bounded material lost {lost} cp; recovered {recovered} cp; net loss {net} cp.",
            "Before-move enemy capture legality is not inferred by flipping the side to move."))
    if not after_attack.legal_capture_available:
        raise ValueError("Recorded capture contradicts the shared legal attack ledger")
    witness = direct_escape(root, target.initial_square, played, values)
    result = replace(result, avoidance_witness=witness)
    terminal = evidence.terminal_state
    if terminal.is_terminal:
        if terminal.winner == player or terminal.winner is None:
            return _finish(result, "not_blunder", "terminal_compensation", "The supplied line ends in player mate or a terminal draw.", complete=True)
        return _finish(result, "unresolved", "terminal_loss", "Mate takes precedence; this checker does not attribute its cause.")
    # A cutoff recovery is not settled when its capturing piece can be taken back.
    last_capture = replay.events[-1].capture
    if last_capture and any(c.victim == last_capture.capturer for c in legal_recoveries(replay, len(replay.events))):
        return _finish(result, "unresolved", "recovery_unsettled")
    if net <= 0:
        return _finish(result, "not_blunder", "material_recovered", complete=True)
    minimum = min(values[chess.BISHOP], values[chess.KNIGHT])
    if net < minimum:
        return _finish(result, "not_blunder", "below_major_loss", "The retained difference is below one configured minor piece; bad trades are outside V1.", complete=True)
    allowance = policy.recovery_pawns * values[chess.PAWN]
    if recovered > allowance or material.promotions:
        return _finish(result, "unresolved", "substantial_compensation_or_promotion", "This is not an established essentially free loss.")
    if sum(c.victim_color == player and c.victim_type in MAJOR_PIECES for c in material.captures) != 1:
        return _finish(result, "unresolved", "multiple_major_losses", "Additional major losses require separate attribution.")
    if capture.value - recovered < minimum:
        return _finish(result, "unresolved", "target_loss_not_major", "Other losses cannot inflate this target's significance.")
    # Inspect every immediate alternative capture, not just the move actually played.
    root_recovery = replay.events[0].capture.value if replay.events[0].capture else 0
    if any(root_recovery + c.value > allowance for c in recoveries):
        return _finish(result, "unresolved", "alternative_material_recovery", "An unplayed legal major-piece capture needs compensation proof.")
    forcing = set()
    for ply in range(2, len(replay.events) + 1, 2):
        forcing.update(forcing_moves(replay.board_at(ply)))
        if ply > 2 and any(c.value > allowance for c in legal_recoveries(replay, ply)):
            return _finish(result, "unresolved", "later_material_recovery", "Further legal major-piece recovery remains unproved.")
    result = replace(result, unresolved_forcing_moves=tuple(sorted(forcing)))
    if forcing or (ea is not None and ea.mate_for_player is True):
        return _finish(result, "unresolved", "forcing_compensation_unproved", "Checks, promotions or cached mate evidence prevent a free-loss claim.")
    if len(continuation) < 2:
        return _finish(result, "unresolved", "missing_player_response")
    if replay.board_at().is_check():
        return _finish(result, "unresolved", "exchange_unsettled", "The bounded endpoint still has a check or relevant legal capture.")
    if witness is None:
        return _finish(result, "unresolved", "prior_loss_not_excluded", "No quiet direct-escape witness; an already doomed target is not called a new blunder.")
    return _finish(result, "confirmed", "avoidable_bounded_free_loss",
        f"{witness.san} instead avoided direct capture without hanging another major piece.",
        "Confirmed only within the supplied window; distant quiet compensation and long-term forced loss are not evaluated.", complete=True)
