"""Typed settings and one schema for presets, services and a future admin UI."""
from dataclasses import asdict, dataclass, field, fields, is_dataclass
import hashlib
import json
import math
from types import UnionType
from typing import get_args, get_origin, get_type_hints


def setting(default, description, *, minimum=None, maximum=None, options=(), basic=False,
            cache=False, current=True):
    return field(default=default, metadata=dict(description=description, minimum=minimum,
        maximum=maximum, options=options, basic=basic, cache=cache, current=current))


@dataclass(frozen=True)
class SettingDefinition:
    setting_id: str
    label: str
    type: str
    default: object
    minimum: float | None
    maximum: float | None
    options: tuple
    description: str
    level: str
    affects_cache_identity: bool
    affects_analysis_currentness: bool

    def to_schema(self):
        """Frontend-neutral schema with explicit raw-cache and result-currentness flags."""
        return {**asdict(self), "affects_raw_cache_identity": self.affects_raw_cache_identity,
                "affects_result_currentness": self.affects_result_currentness}

    @property
    def affects_raw_cache_identity(self):
        return self.affects_cache_identity

    @property
    def affects_result_currentness(self):
        return self.affects_analysis_currentness


def _matches_type(value, expected_type):
    if expected_type is float:
        return type(value) in (int, float)
    return type(value) is expected_type


def _validate_setting(definition, value, type_hint):
    allowed_types = get_args(type_hint) if get_origin(type_hint) is UnionType else (type_hint,)
    if not any(_matches_type(value, expected) for expected in allowed_types):
        raise ValueError(f"Invalid type for {definition.name}")
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"Empty {definition.name}")
    if type(value) in (int, float):
        minimum = definition.metadata.get('minimum')
        maximum = definition.metadata.get('maximum')
        if not math.isfinite(value):
            raise ValueError(f"Nonfinite {definition.name}")
        if minimum is not None and value < minimum:
            raise ValueError(f"Below minimum: {definition.name}")
        if maximum is not None and value > maximum:
            raise ValueError(f"Above maximum: {definition.name}")
    options = definition.metadata.get('options')
    if options and value not in options:
        raise ValueError(f"Unknown {definition.name}")


class Settings:
    def __post_init__(self):
        hints = get_type_hints(type(self))
        for definition in fields(self):
            _validate_setting(definition, getattr(self, definition.name), hints[definition.name])

    def schema(self, prefix=""):
        result = []
        for f in fields(self):
            value, name = getattr(self, f.name), prefix + f.name
            if isinstance(value, Settings):
                result.extend(value.schema(name + "."))
                continue
            m = f.metadata
            result.append(SettingDefinition(name, f.name.replace("_", " ").capitalize(),
                str(get_type_hints(type(self))[f.name]).replace("<class '", "").replace("'>", ""), value,
                m.get("minimum"), m.get("maximum"), m.get("options", ()), m.get("description", ""),
                "basic" if m.get("basic") else "advanced", m.get("cache", False), m.get("current", True)))
        return tuple(result)


def load_settings(cls, data):
    """Load the same validated JSON data used by presets and future admin controls."""
    if not isinstance(data, dict):
        raise ValueError("Settings must be a JSON object")
    known = {f.name for f in fields(cls)}
    if set(data) - known:
        raise ValueError("Unknown settings: " + str(sorted(set(data) - known)))
    hints = get_type_hints(cls)
    return cls(**{name: load_settings(hints[name], value) if isinstance(hints[name], type)
                  and issubclass(hints[name], Settings) else value for name, value in data.items()})


