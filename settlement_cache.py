"""Explicit settlement namespaces with provenance-preserving legacy cache reuse."""
from collections import Counter
from dataclasses import replace
from candidate_lines import to_data
from candidate_line_request import request_identity


def settlement_settings(base, settlement_plies):
    """Only the proof-family label changes; actual engine options remain identical."""
    return replace(base, engine=replace(base.engine,
        profile_id=f"{base.engine.profile_id}:settlement={settlement_plies}"))


class SettlementCacheAdapter:
    """Reuse compatible raw rows without rewriting them or implying a new search.

    The exact scoped key wins. Legacy reuse requires the exact unscoped request,
    including restrictions, and identical generator metadata. There is no fuzzy
    depth/profile or cross-engine fallback.
    """
    def __init__(self, service, base_settings, windows):
        self.service, self.base_settings = service, base_settings
        self.scopes = tuple(settlement_settings(base_settings, window) for window in windows)
        self.stats = Counter()

    def candidate_lines(self, fen, settings, *, root_moves=()):
        probe = getattr(self.service, "cached_candidate_lines", None)
        if settings not in self.scopes or not callable(probe):
            return self.service.candidate_lines(fen, settings, root_moves=root_moves)
        exact = probe(fen, settings, root_moves=root_moves)
        if exact is not None:
            self.stats['exact_hits'] += 1
            return exact
        legacy = probe(fen, self.base_settings, root_moves=root_moves)
        if legacy is None:
            return self.service.candidate_lines(fen, settings, root_moves=root_moves)
        if (legacy.engine_identity != request_identity(self.base_settings, root_moves)
                or to_data(legacy.generation_metadata.get('generator_settings')) != to_data(self.base_settings)
                or legacy.generation_metadata.get('complete') is not True):
            raise ValueError("Incompatible legacy settlement evidence")
        scoped_identity = request_identity(settings, root_moves)
        self.stats['compatible_legacy_hits'] += 1
        metadata = {**to_data(legacy.generation_metadata), 'generator_settings':to_data(settings),
            'settlement_cache_compatibility':{'rule':'identical_engine_request_except_settlement_namespace_v1',
                'source_engine_identity':legacy.engine_identity,
                'source_generator_settings':to_data(self.base_settings),
                'requested_engine_identity':scoped_identity}}
        return replace(legacy, analysis_profile=settings.engine.profile_id, engine_identity=scoped_identity,
            lines=tuple(replace(line, engine_identity=scoped_identity) for line in legacy.lines), generation_metadata=metadata)
