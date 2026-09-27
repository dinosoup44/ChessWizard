"""Installed opening references are profile data, independent of game databases."""
from dataclasses import dataclass
from pathlib import Path
from opening_book_models import BookSnapshot
from opening_intelligence_models import OpeningGameAssessment


@dataclass(frozen=True)
class InstalledBook:
    installation_id: str
    path: Path
    snapshot: BookSnapshot | None
    enabled: bool
    primary: bool
    origin: str
    provenance_json: str
    error: str = ''
    library_id: str = ''
    library_name: str = ''

    @property
    def label(self):
        if self.snapshot is None:return f'Unavailable · {self.installation_id[:8]}'
        b=self.snapshot.book
        return f'{b.name} · v{b.version} · {self.installation_id[:8]}'


@dataclass(frozen=True)
class ImportResult:
    installation_id: str
    already_installed: bool


@dataclass(frozen=True)
class RemovalPreview:
    installation_id: str
    content_identity: str
    label: str
    enabled: bool
    primary: bool
    origin: str
    selected_in_review: bool
    cached_assessments: str = 'Session-only facts are cleared; no persisted assessments.'


@dataclass(frozen=True)
class RelevantBook:
    installation_id: str
    version: str
    content_identity: str
    matched_plies: int
    longest_authored_run: int
    deepest_variation: str | None
    primary: bool
    assessment: OpeningGameAssessment


@dataclass(frozen=True)
class ReferenceChoice:
    selected_id: str | None
    relevant: tuple[RelevantBook, ...]
    reason: str
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManagedLibrary:
    library_id: str
    name: str
    path: Path
    books: tuple[InstalledBook, ...]
    origin: str
    error: str = ''


@dataclass(frozen=True)
class ManualOpeningSelection:
    """Review-session intent; an instance with no book means explicit None, not Auto."""
    library_id: str | None
    book_reference_id: str | None
