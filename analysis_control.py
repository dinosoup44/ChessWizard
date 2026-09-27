"""Cooperative cancellation for analysis workers, independent of any frontend."""
from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
from threading import Event


class AnalysisCancelled(BaseException):
    """Signal Stop without turning cancelled computation into failed chess evidence.

    Specialists catch Exception to return retryable results. Cancellation bypasses
    those handlers so it cannot become coverage or cached partial evidence.
    """


def check_cancelled(cancel: Event | None) -> None:
    """Raise the control-flow signal when cancellation has been requested.

    Args:
        cancel: Optional event owned by the caller.

    Raises:
        AnalysisCancelled: The event is set.
    """
    if cancel is not None and cancel.is_set():
        raise AnalysisCancelled()


@contextmanager
def cancellable_reads(connection: sqlite3.Connection, cancel: Event | None) -> Iterator[None]:
    """Make a worker's SQLite reads interruptible without taking write ownership.

    Args:
        connection: Dedicated worker connection with no other progress handler.
        cancel: Optional cooperative cancellation event.

    Yields:
        Control while SQL and Python preparation can observe cancellation.

    Raises:
        AnalysisCancelled: Preparation was stopped, including during a SQL query.
        sqlite3.OperationalError: A read failed for a reason other than Stop.
    """
    check_cancelled(cancel)
    if cancel is not None:
        connection.set_progress_handler(lambda: int(cancel.is_set()), 1000)
    try:
        yield
        check_cancelled(cancel)
    except sqlite3.OperationalError:
        check_cancelled(cancel)
        raise
    finally:
        connection.set_progress_handler(None, 0)
