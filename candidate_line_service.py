"""Cache-first shared line service. The caller chooses live/read-only/scratch stores."""
from collections import Counter
from analysis_settings import GeneratorSettings, identity
from candidate_line_request import normalized_root_moves, request_identity


class CandidateLineService:
    """Search once on cache miss; a missing write store makes the service nonpersistent."""
    def __init__(self, generator, read_stores=(), write_store=None):
        self.generator, self.read_stores, self.write_store = generator, tuple(read_stores), write_store
        self.stats = Counter()

    def candidate_lines(self, fen, settings=GeneratorSettings(), *, root_moves=()):
        """Reuse exact engine configuration only; gate and Scale remain separately current."""
        root_moves = normalized_root_moves(root_moves)
        cached = self.cached_candidate_lines(fen, settings, root_moves=root_moves)
        if cached is not None:
            return cached
        self.stats['cache_misses'] += 1
        result = self.generator.generate(fen, settings, **({'root_moves': root_moves} if root_moves else {}))
        self.stats['engine_searches'] += int(not result.generation_metadata.get('terminal'))
        if self.write_store is not None and result.generation_metadata.get('complete'):
            self.stats['cache_inserts'] += int(self.write_store.put(result))
        return result

    def cached_candidate_lines(self, fen, settings=GeneratorSettings(), *, root_moves=()):
        """Probe exact cached evidence only; never search or persist on a miss."""
        cache_key = request_identity(settings, normalized_root_moves(root_moves))
        stores = (*self.read_stores, *((self.write_store,) if self.write_store is not None else ()))
        for store in stores:
            cached = store.get(fen, cache_key)
            if cached is not None:
                self.stats['cache_hits'] += 1
                return cached
        return None
