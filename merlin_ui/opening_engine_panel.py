"""On-demand Tk presentation over portable advisory/authoring services."""
from collections.abc import Callable
from queue import SimpleQueue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import chess
from analysis_control import AnalysisCancelled
from line_playback import LinePlaybackState
from merlin_ui.information_panel import style_information_tree
from merlin_ui.opening_engine_dialog import confirm_engine_variation
from merlin_ui.proof_line_table import ProofLineTable
from opening_engine_authoring import OpeningEngineAuthoringService
from opening_engine_models import OpeningEngineAnalysis, OpeningEngineAnchor
from opening_engine_presentation import (opening_engine_playback, opening_engine_line_text, opening_engine_score_text)
from opening_engine_service import OpeningEngineService

POLL_INTERVAL_MS = 60


class OpeningEnginePanel(ttk.Frame):
    """Render explicit advisory requests without placing chess or persistence rules in Tk.

    Args:
        parent: Notebook container.
        service: Portable engine/cache request service.
        anchor_provider: Fresh saved selection, never the displayed preview board.
        authoring_provider: Explicit destination authoring service.
        show_preview: Board-only projection callback.
        restore_board: Restore the saved authored selection.
        on_added: Refresh authoring views after an explicit successful commit.
        skin: Existing shared information-panel colors.
    """
    def __init__(self, parent: tk.Misc, *, service: OpeningEngineService,
                 anchor_provider: Callable[[], OpeningEngineAnchor],
                 authoring_provider: Callable[[], OpeningEngineAuthoringService],
                 show_preview: Callable[[LinePlaybackState], None], restore_board: Callable[[], None],
                 on_added: Callable[[], None], skin: dict) -> None:
        """Build idle controls; no engine or cache operation runs here.

        Args:
            parent: Notebook container.
            service: Shared advisory service.
            anchor_provider: Current saved anchor callback.
            authoring_provider: Current author repository callback.
            show_preview: Non-mutating board projection.
            restore_board: Return to opening callback.
            on_added: Post-commit authoring refresh.
            skin: Existing terminal-view colors.
        """
        super().__init__(parent)
        self.service, self.anchor_provider = service, anchor_provider
        self.authoring_provider = authoring_provider
        self.show_preview, self.restore_board, self.on_added = show_preview, restore_board, on_added
        self.anchor = self.analysis = self.playback = None
        self.selected_rank = None
        self.editable = self.busy = self.closed = False
        self.generation = self.worker_token = 0
        self.cancel = threading.Event()
        self.events = SimpleQueue()
        self.worker = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)
        self.anchor_text = tk.StringVar(self, 'Select a saved opening position to analyze.')
        ttk.Label(self, textvariable=self.anchor_text, wraplength=500).grid(row=0, column=0, sticky='ew', padx=6, pady=6)
        controls = ttk.Frame(self)
        controls.grid(row=1, column=0, sticky='ew', padx=6)
        self.analyze_button = ttk.Button(controls, text='Analyze Position', command=self.start_analysis)
        self.analyze_button.pack(side='left')
        self.stop_button = ttk.Button(controls, text='Stop', command=self.stop)
        self.stop_button.pack(side='left', padx=4)
        ttk.Label(controls, text='Level:').pack(side='left', padx=(6,2))
        self.profile = tk.StringVar(self, 'Normal')
        self.profile_picker = ttk.Combobox(controls, state='readonly', textvariable=self.profile,
                                          values=('Quick','Normal','Deep'), width=8)
        self.profile_picker.pack(side='left')
        extra = ttk.Frame(self)
        extra.grid(row=2, column=0, sticky='ew', padx=6, pady=4)
        self.refresh_button = ttk.Button(extra, text='Refresh Analysis', command=lambda:self.start_analysis(refresh=True))
        self.refresh_button.pack(side='left')
        self.deeper_button = ttk.Button(extra, text='Analyze Deeper', command=lambda:self.start_analysis(deeper=True))
        self.deeper_button.pack(side='left', padx=4)
        self.status = tk.StringVar(self, 'Stockfish advises. You author the repertoire. Analysis runs only on request.')
        ttk.Label(self, textvariable=self.status, wraplength=500).grid(row=3, column=0, sticky='ew', padx=6, pady=4)
        table = ttk.Frame(self)
        table.grid(row=4, column=0, sticky='nsew', padx=6)
        table.rowconfigure(0, weight=1); table.columnconfigure(0, weight=1)
        self.lines = ttk.Treeview(table, columns=('move','eval','line'), show='headings', height=5, selectmode='browse')
        style_information_tree(self.lines)
        for key, title, width in (('move','Rank / Move',110),('eval','Eval (White)',95),('line','SAN continuation',320)):
            self.lines.heading(key, text=title); self.lines.column(key, width=width, minwidth=65, stretch=key=='line')
        self.lines.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(table, command=self.lines.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(table, orient='horizontal', command=self.lines.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.lines.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.lines.bind('<<TreeviewSelect>>', self.select_line)
        proof_frame = ttk.Frame(self)
        proof_frame.grid(row=5, column=0, sticky='ew', padx=6, pady=5)
        proof_frame.columnconfigure(0, weight=1)
        self.proof = ProofLineTable(proof_frame, skin=skin)
        self.proof.grid(row=0, column=0, sticky='ew')
        proof_scroll = ttk.Scrollbar(proof_frame, command=self.proof.yview)
        proof_scroll.grid(row=0, column=1, sticky='ns')
        self.proof.configure(yscrollcommand=proof_scroll.set)
        preview = ttk.Frame(self)
        preview.grid(row=6, column=0, sticky='ew', padx=6)
        self.left = ttk.Button(preview, text='←', width=4, command=lambda:self.step(-1))
        self.right = ttk.Button(preview, text='→', width=4, command=lambda:self.step(1))
        self.left.pack(side='left');self.right.pack(side='left', padx=3)
        self.return_button = ttk.Button(preview, text='Return to Opening Position', command=self.return_to_anchor)
        self.return_button.pack(side='left', padx=3)
        self.add_button = ttk.Button(self, text='Add as Variation…', command=self.add_variation)
        self.add_button.grid(row=7, column=0, sticky='w', padx=6, pady=8)
        self.bind('<Destroy>', self._destroyed)
        self._controls()
        self.poll_id = self.after(POLL_INTERVAL_MS, self._poll)

    def set_position(self, anchor: OpeningEngineAnchor | None, editable: bool, reason: str = '') -> None:
        """Update saved selection and cancel stale work without starting another request.

        Args:
            anchor: Current saved opening anchor, or None for drafts/unsaved positions.
            editable: Whether explicit Add is allowed for the current library.
            reason: Explanation when analysis is disabled.
        """
        if anchor != self.anchor:
            self.cancel.set()
            self.generation += 1
            self.analysis = self.playback = None
            self.selected_rank = None
            self.lines.delete(*self.lines.get_children())
            self.proof.set_line()
            self.restore_board()
            self.status.set('Stopping previous request…' if self.busy else 'Select Analyze Position to request Stockfish advice.')
        self.anchor, self.editable = anchor, editable
        self.anchor_text.set('Analysis position:\n' + anchor.label if anchor else reason or 'Select a saved opening position.')
        self._controls()

    def _controls(self) -> None:
        ready = self.anchor is not None and not self.busy
        for button in (self.analyze_button, self.refresh_button, self.deeper_button):
            button.configure(state='normal' if ready else 'disabled')
        self.stop_button.configure(state='normal' if self.busy and not self.cancel.is_set() else 'disabled')
        self.profile_picker.configure(state='disabled' if self.busy else 'readonly')
        self.add_button.configure(state='normal' if ready and self.editable and self.analysis and self.selected_rank else 'disabled')
        self.left.configure(state='normal' if self.playback and self.playback.ply else 'disabled')
        self.right.configure(state='normal' if self.playback and self.playback.ply < self.playback.total_plies else 'disabled')
        self.return_button.configure(state='normal' if self.playback else 'disabled')

    def start_analysis(self, *, refresh: bool = False, deeper: bool = False) -> None:
        """Start one background request only in response to an explicit button action.

        Args:
            refresh: Bypass exact cache reads for a fresh request.
            deeper: Use the existing Deep profile, retaining old advice until completion.
        """
        if self.busy or self.anchor is None:
            return
        try:
            anchor = self.anchor_provider()
            if anchor != self.anchor:
                raise ValueError('The saved position changed. Select it again before analysis.')
        except ValueError as error:
            self.status.set(str(error)); return
        if deeper:
            self.profile.set('Deep')
        profile = self.profile.get().lower()
        self.cancel = threading.Event()
        self.generation += 1
        token = self.worker_token = self.generation
        self.busy = True
        self.status.set(f'Analyzing current position · {self.profile.get()}… Previous advice stays visible until ready.')
        self._controls()
        service, events, cancel = self.service, self.events, self.cancel
        def work() -> None:
            try:
                result = service.analyze_opening_position(anchor, profile, refresh=refresh, cancel=cancel)
                events.put((token, 'result', result))
            except AnalysisCancelled:
                events.put((token, 'stopped', None))
            except Exception as error:
                events.put((token, 'error', str(error)))
        self.worker = threading.Thread(target=work, name='opening-stockfish', daemon=False)
        self.worker.start()

    def stop(self) -> None:
        """Cancel this panel's owned request without altering the authored opening."""
        self.cancel.set()
        self.status.set('Stopping Stockfish…')
        self._controls()

    def _poll(self) -> None:
        if self.closed:
            return
        while not self.events.empty():
            token, kind, value = self.events.get()
            if token == self.worker_token:
                self.busy = False
            if token != self.generation:
                if not self.busy:self.status.set('Previous request stopped. Select Analyze Position for this saved position.')
                continue
            if kind == 'result' and not self.cancel.is_set() and value.anchor == self.anchor:
                self.analysis = value
                self.playback = None
                self.selected_rank = None
                self.lines.delete(*self.lines.get_children())
                self.proof.set_line()
                self.restore_board()
                for line in value.lines.lines:
                    self.lines.insert('', 'end', iid=str(line.rank), values=(f'{line.rank}. {line.move_san}',
                        opening_engine_score_text(line), opening_engine_line_text(value, line.rank)))
                origin = 'Exact cached result' if value.cache_hit else 'Fresh Stockfish result'
                self.status.set(f'{origin} · {value.profile.label} · {len(value.lines.lines)} lines · '
                                f'{value.elapsed_seconds:.2f}s. Eval is White POV, not an opening weight or Accuracy.'
                                if value.lines.lines else 'Terminal saved position: no legal candidate moves.')
            elif kind == 'error':
                self.status.set('Stockfish could not complete: ' + value)
            else:
                self.status.set('Stopped. The opening is unchanged; previous complete advice remains available.')
        self._controls()
        self.poll_id = self.after(POLL_INTERVAL_MS, self._poll)

    def select_line(self, event: tk.Event | None = None) -> None:
        """Preview the selected line without changing the saved anchor.

        Args:
            event: Optional Tk selection event.
        """
        selected = self.lines.selection()
        if not selected or self.analysis is None:
            return
        self.selected_rank = int(selected[0])
        self.playback = opening_engine_playback(self.analysis, self.selected_rank)
        self.proof.set_line(self.playback.line)
        self._show_preview()

    def _show_preview(self) -> None:
        self.proof.set_ply(self.playback.ply)
        self.show_preview(self.playback)
        self._controls()

    def step(self, delta: int) -> None:
        """Step the isolated engine preview, clamping at either endpoint.

        Args:
            delta: Signed ply movement.
        """
        if self.playback is not None:
            self.playback = self.playback.step(delta)
            self._show_preview()

    def return_to_anchor(self) -> None:
        """Restore the authored board; keep selected advice available for explicit Add."""
        self.playback = None
        self.proof.set_ply(0)
        self.restore_board()
        self._controls()

    def add_variation(self) -> None:
        """Confirm and apply one entire selected line through the core authoring service."""
        if self.analysis is None or self.selected_rank is None or self.busy or not self.editable:
            return
        try:
            author = self.authoring_provider()
            anchor = self.anchor_provider()
            plan = author.preview_add(self.analysis, self.selected_rank, anchor)
            if not plan.new_edges:
                messagebox.showinfo('Already in opening', 'This line is already in the opening. Existing names and details are unchanged.', parent=self)
                return
            name = confirm_engine_variation(self, self.analysis, self.selected_rank, plan)
            if name is None:
                return
            plan = author.preview_add(self.analysis, self.selected_rank, self.anchor_provider(), variation_name=name)
            author.add_engine_line_to_book(self.analysis, self.selected_rank, self.anchor_provider(), plan)
            count = plan.new_edges
            self.on_added()
            self.status.set(f'Added {count} new moves at the confirmed opening position. Existing author details preserved.')
        except Exception as error:
            messagebox.showerror('Add as Variation', str(error), parent=self)

    def close(self) -> None:
        """Cancel the owned worker and detach polling; the worker closes its own engine."""
        if not self.closed:
            self.closed = True
            self.cancel.set()
            self.after_cancel(self.poll_id)

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget is self:
            self.close()
