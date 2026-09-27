"""X-ray V1 single-position specialist composed from shared proof services."""
from dataclasses import asdict
import json
import chess
from analysis_results import HeavyResult
from analysis_scout import validate_stored_move
from tactical_material import EvaluationSession, MaterialPolicy, MateEvidence, assess_material_move
from xray_geometry import PIECE_VALUES, xray_moves
from xray_attribution import attribute_xray
from xray_opportunities import xray_opportunity

ANALYZER_VERSION = "1"
POLICY = MaterialPolicy()


def analyze_single_move(row, analyze_fen):
    validate_stored_move(row)
    board = chess.Board(row["fen_before"])
    session = EvaluationSession(analyze_fen, board.turn)
    rejections, verified = [], []
    for choice in xray_moves(board, row["uci_played"]):
        try:
            assessment = assess_material_move(row, choice, session, PIECE_VALUES, POLICY)
        except MateEvidence as exc:
            # Baseline mate scores own the whole position; alternative/proof
            # mates also defer conservatively rather than choosing another label.
            return HeavyResult("analyzed_no_hit", details={"reason":"mate_score_deferred",
                "ownership":"mate_review", "score":exc.score,
                "deferred_motifs":[{"kind":"xray", "attribution":"context_only"}]})
        base = {"move_uci":choice.move_uci, "scores":assessment.scores}
        if assessment.reason == "proof_mate":
            return HeavyResult("analyzed_no_hit", details={"reason":"mate_score_deferred",
                "ownership":"mate_review", "deferred_motifs":[{"kind":"xray", "attribution":"context_only"}]})
        if assessment.reason != "material_verified":
            rejections.append({**base, "reason":assessment.reason})
            continue
        for line in choice.lines:
            attribution = attribute_xray(line, assessment.proof)
            detail = {**base, "line":asdict(line), "attribution":asdict(attribution),
                      "retained_material_cp":assessment.retained_cp}
            if attribution.kind != "supported":
                rejections.append({**detail, "reason":"xray_causality_not_supported"})
                continue
            opportunity = xray_opportunity(row, choice, line, assessment, attribution)
            verified.append((assessment.scores["deep"]["tactic"], assessment.retained_cp, choice.move_uci,
                             opportunity, {**detail, "reason":"xray_v1_material_verified"}))
    details = {"rejections":rejections, "evidence":session.evidence, "proof_policy":asdict(POLICY)}
    if not verified:
        return HeavyResult("analyzed_no_hit", details={"reason":"xray_v1_proof_not_met", **details})
    _, _, _, opportunity, selected = max(verified, key=lambda v:v[:3])
    payload = {"candidate_status":"candidate", "confidence":0.9, "detector_version":1,
        "solution_move_uci":opportunity.proof.tactical_move_uci,
        "solution_move_san":board.san(chess.Move.from_uci(opportunity.proof.tactical_move_uci)),
        "solution_line":opportunity.proof.line_san, "notes":opportunity.presentation.explanation,
        "metadata_json":json.dumps({"analyzer":"missed_xray", "analyzer_version":ANALYZER_VERSION})}
    return HeavyResult("candidate", payload, {"reason":"xray_v1_material_verified", "selected":selected, **details}, opportunity)
