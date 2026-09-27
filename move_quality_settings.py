"""Shared typed evidence and scoring settings; no alternate configuration path."""
from dataclasses import dataclass
from analysis_settings import Settings, setting, GeneratorSettings, EngineSettings, identity
from board_analysis.phase import PhaseSettings
from candidate_line_request import request_identity


@dataclass(frozen=True)
class MoveQualitySettings(Settings):
    generator: GeneratorSettings = GeneratorSettings(1, engine=EngineSettings(depth=16))
    phase: PhaseSettings = PhaseSettings()
    policy_version: int = setting(1, "Move-quality interpretation and accuracy contract.", minimum=1)
    half_accuracy_loss_cp: int = setting(100, "Centipawn loss yielding 50 accuracy in 100/(1+(loss/scale)^2).", minimum=1, maximum=1000, basic=True)
    lost_mate_accuracy: float = setting(40.0, "Accuracy when a forced winning mate becomes a finite evaluation.", minimum=0, maximum=100)
    mate_distance_penalty: float = setting(2.0, "Accuracy points per extra move to mate, or move of lost resistance.", minimum=0, maximum=100)
    mate_distance_max_penalty: float = setting(20.0, "Maximum distance-only penalty while mate ownership remains unchanged.", minimum=0, maximum=100)

    @property
    def raw_identity(self):
        return request_identity(self.generator)

    @property
    def currentness_identity(self):
        return identity(self)