def identity(value):
    if is_dataclass(value): value = asdict(value)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class EngineSettings(Settings):
    engine_name: str = setting("Stockfish", "Engine identity.", cache=True)
    engine_version: str = setting("18", "Engine release identity.", cache=True)
    profile_id: str = setting("candidate_lines_v1", "Engine request family.", cache=True)
    depth: int | None = setting(12, "Depth limit; at least one budget must be present.", minimum=1, maximum=64, basic=True, cache=True)
    nodes: int | None = setting(None, "Optional node budget.", minimum=1, maximum=1000000000, cache=True)
    time_seconds: float | None = setting(None, "Optional time budget in seconds.", minimum=0.01, maximum=600, cache=True)
    threads: int = setting(1, "Engine threads.", minimum=1, maximum=64, cache=True)
    hash_mb: int = setting(64, "Engine hash memory in MiB.", minimum=1, maximum=4096, cache=True)

    def __post_init__(self):
        super().__post_init__()
        if all(getattr(self, k) is None for k in ("depth", "nodes", "time_seconds")):
            raise ValueError("An engine budget is required")


@dataclass(frozen=True)
class GeneratorSettings(Settings):
    candidate_line_count: int = setting(3, "Requested root lines (MultiPV); one preserves best-line-only mode.", minimum=1, maximum=256, basic=True, cache=True)
    analysis_version: int = setting(1, "Generator contract/normalization version.", minimum=1, cache=True)
    engine: EngineSettings = EngineSettings()


@dataclass(frozen=True)
class QualityGateSettings(Settings):
    policy_version: int = setting(1, "Acceptance policy version.", minimum=1)
    absolute_tolerance_cp: int = setting(75, "Maximum absolute loss from best.", minimum=0, maximum=10000, basic=True)
    relative_tolerance: float = setting(0.2, "Fraction of positive best advantage; never used on negative scores.", minimum=0, maximum=1)
    winning_floor_cp: int = setting(500, "Farther alternatives at or above this winning floor can pass.", minimum=0, maximum=10000, basic=True)
    acceptable_floor_cp: int | None = setting(None, "Optional separate acceptable floor; disabled by default.", minimum=0, maximum=10000)
    mate_extra_moves: int = setting(3, "Allowed extra moves to deliver mate compared with best.", minimum=0, maximum=100)
    allow_cp_instead_of_mate: bool = setting(False, "Allow a winning cp line instead of a known winning mate.")
    allow_losing_mate: bool = setting(False, "Allow normal acceptance of forced losing-mate lines.")
    losing_mate_shortening: int = setting(2, "Maximum shortening of resistance relative to best losing mate.", minimum=0, maximum=100)
    maximum_deterioration_cp: int | None = setting(None, "Optional drop from an explicit reference evaluation; all failures trigger least-bad retention.", minimum=0, maximum=10000)
    least_bad_line_count: int = setting(2, "How many least-bad lines to retain when every normal decision fails.", minimum=1, maximum=256)
    minimum_depth: int = setting(1, "Evidence below this depth is incomplete, not a chess rejection.", minimum=1, maximum=64)


@dataclass(frozen=True)
class ScaleWeights(Settings):
    objective_strength: float = setting(5.0, "Interest from evaluation, separate from soundness.", minimum=0, maximum=100)
    distance_from_best: float = setting(5.0, "Interest from closeness to best.", minimum=0, maximum=100)
    retained_advantage: float = setting(5.0, "Positive endpoint evaluation, only when explicitly supplied.", minimum=0, maximum=100)
    material_payoff: float = setting(20.0, "Observed net material gain in this PV; not verified settlement.", minimum=0, maximum=100)
    forcingness: float = setting(12.0, "Density of checks, captures and promotions.", minimum=0, maximum=100)
    continuation_trend: float = setting(10.0, "Signed improvement from supplied compatible evaluations.", minimum=0, maximum=100)
    settlement_quality: float = setting(10.0, "Explicitly supplied proof settlement.", minimum=0, maximum=100)
    sacrifice_interest: float = setting(30.0, "Observed material investment, not a sacrifice-motif classification.", minimum=0, maximum=100)
    mate_interest: float = setting(25.0, "Winning mate or critical losing-mate interest.", minimum=0, maximum=100)
    defensive_narrowness: float = setting(12.0, "Explicitly supplied defense evidence; never inferred from MultiPV count.", minimum=0, maximum=100)
    motif_relevance: float = setting(10.0, "Events supplied by a future classifier.", minimum=0, maximum=100)
    rarity: float = setting(10.0, "Observable unusual events, such as underpromotion.", minimum=0, maximum=100)
    complexity: float = setting(3.0, "Bounded line-length proxy, not estimated human difficulty.", minimum=0, maximum=100)


