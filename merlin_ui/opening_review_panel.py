"""Selected-game opening moments; browsing never owns the displayed board cursor."""
from dataclasses import replace
import tkinter as tk
from tkinter import ttk
from opening_intelligence_models import OpeningGameAssessment
from opening_intelligence_lookup import OpeningBookLookup
from opening_intelligence_presentation import context_text
from opening_exploration import explore_book_move
from opening_accuracy import derive_opening_accuracy
from opening_accuracy_presentation import opening_metrics_text
from opening_workspace import opening_moments
from merlin_ui.information_panel import style_information_tree


class OpeningReviewPanel(ttk.Frame):
    """Render exact selected-game events separately from the displayed game.

    Args:
        parent: Adjustable lower workspace pane.
        review: Shared Game Review coordinator.
    """

    def __init__(self, parent: tk.Misc, review: object) -> None:
        """Build the moments grid and explicit line/Studio actions.

        Args:
            parent: Lower pane.
            review: Existing board and actual-game state owner.
        """
        super().__init__(parent)
        self.review = review
        self.assessment = self.lookup = self.accuracy = None
        self.library_name = ''
        self._moment_key = self._selection = None
        self.selected_ply: int | None = None
        self.moments = ()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.indicator = ttk.Label(self, text='Opening Moments', wraplength=520)
        self.indicator.grid(row=0, column=0, sticky='ew', padx=5)
        toolbar = ttk.Frame(self)
        toolbar.grid(row=1, column=0, sticky='ew', pady=4)
        self.show_button = ttk.Button(toolbar, text='Show Opening Line', command=self.show_line)
        self.show_button.pack(side='left')
        self.back = ttk.Button(toolbar, text='Previous Move', command=review.previous_move)
        self.back.pack(side='left', padx=2)
        self.forward = ttk.Button(toolbar, text='Next Move', command=review.next_move)
        self.forward.pack(side='left')
        self.return_button = ttk.Button(toolbar, text='Return to Game', command=review.return_to_game)
        self.return_button.pack(side='left', padx=3)
        area = ttk.Frame(self)
        area.grid(row=2, column=0, sticky='nsew')
        area.columnconfigure(0, weight=1)
        area.rowconfigure(0, weight=1)
        self.events = ttk.Treeview(area, columns=('move','side','event','played','book','variation','quality'),
                                  show='headings', height=5, selectmode='browse')
        style_information_tree(self.events)
        for name, label, width in (('move','Move',55),('side','Side',70),('event','Event / tags',270),
                ('played','Played',65),('book','Opening / preferred',105),('variation','Variation',210),
                ('quality','Stored engine facts',190)):
            self.events.heading(name, text=label)
            self.events.column(name, width=width, minwidth=45, stretch=False)
        self.events.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(area, command=self.events.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(area, orient='horizontal', command=self.events.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.events.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.events.bind('<<TreeviewSelect>>', self._select_event)
        self.summary = ttk.Label(self, text='', wraplength=520)
        self.summary.grid(row=3, column=0, sticky='ew', padx=5, pady=3)
        self.metrics = ttk.Label(self, text='')
        self.studio_button = ttk.Button(self, text='Open in Opening Studio', command=review.open_opening_context)
        self.studio_button.grid(row=4, column=0, sticky='w', padx=5, pady=3)
        self.line_choices = tk.Menu(self, tearoff=False)
        self.bind('<Configure>', self.resize_text)

    def resize_text(self, event: tk.Event) -> None:
        """Wrap context wording within the available pane.

        Args:
            event: Tk layout event.
        """
        for label in (self.summary, self.indicator):
            label.configure(wraplength=max(160, event.width-15))

    def show(self, assessment: OpeningGameAssessment | None, lookup: OpeningBookLookup | None = None,
             library_name: str = '', error: str = '', *, plies: tuple[int, ...] | None = None) -> None:
        """Render selected-game facts without changing board, timeline, or playback.

        Args:
            assessment: Exact selected game/opening facts, or None to clear.
            lookup: Matching immutable opening index.
            library_name: Friendly source context.
            error: Visible unavailable-state explanation.
            plies: Summary occurrence filter; None includes all game moments.
        """
        self.assessment, self.lookup, self.library_name = assessment, lookup, library_name
        view = self.review
        result = view.opening_workspace.result
        game = next((g for g in result.games if assessment and g.book == assessment), None) if result else None
        self.moments = tuple(m for m in opening_moments(assessment, game, result)
                             if plies is None or m.book.ply in plies)
        key = (assessment.game_identity, assessment.provenance, plies,
               result.result_identity if result else None) if assessment else None
        if key != self._moment_key:
            self._moment_key = key
            self.selected_ply = self._selection = None
            self.events.delete(*self.events.get_children())
            for moment in self.moments:
                quality = moment.quality
                facts = f'Accuracy {quality.accuracy:.2f}' if quality and quality.accuracy is not None else 'Accuracy unavailable'
                if quality and quality.eval_loss_cp is not None:
                    facts += f' · loss {quality.eval_loss_cp} cp'
                choices = ', '.join(x.san+(' ★' if x.preferred else '') for x in moment.book.available_moves)
                self.events.insert('', 'end', iid=moment.key, values=(moment.book.move_number,
                    moment.book.actor_color.title(), moment.kind, moment.book.played_san, choices or '—',
                    context_text(moment.book.variation_before, assessment.provenance.book_name), facts))
        same_game = self._same_displayed_game()
        active = view.opening_anchor_ply if same_game else None
        row = assessment.moves[active-1] if assessment and active and active <= assessment.total_plies else None
        state = view.opening_exploration
        label = 'OPENING LINE' if state and same_game else 'Opening Moments'
        if row and row.deviation_relation == 'user' and row.deviation and row.preferred_move:
            label += f' · Opening move: {row.preferred_move.san}'
        self.indicator.configure(text=label)
        self.back.configure(state='normal' if (state.ply > 0 if state else view.current_step > 0) else 'disabled')
        self.forward.configure(state='normal' if (state.ply < len(state.line) if state else view.current_step < len(view.moves)) else 'disabled')
        self.return_button.configure(state='normal' if state else 'disabled')
        self.show_button.configure(state='normal' if row and row.available_moves and self.can_explore() else 'disabled')
        self.studio_button.configure(state='normal' if view.can_open_opening_studio() else 'disabled')
        if not active and self.events.selection():
            self.events.selection_remove(*self.events.selection())
            self._selection = None
        if assessment is None:
            self.accuracy = None
            self.metrics.configure(text='')
            self.summary.configure(text=error or ('Choose an Opening to inspect this game.' if lookup is None
                                                  else 'Select a game, then an Opening Moment to navigate.'))
            return
        try:
            quality = view.game_quality if same_game else None
            self.accuracy = game.accuracy if game else derive_opening_accuracy(
                assessment, quality.moves if quality else (), match_policy=lookup.policy)
            self.metrics.configure(text=opening_metrics_text(self.accuracy))
        except ValueError:
            self.accuracy = None
            self.metrics.configure(text='Opening Accuracy unavailable')
        text = f'Game {assessment.game_id} · {assessment.provenance.book_name}'
        if not assessment.meaningful_match:
            text += f' · This game does not meaningfully enter {assessment.provenance.book_name}.'
        elif result and not game:
            text += ' · Outside selected opening-side matching set; excluded from metrics.'
        elif row:
            text += ' · '+context_text(row.variation_before, assessment.provenance.book_name)
        elif same_game and view.current_step:
            text += ' · '+context_text(assessment.moves[min(view.current_step, assessment.total_plies)-1].variation_after,
                                        assessment.provenance.book_name)
        first = assessment.first_deviation
        if first:
            text += ' · Deviation by: '+{'user':'You','opponent':'Opponent'}.get(first.deviation_relation, 'Unknown')
        if not self.moments:
            text += ' · No matching Opening Moments.'
        self.summary.configure(text=text)

    def _same_displayed_game(self) -> bool:
        current = self.review.current_game
        return bool(self.assessment and current and self.assessment.game_id == current['game_id'])

    def can_explore(self) -> bool:
        """Prevent authored-line exploration from using another browsed game's facts.

        Returns:
            Whether the detail facts describe the current actual or authored position.
        """
        if not self._same_displayed_game() or self.lookup is None:
            return False
        if not self.review.opening_workspace.browsing:
            return True
        return self.selected_ply is not None and self.selected_ply == self.review.opening_anchor_ply

    def _select_event(self, event: tk.Event | None = None) -> None:
        selected = self.events.selection()
        if selected and selected[0] != self._selection:
            moment = next((m for m in self.moments if m.key == selected[0]), None)
            if moment:
                self.select_moment(moment.book.ply)

    def select_moment(self, ply: int) -> None:
        """Load this exact game and navigate to its decision through one action.

        Args:
            ply: One-based actual move in the selected game.
        """
        assessment = self.assessment
        if assessment is None or not 1 <= ply <= assessment.total_plies:
            return
        row = assessment.moves[ply-1]
        view = self.review
        subtab = view.opening_workspace.tabs.select()
        self.selected_ply = ply
        self._selection = next((m.key for m in self.moments if m.book.ply == ply), None)
        if self._selection:
            self.events.selection_set(self._selection)
        if not self._same_displayed_game():
            view.open_game_position(assessment.game_id, row.move_id)
        if not self._same_displayed_game() or ply > len(view.moves) or view.moves[ply-1]['move_id'] != row.move_id:
            view.shell.set_status('Opening Moment is no longer available; refresh Opening Review.', 'bad')
            return
        view.show_opening_moment(ply)
        self._selection = next((m.key for m in self.moments if m.book.ply == ply), None)
        if self._selection:self.events.selection_set(self._selection)
        view.workspace_tabs.select(view.opening_workspace)
        view.opening_workspace.tabs.select(subtab)

    def select_actual(self, ply: int) -> None:
        """Use the actual-history navigation path, exiting hypothetical playback.

        Args:
            ply: Actual move to display after it was played.
        """
        self.review._set_step(ply)

    def show_line(self) -> None:
        """Explore the selected moment's preferred line or offer its authored choices."""
        if not self.can_explore() or not self.review.opening_anchor_ply:
            return
        row = self.assessment.moves[self.review.opening_anchor_ply-1]
        move = row.preferred_move or (row.available_moves[0] if len(row.available_moves) == 1 else None)
        if move:
            self.explore(row.ply, move.move_id, start_at_anchor=True)
        elif row.available_moves:
            self.line_choices.delete(0, 'end')
            for choice in row.available_moves:
                self.line_choices.add_command(label=choice.san,
                    command=lambda mid=choice.move_id, ply=row.ply: self.explore(ply, mid, start_at_anchor=True))
            try:
                self.line_choices.tk_popup(self.show_button.winfo_rootx(),
                    self.show_button.winfo_rooty()+self.show_button.winfo_height())
            finally:
                self.line_choices.grab_release()

    def explore(self, ply: int, move_id: int, *, start_at_anchor: bool = False) -> None:
        """Enter an authored line only when its game matches the displayed context.

        Args:
            ply: Actual decision anchor.
            move_id: Explicit active authored continuation.
            start_at_anchor: Show the decision before the first authored move.
        """
        if not self.can_explore():
            return
        try:
            state = explore_book_move(self.lookup, self.assessment, ply, self.review.moves[ply-1]['fen_before'], move_id)
        except (ValueError, IndexError) as error:
            self.review.shell.set_status(str(error), 'normal')
            return
        view = self.review
        selected = view.opening_anchor_ply or view.current_step or 1
        return_step = view.current_step if selected == ply else ply-1
        view._clear_line_playback()
        view.tactics_panel.clear_selection()
        view.current_step = return_step
        view.opening_anchor_ply = ply
        view.opening_exploration = replace(state, ply=0) if start_at_anchor else state
        view.workspace_tabs.select(view.opening_workspace)
        view.refresh_all()
        view.shell.set_status('OPENING LINE · Opening move, not a Stockfish recommendation.', 'normal')

    def select_line(self, ply: int) -> None:
        """Set a bounded authored cursor without changing the actual anchor.

        Args:
            ply: Requested authored-line cursor.
        """
        state = self.review.opening_exploration
        if state:
            self.review.opening_exploration = state.step(ply-state.ply)
            self.review.refresh_all()

    def step(self, offset: int) -> None:
        """Move the authored cursor by a signed offset.

        Args:
            offset: Requested ply displacement, clamped by the core state.
        """
        if self.review.opening_exploration:
            self.select_line(self.review.opening_exploration.ply+offset)
