"""Typed application preferences using the existing shared settings schema."""
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile
from analysis_settings import Settings, setting, load_settings
from application_paths import application_data_directory
from theme_core.models import valid_id, BoardColors
from theme_core.presets import BOARD_PRESETS
from theme_core.assets import reject_links


MAX_SETTINGS_BYTES = 64 * 1024

@dataclass(frozen=True)
class ApplicationSettings(Settings):
    """Hold appearance preferences separately from engine and analysis settings.

    Args:
        active_theme_id: Saved artwork theme, or the built-in default.
        board_preset_id: Color-only palette; Custom preserves manual/base colors.
        board_custom_light: Optional last manually chosen light-square color.
        board_custom_dark: Optional last manually chosen dark-square color.
        show_last_move: Whether Game Review displays the actual last-move marker.
        review_moves_fraction: Saved proportion of Review height used by game moves.
    """
    active_theme_id: str = setting(
        "default", "One saved board theme for every application board. Missing themes use the default.",
        basic=True, cache=False, current=False)

    board_preset_id: str = setting(
        "custom", "Square palette only; Custom retains the saved artwork theme or manual colors.",
        options=("custom", *(p.preset_id for p in BOARD_PRESETS)), basic=True, cache=False, current=False)
    board_custom_light: str | None = setting(
        None, "Last manual light-square color; absent uses the saved theme.", cache=False, current=False)
    board_custom_dark: str | None = setting(
        None, "Last manual dark-square color; absent uses the saved theme.", cache=False, current=False)

    show_last_move: bool = setting(True, "Show actual last-move highlights in Game Review.", basic=True, cache=False, current=False)

    review_moves_fraction: float = setting(
        0.4, "Game Review height reserved for Actual Game Moves; saved when its divider is dragged.",
        minimum=0.1, maximum=0.9, basic=True, cache=False, current=False)

    def __post_init__(self) -> None:
        """Validate shared preferences and the optional paired custom square colors."""
        super().__post_init__()
        valid_id(self.active_theme_id)
        if (self.board_custom_light is None) != (self.board_custom_dark is None):
            raise ValueError("Custom board colors must specify both squares")
        if self.board_custom_light is not None:
            BoardColors(light_square=self.board_custom_light, dark_square=self.board_custom_dark)


class ApplicationSettingsRepository:
    """Read without creating files; explicit changes replace preferences atomically."""
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else application_data_directory() / "settings.json"

    def load(self) -> ApplicationSettings:
        reject_links(self.path)
        if not self.path.exists():
            return ApplicationSettings()
        with self.path.open("rb") as stream:
            data = stream.read(MAX_SETTINGS_BYTES + 1)
        if len(data) > MAX_SETTINGS_BYTES:
            raise ValueError("Application settings are too large")
        try:
            return load_settings(ApplicationSettings, json.loads(data))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("Invalid application settings JSON") from error

    def save(self, settings: ApplicationSettings) -> bool:
        if not isinstance(settings, ApplicationSettings):
            raise ValueError("Expected application settings")
        reject_links(self.path)
        payload = (json.dumps(asdict(settings), indent=2) + "\n").encode("utf-8")
        if self.path.exists() and self.path.read_bytes() == payload:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=".settings-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            reject_links(self.path)
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return True
