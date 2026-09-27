"""Pin V2 single-position specialist. V1 remains in analyze_pins.py unchanged."""
from dataclasses import asdict
from analysis_settings import VERIFICATION_GENERATOR
from pin_analysis_settings import PinPolicy
import json
import chess

from analysis_results import HeavyResult
from analysis_scout import validate_stored_move
from board_analysis import material_balance
from engine_cache import score_for_color
from pin_geometry import PIECE_VALUES, pinning_moves, pins_from
from pin_attribution import attribute_pin
from pin_opportunities import pin_opportunity
from tactical_opportunities import opportunity_to_dict
from tactical_proof import ProofWindow, validate_evaluation, verify_bounded_line


ANALYZER_VERSION = "2"
QUICK_PROFILE = "tactic_quick_v1"
VERIFY_PROFILE = "tactic_verify_v1"
DEFAULT_POLICY = PinPolicy()
QUICK_MIN_GAIN_CP = DEFAULT_POLICY.quick_min_gain_cp
QUICK_MAX_DROP_CP = DEFAULT_POLICY.quick_max_drop_cp
VERIFY_MIN_GAIN_CP = DEFAULT_POLICY.verify_min_gain_cp
VERIFY_MAX_DROP_CP = DEFAULT_POLICY.verify_max_drop_cp
MIN_RETAINED_MATERIAL_CP = DEFAULT_POLICY.min_retained_material_cp
MIN_FINAL_EVAL_CP = DEFAULT_POLICY.min_final_eval_cp
PROOF_WINDOW = DEFAULT_POLICY.proof_window


