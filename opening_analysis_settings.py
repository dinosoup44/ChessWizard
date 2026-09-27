"""Small interpretation settings; raw engine requests remain owned by Accuracy V1."""
from dataclasses import dataclass
from analysis_settings import Settings, setting


@dataclass(frozen=True)
class OpeningAnalysisSettings(Settings):
    """Configure neutral cross-game summaries, never engine admission or scoring.

    Args:
        gap_minimum_games: Distinct affected games required for a repeated gap signal.
        policy_version: Version of matching-set and summary interpretation.
    """
    gap_minimum_games: int = setting(2, 'Minimum distinct games with the same opponent departure and no active authored continuation.', minimum=2, maximum=1000, basic=True)
    policy_version: int = setting(1, 'Opening analysis aggregation and repertoire-side contract.', minimum=1)
