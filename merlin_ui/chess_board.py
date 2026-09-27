import tkinter as tk
import chess
from theme_core.board_geometry import BoardGeometry
from merlin_ui.appearance import DEFAULT_BOARD_STYLE


class ChessBoard(tk.Canvas):
    """Production board shared by review, training and art preview.

    Position, orientation and overlays use chess-square coordinates. Themes affect
    appearance only; themed layout is independent of assigned decoration slots.
    """

    def __init__(
        self,
        parent,
        board_style,
        piece_set,
        on_move_attempt=None,
        **kwargs
    ):
        super().__init__(
            parent,
            highlightthickness=0,
            cursor="hand2",
            **kwargs
        )

        self._default_board_style = dict(board_style)
        self._default_piece_set = piece_set
        self._default_background = self.cget("bg")
        self.theme_images = None
        self._image_refs = []
        self.geometry_model = BoardGeometry.fit(0, 0)
        self.board_style = dict(board_style)
        self.piece_set = piece_set

        self.on_move_attempt = on_move_attempt

        self.board = chess.Board()

        self.orientation = chess.WHITE

        self.last_move = None
        self.tactical_targets = ()
        self.arrows = []

        self.show_coordinates = True
        self.show_legal_moves = True

        self.input_enabled = False

        self.selected_square = None
        self.legal_moves = []

        self.board_pixels = 0
        self.square_size = 0

        self.offset_x = 0
        self.offset_y = 0

        self.bind(
            "<Configure>",
            self._on_resize
        )

        self.bind(
            "<Button-1>",
            self._on_click
        )

    # -------------------------------------------------
    # PUBLIC METHODS
    # -------------------------------------------------

    def set_position(
        self,
        board,
        orientation=chess.WHITE
    ):
        self.tactical_targets = ()
        self.board = board.copy()
        self.orientation = orientation

        self.clear_selection(
            redraw=False
        )

        self.redraw()

    def set_last_move(
        self,
        move
    ):
        self.last_move = move
        self.redraw()

    def set_tactical_targets(self, squares):
        """Recorded targets are a fill layer above last-move marks, below selection."""
        values = tuple(squares)
        if any(type(square) is not int or square not in chess.SQUARES for square in values):
            raise ValueError("Tactical target must be a chess square")
        self.tactical_targets = tuple(sorted(set(values)))
        self.redraw()

    def set_arrows(
        self,
        arrows
    ):
        self.arrows = arrows
        self.redraw()

    def set_input_enabled(
        self,
        enabled
    ):
        self.input_enabled = enabled

        if not enabled:
            self.clear_selection(
                redraw=False
            )

        self.redraw()

    def set_show_legal_moves(
        self,
        enabled
    ):
        self.show_legal_moves = enabled
        self.redraw()

    def set_show_coordinates(
        self,
        enabled
    ):
        self.show_coordinates = enabled
        self.redraw()

    def clear_overlays(self):
        self.last_move = None
        self.tactical_targets = ()
        self.arrows = []

        self.redraw()

    def clear_selection(
        self,
        redraw=True
    ):
        self.selected_square = None
        self.legal_moves = []

        if redraw:
            self.redraw()

    # -------------------------------------------------
    # RESIZE
    # -------------------------------------------------

    def _on_resize(
        self,
        event
    ):
        self._layout(event.width, event.height)
        self.redraw()

    def _layout(self, width, height):
        self.geometry_model = BoardGeometry.fit(width, height, framed=self.theme_images is not None)
        self.board_pixels = self.geometry_model.size
        self.square_size = self.geometry_model.square_size
        self.offset_x, self.offset_y = self.geometry_model.x, self.geometry_model.y

    def set_theme(self, loaded=None):
        """Apply a validated LoadedTheme, or restore the existing production defaults."""
        self.board_style = dict(self._default_board_style)
        self.piece_set = self._default_piece_set
        self.theme_images = None
        background = self._default_background
        if loaded is not None:
            from merlin_ui.theme_images import ThemeImages
            colors = loaded.theme.colors
            self.board_style.update(light_square=colors.light_square, dark_square=colors.dark_square,
                                    coordinate_light=colors.coordinate, coordinate_dark=colors.coordinate)
            background = colors.frame
            self.theme_images = ThemeImages(self, loaded)
            self.piece_set = self.theme_images
        self.configure(bg=background)
        self._layout(self.winfo_width(), self.winfo_height())
        self.redraw()

    # -------------------------------------------------
    # BOARD COORDINATES
    # -------------------------------------------------

    def square_to_xy(
        self,
        square
    ):
        return self.geometry_model.square_xy(square, self.orientation)

    def square_center(
        self,
        square
    ):
        x1, y1 = self.square_to_xy(
            square
        )

        return (
            x1 + self.square_size / 2,
            y1 + self.square_size / 2
        )

    def xy_to_square(
        self,
        x,
        y
    ):
        return self.geometry_model.square_at(x, y, self.orientation)

    # -------------------------------------------------
    # INTERACTION
    # -------------------------------------------------

    def _on_click(
        self,
        event
    ):
        if not self.input_enabled:
            return

        square = self.xy_to_square(
            event.x,
            event.y
        )

        if square is None:
            return

        piece = self.board.piece_at(
            square
        )

        if self.selected_square is None:

            if (
                piece is not None
                and piece.color
                == self.board.turn
            ):
                self._select_square(
                    square
                )

            return

        if square == self.selected_square:

            self.clear_selection()
            return

        if (
            piece is not None
            and piece.color
            == self.board.turn
        ):
            self._select_square(
                square
            )

            return

        possible_moves = [
            move
            for move in self.legal_moves
            if move.to_square == square
        ]

        if not possible_moves:
            return

        move = self._choose_move(
            possible_moves
        )

        self.clear_selection(
            redraw=False
        )

        if self.on_move_attempt is not None:
            self.on_move_attempt(
                move
            )

        self.redraw()

    def _select_square(
        self,
        square
    ):
        self.selected_square = square

        self.legal_moves = [
            move
            for move in self.board.legal_moves
            if move.from_square == square
        ]

        self.redraw()

    def _choose_move(
        self,
        moves
    ):
        if len(moves) == 1:
            return moves[0]

        for move in moves:

            if move.promotion == chess.QUEEN:
                return move

        return moves[0]

    # -------------------------------------------------
    # DRAWING
    # -------------------------------------------------

    def redraw(self):

        self.delete("all")
        self._image_refs = []

        if self.square_size <= 0:
            return

        self._draw_squares()
        if self.theme_images is not None:
            self.theme_images.draw_decorations(self, self.geometry_model)
        self._draw_last_move()
        self._draw_tactical_targets()
        self._draw_selection()
        self._draw_legal_moves()
        self._draw_arrows()
        self._draw_pieces()

        if self.show_coordinates:
            self._draw_coordinates()

    def _draw_squares(self):

        for square in chess.SQUARES:

            x1, y1 = self.square_to_xy(
                square
            )

            x2 = (
                x1 + self.square_size
            )

            y2 = (
                y1 + self.square_size
            )

            file_index = chess.square_file(
                square
            )

            rank_index = chess.square_rank(
                square
            )

            if (
                file_index
                + rank_index
            ) % 2 == 0:

                color = self.board_style[
                    "dark_square"
                ]

            else:

                color = self.board_style[
                    "light_square"
                ]

            self.create_rectangle(
                x1,
                y1,
                x2,
                y2,
                fill=color,
                outline=color
            )

    def _draw_last_move(self):

        if self.last_move is None:
            return

        for role, square in (("last_move_from", self.last_move.from_square),
                             ("last_move_to", self.last_move.to_square)):
            # Resolve precedence before drawing: target fill alone cannot cover
            # the outside half of a lower-priority last-move border.
            if square in self.tactical_targets:
                continue

            x1, y1 = self.square_to_xy(
                square
            )

            x2 = x1 + self.square_size
            y2 = y1 + self.square_size

            self.create_rectangle(x1, y1, x2, y2,
                outline=self.board_style.get("overlay_dark_edge", DEFAULT_BOARD_STYLE["overlay_dark_edge"]),
                width=max(2, int(self.square_size * .06)) + 2, tags=("overlay_contrast_edge",))
            self.create_rectangle(
                x1,
                y1,
                x2,
                y2,
                tags=("last_move", role),
                outline=self.board_style[
                    "last_move"
                ],
                width=max(
                    2,
                    int(
                        self.square_size
                        * 0.06
                    )
                )
            )

    def _draw_tactical_targets(self):
        for square in self.tactical_targets:
            x, y = self.square_to_xy(square)
            color = self.board_style.get("tactical_target", DEFAULT_BOARD_STYLE["tactical_target"])
            self.create_rectangle(x, y, x + self.square_size, y + self.square_size,
                                  fill=color, stipple="gray50", outline=color,
                                  width=max(2, int(self.square_size * .06)), tags=("tactical_target",))

    def _draw_selection(self):

        if self.selected_square is None:
            return

        x1, y1 = self.square_to_xy(
            self.selected_square
        )

        x2 = x1 + self.square_size
        y2 = y1 + self.square_size

        self.create_rectangle(x1, y1, x2, y2,
            outline=self.board_style.get("overlay_dark_edge", DEFAULT_BOARD_STYLE["overlay_dark_edge"]),
            width=max(3, int(self.square_size * .08)) + 2, tags=("overlay_contrast_edge",))
        self.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            tags=("selected_square",),
            outline=self.board_style[
                "selected_square"
            ],
            width=max(
                3,
                int(
                    self.square_size
                    * 0.08
                )
            )
        )

    def _draw_legal_moves(self):

        if not self.show_legal_moves:
            return

        seen_squares = set()

        for move in self.legal_moves:

            square = move.to_square

            if square in seen_squares:
                continue

            seen_squares.add(
                square
            )

            center_x, center_y = (
                self.square_center(
                    square
                )
            )

            if self.board.is_capture(
                move
            ):
                radius = (
                    self.square_size
                    * 0.37
                )

                width = max(
                    3,
                    int(
                        self.square_size
                        * 0.06
                    )
                )

                self.create_oval(center_x - radius, center_y - radius, center_x + radius, center_y + radius,
                    outline=self.board_style.get("overlay_light_edge", DEFAULT_BOARD_STYLE["overlay_light_edge"]),
                    width=width + 2, tags=("overlay_contrast_edge",))
                self.create_oval(
                    center_x - radius,
                    center_y - radius,
                    center_x + radius,
                    center_y + radius,
                    outline=self.board_style[
                        "legal_capture"
                    ],
                    width=width
                )

            else:

                radius = (
                    self.square_size
                    * 0.11
                )

                self.create_oval(
                    center_x - radius,
                    center_y - radius,
                    center_x + radius,
                    center_y + radius,
                    fill=self.board_style[
                        "legal_move"
                    ],
                    outline=self.board_style.get("overlay_light_edge", DEFAULT_BOARD_STYLE["overlay_light_edge"]),
                    width=max(1, int(self.square_size * .025)), tags=("legal_move_indicator",)
                )

    def _draw_arrows(self):

        for arrow in self.arrows:

            from_square = arrow[
                "from"
            ]

            to_square = arrow[
                "to"
            ]

            color = self.board_style.get("merlin_recommendation", self.board_style["suggestion_arrow"])

            x1, y1 = self.square_center(
                from_square
            )

            x2, y2 = self.square_center(
                to_square
            )

            width = max(
                4,
                int(
                    self.square_size
                    * 0.09
                )
            )

            self.create_line(x1, y1, x2, y2,
                fill=self.board_style.get("overlay_dark_edge", DEFAULT_BOARD_STYLE["overlay_dark_edge"]),
                width=width + 2, arrow=tk.LAST,
                arrowshape=(width * 2 + 2, width * 2 + 2, width + 2), tags=("overlay_contrast_edge",))
            self.create_line(
                x1,
                y1,
                x2,
                y2,
                fill=color,
                width=width,
                tags=("merlin_recommendation", "recommendation_arrow"),
                arrow=tk.LAST,
                arrowshape=(
                    width * 2,
                    width * 2,
                    width
                )
            )

    def _draw_pieces(self):

        for square, piece in (
            self.board.piece_map().items()
        ):

            center_x, center_y = (
                self.square_center(
                    square
                )
            )

            self.piece_set.draw_piece(
                self,
                piece,
                center_x,
                center_y,
                self.square_size
            )

    # -------------------------------------------------
    # GRID COORDINATES
    # -------------------------------------------------

    def _draw_coordinates(self):

        font_size = max(
            10,
            int(
                self.square_size
                * 0.18
            )
        )

        font = (
            "Segoe UI",
            font_size,
            "bold"
        )

        padding = max(
            4,
            int(
                self.square_size
                * 0.07
            )
        )

        # -------------------------------------------------
        # FILE LETTERS: a b c d e f g h
        # -------------------------------------------------

        if self.orientation == chess.WHITE:

            files = [
                0, 1, 2, 3,
                4, 5, 6, 7
            ]

            bottom_rank = 0

        else:

            files = [
                7, 6, 5, 4,
                3, 2, 1, 0
            ]

            bottom_rank = 7

        for display_column, file_index in enumerate(
            files
        ):

            square = chess.square(
                file_index,
                bottom_rank
            )

            x1, y1 = self.square_to_xy(
                square
            )

            color = self._coordinate_color(
                square
            )

            text = chess.FILE_NAMES[
                file_index
            ]

            x = (
                x1
                + self.square_size
                - padding
            )

            y = (
                y1
                + self.square_size
                - padding
            )

            self._draw_coordinate_text(
                x,
                y,
                text,
                color,
                font,
                anchor=tk.SE
            )

        # -------------------------------------------------
        # RANK NUMBERS: 1 2 3 4 5 6 7 8
        # -------------------------------------------------

        if self.orientation == chess.WHITE:

            ranks = [
                7, 6, 5, 4,
                3, 2, 1, 0
            ]

            left_file = 0

        else:

            ranks = [
                0, 1, 2, 3,
                4, 5, 6, 7
            ]

            left_file = 7

        for display_row, rank_index in enumerate(
            ranks
        ):

            square = chess.square(
                left_file,
                rank_index
            )

            x1, y1 = self.square_to_xy(
                square
            )

            color = self._coordinate_color(
                square
            )

            text = str(
                rank_index + 1
            )

            x = (
                x1 + padding
            )

            y = (
                y1 + padding
            )

            self._draw_coordinate_text(
                x,
                y,
                text,
                color,
                font,
                anchor=tk.NW
            )

    def _coordinate_color(
        self,
        square
    ):
        file_index = chess.square_file(
            square
        )

        rank_index = chess.square_rank(
            square
        )

        if (
            file_index
            + rank_index
        ) % 2 == 0:

            return self.board_style[
                "coordinate_light"
            ]

        return self.board_style[
            "coordinate_dark"
        ]

    def _draw_coordinate_text(
        self,
        x,
        y,
        text,
        color,
        font,
        anchor
    ):
        """
        Draw a small dark shadow behind the
        coordinate so it remains readable on
        light and dark board themes.
        """

        shadow_offset = max(
            1,
            int(
                self.square_size
                * 0.015
            )
        )

        self.create_text(
            x + shadow_offset,
            y + shadow_offset,
            text=text,
            fill="#222222",
            font=font,
            anchor=anchor
        )

        self.create_text(
            x,
            y,
            text=text,
            fill=color,
            font=font,
            anchor=anchor
        )