"""Shallow missed-gain filter; never a final motif classifier."""
from analysis_scout import ScoutResult, scout_config

SCOUT_VERSION = "1"
MIN_LOSS_CP = 80


def xray_scout_config():
    return scout_config(min_loss_cp=MIN_LOSS_CP, retain_mate_scores=True,
                        comparison="best_before_vs_played_same_player",
                        geometry="new_direct_slider_xray_v1")


def scout_xray(row, evidence):
    before, played = evidence.for_player(row), evidence.for_player(row, after=True)
    if before["score_type"] == "mate" or played["score_type"] == "mate":
        return ScoutResult(True, "mate_score_needs_specialist")
    send = before["score_cp"] - played["score_cp"] >= MIN_LOSS_CP
    return ScoutResult(send, "possible_xray_gain" if send else "small_shallow_loss")
