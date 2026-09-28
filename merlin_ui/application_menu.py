"""Common desktop menu placement; actions stay owned by their views."""
import tkinter as tk
from collections.abc import Callable
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from merlin_ui.game_review_view import GameReviewView
    from merlin_ui.view_shell import MerlinViewShell


def application_menu(root: tk.Misc, *, review: "GameReviewView", shell: "MerlinViewShell",
                     close: Callable[[], object], last_move_var: tk.BooleanVar,
                     toggle_last_move: Callable[[], object], open_training: Callable[[], object] | None = None,
                     open_review: Callable[[], object] | None = None) -> tk.Menu:
    """Build shared desktop menus using view-owned navigation callbacks.

    Args:
        root: Window receiving the menu.
        review: Owner of game and plugin navigation.
        shell: Owner of appearance and administration dialogs.
        close: Owning window's shutdown callback.
        last_move_var: Existing last-move display preference.
        toggle_last_move: Callback applying that preference.
        open_training: Optional shared training navigation.
        open_review: Optional return-to-review navigation.

    Returns:
        Installed native application menu.
    """
    menu = tk.Menu(root)
    file = tk.Menu(menu, tearoff=False)
    file.add_command(label="Import Games...", command=review.open_import_games)
    file.add_command(label="Manage Data...", command=review.open_manage_data)
    file.add_separator()
    file.add_command(label="Exit", command=close)
    menu.add_cascade(label="File", menu=file)
    view = tk.Menu(menu, tearoff=False)
    if open_review:
        view.add_command(label="Game Review", command=open_review)
    view.add_checkbutton(label="Show Last Move", variable=last_move_var, command=toggle_last_move)
    view.add_command(label="Appearance...", command=shell.open_theme_editor)
    menu.add_cascade(label="View", menu=view)
    tools = tk.Menu(menu, tearoff=False)
    tools.add_command(label="Opening Library...", command=review.open_opening_library)
    tools.add_command(label="Opening Studio...", command=review.open_opening_book_studio)
    tools.add_command(label="Game Explorer...", command=review.open_game_explorer)
    tools.add_command(label="Analyze Games...", command=review.open_analyze_games)
    tools.add_command(label="Training...", command=open_training or review.open_training)
    tools.add_command(label="Human Review / QA...", command=review.open_human_review)
    tools.add_command(label="Plugins...", command=review.open_plugins)
    tools.add_command(label="Admin Console...", command=shell.open_admin_console)
    menu.add_cascade(label="Tools", menu=tools)
    root.configure(menu=menu)
    return menu
