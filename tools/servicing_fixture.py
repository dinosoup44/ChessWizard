"""Explicit disposable Windows fixture creation and immutable safety snapshots."""
import json
from pathlib import Path
import tempfile
from servicing_inventory import file_hash
from servicing_paths import FIXTURE_MARKER, checked_path, tree_files, validate_roots


def initialize_fixture(root: Path, profile: Path) -> Path:
    """Create a new marked fixture only directly under the OS temporary directory.

    Args:
        root: Explicit new path named chesswizard-servicing-*.
        profile: Explicit root/profile destination.

    Returns:
        Written disposable marker path.

    Raises:
        ValueError: Paths resemble a live installation, overlap, or already exist.
    """
    root = checked_path(root)
    if root.parent != checked_path(Path(tempfile.gettempdir())) or not root.name.startswith("chesswizard-servicing-") or root.exists() or profile != root / "profile":
        raise ValueError("Choose a new explicitly disposable temporary fixture and its profile child")
    root.mkdir()
    marker = root / FIXTURE_MARKER
    marker.write_text(json.dumps({"schema_version": 1, "root": str(root), "purpose": "disposable-servicing-test"}), encoding="utf-8")
    validate_roots(root / "app", profile, marker)
    return marker


def snapshot(root: Path) -> dict[str, str]:
    """Hash a test tree without following links.

    Args:
        root: Explicit fixture subtree.

    Returns:
        Relative file names and SHA256 digests.
    """
    return {p.relative_to(root).as_posix(): file_hash(p) for p in tree_files(root)}


def populate_profile(profile: Path) -> dict[str, str]:
    """Create synthetic chess, settings, review, and edited-opening data offline.

    Args:
        profile: Validated disposable user-data directory.

    Returns:
        Protected byte hashes before servicing.
    """
    import io
    from contextlib import closing
    import sqlite3
    import chess
    import chess.pgn
    import import_games
    from database_bootstrap import ensure_database
    from game_import_repository import GameImportRepository
    from opening_book_models import BookDetails, MoveDetails
    from opening_book_repository import OpeningBookRepository
    from opening_book_service import OpeningBookService
    from application_settings import ApplicationSettings, ApplicationSettingsRepository
    ensure_database(profile / 'merlin.db')
    ApplicationSettingsRepository(profile/'settings.json').save(ApplicationSettings(show_last_move=False))
    pgn = '[Event "Synthetic servicing test"]\n[Site "https://lichess.org/AbCdEfGh"]\n[White "ExampleWhite"]\n[Black "ExampleBlack"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 1-0\n'
    game = chess.pgn.read_game(io.StringIO(pgn))
    with closing(sqlite3.connect(profile / 'merlin.db')) as db:
        assert GameImportRepository(db).import_game(import_games, 'ExampleWhite', game, pgn)
        assert db.execute('SELECT count(*) FROM games').fetchone()[0] == 1
        assert db.execute('PRAGMA quick_check').fetchall() == [('ok',)]
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    directory = profile / 'opening_books'
    directory.mkdir(parents=True, exist_ok=True)
    repository = OpeningBookRepository.create(directory / 'synthetic-edited.cwbook')
    try:
        service = OpeningBookService(repository)
        book = service.create_book(BookDetails('Synthetic edited opening'))
        service.save_move(book, chess.STARTING_FEN, 'e2e4', MoveDetails(move_note='Preserve this authored content'))
    finally:
        repository.close()
    for name, value in {'reviews/synthetic.json':'{"review": "preserve"}',
                        'themes/synthetic/theme.json':'{"name": "synthetic"}',
                        'cache/synthetic.txt':'preserve cache bytes'}.items():
        target = profile / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding='utf-8')
    return snapshot(profile)
