"""Desktop QA surface over the existing review target and save contracts."""
import tkinter as tk
from tkinter import ttk
from merlin_ui.human_review_panel import HumanReviewPanel


class HumanReviewWindow:
    def __init__(self, window, *, review):
        self.root = window
        window.title("ChessWizard · Human Review / QA")
        window.geometry("560x440")
        window.minsize(440, 340)
        window.configure(bg=review.ui_skin["panel_bg"])
        window.columnconfigure(0, weight=1)
        ttk.Label(window, text="Review Set").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 4))
        self.picker = ttk.Combobox(window, textvariable=review.review_set_var,
            values=[item.label for item in review.review_sets],
            state="readonly" if len(review.review_sets) > 1 else "disabled")
        self.picker.grid(row=1, column=0, sticky="ew", padx=12)
        self.picker.bind("<<ComboboxSelected>>", lambda event: review.load_games())
        from merlin_ui.scrollable_panel import ScrollablePanel
        viewport = ScrollablePanel(window, background=review.ui_skin["panel_bg"])
        viewport.grid(row=2, column=0, sticky="nsew", padx=12, pady=12)
        window.rowconfigure(2, weight=1)
        self.panel = HumanReviewPanel(viewport.content, ui_skin=review.ui_skin,
            repository=review.human_review_repository, on_select_case=review.jump_to_review_case)
        self.panel.grid(row=0, column=0, sticky="ew")
        if len(review.review_sets) == 1:
            ttk.Label(window, text="Optional QA review sets are not installed.",
                      wraplength=400).grid(row=3, column=0, sticky="w", padx=12, pady=(0, 12))
