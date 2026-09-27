"""Explicit/reference defaults reuse authored-theory facts, never engine evaluations."""
from opening_library_models import RelevantBook, ReferenceChoice, ManualOpeningSelection
from opening_library_service import OpeningLibraryService
from opening_intelligence_lookup import OpeningBookLookup
from opening_intelligence_service import OpeningIntelligenceService


class OpeningReferenceService:
    def __init__(self, database_path, library=None):
        self.database_path=database_path
        self.library=library or OpeningLibraryService()
        self.manual_selection: ManualOpeningSelection | None = None

    def select(self, game_id: int | None, installation_id: str | None) -> None:
        """Record explicit session intent using only selectable metadata.

        Args:
            game_id: Current game for API compatibility; intent spans games.
            installation_id: Managed header identity, or None to clear selection.

        Raises:
            ValueError: The selected opening is no longer available.
        """
        from opening_library_metadata import managed_book_headers
        library_id = self.manual_selection.library_id if self.manual_selection else None
        if installation_id is not None:
            header = next((h for h in managed_book_headers(self.library.repository)
                           if h.installation_id == installation_id), None)
            if header is None:
                raise ValueError('Book is no longer installed.')
            library_id = header.library_id
        self.manual_selection = ManualOpeningSelection(library_id, installation_id)

    def clear_selection(self, game_id=None):
        """Explicitly return the session to automatic reference selection."""
        self.manual_selection = None

    def select_library(self, game_id, library_id):
        if library_id is not None:
            self.library.get_library(library_id)
        self.manual_selection = ManualOpeningSelection(library_id, None)

    def selected_library(self, game_id, choice):
        if choice.selected_id:
            return self.library.get(choice.selected_id).library_id
        library_id = self.manual_selection.library_id if self.manual_selection else None
        if library_id is not None:
            try:
                self.library.get_library(library_id)
            except ValueError:
                return None
        return library_id

    def find_relevant_books(self, game_id):
        """Enabled books only; a disabled primary stays available for explicit selection."""
        matches=[];errors=[]
        for item in self.library.list_books():
            if not item.enabled or item.snapshot.book.status!='active':continue
            if item.snapshot is None:
                errors.append(item.label+': '+item.error);continue
            try:
                lookup=OpeningBookLookup(item.snapshot,library_identity=item.library_id)
                result=OpeningIntelligenceService(self.database_path,lookup).assess_game(game_id)
                if result.entered_book:
                    matches.append(RelevantBook(item.installation_id,item.snapshot.book.version,
                        result.provenance.content_identity,result.in_book_moves,result.max_consecutive_in_book_plies,
                        result.final_named_variation,item.primary,result))
            except (ValueError,OSError) as error:errors.append(item.label+': '+str(error))
        matches.sort(key=lambda m:(not m.primary,-m.longest_authored_run,m.installation_id))
        return ReferenceChoice(None,tuple(matches),'Relevance evidence',tuple(errors))

    def choose(self, game_id):
        if self.manual_selection is not None:
            selected=self.manual_selection.book_reference_id
            if selected is None:return ReferenceChoice(None,(),'Explicitly no book')
            try:
                item=self.library.get(selected)
                if item.snapshot is not None:
                    lookup=OpeningBookLookup(item.snapshot,library_identity=item.library_id)
                    assessment=OpeningIntelligenceService(self.database_path,lookup).assess_game(game_id)
                    reason='Explicit reference · '+('meaningful authored match' if assessment.entered_book else 'no meaningful match in this book')
                    return ReferenceChoice(selected,(),reason)
            except ValueError:pass
            return ReferenceChoice(None,(),'Selected reference is unavailable; choose another book')
        result=self.find_relevant_books(game_id)
        primary=next((r for r in result.relevant if r.primary),None)
        if primary:return ReferenceChoice(primary.installation_id,result.relevant,'Primary meaningfully matches',result.errors)
        if len(result.relevant)==1:return ReferenceChoice(result.relevant[0].installation_id,result.relevant,'One meaningful match',result.errors)
        if result.relevant:
            strength=lambda row:(row.longest_authored_run,row.matched_plies)
            best=max(strength(row) for row in result.relevant)
            strongest=[row for row in result.relevant if strength(row)==best]
            if len(strongest)==1:
                return ReferenceChoice(strongest[0].installation_id,result.relevant,'Strongest unambiguous authored match',result.errors)
        return ReferenceChoice(None,result.relevant,'Choose among matching books' if result.relevant else 'No enabled Active book automatically matches; manual selection is available',result.errors)
