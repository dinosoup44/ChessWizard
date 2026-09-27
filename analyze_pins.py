"""Conservative Pin V1 single-position calculation. No DB/engine lifecycle/I/O.

The evaluator callback is supplied by the adapter's shared position service.
Only a newly created pin with an immediate related capture, retained material,
and depth-18 superiority over the played move can become a candidate.
"""
from collections import Counter
from dataclasses import asdict
import json
import chess
from analysis_results import HeavyResult
from analysis_scout import validate_stored_move
from board_analysis import capture_square, material_balance
from engine_cache import score_for_color
from pin_geometry import PIECE_VALUES, pinning_moves, pins_from

ANALYZER_VERSION = "1"
QUICK_PROFILE = "tactic_quick_v1"
VERIFY_PROFILE = "tactic_verify_v1"
QUICK_MIN_GAIN_CP = 120
QUICK_MAX_DROP_CP = 300
VERIFY_MIN_GAIN_CP = 150
VERIFY_MAX_DROP_CP = 200
MIN_RETAINED_MATERIAL_CP = 100
MIN_FINAL_EVAL_CP = -100


def related_capture(after_pin, pin, pv):
    """Legal best reply then related capture; return proof prefix or None.

    Pinned-piece capture must occur while that pin still exists. Alternatively,
    a relative-pin blocker moves away and the original pinner takes the target.
    Illegal supplied PV is a failure; a short/irrelevant PV is insufficient proof.
    """
    tokens = (pv or "").split()
    if len(tokens) < 2:
        return None
    board = after_pin.copy(stack=False)
    reply = board.parse_san(tokens[0])
    if capture_square(board, reply) == pin.attacker.square:
        return None
    pinned_square = reply.to_square if reply.from_square == pin.pinned.square else pin.pinned.square
    board.push(reply)
    capture = board.parse_san(tokens[1])
    captured_square = capture_square(board, capture)
    active = any(p.pinned.square == pinned_square and p.behind == pin.behind
                 and p.pinned.piece_type == pin.pinned.piece_type
                 for p in pins_from(board, pin.attacker.square))
    if active and captured_square == pinned_square:
        consequence = "wins_pinned_piece"
    elif (pin.pin_type == "relative" and reply.from_square == pin.pinned.square
          and capture.from_square == pin.attacker.square and captured_square == pin.behind.square):
        consequence = "blocker_moves_target_lost"
    else:
        return None
    captured = board.piece_at(captured_square)
    if captured is None or captured.color == pin.attacker.color:
        return None
    sans = [after_pin.san(reply), board.san(capture)]
    board.push(capture)
    return board, sans, consequence, {"square":chess.square_name(captured_square), "piece":chess.piece_name(captured.piece_type)}


