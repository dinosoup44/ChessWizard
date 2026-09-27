"""Read-only application facade using stable managed library and book identities."""
from collections import Counter
from opening_library_service import OpeningLibraryService
from opening_intelligence_lookup import OpeningBookLookup
from opening_intelligence_models import (
    OpeningMatchPolicy, OpeningQuery, OpeningFailure,
    OpeningVariationDistribution, OpeningDeviationResult,
)
from opening_intelligence_service import OpeningIntelligenceService, variation_distribution


class ManagedOpeningIntelligenceService:
    """Resolve a fresh book snapshot per call; never import, migrate or write results.

    Manual assessment permits Draft/Archived/disabled books. Automatic reference
    selection remains the responsibility of OpeningReferenceService.
    """

    def __init__(self, database_path, library=None, *, policy=OpeningMatchPolicy()):
        self.database_path = database_path
        self.library = library or OpeningLibraryService()
        self.policy = policy

    def lookup_for_book(self, library_id, book_id):
        """Resolve a fresh canonical snapshot for shared read-only consumers."""
        if type(book_id) is not int or book_id <= 0:
            raise ValueError('Use a positive book ID within the selected library.')
        library = self.library.get_library(library_id)
        item = next((item for item in library.books if item.snapshot.book.book_id == book_id), None)
        if item is None:
            raise ValueError('Book not found in the selected managed library.')
        lookup = OpeningBookLookup(item.snapshot, library_identity=library.library_id, policy=self.policy)
        return lookup

    def _service(self, library_id, book_id):
        return OpeningIntelligenceService(self.database_path, self.lookup_for_book(library_id, book_id))

    def assess_game_against_book(self, game_id, library_id, book_id):
        """Assess one stored game against the current canonical authored snapshot."""
        return self._service(library_id, book_id).assess_game(game_id)

    def assess_games_against_book(self, game_ids, library_id, book_id):
        """Assess an explicit deduplicated scope with one book and game DB snapshot."""
        return self._service(library_id, book_id).assess_games(game_ids)

    def get_games_for_opening_book(self, library_id, book_id, game_ids=None, *, query=OpeningQuery()):
        """Find meaningful matches; omitted scope explicitly searches all real games."""
        if query.entered_book is not True:
            raise ValueError('Find games for a book requires meaningful matches.')
        service = self._service(library_id, book_id)
        scope = service.game_ids() if game_ids is None else game_ids
        return service.get_games_for_opening(scope, query)

    def variation_distribution(self, library_id, book_id, game_ids):
        """Stream final known contexts of meaningful matches, preserving failures."""
        service = self._service(library_id, book_id)
        counts, errors = Counter(), []
        assessed = matched = 0
        for result in service.iter_games(game_ids):
            if isinstance(result, OpeningFailure):
                errors.append(result)
                continue
            assessed += 1
            matched += result.entered_book
            counts.update(variation_distribution((result,)))
        return OpeningVariationDistribution(service.lookup.provenance, tuple(sorted(counts.items())),
                                            assessed, matched, tuple(errors))

    def get_deviations(self, library_id, book_id, game_ids):
        """Return known-position departures, including leaves, with per-row provenance.

        Scope is explicit; even shallow/nonmatching games retain factual departures.
        Call get_games_for_opening_book first to limit summaries to meaningful entry.
        """
        service = self._service(library_id, book_id)
        deviations, errors = [], []
        assessed = 0
        for result in service.iter_games(game_ids):
            if isinstance(result, OpeningFailure):
                errors.append(result)
                continue
            assessed += 1
            deviations.extend(move for move in result.moves if move.deviation)
        return OpeningDeviationResult(service.lookup.provenance, tuple(deviations), assessed, tuple(errors))
