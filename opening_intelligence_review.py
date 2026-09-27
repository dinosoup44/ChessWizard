"""One-result read-through session for Review; revalidate book and game inputs on refresh."""
from pathlib import Path
from opening_book_reader import read_book
from opening_intelligence_lookup import OpeningBookLookup
from opening_intelligence_service import OpeningIntelligenceService
from opening_intelligence_models import identity


class OpeningReviewSession:
    def __init__(self,database_path):
        self.database_path=Path(database_path).resolve()
        self.library_path=None;self.book_id=None;self.lookup=None;self.assessment=None;self._key=None

    def select(self,library_path,book_id,*,library_identity=None):
        """Managed references supply their stable installation identity across consumers."""
        lookup=(OpeningBookLookup.from_library(library_path,book_id) if library_identity is None else
                OpeningBookLookup(read_book(library_path,book_id),library_identity=library_identity))
        self.library_path=Path(library_path).resolve();self.book_id=book_id
        self.lookup=lookup;self.assessment=None;self._key=None

    def refresh(self,game,moves,*,force=False):
        if self.library_path is None or game is None:
            self.assessment=None;self._key=None;return None
        # Read a coherent snapshot instead of trusting timestamps (including WAL).
        snapshot=read_book(self.library_path,self.book_id)
        if snapshot.identity!=self.lookup.provenance.content_identity:
            self.lookup=OpeningBookLookup(snapshot,library_identity=self.lookup.provenance.library_identity,policy=self.lookup.policy)
        key=identity((self.lookup.provenance.content_identity,game,moves))
        if force or key!=self._key:
            self.assessment=None;self._key=None
            assessment=OpeningIntelligenceService(self.database_path,self.lookup).assess_game(game['game_id'])
            if tuple((m.move_id,m.played_uci) for m in assessment.moves)!=tuple((m['move_id'],m['uci_played']) for m in moves):
                raise ValueError('Game changed; reload Game Review before viewing opening facts.')
            self.assessment=assessment;self._key=key
        return self.assessment
