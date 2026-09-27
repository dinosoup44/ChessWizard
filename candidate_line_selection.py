"""Shared admission of a required historical move, without treating top-N omission as failure."""
from dataclasses import dataclass, replace
from analysis_settings import AnalysisProfile, identity
from candidate_lines import CandidateLineSet, to_data
from quality_gate import ApprovedCandidateLineSet, approve_lines


@dataclass(frozen=True)
class RequiredMoveAdmission:
    root: CandidateLineSet
    approved: ApprovedCandidateLineSet
    required_move: str
    native_rank: int | None
    supplemented: bool

    @property
    def decision(self):
        return next((d for d in self.approved.decisions if d.move_uci == self.required_move), None)


def admit_required_move(service, fen, move_uci, profile=AnalysisProfile()):
    """Use the shared gate against top-N evidence plus an explicitly requested move if absent."""
    root = service.candidate_lines(fen, profile.generator)
    native = next((line for line in root.lines if line.move_uci == move_uci), None)
    base_approval = approve_lines(root, profile.quality_gate, expected_engine_identity=profile.engine_identity)
    if native is not None or base_approval.state in {'incomplete', 'terminal'}:
        return RequiredMoveAdmission(root, base_approval, move_uci, native.rank if native else None, False)
    extra = service.candidate_lines(fen, profile.generator, root_moves=(move_uci,))
    comparison = _comparison_set(root, extra, move_uci)
    approved = approve_lines(comparison, profile.quality_gate, expected_engine_identity=comparison.engine_identity)
    return RequiredMoveAdmission(root, approved, move_uci, None, True)


def _comparison_set(root, extra, move_uci):
    if root.fen != extra.fen or root.analysis_profile != extra.analysis_profile:
        raise ValueError('Incompatible required-move evidence')
    if root.generation_metadata.get('generator_settings') != extra.generation_metadata.get('generator_settings'):
        raise ValueError('Required-move evaluation must use identical generator settings')
    if extra.generation_metadata.get('root_moves') != (move_uci,):
        raise ValueError('Required-move evidence has a different root restriction')
    evidence_id = identity({'root': root.engine_identity, 'required': extra.engine_identity})
    originals = (*root.lines, *extra.lines)
    ordered = sorted(originals, key=lambda line: line.score.ordering(root.side_to_move), reverse=True)
    lines = tuple(replace(line, rank=index, engine_identity=evidence_id,
        metadata={**to_data(line.metadata), 'source_request_identity': line.engine_identity,
                  'native_rank': line.rank if line in root.lines else None})
        for index, line in enumerate(ordered, 1))
    return CandidateLineSet(root.fen, root.side_to_move, root.requested_line_count + 1,
        root.analysis_profile, evidence_id, lines, {
            'complete': root.generation_metadata.get('complete') is True and extra.generation_metadata.get('complete') is True,
            'source': 'top_n_plus_explicit_required_move',
            'profile_requested_line_count': root.requested_line_count,
            'required_move': move_uci,
            'rank_scope': 'observed_comparison_set_not_global_engine_rank',
            'source_request_identities': [root.engine_identity, extra.engine_identity],
        })
