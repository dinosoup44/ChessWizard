"""Studio presentation for a played line staged by Game Review."""
import tkinter as tk
from tkinter import ttk
import chess
from opening_book_models import BookSnapshot
from opening_studio_handoff import OpeningStudioHandoff, handoff_line_plan, handoff_disposition
from merlin_ui.book_line_dialog import confirm_book_line


class StagedReviewLine(ttk.LabelFrame):
    """Keep a Review continuation uncommitted until explicit author confirmation.

    Args:
        parent: Branch Browser container.
        studio: Existing Studio coordinator and ID-preserving repository owner.
    """
    def __init__(self, parent: tk.Misc, studio: object) -> None:
        """Create a hidden staging panel without opening or modifying a opening.

        Args:
            parent: Branch Browser container.
            studio: Existing Studio coordinator.
        """
        super().__init__(parent,text='Played continuation from Game Review')
        self.studio=studio;self.handoff=None
        self._inspected_snapshot=None
        self.message=ttk.Label(self,wraplength=520,justify='left')
        self.message.pack(fill='x',padx=6,pady=5)
        buttons=ttk.Frame(self);buttons.pack(fill='x',padx=6,pady=5)
        self.create_button=ttk.Button(buttons,text='Create Variation from Game',command=self.confirm)
        self.create_button.pack(side='left')
        ttk.Button(buttons,text='Cancel',command=self.cancel).pack(side='right')
        self.bind('<Configure>',lambda event:self.message.configure(wraplength=max(150,event.width-16)))

    def show(self, handoff: OpeningStudioHandoff) -> None:
        """Display an uncommitted candidate at its already selected saved anchor.

        Args:
            handoff: Exact destination and actual continuation, possibly empty.
        """
        self.cancel()
        if not handoff.candidate_moves:return
        self.handoff=handoff
        self.create_button.pack(side="left")
        board=chess.Board(handoff.anchor.fen)
        san=board.variation_san([chess.Move.from_uci(m) for m in handoff.candidate_moves])
        self.message.configure(text=f'This game left your opening here. Game {handoff.source_game_id}, ply {handoff.source_ply}.\n'
                               'Create this variation automatically, or author it with normal Save Move.\n'+san)
        self.pack(fill='x',before=self.studio.step_controls,pady=5)
        self.refresh()

    def cancel(self) -> None:
        """Discard only staged UI state; authored data remains untouched."""
        self.handoff=None;self._inspected_snapshot=None;self.pack_forget()

    def refresh(self) -> None:
        """Retire obsolete proposals once per immutable authored snapshot."""
        if self.handoff is None or self.studio.session is None:
            return
        snapshot = self.studio.session.snapshot
        if snapshot is self._inspected_snapshot:
            return
        self._inspected_snapshot = snapshot
        self._retire_if_resolved(snapshot)

    def _retire_if_resolved(self, snapshot: BookSnapshot) -> bool:
        if self.handoff is None:
            return True
        header = next((b for b in self.studio.book_items if b.path == self.studio.repository.path), None)
        library_id = header.library_id if header else ""
        disposition = handoff_disposition(snapshot, library_id, self.handoff)
        if disposition == "pending":
            return False
        self.handoff = None
        self.create_button.pack_forget()
        self.message.configure(text=("Game continuation already exists in this Opening."
            if disposition == "satisfied" else
            "The Opening has changed. Continue with normal Save Move; no extra handoff save is required."))
        return True

    def confirm(self) -> None:
        """Preview and explicitly commit through the shared atomic merge path."""
        handoff=self.handoff
        if handoff is None:return
        def add() -> None:
            snapshot=self.studio.repository.snapshot(handoff.anchor.book_id)
            if self._retire_if_resolved(snapshot):return
            if self.studio.external_readonly or self.studio.engine_anchor()!=handoff.anchor:
                raise ValueError('Return to the original saved branch before adding this played line.')
            plan=handoff_line_plan(snapshot,handoff.anchor.library_identity,handoff)
            board=chess.Board(handoff.anchor.fen)
            san=board.variation_san([chess.Move.from_uci(m) for m in handoff.candidate_moves])
            name=confirm_book_line(self,handoff.anchor.label,san,plan)
            if name is None:return
            snapshot=self.studio.repository.snapshot(handoff.anchor.book_id)
            if self._retire_if_resolved(snapshot):return
            if self.studio.engine_anchor()!=handoff.anchor:
                raise ValueError('The selected branch changed. Reopen the Review handoff.')
            plan=handoff_line_plan(snapshot,
                                   handoff.anchor.library_identity,handoff,variation_name=name)
            self.studio.repository.apply_line(plan)
            self.cancel();self.studio.engine_line_added()
        self.studio.run(add)
