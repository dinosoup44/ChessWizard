"""Explicit composable transactions for repositories and analysis-stage owners."""
from itertools import count
import sqlite3
import time
from threading import Event
from types import TracebackType
from typing import Self
from analysis_control import check_cancelled

COMMIT_WAIT_SECONDS = 10.0

_savepoints = count()


class SqliteTransaction:
    """Own a transaction or savepoint without committing a caller's enclosing stage.

    Args:
        connection: Caller-owned SQLite connection.
        cancel: Optional Stop event, checked at entry and before commit.

    Repository commits release only their own savepoint. A repository cannot
    publish or roll back the enclosing analysis stage.
    """
    def __init__(self, connection: sqlite3.Connection, cancel: Event | None = None) -> None:
        """Initialize an inactive transaction boundary.

        Args:
            connection: Caller-owned SQLite connection.
            cancel: Optional cooperative Stop event.
        """
        self.connection, self.cancel = connection, cancel
        self.savepoint: str | None = None
        self.active = False

    def begin(self) -> Self:
        """Begin a transaction, nesting with a savepoint when necessary.

        Returns:
            This transaction boundary.

        Raises:
            AnalysisCancelled: Stop was requested.
            sqlite3.Error: SQLite could not begin the unit.
        """
        check_cancelled(self.cancel)
        if self.connection.in_transaction:
            self.savepoint = f'cw_unit_{next(_savepoints)}'
            self.connection.execute('SAVEPOINT ' + self.savepoint)
        else:
            self.connection.execute('BEGIN IMMEDIATE')
        self.active = True
        return self

    def commit(self) -> None:
        """Commit this unit only; nested units merely release their savepoint.

        Raises:
            AnalysisCancelled: Stop arrived before completion.
            sqlite3.Error: SQLite refused the commit/release.
        """
        check_cancelled(self.cancel)
        if self.active:
            if self.savepoint:
                self.connection.execute('RELEASE SAVEPOINT ' + self.savepoint)
            else:
                deadline = time.monotonic() + COMMIT_WAIT_SECONDS
                while True:
                    check_cancelled(self.cancel)
                    try:
                        self.connection.commit()
                        break
                    except sqlite3.OperationalError as error:
                        # A read-only preview can briefly hold a rollback-journal
                        # read lock. Retry bounded busy responses, still observing Stop.
                        if (self.cancel is None or time.monotonic() >= deadline
                                or getattr(error, 'sqlite_errorcode', None) != sqlite3.SQLITE_BUSY):
                            raise
            self.active = False

    def rollback(self) -> None:
        """Discard this unit while preserving the caller's earlier completed work.

        Raises:
            sqlite3.Error: SQLite could not roll back the active boundary.
        """
        if self.active:
            if self.savepoint and self.connection.in_transaction:
                self.connection.execute('ROLLBACK TO SAVEPOINT ' + self.savepoint)
                self.connection.execute('RELEASE SAVEPOINT ' + self.savepoint)
            elif self.connection.in_transaction:
                self.connection.rollback()
            self.active = False

    def __enter__(self) -> Self:
        """Begin this context's transaction."""
        return self.begin()

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 traceback: TracebackType | None) -> None:
        """Commit a successful unit or roll back exceptional/cancelled work."""
        try:
            if kind is None:
                self.commit()
        except BaseException:
            self.rollback()
            raise
        finally:
            if kind is not None:
                self.rollback()
