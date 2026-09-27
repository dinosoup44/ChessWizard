"""Stable requested-size facts for desktop layouts with flexible content panes."""
import tkinter as tk


def grid_chrome_height(parent: tk.Misc, flexible_rows: tuple[int, ...]) -> int:
    """Measure fixed grid rows without feeding allocated window height back into layout.

    Args:
        parent: Grid-managed container.
        flexible_rows: Rows whose content absorbs spare space and must be excluded.

    Returns:
        Requested vertical pixels for the remaining visible rows, including grid padding.
    """
    rows: dict[int, int] = {}
    for widget in parent.grid_slaves():
        info = widget.grid_info()
        row = int(info['row'])
        raw = info.get('pady', 0)
        padding = raw if isinstance(raw, tuple) else parent.tk.splitlist(str(raw))
        values = tuple(parent.winfo_pixels(value) for value in padding)
        extra = sum(values) if len(values) > 1 else 2 * values[0] if values else 0
        rows[row] = max(rows.get(row, 0), (0 if row in flexible_rows else widget.winfo_reqheight()) + extra)
    return sum(rows.values())


class AutomaticSizeGuard:
    """Latch rapid resize oscillation/growth until width, scale or view context changes.

    Args:
        maximum_changes: Maximum automatic size changes in one observation window.
        window_seconds: Interval used to distinguish runaway updates from later edits.
    """
    def __init__(self, maximum_changes: int = 10, window_seconds: float = 2.0) -> None:
        """Initialize a desktop-only guard with no widget or persistence side effects.

        Args:
            maximum_changes: Allowed burst of automatic adjustments.
            window_seconds: Burst observation interval.

        Raises:
            ValueError: Limits cannot detect a meaningful sequence.
        """
        if maximum_changes < 4 or window_seconds <= 0:
            raise ValueError('Resize guard requires at least four changes and a positive interval.')
        self.maximum_changes = maximum_changes
        self.window_seconds = window_seconds
        self.blocked = False
        self._context = None
        self._history: list[tuple[float, tuple[int, int]]] = []

    def allow(self, context: tuple, size: tuple[int, int], *, now: float | None = None) -> bool:
        """Check an automatic adjustment without counting stable no-op requests.

        Args:
            context: Width, display scale and active view; exclude allocated height.
            size: Proposed automatic minimum dimensions or pane heights.
            now: Optional monotonic time for deterministic regression tests.

        Returns:
            False when alternating or excessive adjustments have been latched. A new
            context resets the latch; manual window resizing is never intercepted.
        """
        from time import monotonic
        if context != self._context:
            self._context = context
            self._history.clear()
            self.blocked = False
        if self.blocked:
            return False
        instant = monotonic() if now is None else now
        self._history = [(stamp,value) for stamp,value in self._history if instant-stamp <= self.window_seconds]
        if self._history and self._history[-1][1] == size:
            return True
        values = [value for _,value in self._history] + [size]
        oscillating = len(values) >= 4 and values[-4] == values[-2] and values[-3] == values[-1]
        if oscillating or len(values) > self.maximum_changes:
            self.blocked = True
            return False
        self._history.append((instant,size))
        return True
