"""Normalize stored target/payoff extensions without reconstructing proof."""
from .adapters import piece_label
from .models import FeedbackFact


def target_payoff_facts(opportunity):
    data=opportunity.metadata
    if data.get("realizable_scope")=="approved_counterplay_branches_v1":
        return counterplay_facts(data)
    if data.get("realizable_scope")!="observed_bounded_best_defense_line_only":
        return ()
    facts=[]
    targets=data.get("geometric_targets")
    if isinstance(targets,list):
        labels=[label for target in targets if (label:=piece_label(target))]
        if labels:facts.append(FeedbackFact("geometric_targets",(("targets",", ".join(labels)),),("tactical_opportunity.metadata.geometric_targets",)))
    captures=data.get("target_captures")
    if isinstance(captures,list):
        for capture in captures:
            if not isinstance(capture,dict):continue
            target=piece_label({"piece":capture.get("piece"),"square":capture.get("capture_square")})
            move=capture.get("move")
            if target and isinstance(move,str) and move:
                facts.append(FeedbackFact("realized_capture",(("move",move),("target",target)),("tactical_opportunity.metadata.target_captures",)))
    payoff=data.get("realized_payoff")
    if isinstance(payoff,dict) and opportunity.proof.score_pov in {"white","black"}:
        change,final=payoff.get("net_material_cp"),payoff.get("material_settled_cp")
        if type(change) is int and type(final) is int:
            facts.append(FeedbackFact("settled_payoff",(("change",str(change)),("balance",str(final)),("pov",opportunity.proof.score_pov)),
                                      ("tactical_opportunity.metadata.realized_payoff",)))
    return tuple(facts)


def counterplay_facts(data):
    """Describe all inspected branches; do not promote a representative capture into consensus."""
    facts = []
    labels = [label for target in data.get('geometric_targets', []) if (label := piece_label(target))]
    if labels:
        facts.append(FeedbackFact('geometric_targets', (('targets', ', '.join(labels)),),
                                  ('tactical_opportunity.metadata.geometric_targets',)))
    robustness = data.get('counterplay_robustness')
    if isinstance(robustness, dict):
        status = ('retained payoff agrees' if robustness.get('classification') in {'verified', 'verified_payoff_changed'}
                  else 'no robust retained payoff confirmed')
        facts.append(FeedbackFact('counterplay_status', (
            ('status', status), ('count', str(robustness['continuation_count_considered'])),
            ('settled', str(robustness['settled_continuation_count']))),
            ('tactical_opportunity.metadata.counterplay_robustness',)))
        material_range = robustness.get('material_gain_range')
        if material_range is not None:
            facts.append(FeedbackFact('counterplay_material_range',
                (('minimum', str(material_range[0])), ('maximum', str(material_range[1]))),
                ('tactical_opportunity.metadata.counterplay_robustness.material_gain_range',)))
    elif data.get('verification_reason'):
        facts.append(FeedbackFact('verification_status',
            (('reason', data['verification_reason'].replace('_', ' ')),),
            ('tactical_opportunity.metadata.verification_reason',)))
    return tuple(facts)
