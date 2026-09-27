"""Bounded Tk pumping for explicitly asynchronous opening selection in UI tests."""
import time


def wait_for_opening(view: object, timeout: float = 5) -> None:
    """Await asynchronous selection without blocking Tk dispatch in regression tests.

    Args:
        view: Test-owned Game Review coordinator.
        timeout: Maximum allowed selection duration in seconds.

    Raises:
        AssertionError: Selection does not complete within the bounded wait.
    """
    picker=view.opening_reference
    deadline=time.monotonic()+timeout
    while (picker.worker is not None or picker.pending is not None) and time.monotonic()<deadline:
        view.root.update()
        time.sleep(.005)
    if picker.worker is not None or picker.pending is not None:
        raise AssertionError('Opening selection did not complete: '+picker.status.cget('text'))
    view.root.update()
