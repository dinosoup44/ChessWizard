"""Crash-released operating-system locks; lock-file existence is not ownership."""
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
import os
import time


class PluginBusyError(RuntimeError):
    """Indicate a bounded operation could not obtain its required lease."""


@contextmanager
def file_lease(path: Path, timeout: float = 0.0) -> Iterator[None]:
    """Hold a kernel-backed byte lock that is released if the owner crashes.

    Args:
        path: Already containment-checked lock file owned by the repository.
        timeout: Maximum wait; zero means fail immediately.

    Yields:
        None while the lease is held.

    Raises:
        PluginBusyError: Another operation still owns the lease at the deadline.
        OSError: The lock file cannot be opened.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (BlockingIOError, PermissionError, OSError) as error:
                if time.monotonic() >= deadline:
                    raise PluginBusyError("Plugin operation is busy") from error
                time.sleep(min(0.01, max(0, deadline - time.monotonic())))
        yield
    finally:
        if acquired:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()
