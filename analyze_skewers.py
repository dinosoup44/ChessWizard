"""Skewer V1 single-position calculation; no database, engine lifecycle or crawl."""
from dataclasses import asdict
import json
import chess
from analysis_results import HeavyResult
from analysis_scout import validate_stored_move
from board_analysis import material_balance
from engine_cache import score_for_color
from skewer_geometry import PIECE_VALUES, skewering_moves
from skewer_attribution import attribute_skewer
from skewer_opportunities import skewer_opportunity
from tactical_proof import ProofWindow, validate_evaluation, verify_bounded_line

ANALYZER_VERSION = "1"
QUICK_PROFILE = "tactic_quick_v1"
VERIFY_PROFILE = "tactic_verify_v1"
QUICK_MIN_GAIN_CP = 120
QUICK_MAX_DROP_CP = 300
VERIFY_MIN_GAIN_CP = 150
VERIFY_MAX_DROP_CP = 200
MIN_RETAINED_MATERIAL_CP = 100
MIN_FINAL_EVAL_CP = -100
PROOF_WINDOW = ProofWindow()


def analyze_single_move(row, analyze_fen):
    validate_stored_move(row)
    board = chess.Board(row["fen_before"])
    color = board.turn
    choices = tuple(skewering_moves(board,row["uci_played"]))
    if not choices:
        return HeavyResult("analyzed_no_hit",details={"reason":"no_new_direct_skewer"})
    cached,evidence,rejected = {},[],[]

    def evaluate(fen,profile):
        key = (fen,profile)
        if key not in cached:
            raw = validate_evaluation(analyze_fen(fen,profile))
            score = score_for_color(raw,color)
            cached[key] = (score["score_cp"],raw)
            evidence.append({"cache_id":raw.get("cache_id"),"profile":profile,**score})
        return cached[key]

    def no_hit(reason,**details):
        return HeavyResult("analyzed_no_hit",details={"reason":reason,"rejections":rejected,
            "evidence":evidence,"proof_policy":asdict(PROOF_WINDOW),**details})

    def mate_exit(before_raw,played_raw):
        before = score_for_color(before_raw,color)
        played = score_for_color(played_raw,color)
        return no_hit("mate_score_deferred",ownership="missed_mate" if before["score_type"]=="mate" and before["mate"]>0 else "mate_or_saving_tactic_review",
                      before=before,played=played,
                      deferred_motifs=[{"kind":"skewer","attribution":"context_only",
                          "rationale":"Plausible geometry only; mate ownership and the mating mechanism require the mate specialist."}])

    before_q,before_raw = evaluate(row["fen_before"],QUICK_PROFILE)
    played_q,played_raw = evaluate(row["fen_after"],QUICK_PROFILE)
    if before_q is None or played_q is None:
        return mate_exit(before_raw,played_raw)
    promising = []
    for choice in choices:
        value,raw = evaluate(choice.fen_after,QUICK_PROFILE)
        if value is None:
            rejected.append({"move_uci":choice.move_uci,"reason":"mate_alternative_deferred","ownership":"mate_review"})
        elif value-played_q >= QUICK_MIN_GAIN_CP and before_q-value <= QUICK_MAX_DROP_CP:
            promising.append(choice)
        else:
            rejected.append({"move_uci":choice.move_uci,"reason":"insufficient_quick_gain",
                             "gain_cp":value-played_q,"drop_from_best_cp":before_q-value})
    if not promising:
        return no_hit("no_meaningful_quick_gain")
    before,before_raw = evaluate(row["fen_before"],VERIFY_PROFILE)
    played,played_raw = evaluate(row["fen_after"],VERIFY_PROFILE)
    if before is None or played is None:
        return mate_exit(before_raw,played_raw)
    initial = material_balance(board,color,PIECE_VALUES)
    verified = []
    for choice in promising:
        value,raw = evaluate(choice.fen_after,VERIFY_PROFILE)
        if value is None or value-played < VERIFY_MIN_GAIN_CP or before-value > VERIFY_MAX_DROP_CP:
            rejected.append({"move_uci":choice.move_uci,"reason":"mate_alternative_deferred" if value is None else "insufficient_deep_gain"})
            continue
        after = chess.Board(choice.fen_after)
        proof = verify_bounded_line(after,color,lambda fen:evaluate(fen,VERIFY_PROFILE)[1],PIECE_VALUES,PROOF_WINDOW)
        if proof.state != "stable":
            rejected.append({"move_uci":choice.move_uci,"reason":f"proof_{proof.state}",
                             "ownership":"mate_review" if proof.state=="mate" else None,
                             "proof_line_san":" ".join([choice.move_san,*(s.san for s in proof.steps)])})
            continue
        final_score = score_for_color(proof.final_evidence,color)["score_cp"]
        final = material_balance(chess.Board(proof.final_fen),color,PIECE_VALUES)
        retained = min(final-initial,final-material_balance(after,color,PIECE_VALUES))
        evaluation_ok = (final_score >= MIN_FINAL_EVAL_CP and final_score-played >= VERIFY_MIN_GAIN_CP
                         and before-final_score <= VERIFY_MAX_DROP_CP)
        scores = {"before":before,"played":played,"tactic":value,"final":final_score}
        for skewer in choice.skewers:
            attribution = attribute_skewer(after,skewer,proof)
            resolution = attribution.resolution
            reason = ("material_not_retained" if retained < MIN_RETAINED_MATERIAL_CP else
                      "rear_payoff_not_proven" if not resolution.rear_captured else
                      "related_material_not_retained" if resolution.related_material_cp < MIN_RETAINED_MATERIAL_CP else
                      "front_resolution_not_compelling" if attribution.kind != "supported" else
                      "continuation_not_sustained" if not evaluation_ok else "skewer_v1_material_verified")
            summary = {"move_uci":choice.move_uci,"skewer_type":skewer.skewer_type,
                       "front_square":chess.square_name(skewer.line.front.square),"rear_square":chess.square_name(skewer.line.rear.square),
                       "reason":reason,"attribution":asdict(attribution),"retained_material_cp":retained,
                       "evaluation_player_cp":scores,"proof_line_san":" ".join([choice.move_san,*(s.san for s in proof.steps)])}
            if reason != "skewer_v1_material_verified":
                rejected.append(summary)
                continue
            opportunity = skewer_opportunity(row,choice,skewer,proof,attribution,scores,initial,final)
            payload = {"candidate_status":"candidate","confidence":0.9,"detector_version":1,
                       "solution_move_uci":choice.move_uci,"solution_move_san":choice.move_san,
                       "solution_line":opportunity.proof.line_san,"notes":opportunity.presentation.explanation,
                       "metadata_json":json.dumps({"analyzer":"missed_skewer","analyzer_version":ANALYZER_VERSION,
                                                   "proof_policy":asdict(PROOF_WINDOW)},sort_keys=True)}
            verified.append((value,retained,choice.move_uci,payload,opportunity,summary))
    if not verified:
        return no_hit("skewer_v1_proof_not_met")
    _,_,_,payload,opportunity,summary = max(verified,key=lambda item:item[:3])
    return HeavyResult("candidate",payload,{"reason":"skewer_v1_material_verified","selected":summary,
        "verified_alternatives":[v[5] for v in verified],"rejections":rejected,
        "evidence":evidence,"proof_policy":asdict(PROOF_WINDOW)},opportunity)
