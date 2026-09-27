"""Small, frontend-neutral board palette catalog; no artwork or brand assets."""
from dataclasses import dataclass, replace
from typing import Literal
from .models import BoardColors


@dataclass(frozen=True)
class BoardPreset:
    """Describe a stable color-only board choice.

    Args:
        preset_id: Settings identity, independent of a saved artwork theme.
        name: Fictional display name.
        light_square: Light square color in six-digit hex notation.
        dark_square: Dark square color in six-digit hex notation.
        group: Built-in default, base palette or small alternate collection.
    """
    preset_id: str
    name: str
    light_square: str
    dark_square: str
    group: Literal["default", "base", "alternate"] = "base"

    def apply(self, colors: BoardColors) -> BoardColors:
        """Replace square colors while retaining the frame and coordinates.

        Args:
            colors: Existing saved or preview colors.

        Returns:
            New validated board colors; the supplied object is unchanged.
        """
        return replace(colors, light_square=self.light_square, dark_square=self.dark_square)


BOARD_PRESETS = (
    BoardPreset("default", "ChessWizard Default", BoardColors().light_square, BoardColors().dark_square, "default"),
    BoardPreset("firebirds", "Firebirds", "#f5dfa3", "#984044"),
    BoardPreset("shamrocks", "Shamrocks", "#eee6cc", "#28694c"),
    BoardPreset("borough", "Borough", "#d6d8da", "#42484e"),
    BoardPreset("hornets-nest", "Hornets Nest", "#abdcd6", "#564375"),
    BoardPreset("cows", "Cows", "#e5d8d2", "#913543"),
    BoardPreset("musketeers", "Musketeers", "#eac57e", "#743849"),
    BoardPreset("trail-riders", "Trail Riders", "#cadce7", "#315e8b"),
    BoardPreset("high-country", "High Country", "#e6cf94", "#304e70"),
    BoardPreset("motor-city", "Motor City", "#e3c8cb", "#34598b"),
    BoardPreset("golden-gate", "Golden Gate", "#efce71", "#365d99"),
    BoardPreset("red-orbit", "Red Orbit", "#e3d7d4", "#993d49"),
    BoardPreset("racers", "Racers", "#eed37c", "#344e70"),
    BoardPreset("sailboats", "Sailboats", "#ded8d4", "#304b70"),
    BoardPreset("showtime", "Showtime", "#efce82", "#654985"),
    BoardPreset("river-bears", "River Bears", "#b9d0e3", "#344e74"),
    BoardPreset("vice-heat", "Vice Heat", "#e9b8cb", "#344b57"),
    BoardPreset("stags", "Stags", "#e6ddbb", "#35624c"),
    BoardPreset("timber", "Timber", "#cbddbe", "#355571"),
    BoardPreset("bayou-birds", "Bayou Birds", "#e0ceaa", "#314d68"),
    BoardPreset("empire", "Empire", "#edbc91", "#3a6196"),
    BoardPreset("lightning", "Lightning", "#f1c08a", "#326c9f"),
    BoardPreset("magic-show", "Magic Show", "#d0dce5", "#32658c"),
    BoardPreset("founders", "Founders", "#e7d6d2", "#3c6096"),
    BoardPreset("desert-suns", "Desert Suns", "#f0c08f", "#644b82"),
    BoardPreset("rip-city", "Rip City", "#e7cebf", "#873b43"),
    BoardPreset("royal-court", "Royal Court", "#d4cfde", "#664f88"),
    BoardPreset("silver-spurs", "Silver Spurs", "#cdd1d5", "#454c54"),
    BoardPreset("north-claws", "North Claws", "#e1d6ce", "#943f4b"),
    BoardPreset("mountain-notes", "Mountain Notes", "#b9d7e6", "#5a477d"),
    BoardPreset("monuments", "Monuments", "#e2cbc4", "#334e6d"),
    BoardPreset("emerald-sound", "Emerald Sound", "#eed58e", "#347455", "alternate"),
    BoardPreset("teal-dinosaur", "Teal Dinosaur", "#afe0d8", "#6c4f88", "alternate"),
    BoardPreset("vice-nights", "Vice Nights", "#efb8d1", "#326775", "alternate"),
    BoardPreset("desert-sunset", "Desert Sunset", "#f1b28e", "#77445f", "alternate"),
    BoardPreset("rainbow-skyline", "Rainbow Skyline", "#e9cd85", "#416684", "alternate"),
    BoardPreset("motor-retro", "Motor Retro", "#c7e0d5", "#356a70", "alternate"),
    BoardPreset("cream-town", "Cream Town", "#eee3c6", "#426855", "alternate"),
    BoardPreset("city-lights", "City Lights", "#d4c4e4", "#3c536d", "alternate"),
)


def board_preset(preset_id: str) -> BoardPreset:
    """Look up a color-only preset by its stable identity.

    Args:
        preset_id: Catalog identity; Custom is a preference, not a preset.

    Returns:
        Immutable palette data.

    Raises:
        ValueError: No such preset exists.
    """
    for preset in BOARD_PRESETS:
        if preset.preset_id == preset_id:
            return preset
    raise ValueError("Unknown board preset: " + preset_id)
