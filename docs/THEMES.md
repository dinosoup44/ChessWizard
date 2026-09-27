# Theme Editor V1

Open **Appearance…** from Game Review or Training, or run `run_theme_editor.py`.
The integrated screen reuses the Art Tester's controls, all twelve PNG piece roles,
four board/frame/coordinate colors, nine optional decoration slots, thumbnails,
remove/status controls, deterministic preview positions and overlay samples.

## One shared theme

`application_settings.ApplicationSettings.active_theme_id` is the only active
appearance preference. It uses the existing `analysis_settings.Settings`,
`setting`, `load_settings` and setting-definition schema without changing
analysis profiles. Its ID is `active_theme_id`, default `default`, level basic;
it affects neither raw engine cache identity nor analysis result currentness.

Inspection found typed analysis settings but no persisted application preference
repository. `ApplicationSettingsRepository` adds that shared application boundary:
`%LOCALAPPDATA%/ChessWizard/settings.json` on Windows (user-local share directory
fallback elsewhere). It does not create files on read; explicit activation uses
an atomic replacement, and identical saved settings cause no write.

User themes live once in `%LOCALAPPDATA%/ChessWizard/themes/<theme_id>/`.
All frontend surfaces consume `ActiveThemeService`, which returns validated
`LoadedTheme` data. Tk lifecycle/subscription handling stays in
`merlin_ui.theme_binding`; portable core/services have no Tk or chess database
dependency. This boundary is reusable by a future mobile frontend.

**Save as new theme** retains the Art Tester's immutable named-snapshot behavior.
Saving/importing does not activate the set. **Use selected theme** explicitly
persists the selected saved ID. An edited draft must first be saved; there is no
separate Review, Training or editor appearance preference. Draft preview remains
local so unfinished edits cannot silently change other boards.

Already-open boards in the same process receive `ChessBoard.set_theme()`
immediately. Other processes re-read settings when their window regains focus.
An older process started before this integration must be reopened to load the
new code. Changing appearance preserves position, orientation, last move,
tactical targets, arrows, selection and input state. It never triggers training
attempt creation or engine work.

## Existing renderer and fallback

Game Review and Training acquire the binding through their existing
`MerlinViewShell`. Their domain modules and the `ChessBoard` implementation
are unchanged. Theme Editor subclasses the existing Art Tester UI; only optional
repository/title injection was added to that base.

The built-in **Merlin Classic** is a small immutable Theme/LoadedTheme value
with default colors and Unicode fallback pieces: **zero bundled image bytes**.
Application boards and editor previews use the same fixed themed frame geometry.
The component's explicit unthemed mode remains available. Decorations cannot
change that geometry, square hit-testing or overlay coordinates; center-emblem
opacity and piece scaling remain the existing constants.

A draft's unassigned roles use Unicode while its valid assigned PNGs are retained.
A missing/corrupt referenced asset, broken manifest, unsupported version or deleted
active theme falls back to Merlin Classic without modifying the saved preference.
Explicitly selecting a bad theme fails before changing settings. Invalid settings
fall back on read; explicit activation can replace malformed preferences.
The editor explains errors; broken storage does not stop Game Review from loading.

## One Art Tester format; secure import

The inspected private/public Art Tester share byte-identical models, repository,
PNG validator, editor model, geometry and preview fixtures. The public release has
a separate portable-storage locator; it was not modified. Its folder layout is:

```text
<theme_id>/
  theme.json
  pieces/<white_or_black>_<piece>.png
  board/<decoration_slot>.png
```

Missing roles are valid drafts; a referenced missing file is invalid. The manifest
is version 1, with the exact existing fields, colors and fixed role paths.
No ChessWizard-specific manifest format or theme database was added.

The original repositories validate complete theme folders; neither inspected
repository had ZIP import/export code. `theme_core.packages` adds transport only:
import a validated folder or ZIP with `theme.json` at the root, optionally inside
one folder matching the manifest's theme_id. Every entry is inspected before
installation. No ZIP entries are extracted to disk; canonical data is passed
through the existing repository save path after complete validation.

