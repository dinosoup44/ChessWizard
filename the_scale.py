"""Human-interest ranking of approved lines; no soundness or motif classification."""
from dataclasses import dataclass
from analysis_settings import ScaleSettings, identity
from candidate_lines import CandidateLine, to_data
from continuation_quality import ContinuationQuality, SemanticEvent, inspect_continuation
from quality_gate import ApprovedCandidateLineSet


@dataclass(frozen=True)
class ScaleComponent:
    component_id: str
    value: float | None
    weight: float
    contribution: float
    reason: str


@dataclass(frozen=True)
class WeightedCandidateLine:
    line: CandidateLine
    interest_weight: float
    components: tuple[ScaleComponent, ...]
    continuation: ContinuationQuality
    events: tuple[SemanticEvent, ...]

    @property
    def unknown_components(self):
        """Unknown input evidence is not a measured zero."""
        return tuple(component.component_id for component in self.components if component.value is None)


@dataclass(frozen=True)
class WeightedCandidateLines:
    approved: ApprovedCandidateLineSet
    lines: tuple[WeightedCandidateLine, ...]
    scale_identity: str

    @property
    def evidence_provenance(self):
        """Root evidence, acceptance and interest have independently auditable identities."""
        return {"fen": self.approved.source.fen, "engine_identity": self.approved.source.engine_identity,
                "approval_identity": self.approved.currentness_identity, "scale_identity": self.scale_identity}


def _clamp(value, low=0, high=1):
    return min(high, max(low, value))


EVENT_COMPONENTS = frozenset({'sacrifice_interest', 'motif_relevance', 'rarity', 'defensive_narrowness'})


class TheScale:
    """Rank retained lines with visible components and explicit versioned event providers."""
    def __init__(self, settings=ScaleSettings(), event_providers=()):
        self.settings, self.event_providers = settings, tuple(event_providers)
        # Providers are explicit, versioned dependencies; never dynamically loaded from data.
        if any(not getattr(p, 'provider_id', None) or not getattr(p, 'version', None) for p in self.event_providers):
            raise ValueError('Event providers require stable IDs and versions')

    def weigh(self, approved, continuation_evidence=None):
        """Score retained lines only; providers cannot introduce additional moves."""
        if not isinstance(approved, ApprovedCandidateLineSet):
            raise TypeError('The Scale requires a Quality Gate result')
        evidence = dict(continuation_evidence or {})
        if set(evidence) - {line.move_uci for line in approved.lines}:
            raise ValueError('Evidence for nonapproved line')
        s, output = self.settings, []
        color = approved.source.side_to_move
        best = max(approved.source.lines, key=lambda l: l.score.ordering(color)).score.pov(color) if approved.lines else None
        for line in approved.lines:
            facts = inspect_continuation(approved.source.fen, line, s.material, evidence.get(line.move_uci))
            events = self._collect_events(line, facts)
            values = self._component_values(line.score.pov(color), best, facts)
            for event in events:
                if event.component not in values:
                    raise ValueError('Unknown Scale event component')
                old, reason = values[event.component]
                values[event.component] = (max(old or 0, event.value), reason + ' Event: ' + event.event_id + '.')
            components = self._weighted_components(values, facts, events)
            score_weight = round(_clamp(s.base_interest + sum(c.contribution for c in components), 0, 100), 3)
            output.append(WeightedCandidateLine(line, score_weight, components, facts, events))
        output.sort(key=lambda weighted: (-weighted.interest_weight, weighted.line.rank, weighted.line.move_uci))
        return WeightedCandidateLines(approved, tuple(output), identity({'settings': to_data(s),
            'providers': [(p.provider_id, p.version) for p in self.event_providers]}))

    def _collect_events(self, line, facts):
        events = list(facts.events)
        for provider in self.event_providers:
            supplied = tuple(provider.events(line, facts))
            if any(not isinstance(event, SemanticEvent) for event in supplied):
                raise ValueError('Invalid event result')
            if any(event.component not in EVENT_COMPONENTS for event in supplied):
                raise ValueError('Contributed events cannot override objective engine/proof components')
            events.extend(supplied)
        return tuple(events)

    def _component_values(self, score, best, facts):
        s = self.settings
        distance = best.score_cp - score.score_cp if best.score_cp is not None and score.score_cp is not None else None
        endpoint = facts.eval_end.score_cp if facts.eval_end else None
        return {
                'objective_strength': (_clamp(score.score_cp/s.evaluation_unit_cp) if score.score_cp is not None else None, 'Positive cp strength; mate kept separate.'),
                'distance_from_best': (_clamp(1-distance/s.distance_unit_cp) if distance is not None else None, 'CP distance from best; not an acceptance decision.'),
                'retained_advantage': (_clamp(endpoint/s.evaluation_unit_cp) if endpoint is not None else None, 'Supplied endpoint evaluation; unknown for an ordinary root PV.'),
                'material_payoff': (_clamp(facts.material_gain/s.material_unit_cp), 'Observed PV endpoint net material; settlement may be unknown.'),
                'forcingness': (facts.forcing_move_density, 'Checks/captures/promotions divided by all PV plies.'),
                'continuation_trend': (_clamp(facts.eval_trend_cp/s.trend_unit_cp, -1, 1) if facts.eval_trend_cp is not None else None, 'Compatible supplied evaluation samples; unknown without them.'),
                'settlement_quality': (float(facts.settled) if facts.settled is not None else None, 'Explicit proof evidence only.'),
                'sacrifice_interest': (0.0, 'Observable investment or contributed verified event; no sacrifice classifier.'),
                'mate_interest': (0.0, 'Mate-valued engine evidence.'),
                'defensive_narrowness': (facts.defensive_narrowness, 'Supplied defense evidence; MultiPV count is not proof of only-move defense.'),
                'motif_relevance': (None, 'Unknown unless contributed by a classifier.'),
                'rarity': (0.0, 'Observable underpromotion or contributed unusual event.'),
                'complexity': (_clamp(facts.continuation_length/s.complexity_plies)*facts.forcing_move_density, 'Forcing line length proxy; quiet length adds no complexity interest.'),
            }

    def _weighted_components(self, values, facts, events):
        s = self.settings
        components = [ScaleComponent(name, value, getattr(s.weights, name),
                round((value or 0)*getattr(s.weights, name), 6), reason) for name, (value, reason) in values.items()]
        quiet = facts.forcing_move_density == 0 and facts.material_gain <= 0 and not events
        length = _clamp(facts.continuation_length/s.complexity_plies) if quiet else 0
        components.extend((
            ScaleComponent('quiet_without_payoff', float(quiet), -s.quiet_line_penalty,
                -s.quiet_line_penalty if quiet else 0, 'Quiet continuation with no observed concrete event.'),
            ScaleComponent('quiet_length', length, -s.quiet_line_penalty,
                -length*s.quiet_line_penalty, 'Longer quiet lines lose interest.'),
            ScaleComponent('continuation_acceptability_lost', float(facts.line_remains_acceptable is False),
                -s.unacceptable_continuation_penalty,
                -s.unacceptable_continuation_penalty if facts.line_remains_acceptable is False else 0,
                'Supplied continuation evidence; does not rewrite the root Quality Gate verdict.'),
        ))
        return tuple(components)
