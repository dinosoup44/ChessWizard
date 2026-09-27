"""Frontend-neutral theme resolution and persisted color-only board overrides."""
from collections.abc import Callable
from dataclasses import dataclass, replace
from application_settings import ApplicationSettings, ApplicationSettingsRepository, application_data_directory
from .models import BoardColors, Theme
from .presets import board_preset
from .repository import ThemeRepository, LoadedTheme

DEFAULT_THEME = LoadedTheme(Theme("default", "Merlin Classic"), {}, {})


@dataclass(frozen=True)
class ThemeResolution:
    """Carry validated theme data and any recoverable loading problem.

    Args:
        loaded: Artwork theme with the selected board-square override applied.
        requested_id: Saved artwork theme identity.
        error: Human-readable fallback reason, empty on success.
        board_preset_id: Selected palette, or Custom when using manual/base colors.
    """
    loaded: LoadedTheme
    requested_id: str
    error: str = ""
    board_preset_id: str = "custom"


class ActiveThemeService:
    """Resolve shared preferences and notify subscribers without widget operations.

    Args:
        repository: Optional managed artwork repository; created lazily by default.
        settings: Optional application preferences repository.
    """
    def __init__(self, repository: ThemeRepository | None = None,
                 settings: ApplicationSettingsRepository | None = None) -> None:
        """Initialize without writing preferences or creating theme files.

        Args:
            repository: Optional managed artwork repository.
            settings: Optional application preferences repository.
        """
        self._repository = repository
        self.settings = settings if settings is not None else ApplicationSettingsRepository()
        self._listeners: list[Callable[[ThemeResolution], None]] = []
        self.current = self.resolve()

    @property
    def repository(self) -> ThemeRepository:
        """Return the lazily resolved managed artwork repository.

        Returns:
            Existing or default user-data theme repository.
        """
        if self._repository is None:
            self._repository = ThemeRepository(application_data_directory() / "themes")
        return self._repository

    def resolve(self) -> ThemeResolution:
        """Read preferences and overlay only square colors on saved artwork.

        Returns:
            Validated theme or a readable default fallback; never writes settings.
        """
        requested, error = "default", ""
        try:
            settings = self.settings.load()
        except (ValueError, OSError) as problem:
            return ThemeResolution(DEFAULT_THEME, requested, "Using Merlin Classic: " + str(problem))
        requested = settings.active_theme_id
        try:
            loaded = DEFAULT_THEME if requested == "default" else self.repository.load(requested)
        except (ValueError, OSError) as problem:
            loaded, error = DEFAULT_THEME, "Using Merlin Classic: " + str(problem)
        colors = loaded.theme.colors
        if settings.board_preset_id != "custom":
            colors = board_preset(settings.board_preset_id).apply(colors)
        elif settings.board_custom_light is not None:
            colors = replace(colors, light_square=settings.board_custom_light, dark_square=settings.board_custom_dark)
        if colors != loaded.theme.colors:
            loaded = replace(loaded, theme=replace(loaded.theme, colors=colors))
        return ThemeResolution(loaded, requested, error, settings.board_preset_id)

    def refresh(self, *, notify: bool = False) -> ThemeResolution:
        """Refresh subscribers when the effective board appearance changes.

        Args:
            notify: Notify even when preferences and resolved assets match.

        Returns:
            Current resolved appearance.
        """
        resolved = self.resolve()
        if resolved != self.current or notify:
            self.current = resolved
            for callback in tuple(self._listeners):
                callback(resolved)
        return resolved

    def subscribe(self, callback: Callable[[ThemeResolution], None]) -> Callable[[], None]:
        """Register a frontend-owned listener.

        Args:
            callback: Called with validated appearance data after a change.

        Returns:
            Idempotent unsubscribe function for the frontend lifecycle.
        """
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback) if callback in self._listeners else None

    def activate(self, theme_id: str) -> ThemeResolution:
        """Use a complete saved theme, including its original custom board colors.

        Args:
            theme_id: Managed theme identity or the built-in default.

        Returns:
            Newly active theme, with separate square overrides cleared.

        Raises:
            ValueError: The requested saved theme is invalid.
            OSError: Assets cannot be read or preferences cannot be saved.
        """
        if theme_id != "default":
            self.repository.load(theme_id)
        try:
            settings = self.settings.load()
        except (ValueError, OSError):
            settings = ApplicationSettings()
        self.settings.save(replace(settings, active_theme_id=theme_id, board_preset_id="custom",
                                   board_custom_light=None, board_custom_dark=None))
        return self.refresh()

    def activate_board_preset(self, preset_id: str) -> ThemeResolution:
        """Apply square colors immediately without replacing artwork or custom colors.

        Args:
            preset_id: Catalog identity, or Custom to restore the last manual/base colors.

        Returns:
            Persisted effective theme for all subscribing boards.

        Raises:
            ValueError: The preset or current settings are invalid.
            OSError: Preferences cannot be read or saved.
        """
        if preset_id != "custom":
            board_preset(preset_id)
        self.settings.save(replace(self.settings.load(), board_preset_id=preset_id))
        return self.refresh()

    def set_custom_board_colors(self, light: str, dark: str) -> ThemeResolution:
        """Persist manual square colors and select Custom without altering artwork.

        Args:
            light: Light-square hex color.
            dark: Dark-square hex color.

        Returns:
            Persisted custom appearance delivered to subscribed boards.

        Raises:
            ValueError: Colors or current settings are invalid.
            OSError: Preferences cannot be read or saved.
        """
        BoardColors(light_square=light, dark_square=dark)
        self.settings.save(replace(self.settings.load(), board_preset_id="custom",
                                   board_custom_light=light, board_custom_dark=dark))
        return self.refresh()


_default_service = None


def get_active_theme_service() -> ActiveThemeService:
    """Return the shared process-local theme service.

    Returns:
        Lazily constructed frontend-neutral service.
    """
    global _default_service
    if _default_service is None:
        _default_service = ActiveThemeService()
    return _default_service
