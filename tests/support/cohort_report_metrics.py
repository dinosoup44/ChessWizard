"""Comparable audit rates with explicit denominators; no chess or database access."""


def fraction(count: int, denominator: int) -> dict:
    """Retain the denominator and represent an empty population as unavailable.

    Args:
        count: Observed numerator.
        denominator: Explicit population size.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    return dict(count=count, denominator=denominator,
                rate=count/denominator if denominator else None)


def population_rates(metrics: dict) -> dict:
    """Compute comparable rates without mixing different proof/admission denominators.

    Args:
        metrics: Supplied population counts.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    total = metrics['entries']
    classes = metrics['classifications']
    gate = metrics['gate']
    ambiguous = classes.get('ambiguous', 0)
    result = {name: fraction(classes.get(name, 0), total) for name in
              ('verified', 'verified_payoff_changed', 'rejected', 'ambiguous', 'error')}
    result.update(
        gate_admitted=fraction(gate.get('admitted', 0), total),
        gate_admitted_when_reached=fraction(gate.get('admitted', 0),
                                            gate.get('admitted', 0)+gate.get('rejected', 0)),
        proof_complete=fraction(metrics['proof_complete'], total),
        escalation=fraction(metrics['escalated_proposals'], total),
        escalation_resolution=fraction(metrics['escalation_resolved'], metrics['escalated_proposals']),
        mate_terminal=fraction(metrics['mate_terminal_deferrals'], total),
        rank={rank: fraction(metrics['rank'].get(rank, 0), total)
              for rank in ('1', '2', '3', 'outside_top_3', 'not_reached')},
        ambiguity_causes={name: dict(per_entry=fraction(count, total),
                                     per_ambiguous=fraction(count, ambiguous))
                          for name, count in metrics['ambiguity_causes_nonexclusive'].items()})
    return result


def selective_rates(counts: dict) -> dict:
    """Separate eligibility, extension and resolution populations.

    Args:
        counts: Supplied selective-policy counts.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    paired = counts['paired']
    eligible = counts.get('eligible_proposals', 0)
    extended = counts.get('proposals_extended', 0)
    return dict(eligibility=fraction(eligible, paired),
                resolution=fraction(counts.get('resolved', 0), eligible),
                resolution_when_extended=fraction(counts.get('resolved', 0), extended),
                new_deferral=fraction(counts.get('new_deferral_proposals', 0), eligible),
                still_ambiguous=fraction(counts.get('still_ambiguous', 0), extended))


def cost_metrics(summary: dict, mode: str) -> dict:
    """Normalize supplied request accounting without inferring omitted searches.

    Args:
        summary: Supplied cost/result summary.
        mode: Baseline or selective summary key.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    cost = summary['engine_cost'][mode]
    session = cost.get('execution_session', cost.get('final_execution_session'))
    rerun = cost.get('no_engine_rerun', cost.get('deterministic_rerun'))
    entries = sum(m['entries'] for m in summary['mode_'+mode].values())
    searches = cost['journal']['total_searches']
    result = dict(fresh_searches=fraction(searches, entries),
                  journal=cost['journal'], cache_sources=session['cache_sources'],
                  runtime_seconds=session['session_seconds'],
                  no_engine_seconds=rerun['session_seconds'],
                  runtime_bounds=cost.get('analysis_runtime_seconds_bounds'),
                  accounting_note=cost.get('accounting_note'))
    if mode == 'b':
        counts = summary['selective']['counts']
        result.update(searches_per_eligible=fraction(searches, counts.get('eligible_proposals', 0)),
                      searches_per_resolution=fraction(searches, counts.get('resolved', 0)))
    return result


def cohort_comparison(first: dict, second: dict) -> dict:
    """Compare supplied cohorts using identical definitions and separate populations.

    Args:
        first: First supplied cohort summary.
        second: Second supplied cohort summary.

    Returns:
        Structured comparison or factual result for the supplied inputs.
    """
    result = dict(definitions={
        'outcomes_gate_proof_escalation_rank_terminal': 'Each historical/discovery population separately, divided by its entry count. Proof completeness means nonempty retained branches all stable/terminal; not every admitted root reaches proof.',
        'gate_when_reached': 'Admitted / (admitted + rejected); excludes terminal roots where admission was not reached.',
        'ambiguity_causes': 'Nonexclusive causes; both per-entry and per-ambiguous rates are retained. They must not be summed.',
        'escalation_resolution': 'Resolved / proposals with at least one escalated branch.',
        'selective': 'Eligibility / paired entries; resolution and new deferral / eligible proposals. Extended-proposal rates are also explicit.',
        'parity': 'Observations, not independent games or proposals; categories A-H share an observation denominator.',
        'cost': 'Fresh physical searches include bounded/interrupted attempts. Per-entry and selective-eligible/resolved denominators are descriptive only: cache populations and overlap differ.',
    }, cohorts={})
    for name, summary in (('first', first), ('second', second)):
        parity = summary['parity']
        result['cohorts'][name] = dict(
            scope=summary['scope'],
            populations={mode:{kind:population_rates(metrics) for kind, metrics in summary['mode_'+mode].items()}
                         for mode in ('a', 'b')},
            selective=selective_rates(summary['selective']['counts']),
            selective_counts=summary['selective']['counts'],
            parity={category:fraction(parity['categories'].get(category, 0), parity['observations'])
                    for category in 'ABCDEFGH'},
            parity_ranges=parity['ranges'],
            costs={mode:cost_metrics(summary, mode) for mode in ('a', 'b')})
    return result
