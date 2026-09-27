"""Pure composition of authored facts and engine facts, with no new chess judgments."""
from opening_accuracy_evidence import OpeningAccuracyEvidence
from opening_analysis_models import (OpeningAdherence, OpeningAnalysisGame,
                                     OpeningDeviation, OpeningGameContext)
from opening_intelligence_lookup import OpeningBookLookup
from opening_intelligence_models import OpeningGameAssessment


def compose_opening_game(context: OpeningGameContext, assessment: OpeningGameAssessment,
                         evidence: OpeningAccuracyEvidence, lookup: OpeningBookLookup) -> OpeningAnalysisGame:
    """Build full-game adherence/departures alongside the bounded accuracy window.

    Args:
        context: Stored source and owner facts.
        assessment: Validated book replay for this game.
        evidence: Shared existing-evidence join for the same game.
        lookup: The exact selected book snapshot.

    Returns:
        Immutable game result with separate user/opponent first departures.

    Raises:
        ValueError: Inputs refer to different games, books or user sides.
    """
    if (context.game_id != assessment.game_id or context.user_color != assessment.user_color
            or assessment.provenance != lookup.provenance or evidence.accuracy.opening != assessment):
        raise ValueError('Opening analysis inputs must describe the same game/book/user.')
    known = tuple(row for row in assessment.moves
                  if row.actor_color == context.user_color and row.position_in_book)
    adherence = OpeningAdherence(sum(row.played_move_in_book for row in known), len(known))
    actual = {move.step: move for move in evidence.moves}
    qualities = {value.move.step: value for value in evidence.qualities}
    phase = evidence.accuracy.phase
    seen, departures = set(), []
    for row in assessment.moves:
        if not row.deviation:
            continue
        party = 'user' if row.actor_color == context.user_color else 'opponent'
        departures.append(OpeningDeviation(row, actual[row.ply].fen, party, party not in seen,
            qualities.get(row.ply), bool(phase and phase.start_ply <= row.ply <= phase.end_ply),
            lookup.outgoing.get(row.after_position_id, ())))
        seen.add(party)
    return OpeningAnalysisGame(context, assessment, evidence.accuracy, adherence, tuple(departures))
