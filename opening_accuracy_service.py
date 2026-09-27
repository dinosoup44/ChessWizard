"""Read-only managed opening metrics using exact stored Move Quality evidence."""
from contextlib import closing
from pathlib import Path
import sqlite3
from opening_intelligence_managed import ManagedOpeningIntelligenceService
from opening_intelligence_service import OpeningIntelligenceService
from opening_intelligence_models import OpeningFailure
from move_quality_repository import MoveQualityRepository
from opening_accuracy import variation_accuracy
from opening_accuracy_evidence import assess_opening_evidence
from collections.abc import Iterable
from opening_accuracy_settings import OpeningAccuracySettings
from opening_accuracy_models import (OpeningAccuracyBatch, OpeningVariationAccuracySummary,
                                     OpeningDeviationQualitySummary)


class OpeningAccuracyService:
    def __init__(self, database_path, library=None, *, settings=OpeningAccuracySettings()):
        self.path = Path(database_path).resolve()
        self.books = ManagedOpeningIntelligenceService(self.path, library)
        self.settings = settings

    def get_opening_accuracy(self, game_id, library_id, book_id):
        batch = self.get_opening_accuracy_for_games(library_id, book_id, (game_id,))
        if batch.errors: raise ValueError(batch.errors[0].reason)
        return batch.results[0]

    def get_opening_accuracy_for_games(self, library_id: str, book_id: int,
                                      game_ids: Iterable[int]) -> OpeningAccuracyBatch:
        """Join book facts and existing quality evidence in one read transaction.

        Args:
            library_id: Installed library identity.
            book_id: Library-local book identifier.
            game_ids: Explicit database-local game scope.

        Returns:
            Existing window scores and separately reported game failures.

        Raises:
            ValueError: Scope or selected book is invalid.
            sqlite3.Error: The read snapshot cannot be opened.
        """
        lookup = self.books.lookup_for_book(library_id, book_id)
        facts = OpeningIntelligenceService(self.path, lookup)
        ids = tuple(dict.fromkeys(game_ids))
        if any(type(gid) is not int or gid <= 0 for gid in ids): raise ValueError('Use positive game IDs.')
        results, errors = [], []
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
            quality = MoveQualityRepository(db, self.settings.quality)
            for game_id in ids:
                try:
                    assessment = facts.assess_game_in_snapshot(db, game_id)
                    results.append(assess_opening_evidence(assessment, quality,
                        lookup.policy, self.settings).accuracy)
                except (ValueError,KeyError,TypeError,sqlite3.Error) as error:
                    errors.append(OpeningFailure(game_id,str(error)))
        return OpeningAccuracyBatch(tuple(results), tuple(errors))

    def get_variation_accuracy_summary(self, library_id, book_id, game_ids):
        batch = self.get_opening_accuracy_for_games(library_id,book_id,game_ids)
        return OpeningVariationAccuracySummary(variation_accuracy(batch.results),batch.errors,batch.results)

    def get_opening_deviation_quality(self, library_id, book_id, game_ids):
        """All scoped deviations, with party/position/book identity for later grouping."""
        batch = self.get_opening_accuracy_for_games(library_id,book_id,game_ids)
        return OpeningDeviationQualitySummary(tuple(row for game in batch.results for row in game.moves if row.book.deviation),
                                              batch.errors,batch.results)
