# Themes and Art Tester V1

Art Tester is a standalone PNG editor/preview utility. It uses the **same
`merlin_ui.chess_board.ChessBoard`** as Game Review and Training through
`MerlinViewShell`. It does not open a game database, import games, launch Stockfish,
run analysis, or change the active application appearance.

## Launch

From `C:\Projects\ChessWizard`:

```powershell
.\.venv\Scripts\python.exe run_art_tester.py
```

With an activated project environment: `python run_art_tester.py`.
Install project requirements in that environment if needed (`python -m pip install
-r requirements.txt`). PNG decoding/scaling uses Pillow; V1 is tested with Pillow
12.3.0, Python 3.14 and Tk 9.0 on this Windows host. No art program is required:
export PNG from GIMP, Krita, Photoshop, Procreate, Affinity, or another editor.

## Artist workflow

1. Enter a set name and optional author.
2. In **12 piece roles**, choose a PNG for each white and black king, queen, rook,
   bishop, knight, and pawn. Scroll to reach the black-piece rows. Every row has
   a filename display, thumbnail, validation message, and Remove button.
3. In **Board & decoration**, choose light/dark square, frame, and coordinate
   colors. Use Pick or enter `#RRGGBB` and press Enter/leave the field.
4. Optionally choose decoration PNGs. Changes preview immediately.
5. Click **Save Theme**. Each save creates a new named snapshot with a unique ID;
   earlier sets are preserved. Select a saved set in the preview selector to load
   it into the editor. Edits can then be saved as another set.
6. Use Previous/Next or the sample selector, Flip board, Coordinates, and optional
   Overlay sample to inspect readability. These controls change preview state only.

All 12 piece PNGs are required for **complete** status. Missing assets produce a
clearly labeled **draft**, which may be saved and previewed with Unicode fallback
pieces. A failed replacement leaves the previous valid asset intact. A theme with
a missing referenced file or invalid package is rejected before replacing the
current preview. Close the window when finished; unsaved editor changes are not
persisted. Saving does not affect the active app theme.

## PNG requirements and layout

- Static PNG only. Transparent backgrounds are recommended; opaque PNGs work.
- Maximum 8 MiB per input/canonical PNG and 2048 × 2048 pixels.
- Prefer a consistent canvas size, padding and visual center across all pieces.
- Pieces scale proportionally to fit 82% of the square, without stretching.
  Transparent padding remains part of the canvas, so excessive padding makes art
  appear smaller. Thumbnails are also proportional.
- Board squares remain vector rectangles, not a full-board bitmap.
- The themed frame occupies a fixed 8% of the smaller widget dimension on each
  side, whether or not decorations exist. Its size is never driven by asset sizes.
- Frame decorations use proportional **contain** fit inside fixed slots, never
  free-form coordinates. Use a wide image for top/bottom borders and a tall image
  for side borders; a square image is centered within the strip.

Slots:

| Role | Placement |
| --- | --- |
| `corner_top_left`, `corner_top_right` | Corresponding frame corners |
| `corner_bottom_left`, `corner_bottom_right` | Corresponding frame corners |
| `border_top`, `border_bottom` | Horizontal frame strips outside the board |
| `border_left`, `border_right` | Vertical frame strips outside the board |
| `center_emblem` | Centered within 40% of board width; fixed 12% opacity |

Missing decorations draw nothing. Decorations are drawn after the base squares
and before highlights/arrows/pieces/coordinates. The emblem is deliberately faint
and beneath pieces. Frame slots stay in screen-relative positions when the board
flips. Artwork cannot alter square geometry or move hit-testing. Scaled Tk images
use a bounded cache and current-frame references to prevent disappearing pieces.

## Data format and storage

```text
themes/
  <sanitized-name>-<unique-id>/
    theme.json
    pieces/
      white_king.png
      white_queen.png
      white_rook.png
      white_bishop.png
      white_knight.png
      white_pawn.png
      black_king.png
      black_queen.png
      black_rook.png
      black_bishop.png
      black_knight.png
      black_pawn.png
    board/
      corner_top_left.png
      ...assigned decoration slots only...
```

