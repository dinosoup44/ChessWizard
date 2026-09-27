from merlin_ui.information_panel import BACKGROUND, FOREGROUND
import tkinter as tk
from chesswizard_version import window_title

from merlin_ui.appearance import (
    DEFAULT_UI_SKIN,
    DEFAULT_BOARD_STYLE,
    DEFAULT_PIECE_STYLE,
)

from merlin_ui.piece_sets import (
    create_piece_set,
)

from merlin_ui.chess_board import (
    ChessBoard,
)


class MerlinViewShell:
    """
    Reusable two-pane Merlin view foundation.

    This class owns only shared UI structure:
    - application window styling
    - chess board area
    - status line
    - left-side control container
    - right-side feature panel
    - shared button/checkbutton styling

    It intentionally does NOT know anything about:
    - tactic candidates
    - training attempts
    - game review
    - openings
    - repertoires
    - Stockfish

    Feature views build their own controls and behavior on top
    of this shell.
    """

    def __init__(
        self,
        root,
        on_move_attempt=None,
        title=window_title("Merlin"),
        geometry="1120x760",
        min_size=(900, 650),
        ui_skin=None,
        board_style=None,
        piece_style=None,
        theme_service=None,
        admin_database_path=None,
    ):
        self.root = root
        self.admin_database_path = admin_database_path
        from theme_core.active import get_active_theme_service
        self.theme_service = theme_service if theme_service is not None else get_active_theme_service()

        self.ui_skin = (
            ui_skin
            if ui_skin is not None
            else DEFAULT_UI_SKIN
        )

        self.root._merlin_ui_skin = self.ui_skin

        self.board_style = (
            board_style
            if board_style is not None
            else DEFAULT_BOARD_STYLE
        )

        self.piece_style = (
            piece_style
            if piece_style is not None
            else DEFAULT_PIECE_STYLE
        )

        self.status_var = tk.StringVar(
            value=""
        )

        self._configure_window(
            title,
            geometry,
            min_size,
        )

        self._build_layout(
            on_move_attempt
        )
        from merlin_ui.theme_binding import BoardThemeBinding
        self.theme_binding = BoardThemeBinding(self.board_widget, self.theme_service)
        self._theme_window = None
        self._admin_window = None

    # -------------------------------------------------
    # WINDOW
    # -------------------------------------------------

    def open_admin_console(self):
        """Open the read-only console using this view's shared appearance service."""
        if self._admin_window is not None and self._admin_window.winfo_exists():
            self._admin_window.lift()
            return
        from admin_service import AdminService
        from merlin_ui.admin_console import AdminConsole
        self._admin_window = tk.Toplevel(self.root)
        self._admin_console = AdminConsole(self._admin_window, AdminService(database_path=self.admin_database_path,theme_service=self.theme_service))

    def open_theme_editor(self):
        """Keep one Appearance window per view, sharing the application's preference."""
        if self._theme_window is not None and self._theme_window.winfo_exists():
            self._theme_window.lift()
            return
        from merlin_ui.theme_editor import ThemeEditor
        self._theme_window = tk.Toplevel(self.root)
        try:
            self._theme_editor = ThemeEditor(self._theme_window, self.theme_service)
        except (ValueError, OSError) as error:
            self._theme_window.destroy()
            from tkinter import messagebox
            messagebox.showerror("Appearance unavailable", str(error), parent=self.root)

    def _configure_window(
        self,
        title,
        geometry,
        min_size,
    ):
        self.root.title(
            title
        )

        self.root.geometry(
            geometry
        )

        self.root.minsize(
            min_size[0],
            min_size[1],
        )

        self.root.configure(
            bg=self.ui_skin[
                "window_bg"
            ]
        )

    # -------------------------------------------------
    # SHARED LAYOUT
    # -------------------------------------------------

    def _build_layout(
        self,
        on_move_attempt,
    ):
        self.main = tk.Frame(
            self.root,
            bg=self.ui_skin[
                "window_bg"
            ]
        )

        self.main.pack(
            fill=tk.BOTH,
            expand=True,
            padx=14,
            pady=14,
        )

        self.main.columnconfigure(0, weight=3, uniform="pane")

        self.main.columnconfigure(1, weight=2, uniform="pane")

        self.main.rowconfigure(
            0,
            weight=1,
        )

        # -------------------------------------------------
        # LEFT PANE
        # -------------------------------------------------

        self.left = tk.Frame(
            self.main,
            bg=self.ui_skin[
                "window_bg"
            ]
        )

        self.left.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 12),
        )

        self.left.rowconfigure(
            0,
            weight=1,
        )

        self.left.columnconfigure(
            0,
            weight=1,
        )

        piece_set = create_piece_set(
            self.piece_style
        )

        self.board_widget = ChessBoard(
            self.left,
            board_style=self.board_style,
            piece_set=piece_set,
            on_move_attempt=on_move_attempt,
            bg=self.ui_skin[
                "window_bg"
            ],
        )

        self.board_widget.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        # -------------------------------------------------
        # STATUS
        # -------------------------------------------------

        self.status_label = tk.Label(
            self.left,
            textvariable=self.status_var,
            bg=self.ui_skin[
                "window_bg"
            ],
            fg=self.ui_skin[
                "muted_text"
            ],
            font=(
                "Segoe UI",
                11,
                "bold",
            ),
            anchor="w",
        )

        self.status_label.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(8, 2),
        )

        self.status_label.configure(bg=BACKGROUND, fg=FOREGROUND, justify="left", padx=10, pady=6)
        self.left.bind("<Configure>", lambda event: self.status_label.configure(wraplength=max(100, event.width-20)))

        # -------------------------------------------------
        # FEATURE-SPECIFIC LEFT CONTROLS
        # -------------------------------------------------

        self.left_controls = tk.Frame(
            self.left,
            bg=self.ui_skin[
                "window_bg"
            ]
        )

        self.left_controls.grid(
            row=2,
            column=0,
            sticky="ew",
            pady=(4, 0),
        )

        # -------------------------------------------------
        # RIGHT PANE
        # -------------------------------------------------

        self.right_panel = tk.Frame(
            self.main,
            bg=self.ui_skin[
                "panel_bg"
            ],
            highlightthickness=1,
            highlightbackground=(
                self.ui_skin[
                    "border"
                ]
            ),
        )

        self.right_panel.grid(
            row=0,
            column=1,
            sticky="nsew",
        )

        self.right_panel.columnconfigure(
            0,
            weight=1,
        )

    # -------------------------------------------------
    # SHARED STATUS
    # -------------------------------------------------

    def set_status(
        self,
        text,
        kind="normal",
    ):
        self.status_var.set(
            text
        )

        if kind == "good":
            color = self.ui_skin[
                "status_good"
            ]

        elif kind == "bad":
            color = self.ui_skin[
                "status_bad"
            ]

        else:
            color = self.ui_skin[
                "muted_text"
            ]

        self.status_label.configure(
            fg=color
        )

    # -------------------------------------------------
    # SHARED WIDGET HELPERS
    # -------------------------------------------------

    def make_button(
        self,
        parent,
        text,
        command,
    ):
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=self.ui_skin[
                "button_bg"
            ],
            fg=self.ui_skin[
                "button_fg"
            ],
            activebackground=(
                self.ui_skin[
                    "button_active_bg"
                ]
            ),
            activeforeground=(
                self.ui_skin[
                    "button_fg"
                ]
            ),
            disabledforeground="#777777",
            relief=tk.FLAT,
            padx=10,
            pady=6,
            cursor="hand2",
        )

    def make_checkbutton(
        self,
        parent,
        text,
        variable,
        command,
    ):
        return tk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            command=command,
            bg=self.ui_skin[
                "window_bg"
            ],
            fg=self.ui_skin[
                "text"
            ],
            activebackground=(
                self.ui_skin[
                    "window_bg"
                ]
            ),
            activeforeground=(
                self.ui_skin[
                    "text"
                ]
            ),
            selectcolor=(
                self.ui_skin[
                    "panel_bg"
                ]
            ),
        )
