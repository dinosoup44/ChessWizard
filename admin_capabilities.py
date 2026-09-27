"""Source-labelled capability inspection; registry membership is not running state."""
from dataclasses import asdict
import re
import ast
from pathlib import Path
from analysis_registry import ANALYZERS
from candidate_verification_registry import CANDIDATE_VERIFIERS
from discovery_registry import DISCOVERY_ANALYZERS
from analysis_settings import BUILTIN_PROFILES, AnalysisProfile
from engine_cache import PROFILES

DOCUMENTED_COMPONENTS = (
    ("major_material_blunder", "Major Material Blunder", "analyzer",
     "docs/MAJOR_MATERIAL_BLUNDERS.md", "major_material_blunders.py"),
    ("position_range_evidence", "Position/Range Evidence Toolkit", "toolkit",
     "docs/POSITION_RANGE_EVIDENCE.md", "position_range_evidence/__init__.py"),
    ("board_analysis", "Board-analysis facts", "toolkit",
     "docs/BOARD_ANALYSIS.md", "board_analysis/__init__.py"),
    ("see", "SEE Toolkit V1", "toolkit",
     "docs/STATIC_EXCHANGE_EVALUATION.md", "board_analysis/static_exchange.py"),
)


def _document_status(root, relative):
    try:
        text = (root/relative).read_text(encoding="utf-8")
        status = next((line for line in text.splitlines()[:8] if line.startswith("Status:")), "")
        return status.removeprefix("Status:").strip().replace("**","") or "Maturity not declared in source metadata"
    except (OSError, UnicodeError):
        return "Documentation unavailable"


def _document_version(root, relative):
    try:
        heading=(root/relative).read_text(encoding="utf-8").splitlines()[0]
        match=re.search(r"\bV(\d+(?:\.\d+)*)\b",heading,re.IGNORECASE)
        return match.group(1) if match else "Not declared"
    except (OSError,UnicodeError,IndexError):
        return "Unavailable"


def _see_contract(root):
    """Inspect literal metadata without importing the frozen, consumer-free toolkit."""
    source = "board_analysis/static_exchange_models.py"
    result = dict(source=source, provenance=None, authoritative_for_tactic_truth=None,
                  safe_for_hard_rejection=None)
    try:
        tree = ast.parse((root/source).read_text(encoding="utf-8"))
        model = next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=="StaticExchangeResult")
        for node in model.body:
            if (isinstance(node,ast.AnnAssign) and isinstance(node.target,ast.Name)
                    and node.target.id in result and isinstance(node.value,ast.Call)):
                value = next((item.value for item in node.value.keywords if item.arg=="default"),None)
                if isinstance(value,ast.Constant):
                    result[node.target.id] = value.value
    except (OSError,UnicodeError,SyntaxError,StopIteration):
        pass
    return result


def capability_status(root, candidate_counts):
    root = Path(root)
    registered = [dict(key=key, name=item.label, analyzer_version=str(item.analyzer_version),
        screener_version=str(item.screener_version), scout_version=str(item.scout_version),
        registered=True, activation="Central crawler registration; not a running/enabled scheduler state",
        maturity="Not declared in registry", candidate_rows=candidate_counts.get(key,0) if candidate_counts is not None else None,
        implementation=item.heavy.__module__+"."+item.heavy.__name__,
        source="analysis_registry.ANALYZERS") for key,item in ANALYZERS.items()]
    other = [dict(key=key,name=name,kind=kind,available=(root/module).is_file(),
                  status=_document_status(root,doc),version=_document_version(root,doc),source=doc,implementation=module,
                  activation="Report-only; not in central crawler" if kind=="analyzer" else "Reusable fact provider")
             for key,name,kind,doc,module in DOCUMENTED_COMPONENTS]
    see=next(item for item in other if item["key"]=="see")
    see["contract"] = _see_contract(root)
    see["description"] = ("Advisory only; not authoritative for tactic truth. No production analyzer consumers per the documented freeze."
        if see["contract"]["authoritative_for_tactic_truth"] is False
        and see["contract"]["safe_for_hard_rejection"] is False
        else "Contract flags unavailable or changed; consult the installed source.")
    return dict(registered_analyzers=registered, other_capabilities=other,
        candidate_verifiers=[dict(key=key,version=str(item.analyzer_version),source="candidate_verification_registry.CANDIDATE_VERIFIERS")
                             for key,item in CANDIDATE_VERIFIERS.items()],
        opt_in_discovery_workflows=[dict(key=key,factory=value.__module__+"."+value.__name__,
                                       source="discovery_registry.DISCOVERY_ANALYZERS",
                                       activation="Explicit opt-in workflow; not the default crawler")
                                   for key,value in DISCOVERY_ANALYZERS.items()],
        note="Candidate counts include all stored statuses/versions; they do not certify current analyzer truth.")


def profile_status():
    return dict(selection="No global active analysis-profile preference exists. Callers choose their profile.",
        default_model=asdict(AnalysisProfile()), presets={key:asdict(value) for key,value in BUILTIN_PROFILES.items()},
        typed_schema={key:[item.to_schema() for item in value.schema()] for key,value in BUILTIN_PROFILES.items()},
        position_cache_profiles=PROFILES, source="analysis_settings.BUILTIN_PROFILES; engine_cache.PROFILES",
        editing="Read-only: no supported persistent analysis-settings mutation path is activated.")