`theme.json` contains `theme_id`, `name`, optional `author`/`description`, `version: 1`,
`colors`, `pieces`, and `decorations`. Colors contain `light_square`, `dark_square`,
`frame`, and `coordinate`. Piece/decor maps contain only assigned roles with their
canonical relative filenames. Completeness is derived from the 12 roles; the
manifest cannot assert it independently. Duplicate JSON fields/roles are rejected.
The frozen model copies and exposes mappings as read-only data.

The editor validates, decodes and re-encodes each PNG to RGBA before installation.
Saved files have no dependency on arbitrary Desktop/external paths. All assets and
the manifest are staged under the managed root before the new directory is
renamed into place. No existing set or backup is overwritten or deleted. An I/O
failure can leave a hidden `.pending-*` staging directory; it is not listed as an
installed theme. V1 does not automatically delete or recover incomplete staging.

## Security: data and assets only

V1 has no archive/package-import or dynamic-plugin feature. Choose File accepts
PNG assets; JSON manifests are generated by the editor. Loading a saved set treats
the manifest and every file as untrusted data:

- Allowlisted PNG signature, actual format, full decode, file/dimension limits;
  invalid images and animated PNGs are rejected.
- PNG metadata/trailing data is discarded by re-encoding.
- Only exact role-based `pieces/*.png`, `board/*.png`, and `theme.json` paths.
- No traversal, absolute manifest paths, extra files/directories, scripts,
  executables, DLLs, unsupported extensions, archives, symlinks or Windows
  reparse points/junctions (including ancestors).
- Maximum 22 package files, 64 MiB total, and a 64 KiB manifest.
- JSON parsing uses no `eval`, import, shell, executable or plugin mechanism.

Themes and future feedback/art packs may never execute code. Future archive import
must preserve this allowlist and inspect every entry before installation; V1 does
not implicitly authorize ZIP, SVG, JavaScript, Python, or other formats.

## Preview fixtures

Ten deterministic FEN fixtures live in `theme_core.preview_states`: Empty board,
Starting position, Pawns only, Knights only, Bishops only, Rooks only, Kings +
queens, Crowded center, Edge/corner stress, and Mixed realistic position.
Piece-isolation samples intentionally need not be legal games (some omit kings or
have extra material); all parse as static board positions. No playable sequence or
analysis is implied. Overlay sample uses one fixed arrow, selection and last-move
highlight solely for visual inspection. **No ghost pieces, animation, or sound.**

## Shared-renderer and portability contract

Portable modules in `theme_core/` own typed models, validation, PNG data loading,
additive storage, editor draft state, preview fixtures and display geometry.
They import neither Tkinter nor database/analyzer/engine modules.

`merlin_ui/theme_images.py` owns only Tk image resources. The existing
`ChessBoard` continues to own the production desktop canvas and input behavior.
`set_position(board, orientation)`, `set_show_coordinates`, `set_arrows`,
`set_last_move`, and the selected-square state remain unchanged. New
`set_theme(loaded_theme)` applies validated data; `set_theme(None)` restores the
original board/piece styles and original no-frame layout. Legacy callers retain
identical square geometry. Existing Review and Training view code was not changed.

Theme Preview, future Merlin Line and Pattern Builder desktop boards must use this
same component. A future mobile frontend reuses theme data/validation/geometry
with its own drawing backend; no theme business logic belongs in Tk callbacks.

## Exact next integration step for Game Review / Training

V1 intentionally provides **preview selection only**, since current app appearance
is provided by static defaults and there is no shared active-theme preference to
extend narrowly. Both screens already use the production component that was tested.
A later approved appearance-settings change should load one saved theme through
`ThemeRepository` and pass it to the existing widget:

```python
from theme_core import ThemeRepository
loaded = ThemeRepository(project_root / "themes").load(theme_id)
view.board_widget.set_theme(loaded)
```

Resolve the selected ID once in the shared appearance/view-shell setup, not
independently in each screen. On a missing/invalid set, report the problem and use
`set_theme(None)`. Do not copy board drawing into a feature UI. Persisting active
selection and adding Appearance navigation are separate future work; no database,
engine setting or analyzer migration is required for theme rendering.
