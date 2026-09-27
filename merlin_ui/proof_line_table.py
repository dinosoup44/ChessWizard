"""Compact move-pair display with one subtle current-ply cell marker."""
import tkinter as tk
from merlin_ui.information_panel import style_information, CURRENT, FOREGROUND
from line_playback import format_proof_line_rows


class ProofLineTable(tk.Text):
    def __init__(self, parent, *, skin):
        super().__init__(parent, height=3, wrap="none", relief="flat", font=("Consolas", 10),
                         bg=skin["panel_bg"], fg=skin["text"], state="disabled", cursor="arrow")
        style_information(self)
        self.cells = {}
        self.tag_configure("current_ply", background=CURRENT, foreground=FOREGROUND)
        self.tag_configure("heading", foreground=skin["muted_text"])
        self.bind("<Configure>", self._resize_columns)

    def _resize_columns(self, event):
        self.configure(tabs=(55, max(165, int(event.width * .55))))

    def set_line(self, line=None):
        self.configure(state="normal", height=3)
        self.delete("1.0", "end")
        self.cells = {}
        if line and line.raw_text:
            try:
                rows = format_proof_line_rows(line)
            except ValueError:
                self.insert("end", "Playback unavailable: stored line is invalid or incomplete.\n" + line.raw_text)
            else:
                self.configure(height=min(5, len(rows) + 1))
                self.insert("end", "Move\tWhite\tBlack\n", "heading")
                for row in rows:
                    self.insert("end", str(row.move_number) + "\t")
                    for token, ply, ending in ((row.white, row.white_ply, "\t"), (row.black, row.black_ply, "\n")):
                        start = self.index("end-1c")
                        self.insert("end", token)
                        if ply is not None:
                            self.cells[ply] = (start, self.index("end-1c"))
                        self.insert("end", ending)
        self.configure(state="disabled")
        self.yview_moveto(0)

    def set_ply(self, ply=0):
        self.tag_remove("current_ply", "1.0", "end")
        if ply in self.cells:
            start, end = self.cells[ply]
            self.tag_add("current_ply", start, end)
            self.see(start)
