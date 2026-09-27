"""Explicit first-install seeding into editable user storage; reads never seed."""
import hashlib
import json
from pathlib import Path
import uuid
from application_paths import application_root
from opening_library_repository import OpeningLibraryRepository
from opening_library_service import OpeningLibraryService
from opening_library_models import ManagedLibrary
from opening_library_package import inspect_package, write_library_package

DEFAULT_LIBRARY_NAME = 'ChessWizard Default Openings'


def seed_default_openings(repository: OpeningLibraryRepository | None = None,
                          bundle: Path | None = None) -> ManagedLibrary | None:
    """Copy trusted default content once without replacing an existing profile.

    Args:
        repository: Managed writable user-library catalog; never the game database.
        bundle: Immutable shipped content directory, overridable for isolated tests.

    Returns:
        Newly installed editable library, or None for any existing library catalog
        or authored files. Later launches never overwrite customized/default content.

    Raises:
        ValueError: Bundle hashes, package or provenance fail validation.
        OSError: User storage cannot be written.
    """
    repo = repository or OpeningLibraryRepository()
    if repo.catalog.exists() or any(repo.root.glob('*.cwbook')):
        return None
    bundle = bundle or application_root() / 'assets' / 'openings'
    source = bundle / f'{DEFAULT_LIBRARY_NAME}.cwbook'
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest['cwbook_sha256']:
        raise ValueError('Default opening content hash mismatch.')
    preview = inspect_package(source)
    identifier = str(uuid.uuid4())
    destination = repo.path(identifier)
    created = False
    try:
        with repo.write() as db:
            if db.execute('SELECT 1 FROM installed_books LIMIT 1').fetchone():
                return None
            write_library_package(preview.books, destination)
            created = True
            provenance = dict(library_name=DEFAULT_LIBRARY_NAME, library_contract=2,
                studio_home=True, default_content_version=1, source=manifest['source'],
                source_file_sha256=preview.file_sha256)
            db.execute('INSERT INTO installed_books VALUES (?,1,0,?,?)',
                       (identifier, 'bundled editable default', json.dumps(provenance, sort_keys=True)))
    except BaseException:
        if created:
            destination.unlink()
        raise
    return OpeningLibraryService(repo).get_library(identifier)
