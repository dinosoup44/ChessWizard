"""Flat reusable managed-book choices; containers remain internal identity plumbing."""
from dataclasses import dataclass
from opening_library_service import OpeningLibraryService
from opening_repertoire import RepertoireSide
from opening_library_metadata import managed_book_headers, header_labels


@dataclass(frozen=True)
class ManagedBookChoice:
    """Describe one usable book without exposing a physical storage path.

    Args:
        reference_id: Stable installed-book identity used to resolve its container.
        library_id: Internal namespace for the local book ID.
        book_id: Library-local book ID.
        name: Friendly authored title.
        label: Unique display label, disambiguated only when names collide.
        library_name: Friendly origin context, never a file path.
        status: Draft, active or archived authoring status.
        repertoire_side: Explicit intent, or None for unconfigured legacy books.
        version: Authored book version.
        revision: Content revision used for refresh checks.
        content_identity: Not populated by metadata listing; resolve the selected snapshot for truth.
    """
    reference_id: str
    library_id: str
    book_id: int
    name: str
    label: str
    library_name: str
    status: str
    repertoire_side: RepertoireSide | None
    version: str
    revision: int
    content_identity: str | None = None


def managed_book_choices(library: OpeningLibraryService) -> tuple[ManagedBookChoice, ...]:
    """List all usable manual choices, including Draft/Archived and disabled books.

    Args:
        library: Shared managed-library service; no game analysis is performed.

    Returns:
        Stable sorted choices with the same disambiguation used by Studio.
    """
    headers = managed_book_headers(library.repository)
    return tuple(ManagedBookChoice(h.installation_id, h.library_id, h.book.book_id,
        h.book.name, label, h.library_name, h.book.status, h.book.repertoire_side,
        h.book.version, h.book.revision) for h, label in zip(headers, header_labels(headers)))
