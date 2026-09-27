"""Read-only opening headers for selectors; graph evidence is resolved separately."""
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from opening_book_models import OpeningBook
from opening_book_reader import read_books, read_book
from opening_library_catalog import LibraryOptions
from opening_library_models import InstalledBook
from opening_library_repository import OpeningLibraryRepository


@dataclass(frozen=True)
class ManagedBookHeader:
    """Describe a selectable opening without loading positions or move graphs.

    Args:
        installation_id: Stable managed reference, including legacy bare IDs.
        library_id: Managed file namespace.
        library_name: Friendly container name.
        path: Canonical managed file.
        book: Header row with authored revision and side metadata.
        enabled: Catalog eligibility for automatic consumers.
        primary: Catalog reference preference, not an implicit UI selection.
        origin: Catalog source description.
        provenance_json: Existing catalog envelope.
    """
    installation_id: str
    library_id: str
    library_name: str
    path: Path
    book: OpeningBook
    enabled: bool
    primary: bool
    origin: str
    provenance_json: str


def managed_book_headers(repository: OpeningLibraryRepository) -> tuple[ManagedBookHeader, ...]:
    """Read catalog and book metadata only; unavailable files are not selectable.

    Args:
        repository: Managed directory and read-only catalog accessor.

    Returns:
        Sorted authoring choices, including disabled, draft and archived books.
    """
    result = []
    for row in repository.rows():
        library_id = row['installation_id']
        path = repository.path(library_id)
        try:
            books = read_books(path)
            options = LibraryOptions.from_row(row, tuple(SimpleNamespace(book=b) for b in books))
            deleted = set(json.loads(row['provenance_json']).get('studio_deleted_books', ()))
            for book in books:
                if book.book_id not in deleted:
                    result.append(ManagedBookHeader(options.reference_id(library_id, book.book_id),
                        library_id, options.name, path, book, options.enabled(book.book_id),
                        options.primary_book_id == book.book_id, row['origin'], row['provenance_json']))
        except (ValueError, OSError, sqlite3.Error):
            continue
    return tuple(sorted(result, key=lambda h: (h.book.name.casefold(), h.library_name, h.installation_id)))


def header_labels(headers: tuple[ManagedBookHeader, ...]) -> tuple[str, ...]:
    """Disambiguate friendly labels consistently without graph inspection.

    Args:
        headers: Ordered metadata choices.

    Returns:
        Unique labels in the same order.
    """
    from collections import Counter
    counts = Counter(h.book.name for h in headers)
    labels = []
    for header in headers:
        base = header.book.name if counts[header.book.name] == 1 else f'{header.book.name} — {header.library_name}'
        label, counter = base, 2
        while label in labels:
            label = f'{base} ({counter})'; counter += 1
        labels.append(label)
    return tuple(labels)


def resolve_managed_book(repository: OpeningLibraryRepository, reference_id: str) -> InstalledBook:
    """Load only the explicitly selected graph through the shared read-only reader.

    Args:
        repository: Managed catalog accessor.
        reference_id: Exact header identity, never an external path.

    Returns:
        Selected immutable book and catalog provenance.

    Raises:
        ValueError: The selected opening is unavailable or was removed.
        sqlite3.Error: The selected file cannot be read coherently.
    """
    header = next((h for h in managed_book_headers(repository) if h.installation_id == reference_id), None)
    if header is None:
        raise ValueError('Book is no longer installed.')
    snapshot = read_book(header.path, header.book.book_id)
    return InstalledBook(header.installation_id, header.path, snapshot, header.enabled, header.primary,
        header.origin, header.provenance_json, library_id=header.library_id, library_name=header.library_name)


def library_fingerprint(repository: OpeningLibraryRepository) -> tuple[tuple[str, int, int], ...]:
    """Detect committed file changes, including SQLite journals and WAL files.

    Args:
        repository: Managed directory to inspect without opening graph data.

    Returns:
        File names, nanosecond modification times and sizes; not a chess identity.
    """
    if not repository.root.exists():
        return ()
    result = []
    for path in sorted(repository.root.iterdir()):
        if path.name.startswith('catalog.sqlite') or '.cwbook' in path.name:
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            result.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(result)
