"""Tk lifecycle adapter for the portable active-theme service."""
import tkinter as tk


class BoardThemeBinding:
    def __init__(self, board, service):
        self.board, self.service = board, service
        self.top = board.winfo_toplevel()
        self.unsubscribe = service.subscribe(self.apply)
        self.focus_id = self.top.bind("<FocusIn>", self.on_focus, add="+")
        board.bind("<Destroy>", self.on_destroy, add="+")
        self.apply(service.refresh())

    def apply(self, resolution):
        try:
            self.board.set_theme(resolution.loaded)
        except (ValueError, OSError, tk.TclError):
            self.board.set_theme()

    def on_focus(self, event):
        if event.widget == self.board.winfo_toplevel():
            self.service.refresh()

    def on_destroy(self, event):
        if event.widget == self.board:
            self.unsubscribe()
            self.top.unbind("<FocusIn>", self.focus_id)
