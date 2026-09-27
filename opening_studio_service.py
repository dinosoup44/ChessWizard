"""One authoring workspace over stable managed books; no frontend or engine imports."""
from dataclasses import dataclass, replace
import json
from opening_book_models import BookDetails
from opening_book_repository import OpeningBookRepository
from opening_book_service import OpeningBookService
from opening_book_transfer import append_books
from opening_library_package import semantic_identity
from opening_library_service import OpeningLibraryService

WORKSPACE_NAME = "My ChessWizard Opening Library"


@dataclass(frozen=True)
class StudioImportEntry:
    book_id: int
    name: str
    version: str
    author: str
    duplicate_id: str | None
    name_conflict: bool


class OpeningStudioService:
    """Legacy files remain in place; a single durable home receives new books."""
    def __init__(self, library=None):
        self.library = library or OpeningLibraryService()

    def books(self):
        return tuple(sorted(self.library.list_books(), key=lambda b:(b.snapshot.book.name.casefold(), b.library_name, b.installation_id)))

    def labels(self, books):
        names = [b.snapshot.book.name for b in books]
        labels = []
        for book in books:
            name = book.snapshot.book.name
            label = name if names.count(name)==1 else f"{name} — {book.library_name}"
            base = label; counter = 2
            while label in labels:
                label = f"{base} ({counter})"; counter += 1
            labels.append(label)
        return tuple(labels)

    def home(self, *, create=False):
        return self.library.authoring_library(create=create)

    @staticmethod
    def draft():
        repo = OpeningBookRepository.in_memory()
        OpeningBookService(repo).create_book(BookDetails("New book", status="active"))
        return repo

    def commit_draft(self, snapshot, title):
        details = BookDetails(title.strip(), snapshot.book.description, snapshot.book.version,
                              snapshot.book.status, snapshot.book.metadata_json)
        snapshot = replace(snapshot, book=replace(snapshot.book, name=details.name))
        home = self.home(create=True)
        repo = OpeningBookRepository.open(home.path)
        try:bid, = append_books(repo, (snapshot,))
        finally:repo.close()
        return self.library.get(f"{home.library_id}:{bid}")

    def preview(self, package):
        books = self.books()
        identities = {semantic_identity(b.snapshot):b.installation_id for b in books}
        names = {b.snapshot.book.name.casefold() for b in books}
        return tuple(StudioImportEntry(s.book.book_id,s.book.name,s.book.version,
                    str(json.loads(s.book.metadata_json).get('author','')),
                    identities.get(semantic_identity(s)),s.book.name.casefold() in names)
                     for s in package.books)

    def import_selected(self, path, preview, selected_ids):
        if self.library.preview_import(path)!=preview:raise ValueError("The source changed. Preview it again before importing.")
        selected = tuple(dict.fromkeys(selected_ids))
        if not selected:raise ValueError("Select at least one book.")
        snapshots = {s.book.book_id:s for s in preview.books}
        if any(bid not in snapshots for bid in selected):raise ValueError("Select books from this preview.")
        entries = {e.book_id:e for e in self.preview(preview)}
        results = {}; pending = []; identities = {}
        for bid in selected:
            entry = entries[bid]
            if entry.duplicate_id:results[bid] = entry.duplicate_id
            else:
                identity = semantic_identity(snapshots[bid])
                identities.setdefault(identity, []).append(bid)
                if len(identities[identity])==1:pending.append(snapshots[bid])
        if pending:
            home = self.home(create=True)
            repo = OpeningBookRepository.open(home.path)
            try:new_ids = append_books(repo,pending)
            finally:repo.close()
            for snapshot,new_id in zip(pending,new_ids):
                reference = f"{home.library_id}:{new_id}"
                for bid in identities[semantic_identity(snapshot)]:results[bid] = reference
        return tuple(self.library.get(results[bid]) for bid in selected)