@dataclass(frozen=True)
class MaterialValues(Settings):
    pawn: int = setting(100, "Pawn accounting value.", minimum=1, maximum=10000)
    knight: int = setting(300, "Knight accounting value.", minimum=1, maximum=10000)
    bishop: int = setting(300, "Bishop accounting value.", minimum=1, maximum=10000)
    rook: int = setting(500, "Rook accounting value.", minimum=1, maximum=10000)
    queen: int = setting(900, "Queen accounting value.", minimum=1, maximum=10000)

    def piece_values(self):
        return {1: self.pawn, 2: self.knight, 3: self.bishop, 4: self.rook, 5: self.queen, 6: 0}


@dataclass(frozen=True)
class ScaleSettings(Settings):
    policy_version: int = setting(1, "Scale/event semantics version.", minimum=1)
    base_interest: float = setting(10.0, "Baseline before visible component contributions.", minimum=0, maximum=100)
    material_unit_cp: int = setting(300, "Material gain for full component credit.", minimum=1, maximum=10000)
    evaluation_unit_cp: int = setting(500, "Positive evaluation for full objective credit.", minimum=1, maximum=10000)
    trend_unit_cp: int = setting(150, "Evaluation change for full trend credit.", minimum=1, maximum=10000)
    distance_unit_cp: int = setting(300, "Distance at which closeness credit reaches zero.", minimum=1, maximum=10000)
    complexity_plies: int = setting(20, "Line length for full length-proxy credit.", minimum=1, maximum=200)
    quiet_line_penalty: float = setting(5.0, "Penalty for a quiet line without concrete observed payoff.", minimum=0, maximum=100)
    unacceptable_continuation_penalty: float = setting(20.0, "Interest penalty when supplied continuation quality says acceptability was lost.", minimum=0, maximum=100)
    weights: ScaleWeights = ScaleWeights()
    material: MaterialValues = MaterialValues()


@dataclass(frozen=True)
class ProofDefaults(Settings):
    user_moves: int = setting(4, "Future specialist proof-window default; existing specialists unchanged.", minimum=1, maximum=4)
    settlement_plies: int = setting(4, "Bounded settlement extension; existing defaults remain unchanged.", minimum=0, maximum=16)
    quiet_plies: int = setting(2, "Shared bounded proof stability requirement.", options=(2,))


VERIFICATION_GENERATOR = GeneratorSettings(1, engine=EngineSettings(profile_id="candidate_lines_verify_v1", depth=18))


@dataclass(frozen=True)
class SettlementExtensionPolicy(Settings):
    enabled: bool = setting(False, "Allow opt-in specialists to extend only proven pure-window cases; no live activation.", basic=True)
    policy_version: int = setting(1, "Pure-window eligibility and continuation semantics.", options=(1,))
    source_settlement_plies: int = setting(8, "Required normal verification settlement boundary.", options=(8,))
    target_settlement_plies: int = setting(12, "Maximum selective settlement extension; payoff clock is unchanged.", options=(12,))


