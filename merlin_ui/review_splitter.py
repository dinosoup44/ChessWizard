"""Resizable desktop panes; only an explicit divider drag requests persistence."""
from collections.abc import Callable
import tkinter as tk
from tkinter import font as tkfont


class ReviewSplitter(tk.PanedWindow):
    """Own resizable Review panes and cancel queued layout work on destruction.

    Args:
        parent: Owning Tk container.
        fraction: Current move-list share of vertical space.
        on_resize: Callback for an explicit user divider drag.
        background: Theme background color.
    """
    def __init__(self, parent: tk.Misc, *, fraction: float,
                 on_resize: Callable[[float], None], background: str) -> None:
        """Initialize the desktop layout and its owned callbacks.

        Args:
            parent: Owning Tk container.
            fraction: Move-list share of the available height.
            on_resize: Notification for an explicit divider drag.
            background: Theme background color.
        """
        line = tkfont.nametofont("TkDefaultFont", root=parent).metrics("linespace")
        self.sash_size = max(8, line // 2)
        super().__init__(parent, orient=tk.VERTICAL, bg=background, borderwidth=0,
                         sashwidth=self.sash_size, sashrelief="raised", opaqueresize=True)
        self.fraction = fraction
        self.on_resize = on_resize
        self.minimum_heights = (7 * line, 6 * line)
        self._dragging = False
        self._drag_start_y = None
        self._drag_moved = False
        self._layout_pending = None
        self._drag_pending = None
        self.bind("<Destroy>", self._destroyed, add="+")
        self.bind("<Configure>", self._schedule_layout)
        self.bind("<ButtonPress-1>", self._start_drag)
        self.bind("<B1-Motion>", self._move_drag)
        self.bind("<ButtonRelease-1>", self._finish_drag)

    def add_panels(self, first, second):
        for panel, minimum in zip((first, second), self.minimum_heights):
            self.add(panel, minsize=minimum, stretch="always")
        self._schedule_layout()

    def _schedule_layout(self, event=None):
        if self._layout_pending is None:
            self._layout_pending = self.after_idle(self._layout)

    def _layout(self):
        self._layout_pending = None
        if self._dragging or len(self.panes()) != 2:
            return
        usable = self.winfo_height() - self.sash_size
        if usable < sum(self.minimum_heights):
            return
        y = max(self.minimum_heights[0], min(usable - self.minimum_heights[1], round(usable * self.fraction)))
        self.sash_place(0, 0, y)

    def _start_drag(self, event):
        self._dragging = bool(self.identify(event.x, event.y))
        self._drag_start_y = event.y
        self._drag_moved = False

    def _move_drag(self, event):
        if self._dragging and abs(event.y - self._drag_start_y) > 1:
            self._drag_moved = True

    def _finish_drag(self, event):
        if self._dragging:
            # Tk's class binding settles sash geometry after this widget binding.
            if self._drag_pending is None:
                self._drag_pending = self.after_idle(self._commit_drag)

    def _commit_drag(self):
        self._drag_pending = None
        self._dragging = False
        if not self._drag_moved:
            self._schedule_layout()
            return
        usable = self.winfo_height() - self.sash_size
        if usable <= 0:
            return
        fraction = max(0.1, min(0.9, self.sash_coord(0)[1] / usable))
        if abs(fraction - self.fraction) > 0.001:
            self.fraction = fraction
            self.on_resize(fraction)


    def _destroyed(self, event: tk.Event) -> None:
        """Remove callbacks before Tk deletes this widget's registered commands."""
        if event.widget == self:
            for name in ('_layout_pending', '_drag_pending'):
                pending = getattr(self, name)
                if pending is not None:
                    self.after_cancel(pending)
                    setattr(self, name, None)
