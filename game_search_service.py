"""Portable Game Explorer boundary: the caller's database only, no bootstrap or writes."""
from contextlib import closing
from pathlib import Path
import sqlite3
from game_search_models import GameSearchCriteria
from game_search_repository import GameSearchRepository
from game_search_tactics import OccurrenceEvidenceSelection


class GameSearchService:
    def __init__(self, database_path, *, occurrence_selection=OccurrenceEvidenceSelection()):
        self.path = Path(database_path).resolve()
        self.occurrence_selection = occurrence_selection

    def _connect(self):
        db = sqlite3.connect(self.path.as_uri()+"?mode=ro", uri=True)
        db.execute("PRAGMA query_only=ON")
        return db

    def search(self, criteria=GameSearchCriteria()):
        with closing(self._connect()) as db:
            # One read snapshot keeps metadata, candidate visibility and scores consistent.
            db.execute("BEGIN")
            return GameSearchRepository(db, occurrence_selection=self.occurrence_selection).search(criteria)

    def options(self):
        with closing(self._connect()) as db:
            return GameSearchRepository(db).options()


    def search_openings(self, lookup, criteria=GameSearchCriteria(), *, opening_query=None):
        """Compose existing metadata/collection filters with read-only opening facts.

        No opening SQL/cache columns are required. The returned opening batch has
        exact matching game IDs plus failures, suitable for future Explorer/lessons.
        """
        from opening_intelligence_service import OpeningIntelligenceService
        from opening_intelligence_models import OpeningQuery
        ids=tuple(row.game_id for row in self.search(criteria).games)
        return OpeningIntelligenceService(self.path,lookup).get_games_for_opening(
            ids,OpeningQuery() if opening_query is None else opening_query)
