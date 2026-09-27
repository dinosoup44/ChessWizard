"""Tk-only drawings over portable PositionEvaluation values; never invoke analysis."""
import math
import tkinter as tk
from tkinter import font as tkfont
from position_evaluation import EvaluationSettings


class EvaluationBar(tk.Canvas):
    def __init__(self, parent, *, settings=EvaluationSettings(), **kwargs):
        self.text_font = tkfont.Font(root=parent, family="Segoe UI", size=9)
        super().__init__(parent, width=self.text_font.measure("Not analyzed") + 12,
                         highlightthickness=0, bg="#17212b", **kwargs)
        self.settings = settings
        self.value = None
        self.proof_mode = False
        self.bind("<Configure>", lambda event: self.redraw())

    def show(self, value, *, proof_mode=False):
        self.value, self.proof_mode = value, proof_mode
        self.redraw()

    def redraw(self):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        line = self.text_font.metrics("linespace")
        top, bottom = 4 * line, max(5 * line, height - 2 * line)
        fraction = None if self.proof_mode or self.value is None else self.value.white_fraction(self.settings.display_limit_cp)
        label = "Proof line" if self.proof_mode else "Not analyzed" if fraction is None else self.value.label()
        self.create_text(width / 2, line, text=label, fill="#f5f2e9", font=self.text_font, tags="evaluation_label")
        if fraction is not None:
            self.create_text(width / 2, 2 * line, text="White POV", fill="#acbbc7", font=self.text_font)
        left, right = width / 2 - 14, width / 2 + 14
        self.create_rectangle(left, top, right, bottom, fill="#53606c" if fraction is None else "#17212b", outline="#718291")
        if fraction is not None:
            boundary = bottom - (bottom - top) * fraction
            self.create_rectangle(left, boundary, right, bottom, fill="#f5f2e9", outline="")
        self.create_line(left - 4, (top + bottom) / 2, right + 4, (top + bottom) / 2, fill="#30b7ca", dash=(2, 2))
        self.create_text(width / 2, top - line, text="Black", fill="#acbbc7", font=self.text_font, tags="black_label")
        self.create_text(width / 2, bottom + line, text="White", fill="#acbbc7", font=self.text_font, tags="white_label")


class EvaluationTimeline(tk.Canvas):
    """White-POV bars for actual positions only; unknown points have no bars."""
    def __init__(self, parent, on_select, *, settings=EvaluationSettings()):
        self.text_font = tkfont.Font(root=parent, family="Segoe UI", size=9)
        self.line_height = self.text_font.metrics("linespace")
        super().__init__(parent, height=8 * self.line_height + 16, bg="#17212b", highlightthickness=0)
        self.on_select, self.settings = on_select, settings
        self.values = ()
        self.selected_step = 0
        self.proof_mode = False
        self.bind("<Configure>", lambda event: self.redraw())
        self.bind("<Button-1>", self.click)

    def show(self, values, step, *, proof_mode=False):
        self.values, self.selected_step, self.proof_mode = tuple(values), step, proof_mode
        self.redraw()

    def x_for_step(self, step):
        return 24 + step * max(1, self.winfo_width() - 48) / max(1, len(self.values) - 1)

    def click(self, event):
        if self.values:
            step = round((event.x - 24) / max(1, self.winfo_width() - 48) * (len(self.values) - 1))
            self.on_select(max(0, min(len(self.values) - 1, step)))

    def _text(self, x, y, text, **kwargs):
        return self.create_text(x, y, text=text, font=self.text_font, fill="#bdcbd5", **kwargs)

    def redraw(self):
        self.delete("all")
        width, line = self.winfo_width(), self.line_height
        known = sum(v.complete for v in self.values)
        state = "Partial analysis · " if 0 < known < len(self.values) else ""
        self._text(10, line / 2 + 4, f"Evaluation · {state}{known}/{len(self.values)} positions", anchor="w", tags="coverage")
        if not known:
            self._text(10, 3 * line, "No evaluation data for this game.", anchor="w", tags="empty_state")
            self._text(10, 5 * line, "Run Analyze Games to create the evaluation timeline.",
                       anchor="w", width=max(1, width - 20), tags="empty_state")
            return

        top, bottom = 2 * line + 8, 5 * line + 8
        center = (top + bottom) / 2
        self._text(10, 1.5 * line + 4, "White advantage above", anchor="w")
        self._text(10, 5.5 * line + 12, "Black advantage below", anchor="w")
        self.create_line(24, center, width - 24, center, fill="#718291", tags="zero_axis")
        self._text(width - 2, center, "0.00", anchor="e", tags="zero_label")
        half_width = max(0.5, min(5, (width - 48) / max(1, len(self.values) - 1) * 0.35))
        selected = min(max(0, self.selected_step), len(self.values) - 1)
        for step, value in enumerate(self.values):
            fraction = value.white_fraction(self.settings.display_limit_cp)
            if fraction is None:
                continue
            x = self.x_for_step(step)
            y = bottom - (bottom - top) * fraction
            low, high = min(y, center), max(y, center)
            if low == high:
                low, high = center - 1, center + 1
            tags = ("evaluation_bar", f"bar_{step}")
            self.create_rectangle(x - half_width, low, x + half_width, high,
                                  fill="#eee9dc" if fraction >= 0.5 else "#87a7c5", outline="", tags=tags)
            if step == selected:
                self.create_rectangle(x - half_width - 2, low - 2, x + half_width + 2, high + 2,
                                      outline="#42d2e3", width=2, tags="selected_bar")

        # Sparse full-move labels also work for games starting from a setup FEN.
        self._text(24, 6.5 * line + 10, "Start", tags="move_label")
        move_count = max(1, len(self.values) // 2)
        slots = max(1, (width - 48) // 65)
        interval = max(5, math.ceil(move_count / slots / 5) * 5)
        previous_x = 24
        for step, value in enumerate(self.values[1:], 1):
            fields = value.position.fen.split()
            number = int(fields[5])
            x = self.x_for_step(step)
            if fields[1] == "b" and number % interval == 0 and x - previous_x >= 45:
                self._text(x, 6.5 * line + 10, str(number), tags="move_label")
                previous_x = x
        value = self.values[selected]
        if not value.complete:
            # Mark navigation below the plot, without implying an unknown evaluation is zero.
            x = self.x_for_step(selected)
            self.create_oval(x - 3, bottom + 2, x + 3, bottom + 8, outline="#42d2e3", width=2, tags="selected_unknown")
        label = value.label() if value.complete else "Not analyzed"
        anchor = "Actual game anchor · " if self.proof_mode else ""
        self._text(width / 2, 7.5 * line + 12, f"{anchor}{value.position.label} · {label}", tags="selected_label")