@dataclass(frozen=True)
class ProofEscalationPolicy(Settings):
    enabled: bool = setting(False, "Opt in to targeted verification; discovery behavior is unchanged.", basic=True)
    policy_version: int = setting(1, "Escalation and endpoint-proof semantics.", minimum=1)
    verification: GeneratorSettings = VERIFICATION_GENERATOR
    proof: ProofDefaults = ProofDefaults(settlement_plies=8)
    max_escalated_branches_per_candidate: int = setting(3, "Maximum selected branches; no recursive fan-out.", minimum=0, maximum=9)
    max_child_depth_levels: int = setting(2, "Maximum approved entry plies before the verification anchor; distinct from linear proof length.", minimum=0, maximum=2)
    max_requests_per_candidate: int = setting(24, "Maximum distinct verification requests, including cache hits, for deterministic bounded work.", minimum=0, maximum=256)
    escalate_unsettled: bool = setting(True, "Obtain stronger evidence when the bounded continuation did not settle.")
    escalate_disagreement: bool = setting(True, "Recheck conflicting retained target/payoff evidence.")
    ambiguity_policy: str = setting("protect_unresolved", "Unresolved, conflicting or budget-limited proposals remain protected.", options=("protect_unresolved",))
    root_admission_policy: str = setting("preserve_breadth_gate", "A failed root gate never requests deeper branches.", options=("preserve_breadth_gate",))
    mate_policy: str = setting("defer", "Keep mate ownership separate; this layer does not classify a mate as material.", options=("defer",))
    settlement_extension: SettlementExtensionPolicy = SettlementExtensionPolicy()


@dataclass(frozen=True)
class AnalysisProfile(Settings):
    profile_id: str = setting("normal", "Preset identifier.", current=False)
    label: str = setting("Normal", "Display label.", current=False)
    generator: GeneratorSettings = GeneratorSettings()
    quality_gate: QualityGateSettings = QualityGateSettings()
    scale: ScaleSettings = ScaleSettings()
    proof: ProofDefaults = ProofDefaults()
    escalation: ProofEscalationPolicy = ProofEscalationPolicy()

    @property
    def engine_identity(self):
        return identity(self.generator)

    @property
    def currentness_identity(self):
        data = {k: asdict(getattr(self, k)) for k in ("generator", "quality_gate", "scale", "proof")}
        if self.escalation.enabled:
            data["escalation"] = asdict(self.escalation)
            if not self.escalation.settlement_extension.enabled:
                data["escalation"].pop("settlement_extension")
        return identity(data)


BUILTIN_PROFILES = {
    "quick": AnalysisProfile("quick", "Quick", GeneratorSettings(1, engine=EngineSettings(depth=10))),
    "normal": AnalysisProfile(),
    "verification": AnalysisProfile("verification", "Targeted verification", VERIFICATION_GENERATOR, proof=ProofDefaults(settlement_plies=8)),
    "normal_escalation": AnalysisProfile("normal_escalation", "Normal with targeted verification", escalation=ProofEscalationPolicy(enabled=True)),
    "deep": AnalysisProfile("deep", "Deep", GeneratorSettings(5, engine=EngineSettings(depth=16))),
}


def load_profile(data):
    if isinstance(data, str):
        if data not in BUILTIN_PROFILES:
            raise ValueError("Unknown analysis preset")
        return BUILTIN_PROFILES[data]
    return load_settings(AnalysisProfile, data)


@dataclass(frozen=True)
class ProductionAnalysisProfile(Settings):
    """Registered specialist budgets, distinct from opt-in multi-line presets.

    This descriptor does not translate Normal/Quick/Deep into legacy thresholds.
    Budget and currentness identities remain owned by the registry/cache profiles.
    """
    profile_id: str = setting("registered_v1", "Use the registered production specialists unchanged.", options=("registered_v1",), current=False)
    label: str = setting("Production defaults", "Fixed production analyzer profiles.", options=("Production defaults",), current=False)


@dataclass(frozen=True)
class AnalysisBatchSettings(Settings):
    """Configure workload partitioning without changing chess evidence.

    Args:
        batch_size: Maximum stored games inspected before processing that batch.
    """
    batch_size: int = setting(50, "Games per progressive analysis batch.",
                              minimum=1, maximum=500, basic=True, cache=False, current=False)
