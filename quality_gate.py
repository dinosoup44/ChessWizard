"""Objective acceptance before human-interest scoring. Never converts mate to cp."""
from dataclasses import asdict, dataclass
from candidate_lines import CandidateLine, CandidateLineSet, LineScore, to_data
from analysis_settings import QualityGateSettings, identity


@dataclass(frozen=True)
class QualityDecision:
    move_uci: str
    normal_accepted: bool
    retained: bool
    reason: str
    distance_cp: int | None = None


@dataclass(frozen=True)
class ApprovedCandidateLineSet:
    source: CandidateLineSet
    lines: tuple[CandidateLine, ...]
    decisions: tuple[QualityDecision, ...]
    policy_identity: str
    forced_deterioration: bool = False
    state: str = 'approved'

    @property
    def currentness_identity(self):
        return identity({'engine': self.source.engine_identity, 'fen': self.source.fen,
                         'policy': self.policy_identity, 'lines': to_data(self.source.lines)})

    def __post_init__(self):
        if self.state not in {'approved', 'forced_deterioration', 'incomplete', 'terminal'}:
            raise ValueError('Unknown approval state')
        if self.forced_deterioration != (self.state == 'forced_deterioration'):
            raise ValueError('Critical retention must have an explicit critical state')
        object.__setattr__(self, 'lines', tuple(self.lines))
        object.__setattr__(self, 'decisions', tuple(self.decisions))
        source = {line.move_uci: line for line in self.source.lines}
        decisions = {d.move_uci: d for d in self.decisions}
        if len(decisions) != len(self.decisions):
            raise ValueError('Duplicate decisions')
        if set(decisions) != set(source):
            raise ValueError('Every source line needs one decision')
        if self.forced_deterioration and any(d.normal_accepted for d in self.decisions):
            raise ValueError('Forced deterioration requires no normal acceptances')
        if {l.move_uci for l in self.lines} != {d.move_uci for d in self.decisions if d.retained}:
            raise ValueError('Approved lines must match retained decisions')
        for line in self.lines:
            if source.get(line.move_uci) != line:
                raise ValueError('Foreign line in approval')
            if not decisions[line.move_uci].normal_accepted and not self.forced_deterioration:
                raise ValueError('Only explicit critical retention may bypass normal acceptance')
        if self.state in {'incomplete', 'terminal'} and self.lines:
            raise ValueError('No usable lines in this state')
        if self.state in {'approved', 'forced_deterioration'}:
            best = max(self.source.lines, key=lambda line: line.score.ordering(self.source.side_to_move))
            if best not in self.lines:
                raise ValueError('Best realistic line must remain retained')


def _normal_reason(best, score, settings):
    if best.mate_score is not None:
        return _mate_alternative(best, score, settings)
    if score.mate_score is not None:
        return (True, 'winning_mate') if score.mate_winner == score.score_pov else (False, 'allows_forced_mate')
    distance = best.score_cp - score.score_cp
    if distance <= settings.absolute_tolerance_cp:
        return True, 'within_absolute_tolerance'
    if best.score_cp > 0 and distance <= best.score_cp * settings.relative_tolerance:
        return True, 'within_relative_tolerance'
    if score.score_cp >= settings.winning_floor_cp:
        return True, 'clearly_winning_floor'
    if settings.acceptable_floor_cp is not None and score.score_cp >= settings.acceptable_floor_cp:
        return True, 'acceptable_floor'
    return False, 'too_far_from_best'


def _mate_alternative(best, score, settings):
    if best.mate_winner == best.score_pov:
        if score.mate_score is None:
            if settings.allow_cp_instead_of_mate and score.score_cp >= settings.winning_floor_cp:
                return True, 'winning_cp_instead_of_mate'
            return False, 'gives_up_forced_mate'
        if score.mate_winner != score.score_pov:
            return False, 'mate_ownership_lost'
        if abs(score.mate_score) <= abs(best.mate_score) + settings.mate_extra_moves:
            return True, 'winning_mate'
        return False, 'mate_too_much_slower'

    if score.mate_score is None:
        return True, 'avoids_mate'
    if score.mate_winner == score.score_pov:
        return True, 'mate_ownership_improved'
    minimum_resistance = abs(best.mate_score) - settings.losing_mate_shortening
    if settings.allow_losing_mate and abs(score.mate_score) >= minimum_resistance:
        return True, 'near_best_mate_resistance'
    return False, 'forced_losing_mate'


def approve_lines(line_set, settings=QualityGateSettings(), *, expected_engine_identity=None, reference_score=None):
    """Retain normal alternatives or explicit least-bad fallback; incomplete data is separate."""
    if not isinstance(line_set, CandidateLineSet):
        raise TypeError('CandidateLineSet required')
    policy_id = identity({'settings': asdict(settings), 'reference': to_data(reference_score)})
    def incomplete(reason):
        return ApprovedCandidateLineSet(line_set, (), tuple(QualityDecision(l.move_uci, False, False, reason) for l in line_set.lines), policy_id, state='incomplete')
    if expected_engine_identity is not None and expected_engine_identity != line_set.engine_identity:
        return incomplete('incompatible_engine_identity')
    if line_set.generation_metadata.get('terminal'):
        return ApprovedCandidateLineSet(line_set, (), (), policy_id, state='terminal')
    if not line_set.lines or line_set.generation_metadata.get('complete') is not True:
        return incomplete('missing_or_partial_line_evidence')
    if any(line.depth < settings.minimum_depth for line in line_set.lines):
        return incomplete('insufficient_depth')
    if settings.maximum_deterioration_cp is not None and (not isinstance(reference_score, LineScore) or reference_score.score_cp is None):
        return incomplete('missing_cp_reference_for_deterioration')
    color = line_set.side_to_move
    ordered = sorted(line_set.lines, key=lambda l: (l.score.ordering(color), -l.rank), reverse=True)
    best = ordered[0].score.pov(color)
    decisions = []
    for line in ordered:
        score = line.score.pov(color)
        accepted, reason = _normal_reason(best, score, settings)
        if settings.maximum_deterioration_cp is not None:
            ref = reference_score.pov(color).score_cp
            if (score.score_cp is not None and ref - score.score_cp > settings.maximum_deterioration_cp
                    or score.mate_score is not None and score.mate_winner != color):
                accepted, reason = False, 'deteriorates_beyond_reference_policy'
        decisions.append(QualityDecision(line.move_uci, accepted, accepted, reason,
            best.score_cp - score.score_cp if best.score_cp is not None and score.score_cp is not None else None))
    forced = not any(d.normal_accepted for d in decisions)
    kept = {l.move_uci for l in ordered[:settings.least_bad_line_count]} if forced else {d.move_uci for d in decisions if d.normal_accepted}
    # Best realistic result is always retained, including critical fallback.
    kept.add(ordered[0].move_uci)
    decisions = tuple(QualityDecision(d.move_uci, d.normal_accepted, d.move_uci in kept,
        'least_bad_retained: ' + d.reason if forced and d.move_uci in kept else d.reason, d.distance_cp) for d in decisions)
    return ApprovedCandidateLineSet(line_set, tuple(l for l in ordered if l.move_uci in kept), decisions,
        policy_id, forced, 'forced_deterioration' if forced else 'approved')