def analyze_single_move(row, analyze_fen):
    validate_stored_move(row)
    board = chess.Board(row["fen_before"])
    color = board.turn
    choices = tuple(pinning_moves(board, row["uci_played"]))
    if not choices:
        return HeavyResult("analyzed_no_hit", details={"reason":"no_new_direct_pin"})
    evidence = []

    def evaluate(fen, profile):
        raw = analyze_fen(fen, profile)
        if raw.get("score_pov") != "white":
            raise ValueError("Pin analysis requires White-POV engine evidence")
        score = score_for_color(raw, color)
        if score["score_type"] not in {"cp", "mate"}:
            raise ValueError("Unusable engine score")
        evidence.append({"cache_id":raw.get("cache_id"), "profile":profile, "fen":fen, **score})
        return score["score_cp"], raw

    before_quick, _ = evaluate(row["fen_before"], QUICK_PROFILE)
    played_quick, _ = evaluate(row["fen_after"], QUICK_PROFILE)
    if before_quick is None or played_quick is None:
        return HeavyResult("analyzed_no_hit", details={"reason":"mate_score_outside_pin_v1"})
    promising = []
    for choice in choices:
        value, _ = evaluate(choice.fen_after, QUICK_PROFILE)
        if value is not None and value - played_quick >= QUICK_MIN_GAIN_CP and before_quick - value <= QUICK_MAX_DROP_CP:
            promising.append(choice)
    if not promising:
        return HeavyResult("analyzed_no_hit", details={"reason":"no_meaningful_quick_gain"})
    before, _ = evaluate(row["fen_before"], VERIFY_PROFILE)
    played, _ = evaluate(row["fen_after"], VERIFY_PROFILE)
    if before is None or played is None:
        return HeavyResult("analyzed_no_hit", details={"reason":"mate_score_outside_pin_v1"})
    initial_material = material_balance(board, color, PIECE_VALUES)
    verified, rejected = [], Counter()
    for choice in promising:
        value, raw = evaluate(choice.fen_after, VERIFY_PROFILE)
        if value is None or value - played < VERIFY_MIN_GAIN_CP or before - value > VERIFY_MAX_DROP_CP:
            rejected["insufficient_deep_gain"] += 1
            continue
        after_pin = chess.Board(choice.fen_after)
        after_pin_material = material_balance(after_pin, color, PIECE_VALUES)
        for pin in choice.pins:
            proof = related_capture(after_pin, pin, raw.get("principal_variation"))
            if proof is None:
                rejected["no_immediate_pin_related_capture"] += 1
                continue
            after_capture, sans, consequence, captured = proof
            capture_value, capture_raw = evaluate(after_capture.fen(), VERIFY_PROFILE)
            if capture_value is None:
                rejected["mate_score_outside_pin_v1"] += 1
                continue
            response = (capture_raw.get("principal_variation") or "").split()
            if not response:
                rejected["missing_defensive_reply"] += 1
                continue
            best_reply = after_capture.parse_san(response[0])
            response_san = after_capture.san(best_reply)
            final = after_capture.copy(stack=False)
            final.push(best_reply)
            material = material_balance(final, color, PIECE_VALUES)
            gain = material - initial_material
            pin_gain = material - after_pin_material
            if min(gain, pin_gain) < MIN_RETAINED_MATERIAL_CP:
                rejected["material_not_retained"] += 1
                continue
            final_value, _ = evaluate(final.fen(), VERIFY_PROFILE)
            if (final_value is None or final_value < MIN_FINAL_EVAL_CP
                    or final_value - played < VERIFY_MIN_GAIN_CP or before - final_value > VERIFY_MAX_DROP_CP):
                rejected["continuation_not_sustained"] += 1
                continue
            metadata = {
                "analyzer":"missed_pin", "analyzer_version":ANALYZER_VERSION,
                "pin":asdict(pin), "pin_type":pin.pin_type,
                "squares":{"attacker":chess.square_name(pin.attacker.square),
                           "pinned":chess.square_name(pin.pinned.square),"behind":chess.square_name(pin.behind.square)},
                "classification":consequence, "captured":captured,
                "pinning_move_uci":choice.move_uci, "pinning_move_san":choice.move_san,
                "played_move_uci":row["uci_played"], "player_color":row["color"],
                "evaluation_player_cp":{"before":before,"played":played,"pin":value,
                                         "after_capture":capture_value,"after_best_reply":final_value},
                "gain_over_played_cp":value-played, "retained_material_gain_cp":gain,
                "gain_since_pin_cp":pin_gain, "fen_after_proof":final.fen(),
                "proof_line_san":" ".join([choice.move_san,*sans,response_san]),
                "proof_scope":"depth18_best_replies_immediate_capture_not_exhaustive",
            }
            payload = {"candidate_status":"candidate","confidence":0.9,"detector_version":1,
                       "solution_move_uci":choice.move_uci,"solution_move_san":choice.move_san,
                       "solution_line":metadata["proof_line_san"],
                       "notes":f"Missed Pin: {chess.piece_name(pin.attacker.piece_type)} pins the {chess.piece_name(pin.pinned.piece_type)} to the {chess.piece_name(pin.behind.piece_type)}; the verified line retains material.",
                       "metadata_json":json.dumps(metadata,sort_keys=True)}
            verified.append((value,gain,choice.move_uci,payload,metadata))
    if not verified:
        return HeavyResult("analyzed_no_hit", details={"reason":"pin_v1_proof_not_met","rejections":dict(rejected),"evidence":evidence})
    _, _, _, payload, metadata = max(verified, key=lambda v:(v[0],v[1],v[2]))
    return HeavyResult("candidate",payload,{"reason":"pin_v1_material_verified", "classification":metadata["classification"],"evidence":evidence})
