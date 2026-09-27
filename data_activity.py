"""Cross-process exclusion for supported import, analysis and data-management jobs."""
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator
from contextlib import AbstractContextManager
import os


class DataBusyError(RuntimeError):
    """Report an existing supported writer instead of waiting silently."""


@contextmanager
def _exclusive_file_lock(path: Path, message: str) -> Iterator[None]:
    """OS-held lock survives neither crashes nor process exit; no stale lock ownership."""
    stream = path.open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise DataBusyError(message) from error
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise DataBusyError(message) from error
        locked = True
        yield
    finally:
        if locked:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()
        # Keep the empty lock file: unlinking it could split concurrent lock ownership.


def exclusive_data_activity(database_path: str | Path) -> AbstractContextManager[None]:
    """Exclude supported writers without blocking read-only Review.

    Args:
        database_path: Database whose activity lock will be held.

    Returns:
        An OS-lock context released on exit, including process crashes.

    Raises:
        DataBusyError: Another supported writer owns the database.
        OSError: The lock file cannot be opened.
    """
    return _exclusive_file_lock(Path(str(Path(database_path).resolve()) + ".activity-lock"),
        "Import, analysis or data management is already running. Wait for it to finish.")


def exclusive_analysis_activity(database_path: str | Path) -> AbstractContextManager[None]:
    """Own the sole analysis worker for a resolved database path.

    Args:
        database_path: Database identity shared across processes.

    Returns:
        A lock context; an empty stale file never implies stale ownership.

    Raises:
        DataBusyError: An analysis session already owns this database.
        OSError: The lock file cannot be opened.
    """
    return _exclusive_file_lock(Path(str(Path(database_path).resolve()) + ".analysis-lock"),
        "Another ChessWizard analysis session is already running for this database.")
