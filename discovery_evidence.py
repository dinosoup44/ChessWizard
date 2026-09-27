"""Compact audit references and branch settlement for discovery results; no I/O."""
from candidate_lines import to_data
from settlement_provenance import branch_settlement_summary


def compact(value):
    """Keep exact raw-cache references instead of embedding the same MultiPV payload repeatedly."""
    if isinstance(value,(tuple,list)): return [compact(v) for v in value]
    if not isinstance(value,dict): return value
    if {"fen","engine_identity","lines"}<=value.keys():
        return {"cache_reference":{"fen":value["fen"],"engine_identity":value["engine_identity"]},
                "comparison_sources":value.get("generation_metadata",{}).get("source_request_identities",[])}
    return {k:compact(v) for k,v in value.items() if k not in {"proof_steps"}}


def attach_settlements(result, player, profile):
    """Normalize already computed proof ledgers without searching or changing the verdict."""
    for index, branch in enumerate(result.details.get("branches", [])):
        summary = branch_settlement_summary(result.details, index, player, profile)
        if summary is not None:
            branch["settlement_evidence"] = summary



def root_diagnostic(result, player):
    admission=result.details.get("root_admission",{})
    root=admission.get("root",{}); approved=admission.get("approved",{})
    move=admission.get("required_move")
    selected=next((r for r in approved.get("lines",[]) if r["move_uci"]==move),None)
    decision=next((d for d in approved.get("decisions",[]) if d["move_uci"]==move),None)
    return {"native_rank":admission.get("native_rank"),"supplemented":admission.get("supplemented"),
            "root_lines":[{k:line[k] for k in ("rank","move_uci","move_san","score")} for line in root.get("lines",[])],
            "selected_score":selected.get("score") if selected else None,"gate_decision":decision,
            "forced_deterioration":result.details.get("forced_deterioration",False)}
