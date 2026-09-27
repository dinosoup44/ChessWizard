"""Shared terminal surfaces for information, leaving application controls native."""
import tkinter as tk
from tkinter import font, ttk
from tkinter.scrolledtext import ScrolledText

BACKGROUND = "#111b16"
FOREGROUND = "#b8e6c3"
CURRENT = "#294f3a"


def style_information(widget):
    families = set(font.families(widget))
    family = next((n for n in ("Cascadia Mono", "Consolas", "Courier New") if n in families), "TkFixedFont")
    widget.configure(bg=BACKGROUND, fg=FOREGROUND, insertbackground=FOREGROUND,
                     selectbackground=CURRENT, selectforeground="white", font=(family, 10),
                     relief="flat", padx=10, pady=8)
    return widget


class InformationPanel(ScrolledText):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, wrap="word", width=24, height=5, **kwargs)
        style_information(self)
        self.configure(state="disabled")

    def show(self, text):
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.insert("1.0", text)
        self.configure(state="disabled")


def style_information_tree(widget):
    """Use the same terminal palette for navigable information tables."""
    style = ttk.Style(widget)
    # Native Windows fields ignore the empty-area fill. Clone only this surface.
    if "MerlinInformation.field" not in style.element_names():
        style.element_create("MerlinInformation.field", "from", "clam", "Treeview.field")
    style.layout("MerlinInformation.Treeview", [("MerlinInformation.field", {
        "sticky": "nswe", "children": [("Treeview.padding", {
            "sticky": "nswe", "children": [("Treeview.treearea", {"sticky": "nswe"})]})]})])
    style.configure("MerlinInformation.Treeview", background=BACKGROUND,
                    fieldbackground=BACKGROUND, foreground=FOREGROUND,
                    font="TkFixedFont", rowheight=font.nametofont("TkFixedFont", root=widget).metrics("linespace") + 8)
    style.map("MerlinInformation.Treeview", background=[("selected", CURRENT)],
              foreground=[("selected", "white")])
    widget.configure(style="MerlinInformation.Treeview")
    return widget
