"""Read completed replay artifacts and summarize verdicts without rerunning chess analysis."""
from collections import Counter
from pathlib import Path
import json

R = Path(__file__).resolve().parent
P = 'fork_first_500'


def details(value: dict) -> dict:
    """Read the structured analyzer details from a supplied result wrapper.

    Args:
        value: Supplied wrapped result.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    return value['result']['details']
def classification(value: dict) -> str:
    """Read the supplied verdict without deriving a new chess conclusion.

    Args:
        value: Supplied wrapped result.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    return details(value)['classification']


def ambiguity_causes(value: dict) -> list[str]:
    """Separate exhausted bounds from genuine disagreement in retained evidence.

    Args:
        value: Supplied wrapped result.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    d = details(value)
    if d['classification'] != 'ambiguous': return []
    branches = d.get('branches', [])
    causes = set()
    attempts = d.get('escalation_attempts', [])
    if d['reason'] == 'acceptable_continuations_disagree':
        causes.add('genuine_settled_disagreement')
    if d.get('terminal') or any(b.get('ownership') == 'mate' or b.get('proof_state') in ('terminal','deferred') for b in branches):
        causes.add('mate_or_terminal_deferral')
    for a in attempts:
        branch = branches[a['branch_index']]
        if a['status'] == 'budget_exhausted' and branch['proof_state'] != 'stable':
            causes.add({'branch_limit':'branch_limit_constrained','verification_request_limit':'request_limit_constrained',
                'child_depth_limit':'child_depth_constrained'}.get(a['reason'],a['reason']))
    for i,b in enumerate(branches):
        if b['proof_state'] != 'unsettled': continue
        latest = next((a['proof'] for a in reversed(attempts) if a['branch_index']==i and a.get('proof')),None)
        if latest:
            maximum = 2*latest['window']['user_moves']+1+latest['window']['settlement_plies']
            if len(latest['steps'])==maximum: causes.add('settlement_window_exhausted')
        elif b.get('proof_line'):
            maximum = 1+2*d['profile']['proof']['user_moves']+1+d['profile']['proof']['settlement_plies']
            if len(b['proof_line'].split())==maximum: causes.add('settlement_window_exhausted')
    if any(b.get('critical_fallback') for b in branches): causes.add('critical_fallback_causality_uncertain')
    return sorted(causes or {d['reason']})


def metrics(values: list[dict]) -> dict:
    """Summarize only the supplied population and its nonexclusive ambiguity causes.

    Args:
        values: Supplied result population.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    result = dict(entries=len(values), classifications=dict(Counter(classification(x) for x in values)),
        gate=dict(Counter('not_reached' if details(x).get('root_move_passes_gate') is None else
             'admitted' if details(x)['root_move_passes_gate'] else 'rejected' for x in values)),
        rank=dict(Counter(str(x['root_diagnostic'].get('native_rank') or 'outside_top_3')
            if details(x).get('root_admission') else 'not_reached' for x in values)))
    causes=Counter();scale=Counter();escalated=0;resolved=0;complete=0;terminal=0
    for value in values:
        d=details(value);causes.update(ambiguity_causes(value))
        branches=d.get('branches',[])
        complete += bool(branches) and all(b['proof_state'] in ('stable','terminal') for b in branches)
        terminal += bool(d.get('terminal') or any(b.get('ownership')=='mate' or b['proof_state'] in ('terminal','deferred') for b in branches))
        if d.get('escalation', {}).get('branches_escalated', 0) > 0:
            escalated+=1
            resolved+=d['normal_robustness']['classification']=='ambiguous' and d['classification']!='ambiguous'
        weight=next((w['interest_weight'] for w in d.get('root_scale',[]) if w['move_uci']==value['move']),None)
        scale['not_computed' if weight is None else str(int(weight//20)*20)+'..'+str(int(weight//20)*20+20)]+=1
    result.update(ambiguity_causes_nonexclusive=dict(causes),proof_complete=complete,mate_terminal_deferrals=terminal,
        escalated_proposals=escalated,escalation_resolved=resolved,escalation_resolution_rate=resolved/escalated if escalated else None,
        scale_bands=dict(scale))
    return result


def branch_chess(value: dict) -> dict:
    """Project chess facts separately from profile and provenance metadata.

    Args:
        value: Supplied wrapped result.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    d=details(value)
    keys=('opponent_move_uci','player_move_uci','proof_state','state','classification','proof_line','final_fen',
        'material_gain_cp','retained_related_cp','final_player_cp','payoff_signature','realizable_target_squares')
    return dict(classification=d['classification'],root_gate=d.get('root_move_passes_gate'),
        root_diagnostic=value['root_diagnostic'],branches=[{k:b.get(k) for k in keys} for b in d.get('branches',[])])


def comparison(a: list[dict], b: list[dict]) -> dict:
    """Compare paired result sets without counting a changed policy as new engine evidence.

    Args:
        a: Baseline result sequence.
        b: Paired selective result sequence.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    result=Counter();changed=[]
    for key,left in a.items():
        if key not in b: continue
        right=b[key];d=details(right)
        eligible=any(x['eligible'] for x in d.get('settlement_extension_eligibility',[]))
        extensions=[x for x in d.get('escalation_attempts',[]) if x.get('evidence_stage')=='selective_settlement_extension']
        result['paired']+=1;result['eligible_proposals']+=eligible;result['extension_attempts']+=len(extensions)
        result['root_admission_changes']+=left['root_diagnostic']!=right['root_diagnostic'] or details(left).get('root_move_passes_gate')!=d.get('root_move_passes_gate')
        result['proposals_extended']+=bool(extensions)
        deferrals=sum(x.get('status')=='deferred' and x.get('proof') is not None for x in extensions)
        result['new_deferral_branches']+=deferrals
        result['new_deferral_proposals']+=bool(deferrals)
        result['extra_verification_distinct_requests']+=d['escalation']['distinct_requests']-details(left)['escalation']['distinct_requests']
        different=classification(left)!=classification(right)
        result['classification_changes']+=different
        if extensions:
            result['still_ambiguous']+=classification(right)=='ambiguous'
            if classification(left)=='ambiguous' and classification(right)!='ambiguous':
                result['resolved']+=1;result['newly_'+classification(right)]+=1
        if not extensions and branch_chess(left)!=branch_chess(right):
            result['unexpected_control_chess_changes']+=1
        if different:
            changed.append(dict(key=key,before=classification(left),after=classification(right),eligible=eligible,
                extensions=len(extensions),before_reason=details(left)['reason'],after_reason=d['reason']))
            result['unexpected_control_classification_changes']+=not bool(extensions)
    return dict(counts=dict(result),changed=changed)


