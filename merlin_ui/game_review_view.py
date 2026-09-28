"""Game replay and stored tactical moments; no engine or analysis dependencies."""
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from plugin_manager_controller import DisplayedPosition
import sqlite3
import tkinter as tk
from merlin_ui.notebook import MerlinNotebook
from tkinter import ttk
import chess
from dataclasses import replace
from application_settings import ApplicationSettings, ApplicationSettingsRepository
from merlin_ui.information_panel import InformationPanel
from merlin_ui.actual_moves_view import ActualMovesView
from merlin_ui.application_menu import application_menu
from game_review_repository import GameReviewRepository
from game_review_sets import ALL_GAMES, load_review_sets
from application_paths import resolve_database_path
from chesswizard_version import window_title
from merlin_ui.startup import prepare_database
from human_analyzer_reviews import case_for_moment, audit_cases_for_game, review_decision_step
from human_analyzer_review_repository import HumanReviewRepository
from merlin_ui.scrollable_panel import ScrollablePanel
from merlin_ui.review_splitter import ReviewSplitter
from tactic_presentation import TacticReadService, decision_step
from evaluation_repository import EvaluationRepository
from move_quality_repository import MoveQualityRepository
from move_quality_presentation import move_details
from merlin_ui.accuracy_panel import AccuracyPanel
from merlin_ui.evaluation_widgets import EvaluationBar, EvaluationTimeline
from line_playback import LinePlaybackState
from opening_intelligence_review import OpeningReviewSession
from opening_studio_handoff import make_studio_handoff, studio_source_step
from tactic_board_annotations import stationary_target_squares
from merlin_ui.view_shell import MerlinViewShell
from merlin_ui.navigation_controls import NavigationControls
from merlin_ui.tactical_moments_panel import TacticalMomentsPanel

DB_NAME = "merlin.db"


