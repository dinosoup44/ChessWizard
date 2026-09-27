"""Shared affected-game list for opening variations, deviations and gaps."""
from collections.abc import Callable
import tkinter as tk
from tkinter import ttk
from opening_review_navigation import OpeningOccurrence, OpeningGameSelection, affected_games
from merlin_ui.information_panel import style_information_tree


class OpeningOccurrences(ttk.Frame):
    """Render affected games without navigating the displayed board.

    Args:
        parent: Opening Review upper pane.
        on_select: Selection callback for one game and its exact summary visits.
    """
    def __init__(self, parent: tk.Misc, on_select: Callable[[OpeningGameSelection], None]) -> None:
        """Build a compact scrollable affected-game list.

        Args:
            parent: Containing pane.
            on_select: Callback that populates moments without navigating the board.
        """
        super().__init__(parent)
        self.on_select = on_select
        self.rows: dict[str, OpeningGameSelection] = {}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.caption = ttk.Label(self, text='Select a summary to see affected games.')
        self.caption.grid(row=0, column=0, sticky='ew')
        self.tree = ttk.Treeview(self, columns=('game','date','opponent','result','move','accuracy','loss'),
                                 show='headings', height=6, selectmode='browse')
        style_information_tree(self.tree)
        for name, label, width in (('game','Game ID',65),('date','Date',95),('opponent','Opponent',120),
                                  ('result','Result',65),('move','Actual move',90),
                                  ('accuracy','Opening Accuracy',120),('loss','Deviation loss (cp)',130)):
            self.tree.heading(name, text=label)
            self.tree.column(name, width=width, minwidth=45, stretch=False)
        self.tree.grid(row=1, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(self, command=self.tree.yview)
        vertical.grid(row=1, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(self, orient='horizontal', command=self.tree.xview)
        horizontal.grid(row=2, column=0, sticky='ew')
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.bind('<<TreeviewSelect>>', self._select)
        self._selection = None
        self.bind('<Configure>',lambda event:self.caption.configure(wraplength=max(100,event.width-90)))

    def show(self, rows: tuple[OpeningOccurrence, ...], caption: str) -> None:
        """Replace all visit details without implicitly navigating.

        Args:
            rows: Exact occurrences for the selected summary row.
            caption: Context label, including whether this is a coverage signal.
        """
        self._selection = None
        self.rows = {str(row.game.context.game_id): row for row in affected_games(rows)}
        self.tree.delete(*self.tree.get_children())
        self.caption.configure(text=caption)
        for key, row in self.rows.items():
            context = row.game.context
            user = row.game.accuracy.user
            score = user.quality.accuracy if user else None
            accuracy = '—' if score is None else f'{score:.2f}' + (' (partial)' if not user.quality.complete else '')
            losses = [str(visit.quality.eval_loss_cp) for visit in row.occurrences
                      if visit.quality and visit.quality.eval_loss_cp is not None]
            self.tree.insert('', 'end', iid=key, values=(context.game_id,
                (context.played_at or 'Unknown')[:10].replace('.','-'),
                context.black_username if context.user_color == 'white' else context.white_username,
                context.result, ' / '.join(visit.move.move_label for visit in row.occurrences if visit.move) or '—',
                accuracy, ' / '.join(losses) or '—'))

    def _select(self, event: tk.Event | None = None) -> None:
        selected = self.tree.selection()
        if selected and selected[0] != self._selection and selected[0] in self.rows:
            self._selection = selected[0]
            self.on_select(self.rows[selected[0]])
