"""Pin truth consensus is separate from optional branch annotations."""
from dataclasses import replace
from analysis_settings import identity
from candidate_lines import to_data
from tactical_opportunities import TacticalOutcome
from pin_analysis_settings import PinBackbonePolicy


def primary_signature(opportunity):
    # A check-led context pin and a supported causal pin are deliberately distinct.
    motifs = tuple((m.kind, str(m.attribution)) for m in opportunity.motifs
                   if m.primary or m.kind in {"absolute_pin", "relative_pin"})
    return identity({"motifs":motifs, "relationships":to_data(opportunity.relationships),
                     "constraint":opportunity.metadata.get("movement_constraint")})


def motif_consensus(results):
    hits = [r for r in results if r.state == "candidate"]
    primary = len(hits)==len(results) and bool(hits) and len({primary_signature(r.opportunity) for r in hits})==1
    annotations = [{"branch":i, "motifs":to_data(r.opportunity.motifs) if r.opportunity else [],
                    "state":r.state} for i,r in enumerate(results)]
    secondary = [tuple((m.kind,str(m.attribution)) for m in r.opportunity.motifs
                 if not m.primary and m.kind not in {"absolute_pin","relative_pin"}) for r in hits]
    return {"primary_motif_consensus":primary,"secondary_motif_variance":len(set(secondary))>1,
            "branch_motif_evidence":annotations}


def branch_consensus(results, policy=PinBackbonePolicy()):
    """Every branch must verify causal payoff; secondary annotations cannot veto it."""
    if any(r.state=="error" for r in results): return "error",None
    if not results or any(r.state=="ambiguous" for r in results): return "ambiguous",None
    hits=[r for r in results if r.state=="candidate"]
    if not hits: return "rejected",None
    consensus=motif_consensus(results)
    if not consensus["primary_motif_consensus"]: return "ambiguous",None
    if policy.motif_consensus=="all_motifs" and len({tuple((m.kind,str(m.attribution)) for m in r.opportunity.motifs) for r in hits})>1:
        return "ambiguous",None
    def payoff(result):
        op=result.opportunity
        return (identity(op.primary_outcome), str(op.payoff_timing), op.metadata["related_retained_material_cp"])
    chosen=min(hits,key=lambda r:(r.opportunity.metadata["related_retained_material_cp"],r.opportunity.proof.retained_material_gain_cp))
    changed=len({payoff(r) for r in hits})>1
    opportunity=replace(chosen.opportunity, metadata={**chosen.opportunity.metadata, **consensus})
    if changed:
        opportunity=replace(opportunity, primary_outcome=TacticalOutcome("win_material"),
            presentation=replace(opportunity.presentation,title="Win material",
                explanation="Approved continuations retain pin-related material with different payoffs. This representative line shows the smallest verified payoff."),
            metadata={**opportunity.metadata,"payoff_consensus":"varied","proof_is_representative":True})
    candidate={**(chosen.candidate or {}),"notes":opportunity.presentation.explanation}
    return "verified_payoff_changed" if changed else "verified",replace(chosen,candidate=candidate,opportunity=opportunity)
