"""Confirmation UI over a core deletion plan; graph rules remain in the service."""
import tkinter as tk
from tkinter import ttk


def choose_deletion(parent, service, book_id, move_id):
    """Return the exact confirmed preview, or None on cancellation."""
    plans = {False: service.preview_deletion(book_id, move_id),
             True: service.preview_deletion(book_id, move_id, subtree=True)}
    dialog = tk.Toplevel(parent)
    dialog.title("Delete move / variation")
    dialog.transient(parent)
    mode = tk.BooleanVar(dialog, value=False)
    summary = tk.StringVar(dialog, value=plans[False].summary())
    result = []
    for label, value in (("Selected move only", False), ("Selected move and unshared continuation", True)):
        ttk.Radiobutton(dialog, text=label, value=value, variable=mode,
                        command=lambda: summary.set(plans[mode.get()].summary())).pack(anchor="w", padx=18, pady=5)
    ttk.Label(dialog, textvariable=summary, wraplength=480).pack(fill="both", expand=True, padx=18, pady=12)
    buttons = ttk.Frame(dialog);buttons.pack(fill="x", padx=18, pady=12)
    def confirm():
        result.append(plans[mode.get()])
        dialog.destroy()
    ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right")
    ttk.Button(buttons, text="Delete", command=confirm).pack(side="right", padx=8)
    dialog.bind("<Escape>", lambda event: dialog.destroy())
    dialog.grab_set()
    parent.wait_window(dialog)
    return result[0] if result else None
