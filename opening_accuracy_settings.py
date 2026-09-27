"""Opening-window policy over the existing frozen move-quality evidence contract."""
from dataclasses import dataclass, asdict
from analysis_settings import Settings, setting, identity
from move_quality_settings import MoveQualitySettings


@dataclass(frozen=True)
class OpeningAccuracySettings(Settings):
    continuation_plies: int = setting(4, "Maximum actual plies after the last known book position; nearby re-entry renews this bound.", minimum=2, maximum=20, basic=True)
    policy_version: int = setting(1, "Authored opening-window and aggregation contract.", minimum=1)
    @property
    def quality(self):
        """One authoritative V1 profile/formula, not an opening-specific configuration."""
        return MoveQualitySettings()

    @property
    def currentness_identity(self):
        return identity({"opening":asdict(self),"quality":self.quality.currentness_identity})
