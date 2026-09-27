"""Common desktop menu placement; actions stay owned by their views."""
import tkinter as tk


def application_menu(root, *, review, shell, close, last_move_var, toggle_last_move,
                     open_training=None, open_review=None):
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
    tools.add_command(label="Admin Console...", command=shell.open_admin_console)
    menu.add_cascade(label="Tools", menu=tools)
    root.configure(menu=menu)
    return menu
