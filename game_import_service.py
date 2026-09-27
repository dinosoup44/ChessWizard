"""Username import orchestration over existing providers, isolated from desktop UI."""
import http.client
from pathlib import Path
import re
import sqlite3
import threading
import import_chesscom
import import_games
from data_activity import exclusive_data_activity, DataBusyError
from collections.abc import Callable
from game_import_pgn import EmptyImportedGame
from game_import_models import ImportProgress, ImportResult, SOURCE_LABELS
from game_import_repository import GameImportRepository, remembered_accounts

PROVIDERS = {"chesscom": import_chesscom, "lichess": import_games}
MAX_ERROR_DETAILS = 10
PROGRESS_EVERY_GAMES = 25
DATABASE_BUSY_TIMEOUT_SECONDS = 5
_import_lock = threading.Lock()


class GameImportService:
    """Own one worker connection; never hold a DB transaction during network waits."""
    def __init__(self, database_path):
        self.database_path = Path(database_path).resolve()

    def accounts(self):
        return remembered_accounts(self.database_path)

    def run(self, source: str, username: str, *, progress: Callable[[ImportProgress], None] = lambda event: None,
            cancel: threading.Event | None = None) -> ImportResult:
        """Import completed games, reporting empty records without inserting them.

        Args:
            source: Supported canonical provider.
            username: Account name, not a URL.
            progress: Worker-thread notifications.
            cancel: Optional signal to stop between downloads/transactions.

        Returns:
            Counts of committed, duplicate, ignored, empty and failed records.
        """
        username = username.strip()
        if source not in PROVIDERS or not re.fullmatch(r"[A-Za-z0-9_-]{2,50}", username):
            return ImportResult(source, username, errors=1, details=("Choose a supported source and enter a valid username (no URL).",))
        if cancel is not None and cancel.is_set():
            return ImportResult(source, username, cancelled=True)
        if not _import_lock.acquire(blocking=False):
            return ImportResult(source, username, errors=1, details=("Another import is running. Wait for it to finish.",))
        try:
            with exclusive_data_activity(self.database_path):
                return self._run(source, username, progress, cancel or threading.Event())
        except (DataBusyError, OSError) as error:
            return ImportResult(source, username, errors=1, details=(str(error),))
        finally:
            _import_lock.release()

    def _run(self, source, username, progress, cancel):
        found = added = existing = ignored = errors = skipped_empty = 0
        details = []
        connection = None
        provider = PROVIDERS[source]
        def status(message):
            progress(ImportProgress(message, found, added, existing, errors, ignored, skipped_empty))
        def fail(message):
            nonlocal errors
            errors += 1
            if len(details) < MAX_ERROR_DETAILS:
                details.append(message)
        try:
            connection = sqlite3.connect(self.database_path.as_uri() + "?mode=rw", uri=True, timeout=DATABASE_BUSY_TIMEOUT_SECONDS)
            connection.execute("PRAGMA foreign_keys=ON")
            repository = GameImportRepository(connection)
            status("Connecting to " + SOURCE_LABELS[source] + "...")
            archives = provider.get_archive_urls(username) if source == "chesscom" else [None]
            for number, archive in enumerate(reversed(archives), 1):
                if cancel.is_set():
                    break
                status(f"Downloading archive {number} / {len(archives)}..." if archive else "Downloading and importing games...")
                context = (provider.download_archive_pgn(archive, stream=True) if archive else
                           provider.download_games(username, max_games=None, stream=True))
                with context as stream:
                    for game, raw in provider.split_pgn_games(stream):
                        if cancel.is_set():
                            break
                        found += 1
                        try:
                            if repository.import_game(provider, username, game, raw):
                                added += 1
                            elif repository.last_ignored:
                                ignored += 1
                            else:
                                existing += 1
                        except EmptyImportedGame:
                            skipped_empty += 1
                        except ValueError as error:
                            fail(str(error))
                        if found % PROGRESS_EVERY_GAMES == 0:
                            status(f"Processed {found:,} received games...")
            if not cancel.is_set() and not errors:
                repository.completed_account(source, username)
        except (OSError, ValueError, sqlite3.Error, http.client.HTTPException) as error:
            fail(str(error) if isinstance(error, (ValueError, sqlite3.Error)) else "Download interrupted. Successfully imported games were kept; retry when connected.")
        finally:
            if connection is not None:
                connection.close()
        status("Stopped." if cancel.is_set() else "Finished.")
        return ImportResult(source, username, found, added, existing, errors, tuple(details), cancel.is_set(), ignored, skipped_empty)
