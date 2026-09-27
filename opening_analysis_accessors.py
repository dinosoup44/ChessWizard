"""Professor/frontend accessors that share one result without repeating database work."""
from opening_analysis_models import (OpeningAnalysisResult, OpeningAnalysisGame, OpeningAccuracySummary,
    OpeningDeviationPosition, OpeningRepertoireGap, OpeningVariationAccuracy, OpeningVariationGroup)
from opening_analysis_query import OpeningAnalysisQuery, filter_opening_games


def get_games_for_opening_book(result: OpeningAnalysisResult,
                               query: OpeningAnalysisQuery = OpeningAnalysisQuery()) -> tuple[OpeningAnalysisGame, ...]:
    """Read matching games, optionally applying future Explorer filters.

    Args:
        result: Previously computed selected-book analysis.
        query: Optional factual filter contract.

    Returns:
        Detailed games ready for navigation or an explicitly saved Collection.
    """
    return filter_opening_games(result, query)


def get_variation_distribution(result: OpeningAnalysisResult) -> tuple[OpeningVariationGroup, ...]:
    """Read full-path variation counts without flattening hierarchy.

    Args:
        result: Previously computed selected-book analysis.

    Returns:
        Named-path groups containing distinct game IDs.
    """
    return result.variations


def get_user_deviation_summary(result: OpeningAnalysisResult) -> tuple[OpeningDeviationPosition, ...]:
    """Read user departures grouped by canonical decision position.

    Args:
        result: Previously computed selected-book analysis.

    Returns:
        Alternatives, frequencies and existing engine facts, without coaching labels.
    """
    return result.user_deviations


def get_opponent_deviation_summary(result: OpeningAnalysisResult) -> tuple[OpeningDeviationPosition, ...]:
    """Read opponent departures and authored resulting continuations.

    Args:
        result: Previously computed selected-book analysis.

    Returns:
        Position and actual-move summaries with distinct affected game IDs.
    """
    return result.opponent_deviations


def get_repertoire_gap_candidates(result: OpeningAnalysisResult) -> tuple[OpeningRepertoireGap, ...]:
    """Read repeated unanswered opponent-move facts for future repertoire work.

    Args:
        result: Previously computed selected-book analysis.

    Returns:
        Neutral gap signals; none imply a chess weakness.
    """
    return result.repertoire_gaps


def get_opening_accuracy_summary(result: OpeningAnalysisResult) -> OpeningAccuracySummary:
    """Read pooled user-move accuracy and its explicit evidence denominator.

    Args:
        result: Previously computed selected-book analysis.

    Returns:
        Existing Accuracy V1 facts over book-derived windows.
    """
    return result.accuracy


def get_variation_accuracy_summary(result: OpeningAnalysisResult) -> tuple[OpeningVariationAccuracy, ...]:
    """Read variation scores labeled by context within the scoring window.

    Args:
        result: Previously computed selected-book analysis.

    Returns:
        Pooled move scores and separately labeled game-mean/median statistics.
    """
    return result.variation_accuracy
