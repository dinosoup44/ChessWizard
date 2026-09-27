"""Register independent screeners, scouts, and single-move specialists here."""
from dataclasses import dataclass
from typing import Callable

from analysis_scout import SCOUT_VERSION, scout_fork, scout_mate, fork_scout_config, mate_scout_config
from tactic_screeners import fork_screener
from heavy_adapters import fork_adapter, mate_adapter
from pin_geometry import pin_screener, SCREENER_VERSION as PIN_SCREENER_VERSION
from pin_scout import scout_pin, pin_scout_config, SCOUT_VERSION as PIN_SCOUT_VERSION
from pin_adapter_v2 import pin_adapter
from analyze_pins_v2 import ANALYZER_VERSION as PIN_ANALYZER_VERSION
from skewer_geometry import skewer_screener, SCREENER_VERSION as SKEWER_SCREENER_VERSION
from skewer_scout import scout_skewer, skewer_scout_config, SCOUT_VERSION as SKEWER_SCOUT_VERSION
from skewer_adapter import skewer_adapter
from analyze_skewers import ANALYZER_VERSION as SKEWER_ANALYZER_VERSION
from xray_geometry import xray_screener, SCREENER_VERSION as XRAY_SCREENER_VERSION
from xray_scout import scout_xray, xray_scout_config, SCOUT_VERSION as XRAY_SCOUT_VERSION
from xray_adapter import xray_adapter
from analyze_xrays import ANALYZER_VERSION as XRAY_ANALYZER_VERSION
from xray_preflight import (preflight_existing_evidence as xray_existing_preflight,
                            deferred_contract_identity as xray_deferred_contract)


@dataclass(frozen=True)
class AnalyzerDefinition:
    """Register independent calculation and completion contracts.

    Args:
        analysis_type: Stable tactic-family identifier.
        label: Display name.
        screener_version: Static-rule identity.
        analyzer_version: Heavy specialist identity.
        has_safe_screener: Whether static negatives may be persisted.
        screener: Pure static screening function.
        scout: Shared-evidence scout function.
        scout_config: Current shared scout request/policy identity.
        heavy: Single-position specialist returning structured results.
        scout_version: Scout-rule version.
        screen_rejection_reason: Diagnostic for safe static negatives.
        deduplicate_opportunities: Enable shared canonical ownership protection.
        preflight_existing_evidence: Optional read-only planning predicate.
        deferred_contract: Optional exact preflight policy identity; absence forbids receipts.
    """
    analysis_type: str
    label: str
    screener_version: str
    analyzer_version: str
    has_safe_screener: bool
    screener: Callable
    scout: Callable
    scout_config: Callable
    heavy: Callable
    scout_version: str = SCOUT_VERSION
    screen_rejection_reason: str = "safe_static_rejection"
    deduplicate_opportunities: bool = False
    preflight_existing_evidence: Callable | None = None
    deferred_contract: Callable[[], dict] | None = None


def pass_through_screen(row):
    return True


ANALYZERS = {
    "missed_fork": AnalyzerDefinition(
        "missed_fork", "Missed Fork", "2", "2", True,
        fork_screener, scout_fork, fork_scout_config, fork_adapter,
        screen_rejection_reason="no_unplayed_fork_geometry",
    ),
    "missed_mate": AnalyzerDefinition(
        "missed_mate", "Missed Mate", "0", "3", False,
        pass_through_screen, scout_mate, mate_scout_config, mate_adapter,
    ),
    "missed_pin": AnalyzerDefinition(
        "missed_pin", "Missed Pin", PIN_SCREENER_VERSION, PIN_ANALYZER_VERSION, True,
        pin_screener, scout_pin, pin_scout_config, pin_adapter,
        scout_version=PIN_SCOUT_VERSION, screen_rejection_reason="no_new_direct_slider_pin",
    ),
    "missed_skewer": AnalyzerDefinition(
        "missed_skewer", "Missed Skewer", SKEWER_SCREENER_VERSION, SKEWER_ANALYZER_VERSION, True,
        skewer_screener, scout_skewer, skewer_scout_config, skewer_adapter,
        scout_version=SKEWER_SCOUT_VERSION, screen_rejection_reason="no_new_direct_slider_skewer",
    ),
    "missed_xray": AnalyzerDefinition(
        "missed_xray", "Missed X-ray", XRAY_SCREENER_VERSION, XRAY_ANALYZER_VERSION, True,
        xray_screener, scout_xray, xray_scout_config, xray_adapter,
        scout_version=XRAY_SCOUT_VERSION, screen_rejection_reason="no_new_direct_slider_xray",
        deduplicate_opportunities=True,
        preflight_existing_evidence=xray_existing_preflight,
        deferred_contract=xray_deferred_contract,
    ),
}