def analyze_single_move(row, analyze_fen, *, choices=None, proof_solver=verify_bounded_line,
                        policy=DEFAULT_POLICY, proof_depth=VERIFICATION_GENERATOR.engine.depth):
    """Calculate V2 semantics with injected evidence/proof; never persist results."""
    validate_stored_move(row)
    board = chess.Board(row["fen_before"])
    color = board.turn
    choices = tuple(pinning_moves(board, row["uci_played"])) if choices is None else tuple(choices)
    window = policy.proof_window
    if not choices:
        return HeavyResult("analyzed_no_hit", details={"reason": "no_new_direct_pin"})
    cached, evidence, rejected, notes = {}, [], [], []

    def evaluate(fen, profile):
        key = (fen, profile)
        if key not in cached:
            raw = validate_evaluation(analyze_fen(fen, profile))
            score = score_for_color(raw, color)
            cached[key] = (score["score_cp"], raw)
            evidence.append({"cache_id": raw.get("cache_id"), "profile": profile, **score})
        return cached[key]

    def no_hit(reason, **details):
        return HeavyResult("analyzed_no_hit", details={"reason": reason, "rejections": rejected,
            "annotations": notes, "evidence": evidence, "proof_policy": asdict(window), **details})

    def mate_exit(before_raw, played_raw):
        before = score_for_color(before_raw, color)
        played = score_for_color(played_raw, color)
        owner = "missed_mate" if before["score_type"] == "mate" and before["mate"] > 0 else "mate_or_saving_tactic_review"
        return no_hit("mate_score_deferred", ownership=owner, before=before, played=played,
                      explanation="Pin V2 does not create mate/save candidates; no conversion of mate to centipawns or implied avoidance proof.")

    before_q, before_raw = evaluate(row["fen_before"], QUICK_PROFILE)
    played_q, played_raw = evaluate(row["fen_after"], QUICK_PROFILE)
    if before_q is None or played_q is None:
        return mate_exit(before_raw, played_raw)
    promising = []
    for choice in choices:
        value, raw = evaluate(choice.fen_after, QUICK_PROFILE)
        if value is None:
            rejected.append({"move_uci": choice.move_uci, "reason": "mate_alternative_deferred"})
        elif value - played_q >= policy.quick_min_gain_cp and before_q - value <= policy.quick_max_drop_cp:
            promising.append(choice)
        else:
            rejected.append({"move_uci": choice.move_uci, "reason": "insufficient_quick_gain",
                             "gain_cp": value - played_q, "drop_from_best_cp": before_q - value})
    if not promising:
        return no_hit("no_meaningful_quick_gain")
    before, before_raw = evaluate(row["fen_before"], VERIFY_PROFILE)
    played, played_raw = evaluate(row["fen_after"], VERIFY_PROFILE)
    if before is None or played is None:
        return mate_exit(before_raw, played_raw)
    initial = material_balance(board, color, PIECE_VALUES)
    verified = []
    for choice in promising:
        value, raw = evaluate(choice.fen_after, VERIFY_PROFILE)
        if value is None or value - played < policy.verify_min_gain_cp or before - value > policy.verify_max_drop_cp:
            rejected.append({"move_uci": choice.move_uci, "reason": "insufficient_deep_gain" if value is not None else "mate_alternative_deferred",
                             "gain_cp": value - played if value is not None else None,
                             "drop_from_best_cp": before - value if value is not None else None})
            continue
        after = chess.Board(choice.fen_after)
        proof = proof_solver(after, color, lambda fen: evaluate(fen, VERIFY_PROFILE)[1], PIECE_VALUES, window)
        if proof.state != "stable":
            rejected.append({"move_uci": choice.move_uci, "reason": f"proof_{proof.state}",
                             "proof_line_san": " ".join([choice.move_san, *(s.san for s in proof.steps)])})
            continue
        final_score = score_for_color(proof.final_evidence, color)["score_cp"]
        final = material_balance(chess.Board(proof.final_fen), color, PIECE_VALUES)
        gain = min(final - initial, final - material_balance(after, color, PIECE_VALUES))
        evaluation_ok = (final_score >= policy.min_final_eval_cp and final_score - played >= policy.verify_min_gain_cp
                         and before - final_score <= policy.verify_max_drop_cp)
        for pin in choice.pins:
            attribution = attribute_pin(after, pin, proof)
            score_values = {"before": before, "played": played, "tactic": value, "final": final_score}
            tactical = (gain >= policy.min_retained_material_cp and attribution.related_material_cp >= policy.min_retained_material_cp
                        and attribution.kind in {"supported", "check_led"} and evaluation_ok)
            reason = ("material_not_retained" if gain < policy.min_retained_material_cp else
                      "related_material_not_retained" if attribution.related_material_cp < policy.min_retained_material_cp else
                      "causality_not_supported" if attribution.kind not in {"supported", "check_led"} else
                      "continuation_not_sustained" if not evaluation_ok else "pin_v2_material_verified")
            summary = {"move_uci": choice.move_uci, "pin_type": pin.pin_type,
                       "pinned_square": chess.square_name(pin.pinned.square), "reason": reason,
                       "attribution": asdict(attribution), "retained_material_cp": gain,
                       "evaluation_player_cp": score_values,
                       "proof_line_san": " ".join([choice.move_san, *(s.san for s in proof.steps)])}
            if not tactical:
                rejected.append(summary)
                # Only quiet, still-present relationships become positional notes.
                # A transient or unrelated material sequence is simply a no-hit.
                quiet = not any(s.captured_piece for s in proof.steps)
                pin_remains = any(p.pinned == pin.pinned and p.behind == pin.behind
                                  for p in pins_from(chess.Board(proof.final_fen), pin.attacker.square))
                if quiet and pin_remains and evaluation_ok:
                    note = pin_opportunity(row, choice, pin, proof, attribution, score_values, initial, final, tactical=False, proof_depth=proof_depth)
                    notes.append(opportunity_to_dict(note))
                elif (reason == "causality_not_supported" and evaluation_ok and pin.attacker.piece_type == chess.ROOK
                      and attribution.captured_piece == "pawn"):
                    note = pin_opportunity(row, choice, pin, proof, attribution, score_values, initial, final,
                                           tactical=False, material_context=True, proof_depth=proof_depth)
                    notes.append(opportunity_to_dict(note))
                continue
            opportunity = pin_opportunity(row, choice, pin, proof, attribution, score_values, initial, final, tactical=True, proof_depth=proof_depth)
            payload = {"candidate_status": "candidate", "confidence": 0.9, "detector_version": 2,
                       "solution_move_uci": choice.move_uci, "solution_move_san": choice.move_san,
                       "solution_line": opportunity.proof.line_san, "notes": opportunity.presentation.explanation,
                       "metadata_json": json.dumps({"analyzer": "missed_pin", "analyzer_version": ANALYZER_VERSION,
                                                    "proof_policy": asdict(window)}, sort_keys=True)}
            verified.append((value, gain, choice.move_uci, payload, opportunity, summary))
    if not verified:
        return no_hit("pin_v2_proof_not_met")
    _, _, _, payload, opportunity, summary = max(verified, key=lambda item: item[:3])
    return HeavyResult("candidate", payload, {"reason": "pin_v2_material_verified", "selected": summary,
        "verified_alternatives": [v[5] for v in verified],
        "rejections": rejected, "evidence": evidence, "proof_policy": asdict(window)}, opportunity)