class GameReviewView:
    """Coordinate one actual game/board across tactic and opening review modes.

    Args:
        root: Owning desktop window.
        database_path: Existing game database, read-only during review.
        on_train_candidate: Optional training navigation callback.
        review_sets: Optional review-set choices.
        human_review_repository: Optional explicit feedback repository.
    """
    def __init__(self, root: tk.Misc, database_path: str | Path | None = None, *,
                 on_train_candidate: Callable | None = None, review_sets: Iterable | None = None,
                 human_review_repository: HumanReviewRepository | None = None) -> None:
        """Build the shared board and independent review workspaces.

        Args:
            root: Owning Tk window.
            database_path: Existing database path or configured user database.
            on_train_candidate: Optional selected-candidate training action.
            review_sets: Optional human-review filters.
            human_review_repository: Optional feedback storage service.

        Raises:
            sqlite3.Error: The read-only game database cannot be opened.
        """
        self.root = root
        path = resolve_database_path(database_path)
        self.database_path = path
        self.plugin_manager = None
        self._plugin_position_revision = 0
        self._plugin_position_signature = None
        self.opening_book_window = None
        self.opening_facts_window = None
        self.opening_library_window = None
        self.explorer_window = None
        self.management_window = None
        self.training = None
        self.qa_window = None
        self.human_review_panel = None
        self.review_set_picker = None
        self.import_window = None
        self.analysis_window = None
        self.human_review_repository = human_review_repository if human_review_repository is not None else HumanReviewRepository(database_path=path)
        self.connection = sqlite3.connect(path.as_uri()+"?mode=ro",uri=True)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA query_only=ON")
        self.repository = GameReviewRepository(self.connection)
        self.tactics = TacticReadService(self.connection)
        self.evaluations = EvaluationRepository(self.connection)
        self.qualities = MoveQualityRepository(self.connection)
        self.game_quality = None
        self.evaluation_values = ()
        self.evaluation_error = None
        self.games, self.moves, self.moments = [],[],[]
        self.current_game_index, self.current_step = 0,0
        self.current_game = None
        self.line_playback = None
        self.opening_exploration = None
        self.opening_anchor_ply = None
        self._line_return_step = None
        self.settings = ApplicationSettingsRepository()
        try:
            preferences = self.settings.load()
        except (ValueError, OSError):
            preferences = ApplicationSettings()
        self.show_last_move_var = tk.BooleanVar(master=root,value=preferences.show_last_move)
        self._moves_fraction = preferences.review_moves_fraction
        self.filter_var = tk.StringVar(master=root,value="All games")
        self.review_sets = (load_review_sets() if review_sets is None else tuple(review_sets)) or (ALL_GAMES,)
        self.review_set_var = tk.StringVar(master=root,value=self.review_sets[0].label)
        self.shell = MerlinViewShell(root,on_move_attempt=None,title=window_title("Game Review"),admin_database_path=path)
        self.ui_skin, self.board_widget, self.right = self.shell.ui_skin,self.shell.board_widget,self.shell.right_panel
        self.root.protocol("WM_DELETE_WINDOW",self.close)
        self.eval_bar = EvaluationBar(self.shell.left)
        self.eval_bar.grid(row=0,column=1,sticky='ns',padx=(4,0))
        self.shell.status_label.grid_configure(columnspan=2)
        self.shell.left_controls.grid_configure(columnspan=2)
        self.game_mode = ttk.Frame(self.shell.left_controls)
        self.game_mode.pack(fill='both',expand=True)
        side = self.right
        side.rowconfigure(0,weight=1);side.columnconfigure(0,weight=1)
        self.workspace_tabs = MerlinNotebook(side)
        self.workspace_tabs.grid(row=0,column=0,sticky='nsew')
        self.game_review_mode = ttk.Frame(self.workspace_tabs)
        self.game_review_mode.columnconfigure(0,weight=1)
        self.workspace_tabs.add(self.game_review_mode,text='Game Review')
        self.right = self.game_review_mode
        from merlin_ui.opening_workspace import OpeningWorkspace
        self.opening_workspace = OpeningWorkspace(self.workspace_tabs,self)
        self.opening_panel = self.opening_workspace.detail
        self.workspace_tabs.add(self.opening_workspace,text='Opening Review')
        from merlin_ui.opening_reference import OpeningReferencePicker
        self.opening_reference = OpeningReferencePicker(self.opening_workspace.header,self)
        self.opening_reference.pack(fill='x',expand=True)
        self.workspace_tabs.bind('<<NotebookTabChanged>>',self._workspace_mode_changed)
        self.board_identity = ttk.Label(self.game_mode, text='No game loaded', anchor='w')
        self.board_identity.pack(fill='x', pady=(0,3))
        self.eval_timeline = EvaluationTimeline(self.game_mode,self._set_step)
        self.eval_timeline.pack(fill='x',pady=(0,5))
        self.position_info = InformationPanel(self.game_mode)
        self.position_strip = ttk.Label(self.game_mode, text='', wraplength=470, justify='left')
        self.position_strip.pack(fill='x')
        self.position_toggle = ttk.Button(self.game_mode, text='Show position details', command=self._toggle_position_details)
        self.position_toggle.pack(anchor='w', pady=3)
        self.position_info.configure(height=4)
        application_menu(root, review=self, shell=self.shell, close=self.close,
                         last_move_var=self.show_last_move_var, toggle_last_move=self.toggle_last_move)
        self._build_right_panel(on_train_candidate)
        self.load_games()
        from merlin_ui.data_management_events import register
        register(self)

    def _workspace_mode_changed(self, event: tk.Event | None = None) -> None:
        """Switch review context without replacing the loaded game."""
        if self.workspace_tabs.select() == str(self.game_review_mode):
            if self.opening_exploration is not None:self.return_to_game()
        else:
            self.opening_workspace.request_analysis()
            self.opening_reference.refresh_summary()

    def return_to_game(self) -> None:
        """Restore the exact actual decision position retained during book exploration."""
        self.opening_exploration = None
        if hasattr(self,'tactics_panel'):self.refresh_all()

    def show_opening_moment(self, ply: int) -> None:
        """Display an actual decision while highlighting the corresponding played move.

        Args:
            ply: One-based source move from the current loaded game.

        Raises:
            ValueError: The move is outside the loaded game.
        """
        if not 1 <= ply <= len(self.moves):raise ValueError('Select a move in the loaded game.')
        self._clear_line_playback();self.tactics_panel.clear_selection()
        self.current_step=ply-1;self.opening_anchor_ply=ply
        self.refresh_all()
        self.shell.set_status('Opening decision position · authored Opening move arrows apply only to your departures.','normal')

    def open_plugins(self) -> None:
        """Open the core-owned plugin manager without starting discovery on Tk's thread."""
        from merlin_ui.plugin_manager import PluginManager
        manager = self.plugin_manager
        if manager is not None and manager.window.winfo_exists():
            manager.window.lift()
            return
        self.plugin_manager = PluginManager(self.root, self.plugin_current_position)

    def plugin_current_position(self) -> "DisplayedPosition | None":
        """Return the actual displayed board, including opening and proof playback.

        Returns:
            An immutable FEN/navigation revision, or None when no game is loaded.
        """
        from plugin_manager_controller import DisplayedPosition
        if self.current_game is None:
            return None
        return DisplayedPosition(self.board_widget.board.fen(), self._plugin_position_revision)

    def open_opening_facts(self) -> None:
        """Route the existing menu action into the one Opening Review workspace."""
        self.workspace_tabs.select(self.opening_workspace)
        self.opening_workspace.request_analysis()

    def _studio_source(self) -> tuple[OpeningReviewSession, int]:
        """Resolve displayed-game facts; the browse panel never supplies the cursor."""
        picker = getattr(self, 'opening_reference', None)
        if (picker is None or not picker.selected_id or picker.loaded_item is None
                or picker.loaded_item.installation_id != picker.selected_id or self.current_game is None):
            raise ValueError('Choose an Opening and load a game before opening its position in Studio.')
        session = picker.summary_session
        if session.assessment is None or session.lookup is None:
            raise ValueError('Wait for the selected Opening and current game to finish loading.')
        if self.line_playback is not None:
            raise ValueError('Return to the actual game before opening its position in Studio.')
        step = studio_source_step(session.lookup, session.assessment, self.moves,
            self.current_game['game_id'], self.current_step, self.board_widget.board.fen(),
            exploration=self.opening_exploration)
        return session, step

    def can_open_opening_studio(self) -> bool:
        """Check the displayed board independently of Opening Moment selection.

        Returns:
            Whether current game/opening facts safely describe the visible position.
        """
        try:
            self._studio_source()
        except ValueError:
            return False
        return True

    def open_opening_context(self) -> None:
        """Hand the current displayed position to Studio without authoring any moves."""
        try:
            session, step = self._studio_source()
            state = self.opening_exploration
            handoff = make_studio_handoff(session.lookup, session.assessment, self.moves, step,
                explored_fen=state.fen if state else None,
                explored_moves=tuple(m.move_id for m in state.line[:state.ply]) if state else None)
            self.open_opening_book_studio()
            self.opening_book_studio.receive_handoff(handoff)
        except (ValueError, OSError, sqlite3.Error) as error:
            self.shell.set_status(str(error), 'bad')

    def open_opening_library(self):
        if self.opening_library_window is not None and self.opening_library_window.winfo_exists():
            self.opening_library_window.lift();return
        from merlin_ui.opening_library_manager import OpeningLibraryManager
        self.opening_library_window=tk.Toplevel(self.root)
        self.opening_library_manager=OpeningLibraryManager(self.opening_library_window,
            service=self.opening_reference.service.library,
            on_change=lambda:self.opening_reference.refresh(force=True),
            on_open_studio=self.open_installed_book,
            selected_id=lambda:self.opening_reference.selected_id)

    def open_installed_book(self,item):
        if item.error:raise ValueError(item.error)
        self.open_opening_book_studio()
        if not self.opening_book_studio.guard():return
        studio=self.opening_book_studio
        if getattr(item,'snapshot',None) is not None:studio.run(lambda:studio.load_book(item))
        elif item.books:studio.run(lambda:studio.load_book(item.books[0]))
        else:studio.run(studio.open_workspace)

    def open_opening_book_studio(self):
        if self.opening_book_window is not None and self.opening_book_window.winfo_exists():
            self.opening_book_window.lift()
            return
        from merlin_ui.opening_book_studio import OpeningBookStudio
        self.opening_book_window = tk.Toplevel(self.root)
        self.opening_book_studio = OpeningBookStudio(self.opening_book_window,
            game_database_path=self.database_path, theme_service=self.shell.theme_service)

    def open_game_explorer(self):
        if self.explorer_window is not None and self.explorer_window.winfo_exists():
            self.explorer_window.lift()
            self.explorer.search()
            return
        from merlin_ui.game_explorer import GameExplorerWindow
        self.explorer_window = tk.Toplevel(self.root)
        self.explorer = GameExplorerWindow(self.explorer_window, self.database_path,
                                           on_open_game=lambda game_id: self.open_game_position(game_id, None))

    def open_manage_data(self):
        if self.management_window is not None and self.management_window.winfo_exists():
            self.management_window.lift()
            return
        from merlin_ui.manage_data_dialog import ManageDataDialog
        self.management_window = tk.Toplevel(self.root)
        self.management_dialog = ManageDataDialog(self.management_window, self.database_path, self.shell.theme_service)

    def require_data_idle(self):
        for name in ("import", "analysis"):
            window = getattr(self, name + "_window")
            if window is not None and window.winfo_exists():
                dialog = getattr(self, name + "_dialog")
                if dialog.busy or getattr(dialog, "loading", False):
                    raise ValueError("Wait for import/analysis to finish before changing data.")

    def refresh_after_data_change(self):
        self.review_set_var.set(ALL_GAMES.label)
        self.current_game = None
        self.load_games()
        for name in ("import", "analysis"):
            window = getattr(self, name + "_window")
            if window is not None and window.winfo_exists():
                getattr(self, name + "_dialog").close()
        if self.management_window is not None and self.management_window.winfo_exists():
            self.management_dialog.refresh()

    def open_training(self):
        """Both desktop entry points share one Training window and database."""
        if self.training is not None and self.training.root.winfo_exists():
            self.training.root.lift()
            return self.training
        from merlin_ui.candidate_viewer import CandidateViewer
        window = tk.Toplevel(self.root)
        training = CandidateViewer(window, database_path=self.database_path,
                                   on_open_game=self.open_game_position)
        self.training = training
        menu = application_menu(window, review=self, shell=training.shell, close=training.close,
            last_move_var=training.show_last_move_var,
            toggle_last_move=lambda: (training.refresh_board(), training.refresh_info()),
            open_review=self.root.lift)
        view = window.nametowidget(menu.entrycget("View", "menu"))
        view.add_checkbutton(label="Show Legal Moves", variable=training.show_legal_var,
                             command=training.toggle_legal_moves)
        window.protocol("WM_DELETE_WINDOW", training.close)
        return training

    def open_human_review(self):
        """Opening QA reads existing reviews; only its Save action persists a verdict."""
        if self.qa_window is not None and self.qa_window.winfo_exists():
            self.qa_window.lift()
            return
        from merlin_ui.human_review_window import HumanReviewWindow
        self.qa_window = tk.Toplevel(self.root)
        self.qa_view = HumanReviewWindow(self.qa_window, review=self)
        self.human_review_panel = self.qa_view.panel
        self.review_set_picker = self.qa_view.picker
        self.qa_window.protocol("WM_DELETE_WINDOW", self.close_human_review)
        self._refresh_human_review(self.tactics_panel.selected)

    def close_human_review(self):
        self.qa_window.destroy()
        self.qa_window = self.human_review_panel = self.review_set_picker = None
        # A hidden QA filter must not silently restrict normal game navigation.
        if self.review_set_var.get() != ALL_GAMES.label:
            step = self.current_step
            self.review_set_var.set(ALL_GAMES.label)
            self.load_games()
            self._set_step(step)

    def open_import_games(self):
        if self.import_window is not None and self.import_window.winfo_exists():
            self.import_window.lift()
            return
        from merlin_ui.import_games_dialog import ImportGamesDialog
        self.import_window = tk.Toplevel(self.root)
        self.import_dialog = ImportGamesDialog(self.import_window, self.database_path, on_complete=self.import_completed)

    def open_analyze_games(self) -> None:
        """Open explicit analysis and refresh Review after each durable batch."""
        if self.analysis_window is not None and self.analysis_window.winfo_exists():
            self.analysis_window.lift()
            return
        from merlin_ui.analyze_games_dialog import AnalyzeGamesDialog
        self.analysis_window = tk.Toplevel(self.root)
        selected = (self.current_game['game_id'],) if self.current_game else ()
        self.analysis_dialog = AnalyzeGamesDialog(self.analysis_window, self.database_path,
            selected_game_ids=selected, on_complete=lambda result: self.load_games(), on_batch_complete=self.analysis_batch_completed)

    def analysis_batch_completed(self) -> None:
        """Expose saved analysis without interrupting the owner's current replay.

        An active proof/opening/tactic selection remains stable. Reselecting a game
        reads its newly committed results through the existing repositories.
        """
        if self.navigation_mode != 'game' or self.tactics_panel.selected is not None:
            self.shell.set_status('Analysis batch saved; completed games are ready in Review.', 'normal')
            return
        game_id = self.current_game['game_id'] if self.current_game else None
        step = self.current_step
        self.load_games()
        if self.current_game and self.current_game['game_id'] == game_id:
            self._set_step(step)

    def stop_analysis_for_close(self) -> bool:
        """Confirm Stop and resume the existing exit flow when rollback completes.

        Returns:
            Whether it is safe to continue closing immediately.
        """
        if self.analysis_window is not None and self.analysis_window.winfo_exists():
            return self.analysis_dialog.request_close(self.close)
        return True

    def import_completed(self, result):
        if result.added:
            self.review_set_var.set(ALL_GAMES.label)
            self.filter_var.set("All games")
            self.current_game = None
        self.load_games()

    def _label(self,parent,text="",**kwargs):
        return tk.Label(parent,text=text,bg=self.ui_skin["panel_bg"],fg=self.ui_skin["text"],anchor="w",justify="left",**kwargs)

    def _build_right_panel(self, on_train_candidate):
        self.right.rowconfigure(5,weight=1)
        header = tk.Frame(self.right,bg=self.ui_skin["panel_bg"])
        header.grid(row=0,column=0,sticky="ew",padx=14,pady=(14,8)); header.columnconfigure(1,weight=1)
        self._label(header,"GAME REVIEW",font=("Segoe UI",9,"bold")).grid(row=0,column=0,columnspan=2,sticky="w",pady=(0,8))
        self._label(header,"Show games with:").grid(row=2,column=0,sticky="w",padx=(0,8))
        self.filter_options = self.tactics.query.filter_options()
        self.tactic_filter = ttk.Combobox(header,textvariable=self.filter_var,state="readonly",width=20,
            values=[label for _,label in self.filter_options])
        self.tactic_filter.grid(row=2,column=1,sticky="ew")
        self.tactic_filter.bind("<<ComboboxSelected>>",lambda event:self.load_games())
        self.game_picker = ttk.Combobox(header,state="readonly",width=35)
        self.game_picker.grid(row=3,column=0,columnspan=2,sticky="ew",pady=(8,0))
        self.game_picker.bind("<<ComboboxSelected>>",lambda event:self.show_game(self.game_picker.current()))
        self.players = tk.Frame(self.right, bg=self.ui_skin["panel_bg"])
        self.white_label = self._label(self.players, font=("Segoe UI", 13))
        self.white_label.pack(anchor="w")
        self.black_label = self._label(self.players, font=("Segoe UI", 13))
        self.black_label.pack(anchor="w")
        self.title_label = self._label(self.right,font=("Segoe UI",13),wraplength=390)
        self.title_label.grid(row=1,column=0,sticky="ew",padx=14,pady=(4,2))
        self.subtitle_label = self._label(self.right); self.subtitle_label.grid(row=2,column=0,sticky="ew",padx=14)
        self.position_label = self._label(self.right); self.position_label.grid(row=3,column=0,sticky="ew",padx=14,pady=(4,8))
        self.accuracy_panel = AccuracyPanel(self.right, background=self.ui_skin["panel_bg"], foreground=self.ui_skin["text"])
        self.accuracy_panel.grid(row=4,column=0,sticky="ew",padx=14,pady=(0,8))
        self.review_splitter = ReviewSplitter(self.right, fraction=self._moves_fraction,
            on_resize=self._save_moves_fraction, background=self.ui_skin["panel_bg"])
        self.review_splitter.grid(row=5,column=0,sticky="nsew",padx=10,pady=(0,8))
        moves_pane = tk.Frame(self.review_splitter, bg=self.ui_skin["panel_bg"])
        self.actual_moves = ActualMovesView(moves_pane, self._set_step)
        self.actual_moves.pack(fill="both",expand=True)
        self.tactics_viewport = ScrollablePanel(self.review_splitter, background=self.ui_skin["panel_bg"])
        self.review_splitter.add_panels(moves_pane, self.tactics_viewport)
        self.tactics_panel = TacticalMomentsPanel(self.tactics_viewport.content,ui_skin=self.ui_skin,
            make_button=self.shell.make_button,on_select=self.jump_to_tactic,
            load_moment=lambda candidate_id:self.tactics.moment_for_candidate(self.current_game["game_id"],candidate_id),
            on_train_candidate=on_train_candidate, on_line_toggle=self.set_line_visible)
        self.tactics_panel.grid(row=0,column=0,sticky="ew")
        self.tactics_panel.on_selection_changed = self._refresh_human_review
        self.navigation = NavigationControls(self.right,ui_skin=self.ui_skin,make_button=self.shell.make_button,
            on_step_back=self.previous_move,on_reset=self.go_to_start,on_step_forward=self.next_move,
            on_previous_item=self.previous_game,on_next_item=self.next_game,step_back_text="◀ Move",
            reset_text="Start",step_forward_text="Move ▶",previous_item_text="← Previous Game",next_item_text="Next Game →")
        self.navigation.grid(row=6,column=0,sticky="ew")
        self._review_minimum_pending = False
        from merlin_ui.layout_metrics import AutomaticSizeGuard
        self._automatic_size_guard = AutomaticSizeGuard()
        def wrap_header(event):
            for label in (self.title_label,self.white_label,self.black_label,self.subtitle_label,self.position_label):
                label.configure(wraplength=max(150,event.width-28))
            self._schedule_review_minimum()
        self.right.bind("<Configure>",wrap_header)
        self.review_splitter.bind("<Configure>", self._schedule_review_minimum, add="+")
        self.accuracy_panel.bind("<Configure>", self._schedule_review_minimum, add="+")

    def _schedule_review_minimum(self, event=None):
        if not self._review_minimum_pending:
            self._review_minimum_pending = True
            self.right.after_idle(self._ensure_review_minimum)

    def _ensure_review_minimum(self):
        self._review_minimum_pending = False
        height = self.root.winfo_height()
        if not self.game_review_mode.winfo_ismapped() or height <= 1 or self.review_splitter.winfo_height() <= 1:
            return
        from merlin_ui.layout_metrics import grid_chrome_height
        # Allocated child heights can still describe the previous resize event.
        # Requested fixed chrome keeps the minimum independent of that feedback loop.
        tab_chrome = max(0, self.workspace_tabs.winfo_reqheight() - max(
            child.winfo_reqheight() for child in (self.game_review_mode, self.opening_workspace)))
        main_padding = 2 * self.shell.main.winfo_pixels(self.shell.main.pack_info()['pady'])
        panel_border = 2 * int(self.shell.right_panel.cget("highlightthickness"))
        pane_minimum = (grid_chrome_height(self.right, (5,)) + tab_chrome + main_padding + panel_border
                        + sum(self.review_splitter.minimum_heights) + self.review_splitter.sash_size)
        board_minimum = grid_chrome_height(self.shell.left, (0,)) + main_padding + 250
        width, current = self.root.minsize()
        minimum = max(650, pane_minimum, board_minimum)
        if minimum != current:
            context=(self.root.winfo_width(),float(self.root.tk.call('tk','scaling')))
            was_blocked=self._automatic_size_guard.blocked
            if self._automatic_size_guard.allow(context,(width,minimum)):
                self.root.minsize(width, minimum)
            elif not was_blocked:
                import logging
                logging.getLogger(__name__).warning('Automatic Review resizing paused: unstable minimum-size sequence.')

    def _save_moves_fraction(self, fraction):
        try:
            self.settings.save(replace(self.settings.load(), review_moves_fraction=fraction))
        except (OSError, ValueError) as error:
            self.shell.set_status(f"Could not save divider preference: {error}", "normal")

    def _refresh_human_review(self, moment):
        if self.human_review_panel is None:
            return
        if len(self.review_sets) == 1:
            self.human_review_panel.set_targets(None, ())
            return
        review_set = next(item for item in self.review_sets if item.label == self.review_set_var.get())
        audit_cases = audit_cases_for_game(review_set, self.current_game["game_id"], self.moments) if self.current_game else ()
        self.human_review_panel.set_targets(case_for_moment(moment, review_set), audit_cases)

    def load_games(self, *, game_id: int | None = None) -> None:
        """Reload the visible game list and resolve the destination before rendering.

        Args:
            game_id: Explicit destination, otherwise retain the current game when possible.
        """
        self._clear_line_playback()
        if self.review_set_picker is not None:
            self.review_set_picker.configure(state="readonly" if len(self.review_sets) > 1 else "disabled")
        previous_id = game_id if game_id is not None else self.current_game["game_id"] if self.current_game else None
        selected = dict((label,key) for key,label in self.filter_options).get(self.filter_var.get())
        review_set = next(item for item in self.review_sets if item.label == self.review_set_var.get())
        self.games = review_set.filter_games(self.repository.games(selected))
        self.game_picker.configure(values=[review_set.game_label(game) for game in self.games])
        if not self.games:
            self.current_game, self.moves, self.moments = None,[],[]
            self.evaluation_values = ()
            self.evaluation_error = None
            self.game_quality = None
            self.accuracy_panel.show(None)
            self.current_step, self.current_game_index = 0,0
            empty = not self.repository.games()
            self.game_picker.set(""); self.title_label.configure(text="No games imported yet" if empty else "No matching games")
            message = ("No games match this filter." if review_set.id == "all_games" else
                       "No games are available in this review set with the current tactic filter.")
            self.subtitle_label.configure(text="Use Import Games to get started with Chess.com or Lichess." if empty else "Try a different review set or tactic filter."); self.position_label.configure(text="0 games")
            self.tactics_panel.set_moments([]); self.actual_moves.render([], 0)
            self.players.grid_remove(); self.title_label.grid()
            self.refresh_board(); self.refresh_header(); self.refresh_info(); self.refresh_navigation_state()
            self.shell.set_status(message,"normal")
            return
        index = next((i for i,g in enumerate(self.games) if g["game_id"]==previous_id),0)
        self.show_game(index)

    def load_moves_for_game(self, game_id): return self.repository.moves(game_id)

    def show_game(self, index):
        if not self.games: return
        self._clear_line_playback()
        self.current_game_index = index % len(self.games)
        self.current_game = self.games[self.current_game_index]
        self.game_picker.current(self.current_game_index)
        self.moves = self.load_moves_for_game(self.current_game["game_id"])
        self.evaluation_error = None
        try:
            self.evaluation_values = self.evaluations.timeline(self.current_game['game_id'])
        except (ValueError,KeyError,TypeError) as error:
            self.evaluation_values = ()
            self.evaluation_error = str(error)
        try:
            self.game_quality = self.qualities.game(self.current_game["game_id"], self.current_game["user_color"])
        except (ValueError, KeyError, TypeError):
            self.game_quality = None
        self.accuracy_panel.show(self.game_quality)
        self.moments = self.tactics.moments_for_game(self.current_game["game_id"])
        self.tactics_panel.set_moments(self.moments)
        self.current_step = 0; self.refresh_all()
        self.shell.set_status("Choose a tactical moment, or use Move ▶ to replay.","normal")
        case = self.human_review_panel.case if self.human_review_panel is not None else None
        if case is not None and case.candidate_id is None:
            self.jump_to_review_case(case)

    def next_game(self): self.show_game(self.current_game_index+1)
    def previous_game(self): self.show_game(self.current_game_index-1)

    def _set_step(self, step):
        self._clear_line_playback()
        self.current_step = max(0,min(step,len(self.moves)))
        self.tactics_panel.clear_selection(); self.refresh_all()
        self.shell.set_status("End of game." if self.current_step==len(self.moves) and self.moves else "Game review","normal")

    @property
    def navigation_mode(self):
        return "opening_exploration" if self.opening_exploration is not None else "merlin_line" if self.line_playback is not None else "game"

    def _clear_line_playback(self):
        self.opening_anchor_ply = None
        self.opening_exploration = None
        self.line_playback = None
        self._line_return_step = None

    def set_line_visible(self, visible: bool) -> None:
        """Show or hide stored tactic playback through the shared actual-game anchor.

        Args:
            visible: Whether to enter the selected tactic's stored proof.
        """
        self.opening_anchor_ply = None
        self.opening_exploration = None
        if visible:
            moment = self.tactics_panel.selected
            if moment is None:
                return
            try:
                playback = LinePlaybackState(moment.stored_line)
            except ValueError:
                self.shell.set_status("Stored line cannot be replayed. Actual-game navigation remains available.", "bad")
                return
            self._line_return_step = self.current_step
            self.line_playback = playback
            self.shell.set_status("Merlin line · Use the Move buttons.", "normal")
        else:
            if self._line_return_step is not None:
                self.current_step = self._line_return_step
            self._clear_line_playback()
            self.shell.set_status("Game review · Actual-game navigation restored.", "normal")
        self.refresh_all()

    def next_move(self) -> None:
        """Step the active authored/proof line, otherwise advance actual history."""
        if self.opening_exploration is not None:
            self.opening_panel.step(1)
        elif self.line_playback is not None:
            self.line_playback = self.line_playback.step(1)
            self.refresh_all()
        elif self.moves and self.current_step < len(self.moves):
            self._set_step(self.current_step + 1)

    def previous_move(self) -> None:
        """Step the active authored/proof line, otherwise rewind actual history."""
        if self.opening_exploration is not None:
            self.opening_panel.step(-1)
        elif self.line_playback is not None:
            self.line_playback = self.line_playback.step(-1)
            self.refresh_all()
        elif self.moves and self.current_step > 0:
            self._set_step(self.current_step - 1)

    def go_to_start(self) -> None:
        """Return the active line to its anchor, or actual history to game start."""
        if self.opening_exploration is not None:
            self.opening_panel.select_line(0)
        elif self.line_playback is not None:
            self.line_playback = self.line_playback.reset()
            self.refresh_all()
        else:
            self._set_step(0)

    def jump_to_review_case(self, case):
        """Keep audit navigation on the actual-game replay path, without a fake tactic."""
        if case is None:
            return
        if case.candidate_id is not None:
            moment = next((m for m in self.moments if m.candidate_id == case.candidate_id), None)
            if moment is not None:
                self.jump_to_tactic(moment)
            return
        if self.current_game is None or case.game_id != self.current_game["game_id"]:
            self.shell.set_status("Audit case does not belong to the loaded game.", "normal")
            return
        try:
            step = review_decision_step(self.moves, case, game_id=self.current_game["game_id"])
        except ValueError as exc:
            self.shell.set_status(str(exc), "bad")
            return
        if step is None:
            self.shell.set_status("Game-level audit anchor — exact decision position unavailable.", "normal")
            return
        self._set_step(step)
        self.shell.set_status(f"Audit · {case.move_number} · {case.color or ''}", "normal")

    def jump_to_tactic(self, moment):
        self._clear_line_playback()
        if moment is None:
            self.refresh_all()
            return
        if self.current_game is None or moment.game_id!=self.current_game["game_id"]:
            raise ValueError("Tactical moment belongs to another game")
        self.current_step = decision_step(self.moves,moment); self.refresh_all()
        self.shell.set_status(f"{moment.move_number} {moment.color.capitalize()} · {moment.title}","normal")

    def get_orientation(self):
        return chess.BLACK if self.current_game and self.current_game["user_color"]=="black" else chess.WHITE

    def get_board_for_current_step(self):
        if not self.moves: return chess.Board()
        # Keep the existing replay step; use the canonical decision FEN directly.
        fen = self.moves[self.current_step]["fen_before"] if self.current_step<len(self.moves) else self.moves[-1]["fen_after"]
        return chess.Board(fen)

    def get_last_move(self) -> chess.Move | None:
        """Read the current projection's last-move highlight.

        Returns:
            Actual/authored/proof move, or None at its root or when hidden.
        """
        if self.opening_exploration is not None:
            return self.opening_exploration.last_move if self.show_last_move_var.get() else None
        if self.line_playback is not None:
            return self.line_playback.last_move if self.show_last_move_var.get() else None
        if not self.moves or self.current_step==0 or not self.show_last_move_var.get(): return None
        try: return chess.Move.from_uci(self.moves[self.current_step-1]["uci_played"])
        except (ValueError,TypeError): return None

    def refresh_board(self) -> None:
        """Render the current board and role-correct tactic/book annotations."""
        board = (chess.Board(self.opening_exploration.fen) if self.opening_exploration is not None else
                 chess.Board(self.line_playback.fen) if self.line_playback is not None else self.get_board_for_current_step())
        signature = (self.current_game["game_id"] if self.current_game is not None else None, board.fen())
        if signature != self._plugin_position_signature:
            self._plugin_position_signature = signature
            self._plugin_position_revision += 1
        self.board_widget.set_position(board,orientation=self.get_orientation())
        self.board_widget.set_input_enabled(False); self.board_widget.set_show_legal_moves(False)
        arrows = []
        moment = self.tactics_panel.selected
        if moment and moment.solution_uci and self.board_widget.board.fen()==moment.fen_before:
            try:
                move = chess.Move.from_uci(moment.solution_uci)
                if move in self.board_widget.board.legal_moves:
                    arrows = [{"from":move.from_square,"to":move.to_square}]
            except ValueError:
                pass
        targets = ()
        if moment:
            if self.line_playback is not None:
                targets = stationary_target_squares(moment.target_squares,
                    self.line_playback.line.positions[:self.line_playback.ply + 1])
            elif self.board_widget.board.fen() == moment.fen_before:
                targets = moment.target_squares
        if self.opening_exploration is not None:
            targets, arrows = (), []
            suggestion = self.opening_exploration.suggestion if self.opening_exploration.ply==0 else None
            if suggestion:
                move = chess.Move.from_uci(suggestion)
                arrows = [{"from":move.from_square,"to":move.to_square}]
        elif self.opening_anchor_ply is not None:
            from opening_workspace import book_suggestion
            targets, arrows = (), []
            assessment = self.opening_reference.summary_session.assessment
            if assessment and (not self.current_game or assessment.game_id != self.current_game['game_id']):
                assessment = None
            suggestion = book_suggestion(assessment,self.opening_anchor_ply)
            if suggestion:
                move=chess.Move.from_uci(suggestion)
                if move in board.legal_moves:arrows=[{'from':move.from_square,'to':move.to_square}]
        self.board_widget.set_tactical_targets(targets)
        self.board_widget.set_arrows(arrows); self.board_widget.set_last_move(self.get_last_move())

    def refresh_header(self) -> None:
        """Label the loaded game and current actual or projected position."""
        if not self.current_game:
            self.board_identity.configure(text='No game loaded')
            return
        g = self.current_game
        opponent = g['black_username'] if g['user_color']=='white' else g['white_username']
        ply = self.opening_anchor_ply or self.current_step
        move_text = 'Starting position'
        if ply and ply <= len(self.moves):
            row = self.moves[ply-1]
            dots = '...' if row['color']=='black' else '.'
            move_text = f"{row['move_number']}{dots}{row['san_played'] or row['uci_played']}"
        if self.opening_exploration is not None:move_text += ' · Opening Line'
        elif self.line_playback is not None:move_text += ' · Merlin Line'
        elif self.opening_anchor_ply:move_text += ' · decision'
        self.board_identity.configure(text=f"Game {g['game_id']} · vs {opponent} · {move_text}")
        self.title_label.grid_remove()
        self.players.grid(row=1,column=0,sticky="ew",padx=14,pady=(4,2))
        for label, name, won in ((self.white_label,g['white_username'],g['result']=='1-0'),
                                 (self.black_label,g['black_username'],g['result']=='0-1')):
            label.configure(text=name, font=("Segoe UI",13,"bold" if won else "normal"))
        self.subtitle_label.configure(text=f"Game ID {g['game_id']} · {g['source']} {g['source_game_id']}\nResult: {g['result']}")
        self.position_label.configure(text=f"Game {self.current_game_index+1} of {len(self.games)}")
        if self.opening_exploration is not None:
            self.position_label.configure(text=f"OPENING LINE · actual move {self.opening_anchor_ply} remains selected")
        if self.line_playback is not None:
            self.position_label.configure(text="Merlin Line · Hide Line returns to the actual game.")

    def refresh_info(self) -> None:
        """Synchronize actual move anchors and stored facts for the current board mode."""
        self.actual_moves.render(self.moves, (self.opening_anchor_ply or self.current_step) if self.line_playback is None else None)
        board = self.board_widget.board
        lines = ["POSITION", f"{'White' if board.turn else 'Black'} to move"]
        if self.current_step and self.moves:
            lines.append("Actual last move: " + (self.moves[self.current_step-1]["san_played"] or self.moves[self.current_step-1]["uci_played"] or "Not stored"))
        moment = self.tactics_panel.selected
        if moment and (board.fen() == moment.fen_before or self.line_playback is not None):
            lines += ["Moment: " + moment.title, "Played: " + moment.played_move,
                      "Merlin move: " + (moment.suggested_move or "Unavailable")]
            if self.board_widget.tactical_targets:
                lines.append("Targets: " + ", ".join(chess.square_name(s) for s in self.board_widget.tactical_targets))
        if self.line_playback is not None:
            lines.append("MERLIN PROOF · separate from actual game history")
        proof_mode = self.line_playback is not None
        value = self.evaluation_values[self.current_step] if self.current_step < len(self.evaluation_values) else None
        if self.opening_exploration is not None:
            self.eval_bar.grid_remove()
        else:
            self.eval_bar.grid()
        self.eval_bar.show(value,proof_mode=proof_mode)
        self.eval_timeline.show(self.evaluation_values,self.current_step,proof_mode=proof_mode)
        if proof_mode:
            lines.insert(2,'Evaluation: proof line — no actual-game score')
        elif value is not None and value.complete:
            user_color = self.current_game['user_color']
            lines.insert(2,f'Evaluation: {value.advantage_label()}')
        else:
            lines.insert(2,'Evaluation: unavailable (invalid stored game/evidence)' if self.evaluation_error else 'Evaluation: Not analyzed')
        if proof_mode:
            lines.append('Move quality: actual moves only (proof line).')
        else:
            quality = (self.game_quality.moves[self.current_step-1] if self.game_quality is not None
                       and 0 < self.current_step <= len(self.game_quality.moves) else None)
            lines.append(move_details(quality))
        if self.opening_exploration is not None:
            lines = ["OPENING LINE", "Opening continuation; actual-game evaluation does not apply.",
                     f"Actual game anchor: ply {self.current_step}", "Return to Game or click any Actual Game Move."]
        self.position_info.show("\n".join(lines))
        self.position_strip.configure(text=' · '.join(lines[1:3]),
            wraplength=max(180,self.game_mode.winfo_width()-12))
        self.opening_reference.refresh()
        self.opening_reference.refresh_summary()
        if self.opening_facts_window is not None and self.opening_facts_window.winfo_exists():
            self.opening_facts.refresh()

    def _toggle_position_details(self) -> None:
        if self.position_info.frame.winfo_manager():
            self.position_info.pack_forget()
            self.position_toggle.configure(text='Show position details')
        else:
            self.position_info.pack(fill='x')
            self.position_toggle.configure(text='Hide position details')

    def toggle_last_move(self):
        # Toggle one annotation layer without clearing selection or tactical roles.
        self.board_widget.set_last_move(self.get_last_move())
        try:
            self.settings.save(replace(self.settings.load(), show_last_move=self.show_last_move_var.get()))
        except (ValueError, OSError) as error:
            self.shell.set_status("Highlight changed; preference could not be saved: " + str(error), "bad")

    def open_game_position(self, game_id: int, move_id: int | None) -> None:
        """Resolve one actual game and decision through the shared refresh path.

        Args:
            game_id: Requested stored game identity.
            move_id: Exact decision move; None means the game's initial position.
        """
        self.review_set_var.set(ALL_GAMES.label)
        self.filter_var.set("All games")
        self.load_games(game_id=game_id)
        if not self.current_game or self.current_game['game_id']!=game_id:
            self.shell.set_status("Source game is unavailable.", "bad")
            return
        step=0 if move_id is None else next((i for i,m in enumerate(self.moves) if m['move_id']==move_id),None)
        if step is not None:self._set_step(step)
        else:self.shell.set_status("Decision move is unavailable in the source game.", "bad")
        self.root.lift()

    def refresh_navigation_state(self) -> None:
        """Apply bounds for the active authored line, proof or actual-game cursor."""
        self.navigation.set_item_navigation_enabled(len(self.games)>1)
        if self.opening_exploration is not None:
            state=self.opening_exploration
            self.navigation.set_reset_enabled(state.ply>0)
            self.navigation.step_back_button.configure(state='normal' if state.ply>0 else 'disabled')
            self.navigation.step_forward_button.configure(state='normal' if state.ply<len(state.line) else 'disabled')
            return
        if self.line_playback is not None:
            state = self.line_playback
            self.navigation.set_reset_enabled(state.ply > 0)
            self.navigation.step_back_button.configure(state="normal" if state.ply > 0 else "disabled")
            self.navigation.step_forward_button.configure(state="normal" if state.ply < state.total_plies else "disabled")
            return
        self.navigation.set_reset_enabled(bool(self.moves))
        self.navigation.step_back_button.configure(state="normal" if self.moves and self.current_step>0 else "disabled")
        self.navigation.step_forward_button.configure(state="normal" if self.moves and self.current_step<len(self.moves) else "disabled")

    def refresh_all(self) -> None:
        """Render every current-game surface from the same loaded game and cursor."""
        self.refresh_board(); self.refresh_header(); self.refresh_info(); self.refresh_navigation_state()
        self.tactics_panel.proof_text.set_ply(self.line_playback.ply if self.line_playback is not None else 0)

    def close(self) -> None:
        """Close owned views after activity guards and cancel read-only opening work."""
        from merlin_ui.data_management_events import operation_busy
        if operation_busy(self.database_path):
            return
        if not self.stop_analysis_for_close():
            return
        if self.opening_book_window is not None and self.opening_book_window.winfo_exists():
            if not self.opening_book_studio.close():
                return
        if self.training is not None and self.training.root.winfo_exists():
            self.training.close()
        if self.explorer_window is not None and self.explorer_window.winfo_exists():
            self.explorer.close()
        self.opening_workspace.close()
        if getattr(self, "plugin_manager", None) is not None:
            self.plugin_manager.close()
        try: self.connection.close()
        finally: self.root.destroy()


def main():
    root = tk.Tk()
    database_path = prepare_database(root)
    if database_path is None:
        return
    GameReviewView(root, database_path=database_path)
    root.mainloop()


if __name__ == "__main__": main()
