"""Compact desktop rendering of the shared read-only GameQuality model."""
import tkinter as tk
from tkinter import ttk
from merlin_ui.information_panel import InformationPanel
from move_quality_presentation import game_summary, game_details


class AccuracyPanel(tk.Frame):
    def __init__(self, parent, *, background, foreground):
        super().__init__(parent, bg=background)
        self.game = None
        self.details_window = None
        self.columnconfigure(0, weight=1)
        self.summary = tk.Label(self, text="Accuracy not analyzed", bg=background,
                                fg=foreground, anchor="w", justify="left", font=("Segoe UI", 9))
        self.summary.grid(row=0, column=0, sticky="ew")
        self.button = ttk.Button(self, text="Details", command=self.open_details)
        self.button.grid(row=0, column=1, sticky="ne", padx=(6, 0))
        self.bind("<Configure>", lambda event: self.summary.configure(wraplength=max(100, event.width-self.button.winfo_reqwidth()-10)))

    def show(self, game):
        self.game = game
        self.summary.configure(text=game_summary(game) if game is not None else "Accuracy unavailable")
        self.button.configure(state="normal" if game is not None else "disabled")
        if self.details_window is not None and self.details_window.winfo_exists():
            self.details_text.show(game_details(game) if game is not None else "Accuracy unavailable")

    def open_details(self):
        if self.game is None:
            return
        if self.details_window is None or not self.details_window.winfo_exists():
            self.details_window = tk.Toplevel(self)
            self.details_window.title("Accuracy details")
            self.details_window.geometry("620x380")
            self.details_text = InformationPanel(self.details_window)
            self.details_text.pack(fill="both", expand=True)
        self.details_text.show(game_details(self.game))
        self.details_window.lift()
