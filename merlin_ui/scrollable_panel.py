"""A bounded desktop viewport for details that may exceed the window height."""
import tkinter as tk
from tkinter import ttk


class ScrollablePanel(tk.Frame):
    def __init__(self, parent, *, background):
        super().__init__(parent, bg=background)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=background, highlightthickness=0, width=1, height=1)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.content = tk.Frame(self.canvas, bg=background)
        self.content.columnconfigure(0, weight=1)
        self._item = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._content_changed)
        self.canvas.bind("<Configure>", self._resize)

    def _content_changed(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize(self, event):
        self.canvas.itemconfigure(self._item, width=event.width)
