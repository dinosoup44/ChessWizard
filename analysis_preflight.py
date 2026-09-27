"""Generic opt-in existing-evidence stage; dispositions are not coverage rows."""
from collections import Counter
from dataclasses import asdict, dataclass
from existing_position_evidence import ExistingPositionEvidence
from solution_ownership import SolutionOwnershipService

DISPOSITIONS = {"heavy_required", "cached_quick_rejected", "mate_deferred", "already_owned", "played_checkmate"}


@dataclass(frozen=True)
class PreflightResult:
    disposition: str
    reason: str
    provenance: dict

    def __post_init__(self):
        if self.disposition not in DISPOSITIONS:
            raise ValueError("Unknown existing-evidence disposition")


@dataclass(frozen=True)
class PreflightContext:
    analysis_type: str
    analyzer_version: str
    positions: object
    ownership: object


def apply_existing_preflight(connection, definitions, moves, plan):
    """Reconsider every pending check using current evidence on every call.

    No persisted dispositions, durable negative semantics, or engine capability.
    Failures conservatively retain the item. Unregistered analyzers are untouched.
    """
    enabled = {d.analysis_type:d for d in definitions if d.preflight_existing_evidence is not None}
    if not enabled:
        return plan
    by_move = {r["move_id"]:r for r in moves}
    evidence = ExistingPositionEvidence(connection)
    ownership = SolutionOwnershipService(connection)
    pending, records = [], []
    metric_names = sorted(DISPOSITIONS | {"entering", "errors", "unresolved", "with_missing_or_incompatible_evidence"})
    counts = {name:Counter({key:0 for key in metric_names}) for name in enabled}
    for item in plan["pending_heavy_checks"]:
        definition = enabled.get(item["analysis_type"])
        if definition is None:
            pending.append(item)
            continue
        metrics = counts[definition.analysis_type]
        metrics["entering"] += 1
        try:
            result = definition.preflight_existing_evidence(by_move[item["move_id"]],
                PreflightContext(definition.analysis_type, definition.analyzer_version, evidence, ownership))
            if not isinstance(result, PreflightResult):
                raise TypeError("Invalid preflight result")
        except Exception as exc:
            metrics["errors"] += 1
            result = PreflightResult("heavy_required", "preflight_error",
                {"analyzer_version":definition.analyzer_version, "error_type":type(exc).__name__, "message":str(exc)})
        metrics[result.disposition] += 1
        if result.disposition == "heavy_required":
            pending.append(item)
            metrics["unresolved"] += 1
            if result.provenance.get("missing_or_incompatible_evidence"):
                metrics["with_missing_or_incompatible_evidence"] += 1
        records.append({**item, **asdict(result)})
    return {**plan, "pending_before_preflight":plan["pending_heavy_checks"],
            "pending_heavy_checks":pending,
            "existing_evidence_preflight":{"analyzers":counts, "records":records,
                "cache_reads":dict(evidence.stats), "engine_searches":0, "coverage_writes":0,
                "persistence":"none; dispositions must be recomputed, not treated as coverage"}}
