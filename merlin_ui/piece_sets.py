import tkinter as tk
import chess
from theme_core.board_geometry import PIECE_FRACTION


class UnicodePieceSet:

    def __init__(self, style):
        self.style = style

    def draw_piece(self, canvas: tk.Canvas, piece: chess.Piece, center_x: float,
                   center_y: float, square_size: float) -> None:
        """Draw a fallback glyph with a thin contrasting edge on either square color.

        Args:
            canvas: Board canvas that owns the rendered items.
            piece: Piece identity and side.
            center_x: Horizontal square center in canvas pixels.
            center_y: Vertical square center in canvas pixels.
            square_size: Current square width, used to scale glyph and edge.
        """
        symbol = piece.unicode_symbol()

        # Negative Tk font sizes use pixels; points would scale twice with the board.
        font_size = -max(1, round(square_size * PIECE_FRACTION))

        if piece.color:
            color = self.style[
                "white_piece"
            ]

        else:
            color = self.style[
                "black_piece"
            ]

        edge_color = self.style["black_piece" if piece.color else "white_piece"]
        edge_width = max(1, round(square_size * .018))
        for dx, dy in ((-edge_width, 0), (edge_width, 0), (0, -edge_width), (0, edge_width)):
            canvas.create_text(center_x + dx, center_y + dy, text=symbol,
                font=(self.style["font_family"], font_size), fill=edge_color,
                anchor=tk.CENTER, tags=("piece_contrast_edge",))

        canvas.create_text(
            center_x,
            center_y,
            text=symbol,
            font=(
                self.style[
                    "font_family"
                ],
                font_size
            ),
            fill=color,
            anchor=tk.CENTER
        )


def create_piece_set(style):

    renderer = style.get(
        "renderer",
        "unicode"
    )

    if renderer == "unicode":
        return UnicodePieceSet(
            style
        )

    raise ValueError(
        f"Unknown piece renderer: "
        f"{renderer}"
    )