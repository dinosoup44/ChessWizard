"""Single-move specialists; candidate/coverage writes belong to the crawler.

Never call legacy main(), analyze_position() (fork), save_*(), delete_*(),
clear_*(), or remove_old_*() paths. Cache-only authorization is defense in depth.
"""
from collections import Counter
from analysis_results import HeavyResult

import chess

import analyze_forks_v2 as fork_v2
import analyze_mates as mate_v3
from analysis_scout import validate_stored_move
from engine_cache import score_for_color
from analysis_engine import PositionAnalysisService
from analysis_safety import write_authorizer


FORK_ROW_FIELDS = (
    "move_id", "game_id", "ply_number", "move_number", "color", "san_played",
    "uci_played", "fen_before", "fen_after", "source", "source_game_id",
    "white_username", "black_username",
)


def fork_adapter(row, positions):
    result = fork_v2.analyze_single_move(tuple(row[key] for key in FORK_ROW_FIELDS),positions.position)
    if result is None:
        return HeavyResult("analyzed_no_hit",details={"reason":"fork_v2_validation_no_hit"})
    return HeavyResult("candidate",result["candidate"],{"reason":"fork_v2_verified", "outcome":result["outcome"]})


def mate_adapter(row, positions):
    evidence = []
    def analyze_fen(fen, color, depth):
        profiles = {mate_v3.QUICK_DEPTH:"tactic_quick_v1",mate_v3.VERIFY_DEPTH:"tactic_verify_v1"}
        cached = positions.position(fen,profiles[depth])
        score = score_for_color(cached,color)
        if score["score_type"] == "cp" and score["score_cp"] is None:
            raise ValueError("Engine returned no usable score")
        evidence.append({"cache_id":cached["cache_id"],"profile":profiles[depth],"mate_player_pov":score["mate"]})
        return {"mate_distance":score["mate"],"best_move_uci":cached["best_move_uci"],
                "best_move_san":cached["best_move_san"],"principal_variation":cached["principal_variation"]}
    result = mate_v3.analyze_single_move(row,analyze_fen)
    return HeavyResult("candidate" if result["candidate"] else "analyzed_no_hit",result["candidate"],
                       {"reason":result["reason"],"evidence":evidence})


def dispatch_heavy(definition, connection, engine, row, stats, *, position_service=None):
    """Return failures as retryable results; permit only engine-cache writes."""
    connection.set_authorizer(write_authorizer())
    try:
        validate_stored_move(row)
        positions = position_service if position_service is not None else PositionAnalysisService(connection,engine,stats)
        result = definition.heavy(row,positions)
        if result.state not in {"candidate","analyzed_no_hit","error"}:
            raise ValueError("Invalid heavy result state")
        if result.state == "candidate":
            payload = result.candidate
            if not payload or not payload.get("solution_line"):
                raise ValueError("Candidate is missing a solution")
            board = chess.Board(row["fen_before"])
            move = chess.Move.from_uci(payload["solution_move_uci"])
            if move not in board.legal_moves or board.san(move) != payload["solution_move_san"]:
                raise ValueError("Candidate solution move is invalid")
            if str(payload["detector_version"]) != definition.analyzer_version:
                raise ValueError("Adapter/registry analyzer versions disagree")
        return result
    except Exception as exc:
        return HeavyResult("error",details={"error_type":type(exc).__name__,"message":str(exc)})
    finally:
        connection.set_authorizer(None)
