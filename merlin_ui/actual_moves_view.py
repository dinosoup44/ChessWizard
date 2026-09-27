"""Actual-history cells have explicit half-move targets; proof playback is separate."""
from merlin_ui.information_panel import InformationPanel, CURRENT
from game_context import actual_move_rows


class ActualMovesView(InformationPanel):
    def __init__(self, parent, on_jump):
        super().__init__(parent)
        self.configure(wrap="none")
        self.bind("<Configure>",lambda event:self.configure(tabs=(48,max(145,int(event.width*.55)))))
        self.on_jump = on_jump
        self.tag_configure("current", background=CURRENT, foreground="white")
        self.configure(cursor="hand2")

    def render(self, moves, current_step):
        self.configure(state="normal")
        self.delete("1.0", "end")
        for tag in self.tag_names():
            if tag.startswith("step_"):
                self.tag_delete(tag)
        self.insert("end", "ACTUAL GAME MOVES\nMove\tWhite\tBlack\n")
        if not moves:
            self.insert("end", "No stored moves.")
        for row in actual_move_rows(moves):
            self.insert("end", str(row.number)+"\t")
            for color in ("white", "black"):
                step = getattr(row, color+"_step")
                text = getattr(row, color)
                tag = "step_"+str(step)
                tags = (tag, "current") if step == current_step else (tag,)
                self.insert("end", text, tags if step is not None else ())
                if color == "white":
                    self.insert("end", "\t")
                if step is not None:
                    self.tag_bind(tag, "<Button-1>", lambda event, s=step: self.on_jump(s))
            self.insert("end", "\n")
        self.configure(state="disabled")
        ranges = self.tag_ranges("current")
        if ranges:
            self.see(ranges[0])
