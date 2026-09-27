"""Application integration around the existing Art Tester controls and preview."""
import tkinter as tk
from dataclasses import replace
from chesswizard_version import window_title
from tkinter import ttk, filedialog
from theme_core.active import DEFAULT_THEME, ActiveThemeService, get_active_theme_service
from theme_core.presets import BOARD_PRESETS
from theme_core.models import BoardColors
from theme_core.editor import ThemeDraft
from theme_core.packages import import_theme_package
from .art_tester import ArtTester


class ThemeEditor(ArtTester):
    """Edit artwork drafts and apply persisted board colors through shared services.

    Args:
        root: Owning desktop window.
        service: Shared appearance service; omitted uses the application default.
    """
    def __init__(self, root: tk.Misc, service: ActiveThemeService | None = None) -> None:
        """Build the shared artwork editor and immediately applied board palette picker.

        Args:
            root: Owning desktop window.
            service: Shared appearance service or the application default.
        """
        self.service = service if service is not None else get_active_theme_service()
        self.active_label = tk.StringVar(root)
        self.board_choice = tk.StringVar(root, value="Custom")
        self.board_choices = {"Custom": "custom", **{p.name: p.preset_id for p in BOARD_PRESETS}}
        super().__init__(root, repository=self.service.repository, title=window_title("Appearance / Theme Editor"))
        self.save_button.configure(text="Save as new theme")
        self.unsubscribe = self.service.subscribe(self.active_changed)
        root.bind("<Destroy>", self._destroyed, add="+")
        root.bind("<FocusIn>", self._focused, add="+")
        self.active_changed(self.service.refresh())
        current = self.service.current.loaded.theme.theme_id
        self.refresh_saved(current)
        self.select_theme()
        self._preview_square_colors(self.service.current.loaded.theme.colors)
        self._sync_board_choice()

    def _build_editor(self, parent):
        ttk.Label(parent, textvariable=self.active_label, wraplength=430).pack(anchor="w", pady=(0, 5))
        actions = ttk.Frame(parent)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="Use selected theme", command=self.activate_selected).pack(side="left")
        ttk.Button(actions, text="Import ZIP…", command=self.import_zip).pack(side="left", padx=5)
        ttk.Button(actions, text="Import folder…", command=self.import_folder).pack(side="left")
        palette = ttk.Frame(parent)
        palette.pack(fill="x", pady=(0, 5))
        ttk.Label(palette, text="Board Theme:").pack(side="left", padx=(0, 8))
        self.board_selector = ttk.Combobox(palette, textvariable=self.board_choice,
            values=tuple(self.board_choices), state="readonly")
        self.board_selector.pack(side="left", fill="x", expand=True)
        self.board_selector.bind("<<ComboboxSelected>>", lambda event: self.select_board_preset())
        ttk.Label(parent, text="Board colors apply immediately. Piece art and decorations stay unchanged.",
                  wraplength=430).pack(anchor="w", pady=(0, 6))
        super()._build_editor(parent)

    def _preview_square_colors(self, colors: BoardColors) -> None:
        self.draft.colors = replace(self.draft.colors, light_square=colors.light_square, dark_square=colors.dark_square)
        for key in ("light_square", "dark_square"):
            self.color_vars[key].set(getattr(colors, key))
        self.refresh_preview()

    def _sync_board_choice(self) -> None:
        current = self.service.current
        active, draft = current.loaded.theme.colors, self.draft.colors
        selected = current.board_preset_id if (active.light_square, active.dark_square) == (draft.light_square, draft.dark_square) else "custom"
        self.board_choice.set(next(name for name, pid in self.board_choices.items() if pid == selected))

    def select_board_preset(self) -> bool:
        """Apply the chosen square palette to the preview and shared application boards.

        Returns:
            True on successful persistence; False with a readable status on failure.
        """
        try:
            resolution = self.service.activate_board_preset(self.board_choices[self.board_choice.get()])
        except (ValueError, OSError) as error:
            self._sync_board_choice()
            self.status.set("Board colors not applied: " + str(error))
            return False
        self._preview_square_colors(resolution.loaded.theme.colors)
        self._sync_board_choice()
        self.status.set("Board colors applied and saved. Artwork is unchanged.")
        return True

    def apply_colors(self) -> bool:
        """Persist manual square edits as Custom; keep other artwork edits in preview.

        Returns:
            True for valid applied colors; False when validation or saving fails.
        """
        try:
            colors = BoardColors(**{key: value.get() for key, value in self.color_vars.items()})
            if (colors.light_square, colors.dark_square) != (self.draft.colors.light_square, self.draft.colors.dark_square):
                self.service.set_custom_board_colors(colors.light_square, colors.dark_square)
        except (ValueError, OSError) as error:
            self.status.set("Board colors not applied: " + str(error))
            return False
        result = super().apply_colors()
        self._sync_board_choice()
        return result

    def sync_editor(self) -> None:
        """Refresh draft controls without activating the preview artwork theme."""
        super().sync_editor()
        self._sync_board_choice()

    def refresh_saved(self, selected_id=None):
        try:
            super().refresh_saved()
        except (ValueError, OSError) as error:
            self.saved = {}
            self.status.set("Cannot list themes: " + str(error))
        self.saved = {"Merlin Classic · built-in": "default", **self.saved}
        self.theme_selector.configure(values=["Editor preview", *self.saved])
        if selected_id:
            self.theme_choice.set(next((k for k,v in self.saved.items() if v == selected_id), "Merlin Classic · built-in"))

    def select_theme(self):
        if self.saved.get(self.theme_choice.get()) == "default":
            self.draft = ThemeDraft.from_loaded(DEFAULT_THEME)
            self.sync_editor()
            self.status.set("Built-in default. Use selected theme to apply it everywhere.")
        else:
            super().select_theme()

    def activate_selected(self) -> bool:
        """Activate saved artwork and refresh the preview after clearing square overrides.

        Returns:
            True when the saved theme is active; False for an unsaved draft or error.
        """
        theme_id = self.saved.get(self.theme_choice.get())
        if theme_id is None:
            self.status.set("Save this draft, then use the saved theme.")
            return False
        try:
            resolution = self.service.activate(theme_id)
            self._preview_square_colors(resolution.loaded.theme.colors)
            self._sync_board_choice()
        except (ValueError, OSError) as error:
            self.status.set("Theme not activated: " + str(error))
            return False
        self.status.set("Active theme applied. Other open windows refresh when focused.")
        return True

    def active_changed(self, resolution):
        selected = self.saved.get(self.theme_choice.get())
        self.refresh_saved(selected)
        if selected and selected not in self.saved.values():
            self.select_theme()
        self.active_label.set("Active: " + resolution.loaded.theme.name + (" (default fallback)" if resolution.error else ""))
        if resolution.error:
            self.status.set(resolution.error)

    def import_package(self, path):
        try:
            loaded = import_theme_package(self.repository, path)
        except (ValueError, OSError) as error:
            self.status.set("Import rejected: " + str(error))
            return False
        self.refresh_saved(loaded.theme.theme_id)
        self.select_theme()
        self.status.set("Imported safely. Use selected theme to apply it everywhere.")
        return True

    def import_zip(self):
        path = filedialog.askopenfilename(parent=self.root, title="Import Art Tester theme",
                                          filetypes=[("Theme ZIP package", "*.zip")])
        if path:
            self.import_package(path)

    def import_folder(self):
        path = filedialog.askdirectory(parent=self.root, title="Choose the folder containing theme.json")
        if path:
            self.import_package(path)

    def _focused(self, event):
        if event.widget == self.root:
            self.service.refresh()

    def _destroyed(self, event):
        if event.widget == self.root:
            self.unsubscribe()


def main():
    root = tk.Tk()
    ThemeEditor(root)
    root.mainloop()
