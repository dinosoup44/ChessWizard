"""Stockfish-specific presentation around the shared author confirmation."""
import tkinter as tk
from opening_book_line import BookLinePlan
from opening_engine_models import OpeningEngineAnalysis
from opening_engine_presentation import opening_engine_line_text
from merlin_ui.book_line_dialog import confirm_book_line


def confirm_engine_variation(parent: tk.Misc, analysis: OpeningEngineAnalysis,
                             rank: int, plan: BookLinePlan) -> str | None:
    """Show the exact destination and full engine continuation before authoring.

    Args:
        parent: Owning Studio widget.
        analysis: Advice shown to the author.
        rank: Selected actual candidate.
        plan: Side-effect-free merge preview.

    Returns:
        The optional name on explicit Add, or None on cancellation.
    """
    return confirm_book_line(parent, analysis.anchor.label,
                             opening_engine_line_text(analysis, rank), plan,
                             title='Add Stockfish Variation')
