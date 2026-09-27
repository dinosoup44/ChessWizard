"""Explicit experiment registrations; default live analyzers are not silently replaced."""
from dataclasses import replace
from analysis_registry import ANALYZERS
from analysis_settings import load_profile
from fork_discovery import analyze_single_move, discovery_identity


def fork_v31():
    profile=load_profile("normal_escalation")
    def heavy(row, services):
        return analyze_single_move(row,services.breadth,services.verification,profile)
    definition=replace(ANALYZERS["missed_fork"],analyzer_version="3.1",heavy=heavy)
    return definition,profile,discovery_identity(profile)


DISCOVERY_ANALYZERS={"fork_v31":fork_v31}
