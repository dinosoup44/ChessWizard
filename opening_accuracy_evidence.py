"""Shared read-only join of authored game facts and exact Accuracy V1 evidence."""
from dataclasses import dataclass
from move_quality import MoveQuality, QualityMove
from move_quality_repository import MoveQualityRepository
from opening_accuracy import derive_opening_accuracy, opening_phase
from opening_accuracy_models import OpeningGameAccuracy
from opening_accuracy_settings import OpeningAccuracySettings
from opening_intelligence_models import OpeningGameAssessment, OpeningMatchPolicy


@dataclass(frozen=True)
class OpeningAccuracyEvidence:
    """Keep exact played FENs alongside the unchanged bounded-window score.

    Args:
        accuracy: Existing opening-window calculation.
        moves: All legal actual game moves, retaining engine-request clocks.
        qualities: Only requested existing evidence; never generated on a miss.
    """
    accuracy: OpeningGameAccuracy
    moves: tuple[QualityMove, ...]
    qualities: tuple[MoveQuality, ...]


def assess_opening_evidence(
    assessment: OpeningGameAssessment,
    repository: MoveQualityRepository,
    match_policy: OpeningMatchPolicy,
    settings: OpeningAccuracySettings,
    *,
    include_user_deviations: bool = False,
) -> OpeningAccuracyEvidence:
    """Reuse exact stored quality evidence within a caller-owned read snapshot.

    Args:
        assessment: Legally replayed authored-book facts.
        repository: Existing read-only Move Quality repository.
        match_policy: The same policy used to produce the authored facts.
        settings: Shared opening-window and Move Quality settings.
        include_user_deviations: Also retrieve user departure facts outside the
            scoring window. These facts never extend the accuracy denominator.

    Returns:
        Existing opening accuracy plus exact moves and requested quality facts.

    Raises:
        ValueError: Game moves or match/evidence identities are incompatible.
        sqlite3.Error: Reading the caller's snapshot fails.
    """
    if repository.settings != settings.quality:
        raise ValueError('Quality repository and opening settings must agree.')
    phase = opening_phase(assessment, match_policy, settings)
    needed = set(range(phase.start_ply, phase.end_ply + 1)) if phase else set()
    if include_user_deviations:
        needed.update(row.ply for row in assessment.moves
                      if row.deviation and row.actor_color == assessment.user_color)
    moves = repository.moves(assessment.game_id) if needed else ()
    qualities = tuple(repository.assess(move) for move in moves if move.step in needed)
    accuracy = derive_opening_accuracy(assessment, qualities, match_policy=match_policy, settings=settings)
    return OpeningAccuracyEvidence(accuracy, moves, qualities)
