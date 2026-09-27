"""Palette-aware tabs with native Notebook selection and keyboard behavior."""
from hashlib import sha256
import json
import tkinter as tk
from tkinter import font, ttk
from collections.abc import Mapping

from merlin_ui.appearance import DEFAULT_UI_SKIN


def _luminance(widget: tk.Misc, color: str) -> float:
    channels = [value / 65535 for value in widget.winfo_rgb(color)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
              for value in channels]
    return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(widget: tk.Misc, first: str, second: str) -> float:
    """Return the luminance contrast ratio for two Tk colors."""
    light, dark = sorted((_luminance(widget, first), _luminance(widget, second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def tab_colors(widget: tk.Misc, skin: Mapping[str, str]) -> dict[str, str]:
    """Resolve readable tab states, including low-contrast custom palettes."""
    def readable(background: str) -> str:
        preferred = skin["text"]
        if contrast(widget, background, preferred) >= 4.5:
            return preferred
        return max((skin["window_bg"], "#000000", "#ffffff"),
                   key=lambda color: contrast(widget, background, color))

    inactive = skin["button_bg"]
    selected = skin["accent"]
    # A custom accent may match the panel; retain a visible selection in that case.
    if contrast(widget, selected, inactive) < 3:
        selected = readable(inactive)
    hover = skin["button_active_bg"]
    return {"inactive": inactive, "inactive_text": readable(inactive),
            "selected": selected, "selected_text": readable(selected),
            "hover": hover, "hover_text": readable(hover), "border": skin["border"]}


def _inherited_skin(parent: tk.Misc) -> Mapping[str, str]:
    current = parent
    while current is not None:
        if hasattr(current, "_merlin_ui_skin"):
            return current._merlin_ui_skin
        current = getattr(current, "master", None)
    return DEFAULT_UI_SKIN


class MerlinNotebook(ttk.Notebook):
    """Shared desktop tabs; optional skins inherit through the owning window.

    Only notebook elements use clam rendering, because Windows native tab elements
    ignore background maps. The application's theme and other controls stay native.
    """
    def __init__(self, master: tk.Misc, *, ui_skin: Mapping[str, str] | None = None, **kwargs):
        skin = {**DEFAULT_UI_SKIN, **(ui_skin if ui_skin is not None else _inherited_skin(master))}
        colors = tab_colors(master, skin)
        style = ttk.Style(master)
        identity = sha256(json.dumps(skin, sort_keys=True).encode()).hexdigest()[:16]
        name = f"Merlin{identity}.TNotebook"
        tab = name + ".Tab"
        elements = style.element_names()
        for element in ("tab", "client"):
            target = "Merlin.Notebook." + element
            if target not in elements:
                style.element_create(target, "from", "clam", "Notebook." + element)
        style.layout(name, [("Merlin.Notebook.client", {"sticky": "nswe"})])
        style.layout(tab, [("Merlin.Notebook.tab", {"sticky": "nswe", "children": [
            ("Notebook.padding", {"sticky": "nswe", "children": [
                ("Notebook.focus", {"sticky": "nswe", "children": [
                    ("Notebook.label", {"sticky": "nswe"})]})]})]})])
        root = master._root()
        if not hasattr(root, "_merlin_tab_fonts"):
            root._merlin_tab_fonts = {}
        if identity not in root._merlin_tab_fonts:
            selected_font = font.nametofont("TkDefaultFont", root=master).copy()
            selected_font.configure(weight="bold")
            root._merlin_tab_fonts[identity] = selected_font
        self._tab_font = root._merlin_tab_fonts[identity]
        style.configure(name, background=skin["panel_bg"], bordercolor=colors["border"],
                        lightcolor=colors["border"], darkcolor=colors["border"], tabmargins=(2, 3, 2, 0))
        style.configure(tab, padding=(".16i", ".08i"), font="TkDefaultFont",
                        background=colors["inactive"], foreground=colors["inactive_text"],
                        bordercolor=colors["border"], lightcolor=colors["border"],
                        darkcolor=colors["border"], focuscolor=colors["selected_text"])
        for option, values in {
            "background": (colors["selected"], colors["hover"], colors["inactive"]),
            "foreground": (colors["selected_text"], colors["hover_text"], colors["inactive_text"]),
            "lightcolor": (colors["selected"], colors["border"], colors["border"]),
        }.items():
            style.map(tab, **{option: [("disabled", values[2]), ("selected", values[0]),
                                      ("active", values[1]), ("!selected", values[2])]})
        style.map(tab, font=[("selected", self._tab_font), ("!selected", "TkDefaultFont")])
        kwargs["style"] = name
        super().__init__(master, **kwargs)
