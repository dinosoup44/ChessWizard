"""Responsive Tk controls over cancellable, frontend-neutral analysis services."""
from collections.abc import Callable
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from merlin_ui.action_dialog import choose_action
from merlin_ui.information_panel import style_information
from chesswizard_version import window_title
from analysis_control import AnalysisCancelled
from game_analysis_models import (AnalysisScopeKind, GameAnalysisScope, GameAnalysisResult,
                                  AnalysisProgress, CoverageProgress)
from game_analysis_service import GameAnalysisService

POLL_INTERVAL_MS = 100


class AnalyzeGamesDialog:
    """Present asynchronous coverage and explicitly started analysis.

    Args:
        root: Window owned by this dialog.
        database_path: Profile database; workers open their own connections.
        selected_game_ids: Current Review selection.
        on_complete: Main-thread callback after a completed/stopped run.
        service: Optional shared service override for tools and tests.
        on_batch_complete: Main-thread notification after a committed batch.
    """
    def __init__(self, root: tk.Misc, database_path: str | Path, *,
                 selected_game_ids: tuple[int, ...] = (),
                 on_complete: Callable[[GameAnalysisResult], None] = lambda result: None,
                 service: GameAnalysisService | None = None,
                 on_batch_complete: Callable[[], None] = lambda: None) -> None:
        """Build responsive controls and schedule background readiness detection.

        Args:
            root: Owning Tk window.
            database_path: Existing profile database.
            selected_game_ids: Review's current game selection.
            on_complete: Main-thread completion notification.
            service: Optional shared analysis service override.
            on_batch_complete: Main-thread callback making committed work visible in Review.
        """
        self.root = root
        self.service = service if service is not None else GameAnalysisService(database_path)
        self.selected_game_ids = tuple(selected_game_ids)
        self.on_complete = on_complete
        self.on_batch_complete = on_batch_complete
        self.events = queue.SimpleQueue()
        self.cancel = threading.Event()
        self.preview_cancel = threading.Event()
        self.preview_generation = 0
        self.busy = self.loading = self.closed = False
        self.snapshot = None
        self.started = None
        self.worker = None
        self.when_stopped = None
        root.title(window_title('Analyze Games'))
        root.geometry('680x640')
        root.minsize(520, 470)
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Analyze Games', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
        self.pending = tk.StringVar(root, value='Games needing analysis: Checking...')
        ttk.Label(frame, textvariable=self.pending, wraplength=610).pack(anchor='w', pady=10)
        ttk.Label(frame, text='Scope').pack(anchor='w')
        self.scope = tk.StringVar(root, value=AnalysisScopeKind.RECENT_50.value)
        self.scope_picker = ttk.Combobox(frame, textvariable=self.scope, state='readonly',
                                         values=tuple(k.value for k in AnalysisScopeKind))
        self.scope_picker.pack(fill='x', pady=(4, 8))
        self.scope_picker.bind('<<ComboboxSelected>>', lambda event: self.refresh())
        ttk.Label(frame, text='Profile: ' + self.service.profile.label).pack(anchor='w')
        quality = self.service.quality_settings
        quality_label = (f'Move quality compares best/played continuations at depth {quality.generator.engine.depth}.'
                         if quality is not None else 'Move quality is disabled for this tool.')
        ttk.Label(frame, text='Analysis saves reusable evidence and uses disk space.\n'
                  + quality_label + '\nStop cancels the current stage; completed stages are kept.',
                  wraplength=610).pack(anchor='w', pady=10)
        bar = ttk.Frame(frame)
        bar.pack(fill='x')
        self.start_button = ttk.Button(bar, text='Start Analysis', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(bar, text='Stop', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=8)
        self.refresh_button = ttk.Button(bar, text='Refresh count', command=self.refresh)
        self.refresh_button.pack(side='left')
        self.status = tk.StringVar(root, value='Idle — click Start Analysis when ready.')
        ttk.Label(frame, textvariable=self.status, wraplength=610).pack(anchor='w', pady=10)
        self.progress_bar = ttk.Progressbar(frame, maximum=100, mode='determinate')
        self.progress_bar.pack(fill='x')
        self.elapsed = tk.StringVar(root)
        ttk.Label(frame, textvariable=self.elapsed).pack(anchor='w')
        self.output = ScrolledText(frame, height=12, wrap='word', state='disabled')
        style_information(self.output)
        self.output.pack(fill='both', expand=True, pady=8)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<Destroy>', self.destroyed, add='+')
        self.poll_id = root.after(POLL_INTERVAL_MS, self.poll)
        self.refresh()

    def _scope(self) -> GameAnalysisScope:
        kind = AnalysisScopeKind(self.scope.get())
        return GameAnalysisScope(kind, self.selected_game_ids if kind == AnalysisScopeKind.SELECTED else ())

    def _controls(self) -> None:
        self.scope_picker.configure(state='disabled' if self.busy else 'readonly')
        self.refresh_button.configure(state='disabled' if self.busy else 'normal')
        try:
            self._scope()
            ready = self.snapshot is None or bool(self.snapshot.queued) or not self.snapshot.scope_complete
        except ValueError:
            ready = False
        self.start_button.configure(state='normal' if ready and not self.busy else 'disabled')
        self.stop_button.configure(state='normal' if self.busy and not self.cancel.is_set() else 'disabled')

    def _cancel_preview(self) -> None:
        self.preview_cancel.set()
        self.preview_generation += 1
        self.loading = False

    def refresh(self) -> None:
        """Replace background detection; scope controls remain immediately usable."""
        if self.busy or self.closed:
            return
        self._cancel_preview()
        self.snapshot = None
        try:
            scope = self._scope()
        except ValueError as error:
            self.pending.set(str(error))
            self._controls()
            return
        self.loading = True
        self.preview_cancel = threading.Event()
        self.preview_started = time.monotonic()
        self.pending.set('Games needing analysis: Checking...')
        self._controls()
        service, events = self.service, self.events
        generation, cancel = self.preview_generation, self.preview_cancel
        def worker() -> None:
            try:
                value = service.preview(scope, cancel=cancel,
                    progress=lambda event: events.put(('coverage', event, generation)))
                events.put(('snapshot', value, generation))
            except AnalysisCancelled:
                pass
            except Exception as error:
                events.put(('preview_error', f'{type(error).__name__}: {error}', generation))
        threading.Thread(target=worker, name='analysis-preview', daemon=False).start()

    def start(self) -> None:
        """Start the chosen scope without depending on a completed global preview."""
        if self.busy or self.closed:
            return
        try:
            scope = self._scope()
        except ValueError as error:
            self.pending.set(str(error))
            return
        if self.snapshot is not None and not self.snapshot.queued and self.snapshot.scope_complete:
            return
        self._cancel_preview()
        self.busy = True
        self.cancel.clear()
        self.started = time.monotonic()
        self._controls()
        self.status.set('Checking analysis coverage for the selected scope...')
        self.show_text('')
        service, events, cancel = self.service, self.events, self.cancel
        def worker() -> None:
            try:
                result = service.run(scope, cancel=cancel,
                    progress=lambda event: events.put(('progress', event, None)))
            except Exception as error:
                result = GameAnalysisResult(errors=1, fatal_errors=1, queue_complete=False,
                    details=(f'{type(error).__name__}: {error}',))
            events.put(('result', result, None))
        self.worker = threading.Thread(target=worker, name='game-analysis', daemon=False)
        self.worker.start()

    def stop(self) -> None:
        """Cancel active computation; the service rolls back its unfinished stage."""
        self.cancel.set()
        self.status.set('Stopping... cancelling the engine and rolling back the unfinished stage.')
        self._controls()

    def show_text(self, text: str) -> None:
        """Replace the status body.

        Args:
            text: Current phase details or final run summary.
        """
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        self.output.insert('1.0', text)
        self.output.configure(state='disabled')

    def _coverage(self, value: CoverageProgress) -> None:
        self.progress_bar['value'] = value.percent
        self.show_text(f'Phase: Checking analysis coverage\n'
            f'Games checked: {value.checked:,} / {value.total:,} ({value.percent:.1f}%)')

    def _progress(self, value: AnalysisProgress) -> None:
        if not self.cancel.is_set():
            self.status.set(value.message)
        batch = (f'Batch {value.batch_index:,} of {value.batch_count:,} · '
                 f'Games {value.batch_start:,}–{value.batch_end:,} of {value.scope_total:,}\n'
                 f'Complete in batch: {value.batch_completed:,} / {value.batch_end-value.batch_start+1:,}\n'
                 f'Games inspected this run: {value.games_inspected:,} / {value.scope_total:,}\n'
                 f'Games with completed coverage: {value.overall_completed:,}\n'
                 if value.batch_index else '')
        self.progress_bar['value'] = 100*value.games_inspected/value.scope_total if value.scope_total else 0
        if value.phase == 'Checking analysis coverage':
            percent = 100*value.coverage_checked/value.coverage_total if value.coverage_total else 100
            self.show_text(batch + f'Phase: {value.phase}\n'
                f'This batch checked: {value.coverage_checked:,} / {value.coverage_total:,} ({percent:.1f}%)')
            return
        self.show_text(batch + f'Phase: {value.phase}\n'
            f'Games processed needing work: {value.games_visited:,} / {value.games_queued:,} discovered so far\n'
            f'Current game: {value.game_label}\nCurrent stage: {value.analyzer}\n'
            f'Position evaluation: {value.evaluation_completed:,} / {value.evaluation_total:,}\n'
            f'Move quality: {value.quality_completed:,} / {value.quality_total:,}\n'
            f'Completed tactical checks: {value.checks_processed:,}\n'
            f'New tactical candidates: {value.candidates_created:,}\n'
            f'Games deferred: {value.games_deferred:,}\n'
            f'Recoverable errors: {value.recoverable_errors:,} · Fatal errors: {value.fatal_errors:,}')
        if value.phase == 'Batch completed':
            self.on_batch_complete()

    def poll(self) -> None:
        """Apply worker messages on the Tk thread, ignoring obsolete previews."""
        if self.closed:
            return
        while not self.events.empty():
            kind, value, generation = self.events.get()
            if generation is not None and generation != self.preview_generation:
                continue
            if kind == 'coverage':
                self._coverage(value)
            elif kind == 'snapshot':
                self.loading = False
                self.snapshot = value
                prefix = 'Games needing analysis' if value.scope_complete else 'First batch needing analysis'
                self.pending.set(f'{prefix}: {len(value.queued):,} · Already complete: {value.complete_games:,}'
                    + (f' · {value.eligible_games:,} eligible games; older batches not yet inspected' if not value.scope_complete else '')
                    + (f' · Empty records skipped: {len(value.skipped_empty_ids):,}' if value.skipped_empty_ids else '')
                    + (f' · Protected stale checks: {value.protected_checks:,}' if value.protected_checks else ''))
                self._controls()
            elif kind == 'preview_error':
                self.loading = False
                self.pending.set('Cannot inspect analysis scope: ' + value)
                self._controls()
            elif kind == 'progress':
                self._progress(value)
            elif kind == 'result':
                self.busy = False
                self.snapshot = None
                self.elapsed.set(f'Elapsed: {value.elapsed_seconds:.1f} seconds')
                self.progress_bar['value'] = value.progress_percent
                self.status.set('Analysis stopped.' if value.cancelled else 'Stopped safely after a fatal system error.' if value.fatal_errors else
                    'Run finished; recoverable errors were isolated and later games continued.' if value.recoverable_errors else
                    'Run finished. ' + value.remaining_explanation if value.remaining_explanation else 'Analysis complete.')
                self.pending.set(f'Games still needing work in this scope: {value.games_remaining:,}' if value.queue_complete
                                 else 'Games needing analysis: Not counted (coverage check unfinished)')
                self.show_text(value.summary())
                self._controls()
                if self.when_stopped is not None:
                    callback, self.when_stopped = self.when_stopped, None
                    callback()
                    if self.closed:
                        return
                else:
                    self.on_complete(value)
        if self.busy and self.started is not None:
            self.elapsed.set(f'Elapsed: {time.monotonic()-self.started:.1f} seconds')
        elif self.loading:
            self.elapsed.set(f'Coverage check: {time.monotonic()-self.preview_started:.1f} seconds')
        self.poll_id = self.root.after(POLL_INTERVAL_MS, self.poll)

    def request_close(self, after_stop: Callable[[], None]) -> bool:
        """Confirm cancellation and schedule a close when the worker has exited.

        Args:
            after_stop: Main-thread continuation that completes the requested exit.

        Returns:
            True if no worker needs stopping; otherwise False.
        """
        if not self.busy:
            return True
        if self.when_stopped is None:
            choice = choose_action(self.root, 'Analysis is running',
                'Stop analysis and exit? Completed stages will be kept. The unfinished stage will be redone on resume.',
                (('Stop analysis and exit', 'stop'), ('Keep running / Cancel exit', 'cancel')))
            if choice == 'stop':
                self.when_stopped = after_stop
                self.stop()
        return False

    def close(self) -> None:
        """Close immediately, or finish closing automatically after confirmed Stop."""
        if self.request_close(self.root.destroy):
            self.root.destroy()

    def destroyed(self, event: tk.Event) -> None:
        """Cancel detached work when the owning Tk window is destroyed.

        Args:
            event: Tk destroy event; child-widget events are ignored.
        """
        if event.widget == self.root:
            self.closed = True
            self.cancel.set()
            self._cancel_preview()
            self.root.after_cancel(self.poll_id)
