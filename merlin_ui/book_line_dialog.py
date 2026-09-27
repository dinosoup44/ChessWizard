"""Shared explicit confirmation for an atomic authored continuation."""
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from merlin_ui.information_panel import style_information
from opening_book_line import BookLinePlan
from opening_book_models import MoveDetails
def confirm_book_line(parent: tk.Misc, destination: str, san: str, plan: BookLinePlan,
                      *, title: str = 'Add Played Variation') -> str | None:
    """Confirm a complete line and optional name before any opening mutation.

    Args:
        parent: Owning Studio widget.
        destination: Exact saved opening and branch label.
        san: Full legal continuation to preview.
        plan: Shared side-effect-free merge preview.
        title: Source-specific dialog title.

    Returns:
        Optional author name on Add, or None on cancellation.
    """
    window = tk.Toplevel(parent)
    window.title(title)
    window.geometry('700x480')
    window.minsize(550, 360)
    window.transient(parent)
    window.columnconfigure(0, weight=1)
    window.rowconfigure(1, weight=1)
    ttk.Label(window, text='Add line to:\n' + destination,
              wraplength=640).grid(row=0, column=0, sticky='ew', padx=12, pady=12)
    text = ScrolledText(window, wrap='word', height=7)
    style_information(text)
    text.grid(row=1, column=0, sticky='nsew', padx=12)
    text.insert('1.0', san)
    text.configure(state='disabled')
    reused = len(plan.steps) - plan.new_edges
    summary = (f'First {plan.existing_prefix} plies already exist. {plan.new_edges} new move edges will be added.\n'
               f'{reused} plies reuse existing/planned theory. Existing notes, names, weights and preferences stay intact.\n'
               f'New moves: weight {MoveDetails().weight}, not Preferred. Optional name applies to the first new move.')
    ttk.Label(window, text=summary, wraplength=640).grid(row=2, column=0, sticky='ew', padx=12, pady=10)
    names = ttk.Frame(window)
    names.grid(row=3, column=0, sticky='ew', padx=12)
    names.columnconfigure(1, weight=1)
    ttk.Label(names, text='Variation name (optional):').grid(row=0, column=0)
    name = tk.StringVar(window)
    entry = ttk.Entry(names, textvariable=name)
    entry.grid(row=0, column=1, sticky='ew', padx=8)
    result = []
    def accept() -> None:
        result.append(name.get().strip())
        window.destroy()
    buttons = ttk.Frame(window)
    buttons.grid(row=4, column=0, sticky='ew', padx=12, pady=12)
    ttk.Button(buttons, text='Add Variation', command=accept).pack(side='left')
    ttk.Button(buttons, text='Cancel', command=window.destroy).pack(side='right')
    entry.focus_set()
    window.grab_set()
    parent.wait_window(window)
    return result[0] if result else None
