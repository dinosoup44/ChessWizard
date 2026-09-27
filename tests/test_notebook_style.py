"""Shared tab contrast and native navigation contracts; no application data needed."""
import gc
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from merlin_ui.appearance import DEFAULT_UI_SKIN
from merlin_ui.notebook import MerlinNotebook, contrast, tab_colors

LIGHT_SKIN = {**DEFAULT_UI_SKIN, "window_bg": "#fafafa", "panel_bg": "#eeeeee",
              "text": "#202124", "button_bg": "#dddddd", "accent": "#574184",
              "button_active_bg": "#c5c5c5", "border": "#777777"}


class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("900x350+10+10")
        self.addCleanup(self.root.destroy)
        for target in ("sqlite3.connect", "chess.engine.SimpleEngine.popen_uci"):
            guard = patch(target, side_effect=AssertionError("Tabs cannot access data or engines"))
            guard.start()
            self.addCleanup(guard.stop)

    def notebook(self, **kwargs):
        tabs = MerlinNotebook(self.root, **kwargs)
        tabs.pack(fill="both", expand=True)
        for label in ("Saved moves here", "Branch browser", "How to"):
            tabs.add(ttk.Frame(tabs), text=label)
        self.root.update()
        return tabs

    def test_readable_states_in_dark_light_and_low_contrast_palettes(self):
        for skin in (DEFAULT_UI_SKIN, LIGHT_SKIN,
                     {**LIGHT_SKIN, "accent": LIGHT_SKIN["button_bg"], "text": "#dddddd"}):
            with self.subTest(skin=skin):
                colors = tab_colors(self.root, skin)
                for state in ("selected", "inactive", "hover"):
                    self.assertGreaterEqual(contrast(self.root, colors[state], colors[state + "_text"]), 4.5)
                self.assertGreaterEqual(contrast(self.root, colors["selected"], colors["inactive"]), 3)

    def test_navigation_and_label_space_at_three_scales(self):
        style = ttk.Style(self.root)
        original_theme = style.theme_use()
        for percent in (100, 125, 150):
            with self.subTest(percent=percent):
                self.root.tk.call("tk", "scaling", percent / 100 * 96 / 72)
                tabs = self.notebook()
                self.assertEqual(style.theme_use(), original_theme)
                self.assertEqual(tabs.index("current"), 0)
                tabs.focus_force();self.root.update()
                tabs.event_generate("<Right>");self.root.update()
                self.assertEqual(tabs.index("current"), 1)
                tabs.event_generate("<Left>");self.root.update()
                self.assertEqual(tabs.index("current"), 0)
                positions = {}
                for x in range(tabs.winfo_width()):
                    try:
                        index = tabs.index(f"@{x},12")
                        positions.setdefault(index, []).append(x)
                    except tk.TclError:
                        pass
                self.assertEqual(set(positions), {0, 1, 2})
                for index, points in positions.items():
                    self.assertGreater(len(points), 40 * percent / 100)
                x = positions[2][len(positions[2]) // 2]
                tabs.event_generate("<ButtonPress-1>", x=x, y=12)
                tabs.event_generate("<ButtonRelease-1>", x=x, y=12)
                self.root.update()
                self.assertEqual(tabs.index("current"), 2)
                tabs.tab(1, state="disabled")
                tabs.focus_force();tabs.event_generate("<Left>");self.root.update()
                self.assertEqual(tabs.index("current"), 0)
                tabs.destroy()

    def test_palette_inheritance_and_independent_windows(self):
        self.root._merlin_ui_skin = LIGHT_SKIN
        light = self.notebook()
        dark = self.notebook(ui_skin=DEFAULT_UI_SKIN)
        style = ttk.Style(self.root)
        self.assertNotEqual(light.cget("style"), dark.cget("style"))
        for tabs, skin in ((light, LIGHT_SKIN), (dark, DEFAULT_UI_SKIN)):
            self.assertEqual(style.lookup(tabs.cget("style") + ".Tab", "background", ("selected",)), skin["accent"])

    def test_closing_one_notebook_keeps_other_selected_font_alive(self):
        first = self.notebook()
        second = self.notebook()
        second.destroy();del second;gc.collect()
        font_name = ttk.Style(self.root).lookup(first.cget("style") + ".Tab", "font", ("selected",))
        self.assertIn(font_name, self.root.tk.call("font", "names"))
        first.select(2);self.root.update()
        self.assertEqual(first.index("current"), 2)
