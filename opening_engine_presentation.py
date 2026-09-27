"""Readable advisory notation and preview using the existing legal line player."""
from candidate_lines import CandidateLine
from line_playback import LinePlaybackState, format_proof_line_rows
from opening_engine_models import OpeningEngineAnalysis
from position_evaluation import format_evaluation_score
from stored_line import StoredLine


def opening_engine_playback(analysis: OpeningEngineAnalysis, rank: int) -> LinePlaybackState:
    """Create an isolated board cursor without changing the authored-book selection.

    Args:
        analysis: Validated advice bound to its saved anchor.
        rank: One actual returned candidate rank.

    Returns:
        Existing legal line-playback state at the anchor, ready for bounded stepping.

    Raises:
        ValueError: The selected rank or returned line is invalid.
    """
    line = next((row for row in analysis.lines.lines if row.rank == rank), None)
    if line is None:
        raise ValueError('Select a returned Stockfish line.')
    stored = StoredLine.from_san(analysis.anchor.fen, ' '.join(line.pv_san))
    if stored.moves_uci != line.pv_uci:
        raise ValueError('Stockfish notation and legal replay disagree.')
    return LinePlaybackState(stored)


def opening_engine_line_text(analysis: OpeningEngineAnalysis, rank: int) -> str:
    """Format the full SAN continuation with actual move numbers and Black starts.

    Args:
        analysis: Anchored engine advice.
        rank: Returned candidate rank.

    Returns:
        Human-readable whole continuation; no raw UCI in the normal interface.
    """
    playback = opening_engine_playback(analysis, rank)
    return ' '.join(f'{row.move_number}. {row.white} {row.black}'.strip() if row.white
                    else f'{row.move_number}… {row.black}' for row in format_proof_line_rows(playback.line))


def opening_engine_score_text(line: CandidateLine) -> str:
    """Use the same canonical White-POV cp/mate labels as Game Review.

    Args:
        line: Actual candidate evidence.

    Returns:
        Signed pawn units or typed M-distance, never a weight/accuracy score.
    """
    return format_evaluation_score(line.score, 'white')
