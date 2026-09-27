"""Enumerate unplayed Fork geometry; compose V3.1 without persistence or engine ownership."""
from dataclasses import replace
import json
import chess
from analysis_results import HeavyResult
from analysis_settings import load_profile, identity
from analyze_forks_v31 import analyze_position, PROOF_SCOPE
from analyze_forks_v3 import POLICY
from candidate_lines import to_data
from tactic_screeners import is_light_fork_shape
from discovery_evidence import attach_settlements, compact, root_diagnostic


def discovery_identity(profile):
    return identity({"analyzer":"3.1", "profile":to_data(profile), "payoff":to_data(POLICY),
                     "proof_scope":PROOF_SCOPE,"discovery":"all_unplayed_geometry_v1","selection":"best_objective_verified_uci_tiebreak_v1"})


def analyze_single_move(row, lines, verification_lines=None, profile=None):
    """One canonical stored result per user move; retain every geometric proposal in the audit."""
    profile=profile or load_profile("normal_escalation")
    board=chess.Board(row["fen_before"])
    moves=sorted((m for m in board.legal_moves if m.uci()!=row["uci_played"]
                  and is_light_fork_shape(board,m,board.turn)),key=lambda m:m.uci())
    proposals=[]
    for move in moves:
        result=analyze_position(row,move.uci(),lines,verification_lines,profile)
        attach_settlements(result,row["color"],profile)
        proposals.append({"move_uci":move.uci(),"move_san":board.san(move),
                          "root_diagnostic":root_diagnostic(result,row["color"]),"result":to_data(result)})
    hits=[p for p in proposals if p["result"]["state"]=="candidate"]
    details={"discovery_identity":discovery_identity(profile),"proposals":proposals,
             "geometric_proposals":len(proposals),"reason":"all_unplayed_fork_geometry_examined"}
    if hits:
        def strength(p):
            admission=p["result"]["details"]["root_admission"]
            selected=next(line for line in admission["approved"]["lines"] if line["move_uci"]==p["move_uci"])
            score=selected["score"]["score_cp"]
            return -(score if row["color"]=="white" else -score) if score is not None else float("inf"),p["move_uci"]
        chosen=min(hits,key=strength)
        from tactical_opportunities import opportunity_from_dict
        op=opportunity_from_dict({"schema_version":1,**chosen["result"]["opportunity"]})
        payload={**chosen["result"]["candidate"],"detector_version":"3.1"}
        metadata=json.loads(payload["metadata_json"])
        metadata.update(analyzer_version="3.1",discovery_identity=details["discovery_identity"],
                        backbone_provenance=chosen["result"]["details"]["backbone_provenance"])
        payload["metadata_json"]=json.dumps(metadata,sort_keys=True)
        details["selected_move_uci"]=chosen["move_uci"]
        return HeavyResult("candidate",payload,compact(details),op)
    uncertain=any(p["result"]["state"] in {"ambiguous","error"} for p in proposals)
    details["classification"]="ambiguous" if uncertain else "rejected"
    # Existing schema has no ambiguity status: preserve retryability, never claim no-hit.
    return HeavyResult("error" if uncertain else "analyzed_no_hit",details=compact(details))
