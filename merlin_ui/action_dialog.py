"""Small, explicit action choices shared by desktop workflows."""
from collections.abc import Sequence
import tkinter as tk
from tkinter import ttk


def choose_action(parent: tk.Misc, title: str, message: str,
                  actions: Sequence[tuple[str, str]]) -> str:
    """Return an explicit action; Escape/window close means cancellation.

    Args:
        parent: Owning desktop window.
        title: Dialog title.
        message: Explanation displayed above the choices.
        actions: Button labels paired with stable action identifiers.

    Returns:
        The chosen identifier, or cancel when dismissed.
    """
    window = tk.Toplevel(parent)
    window.title(title)
    window.transient(parent)
    result: list[str] = []
    ttk.Label(window, text=message, wraplength=510, justify="left").pack(padx=18, pady=16)
    buttons = ttk.Frame(window)
    buttons.pack(padx=18, pady=(0, 16))
    def choose(value: str) -> None:
        result.append(value)
        window.destroy()
    for label, value in actions:
        ttk.Button(buttons, text=label, command=lambda v=value: choose(v)).pack(side="left", padx=5)
    window.protocol("WM_DELETE_WINDOW", lambda: choose("cancel"))
    window.bind("<Escape>", lambda event: choose("cancel"))
    window.grab_set()
    parent.wait_window(window)
    return result[0] if result else "cancel"