Security remains an allowlist: **theme.json plus the manifest's exact PNG role
paths only**. Reject scripts/executables, SVG, unknown files, unlisted PNGs,
nested archives, traversal, absolute/drive/backslash paths, symlinks, reparse/special
entries, encrypted archives and duplicate entries/manifest keys. JSON is data.
Existing PNG signature/decoder checks reject corrupt/disguised/animated files,
strip metadata by re-encoding, and enforce 8 MiB/file and 2048×2048 dimensions.
The manifest limit is 64 KiB, package limit 22 files and 64 MiB total. ZIPs also
have a 25-entry ceiling including up to three directories and a 128 MiB container
ceiling. No engine, shell or plugin execution is part of import.

Import validates before writing, creates one independent managed snapshot with a
new ID, and never changes the source package. Rejected packages install nothing.
A frozen manifest from the existing Art Tester QA set tests all 12 pieces and
9 decoration slots, including a maximum-size valid package structure.

Export keeps the existing folder format: share/copy a saved theme folder or ZIP
that folder with ordinary archive tooling. There is no new export button.
Repository snapshots remain immutable: no overwrite or delete capability was
added because the existing repository supports neither. Saving again/importing
again intentionally creates a separate snapshot.

## Footprint and compatibility boundaries

There is no bundled sample art, theme library or public Art Tester executable.
Each window references the same managed set; decoded/scaled Tk images are in
memory only. Assets are not copied into Review/Training/editor directories.
One import copies each assigned role once. Explicit independent snapshots retain
their own role files as the existing format requires; identical images assigned
to several roles may occupy several role files. No cross-snapshot deduplication
or cleanup policy was introduced.

Tests generate temporary PNG/ZIP/settings/database fixtures. The frozen example
manifest is test-only and never installed as a runtime theme. This public
footprint summary does not include owner theme exports or local measurement
receipts. See the [shared renderer contract](#existing-renderer-and-fallback)
for the reuse boundary.
No distribution builder for ChessWizard was added or changed.

The public Art Tester checkout/build is untouched. Safest future synchronization:
review the small UI injection hook and optional package importer against the
standalone release, retaining its portable-storage choice and database-free
launcher. Do not copy the whole private application or its settings integration
into the public repository. Existing folder packages remain compatible today.

No analyzer, SEE, occurrence truth/storage, review truth or chess data changes.
Marketplace, animation, sound, scripting, cloud sync and Admin Console remain
outside V1.


## Color-only board presets

In **Appearance / Theme Editor**, use **Board Theme** to apply square colors
immediately to open ChessWizard boards. There are 30 playful base palettes, eight
alternates, **ChessWizard Default**, and **Custom** (40 choices). The catalog is
`theme_core/presets.py`; adding a palette is one immutable data entry. It contains
colors only, with no franchise names, logos, executable content or extra artwork.

The dropdown persists through the existing application settings repository.
Manual square-color edits select **Custom** and persist immediately too. Switching
back to Custom restores the last manual pair, or the saved artwork theme's colors
if no manual override exists. Old settings files default to Custom without being
rewritten. Piece PNGs, decorations, frame/coordinate colors and the application
UI skin are not replaced by presets. All profile/cache/currentness flags are false.

Artwork editing retains **Save as new theme** / **Use selected theme**. Explicitly
using a saved theme restores that theme's complete appearance and clears separate
square overrides. Presets do not create or modify saved theme folders. Frame and
coordinate edits remain draft changes until saved/activated as before.

The renderer outlines fallback Unicode pieces and movement markers for visibility
on colored squares. User PNG art is unchanged, so custom artwork should still be
checked with the existing preview. Core palette data and preference resolution do
not import Tkinter and are reusable by another frontend.
