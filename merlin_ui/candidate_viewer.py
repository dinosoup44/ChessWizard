from game_context import training_game_context
from merlin_ui.information_panel import InformationPanel
from application_paths import resolve_database_path
from chesswizard_version import window_title
from merlin_ui.startup import prepare_database
import sqlite3
import json
import re
import tkinter as tk
from tkinter import ttk
import chess
from tactic_query import TacticQuery

from merlin_ui.view_shell import (
    MerlinViewShell,
)

from merlin_ui.navigation_controls import (
    NavigationControls,
)

from training_history import (
    start_attempt,
    record_move_attempt,
    mark_solution_revealed,
    finish_attempt,
    get_attempt,
    is_perfect_solve,
)


class CandidateViewer:

    def __init__(
        self,
        root,
        database_path=None,
        *, on_open_game=None
    ):
        self.root = root

        path = resolve_database_path(database_path)
        self.database_path = path
        self.on_open_game = on_open_game
        self.review_window = None
        self.context = None
        self.show_game_line = False
        self.connection = sqlite3.connect(path)

        self.connection.row_factory = (
            sqlite3.Row
        )

        self.candidates = []

        self.current_index = 0
        self.current_candidate = None

        self.base_board = None

        self.line_moves = []
        self.line_san = []
        self.line_step = 0

        # -------------------------------------------------
        # TRAINING ATTEMPT STATE
        # -------------------------------------------------

        self.training_attempt_id = None
        self._training_activity = None

        # -------------------------------------------------
        # UI STATE
        # -------------------------------------------------

        self.puzzle_mode_var = (
            tk.BooleanVar(
                value=False
            )
        )

        self.show_arrow_var = (
            tk.BooleanVar(
                value=False
            )
        )

        self.show_last_move_var = (
            tk.BooleanVar(
                value=False
            )
        )

        self.show_solution_var = (
            tk.BooleanVar(
                value=False
            )
        )

        self.show_legal_var = (
            tk.BooleanVar(
                value=True
            )
        )

        self.filter_var = (
            tk.StringVar(
                value="All"
            )
        )

        # -------------------------------------------------
        # SHARED MERLIN VIEW FOUNDATION
        # -------------------------------------------------

        self.shell = MerlinViewShell(
            self.root,
            on_move_attempt=(
                self.on_move_attempt
            ),
            title=window_title("Training"),
            admin_database_path=path
        )

        # Keep these aliases while the feature view is
        # being separated from the shared shell. They make
        # this refactor intentionally low-risk and keep the
        # rest of the training behavior unchanged.
        self.ui_skin = self.shell.ui_skin
        self.board_style = self.shell.board_style
        self.piece_style = self.shell.piece_style
        self.board_widget = self.shell.board_widget
        self.status_var = self.shell.status_var
        self.status_label = self.shell.status_label

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.close
        )

        self._build_ui()
        self.load_candidates()

    # -------------------------------------------------
    # FEATURE UI
    # -------------------------------------------------

        from merlin_ui.data_management_events import register
        register(self)

    def _build_ui(self):
        right = self.shell.right_panel
        right.rowconfigure(4, weight=1)
        header = tk.Frame(right, bg=self.ui_skin["panel_bg"])
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=10)
        header.columnconfigure(1, weight=1)
        tk.Label(header, text="Tactic:", bg=self.ui_skin["panel_bg"], fg=self.ui_skin["text"]).grid(row=0,column=0,padx=(0,8))
        self.filter_box = ttk.Combobox(header, textvariable=self.filter_var, state="readonly",
                                      values=("All", "Missed Mate", "Missed Fork"))
        self.filter_box.grid(row=0,column=1,sticky="ew")
        self.filter_box.bind("<<ComboboxSelected>>",lambda event:self.change_filter())
        for row, attr in ((1,"title_label"),(2,"subtitle_label"),(3,"position_label")):
            label = tk.Label(right, text="", bg=self.ui_skin["panel_bg"], fg=self.ui_skin["text"],
                             anchor="w", justify="left", font=("Segoe UI", 12 if row==1 else 10))
            label.grid(row=row,column=0,sticky="ew",padx=12,pady=2)
            setattr(self,attr,label)
        self.info_text = InformationPanel(right)
        self.info_text.grid(row=4,column=0,sticky="nsew",padx=8,pady=6)
        self.navigation = NavigationControls(right,ui_skin=self.ui_skin,make_button=self._make_button,
            on_step_back=self.step_back,on_reset=self.reset_line,on_step_forward=self.step_forward,
            on_previous_item=self.previous_candidate,on_next_item=self.next_candidate,
            step_back_text="◀ Proof",reset_text="Reset",step_forward_text="Proof ▶",
            previous_item_text="Previous Puzzle",next_item_text="Next Puzzle")
        self.navigation.grid(row=5,column=0,sticky="ew")
        self.line_back_button = self.navigation.step_back_button
        self.reset_button = self.navigation.reset_button
        self.line_forward_button = self.navigation.step_forward_button
        actions = tk.Frame(right,bg=self.ui_skin["panel_bg"])
        actions.grid(row=6,column=0,sticky="ew",padx=12,pady=(4,12))
        actions.columnconfigure((0,1),weight=1,uniform="action")
        for row,col,attr,label,command in (
            (0,0,"last_move_button","Show Last Move",self.toggle_last_context),
            (0,1,"game_line_button","Show Game Line",self.toggle_game_line),
            (1,0,"hint_button","Hint",self.show_hint),
            (1,1,"reveal_button","Reveal Solution",self.reveal_solution),
            (2,0,"practice_button","Start Puzzle",self.toggle_practice),
            (3,0,"review_button","Open in Game Review",self.open_source_game)):
            button = self._make_button(actions,label,command)
            button.grid(row=row,column=col,columnspan=2 if row>=2 else 1,sticky="ew",padx=2,pady=3)
            setattr(self,attr,button)
        def resize(event):
            for label in (self.title_label,self.subtitle_label,self.position_label):
                label.configure(wraplength=max(100,event.width-28))
        right.bind("<Configure>",resize)
        menu = tk.Menu(self.root)
        view = tk.Menu(menu,tearoff=False)
        view.add_checkbutton(label="Show Legal Moves",variable=self.show_legal_var,command=self.toggle_legal_moves)
        view.add_command(label="Appearance...",command=self.shell.open_theme_editor)
        menu.add_cascade(label="View",menu=view)
        self.root.configure(menu=menu)

    def toggle_last_context(self):
        self.show_last_move_var.set(not self.show_last_move_var.get())
        self.refresh_board()
        self.refresh_info()

    def toggle_game_line(self):
        self.show_game_line = not self.show_game_line
        self.refresh_info()

    def show_hint(self):
        self.show_arrow_var.set(True)
        self.toggle_suggestion_arrow()

    def reveal_solution(self):
        self.show_solution_var.set(True)
        self.toggle_solution_text()

    def toggle_practice(self):
        if self.current_candidate is None:
            return
        self.puzzle_mode_var.set(not self.puzzle_mode_var.get())
        self.toggle_puzzle_mode()

    def open_source_game(self):
        if self.current_candidate is None:
            return
        candidate = self.current_candidate
        if self.on_open_game is not None:
            self.on_open_game(candidate["game_id"],candidate["move_id"])
            return
        from merlin_ui.game_review_view import GameReviewView
        if self.review_window is None or not self.review_window.winfo_exists():
            self.review_window = tk.Toplevel(self.root)
            self.source_review = GameReviewView(self.review_window,self.database_path)
        self.source_review.open_game_position(candidate["game_id"],candidate["move_id"])

    # -------------------------------------------------
    # SHARED WIDGET HELPERS
    # -------------------------------------------------

    def _make_button(
        self,
        parent,
        text,
        command
    ):
        return self.shell.make_button(
            parent,
            text,
            command
        )

    def _make_checkbutton(
        self,
        parent,
        text,
        variable,
        command
    ):
        return self.shell.make_checkbutton(
            parent,
            text,
            variable,
            command
        )

    # -------------------------------------------------
    # DATABASE
    # -------------------------------------------------

    def require_data_idle(self):
        if self.training_attempt_id is not None:
            raise ValueError("Finish or close the current Training session before changing data.")

    def refresh_after_data_change(self):
        self.puzzle_mode_var.set(False)
        self.line_moves = []
        self.line_san = []
        self.line_step = 0
        self.load_candidates()

    def change_filter(self):

        self.finish_current_attempt_if_needed(
            "quit"
        )

        self.load_candidates()

    def load_candidates(self):

        selected = {"Missed Mate": ("missed_mate",),
                    "Missed Fork": ("missed_fork",)}.get(
                        self.filter_var.get(), ("missed_mate", "missed_fork"))
        self.candidates = sorted(
            TacticQuery(self.connection).candidates(tactic_types=selected),
            key=lambda row:(row["tactic_type"],row["candidate_id"]))

        self.current_index = 0
        if hasattr(self, "last_move_button"):
            for button in (self.last_move_button,self.game_line_button,self.hint_button,
                           self.reveal_button,self.practice_button,self.review_button):
                button.configure(state="normal" if self.candidates else "disabled")

        if self.candidates:

            self.show_candidate(
                0
            )

        else:

            self.current_candidate = None
            self.context = None
            self.info_text.show("No puzzles match this filter.")
            self.board_widget.set_position(chess.Board())
            self.board_widget.set_last_move(None)
            self.board_widget.set_arrows([])
            self.board_widget.set_input_enabled(False)

            self.title_label.configure(
                text="No candidates found"
            )

            self.subtitle_label.configure(
                text=""
            )

            self.position_label.configure(
                text=""
            )

    # -------------------------------------------------
    # TRAINING HISTORY
    # -------------------------------------------------

    def start_current_attempt(self):

        if (
            not self.puzzle_mode_var.get()
            or self.current_candidate is None
        ):
            return

        from training_session import begin_training_session, RemovedTrainingCandidate
        candidate = self.current_candidate
        try:
            session = begin_training_session(self.connection, self.database_path,
                candidate["candidate_id"], candidate["tactic_type"], candidate["episode_id"])
        except RemovedTrainingCandidate as error:
            self.puzzle_mode_var.set(False)
            self.load_candidates()
            self.shell.set_status(str(error), "normal")
            return
        except (RuntimeError, OSError) as error:
            self.puzzle_mode_var.set(False)
            self.shell.set_status(str(error), "bad")
            return
        self._training_activity = session
        self.training_attempt_id = session.attempt_id

    def _release_training_activity(self):
        session = getattr(self, "_training_activity", None)
        if session is not None:
            session.close()
            self._training_activity = None

    def finish_current_attempt_if_needed(
        self,
        result
    ):
        if self.training_attempt_id is None:
            return

        attempt = get_attempt(
            self.connection,
            self.training_attempt_id
        )

        if (
            attempt is not None
            and attempt["result"]
            == "in_progress"
        ):

            finish_attempt(
                self.connection,
                self.training_attempt_id,
                result
            )

        self.training_attempt_id = None
        self._release_training_activity()

    def get_current_attempt(self):

        if self.training_attempt_id is None:
            return None

        return get_attempt(
            self.connection,
            self.training_attempt_id
        )

    # -------------------------------------------------
    # CANDIDATE
    # -------------------------------------------------

    def show_candidate(
        self,
        index
    ):
        if not self.candidates:
            return

        self.finish_current_attempt_if_needed(
            "quit"
        )

        index = max(
            0,
            min(
                index,
                len(self.candidates) - 1
            )
        )

        self.current_index = index

        self.current_candidate = (
            self.candidates[
                index
            ]
        )

        self.context = training_game_context(self.connection, self.current_candidate["game_id"], self.current_candidate["move_id"])
        self.show_last_move_var.set(False)
        self.show_solution_var.set(False)
        self.show_arrow_var.set(False)
        self.show_game_line = False

        self.base_board = chess.Board(
            self.current_candidate[
                "fen_before"
            ]
        )

        (
            self.line_moves,
            self.line_san
        ) = self.parse_solution_line(
            self.current_candidate[
                "solution_line"
            ]
        )

        self.line_step = 0

        if self.puzzle_mode_var.get():

            self.show_arrow_var.set(
                False
            )

            self.show_solution_var.set(
                False
            )

            self.start_current_attempt()

        self.reset_status()

        self.refresh_board()
        self.refresh_info()

    # -------------------------------------------------
    # SOLUTION LINE
    # -------------------------------------------------

    def parse_solution_line(
        self,
        solution_line
    ):
        if not solution_line:
            return [], []

        board = self.base_board.copy()

        moves = []
        san_moves = []

        tokens = (
            solution_line
            .replace("\n", " ")
            .split()
        )

        for token in tokens:

            token = token.strip()

            if not token:
                continue

            if token in {
                "1-0",
                "0-1",
                "1/2-1/2",
                "*"
            }:
                continue

            if re.match(
                r"^\d+\.(\.\.)?$",
                token
            ):
                continue

            try:

                move = board.parse_san(
                    token
                )

            except ValueError:

                try:

                    move = (
                        chess.Move.from_uci(
                            token
                        )
                    )

                    if (
                        move
                        not in board.legal_moves
                    ):
                        break

                except ValueError:
                    break

            canonical_san = (
                board.san(
                    move
                )
            )

            moves.append(
                move
            )

            san_moves.append(
                canonical_san
            )

            board.push(
                move
            )

        return moves, san_moves

    def build_board_at_step(self):

        board = self.base_board.copy()

        for move in self.line_moves[
            :self.line_step
        ]:

            board.push(
                move
            )

        return board

    def get_player_color(self):

        if (
            self.current_candidate[
                "color"
            ]
            == "white"
        ):
            return chess.WHITE

        return chess.BLACK

    # -------------------------------------------------
    # PUZZLE MODE
    # -------------------------------------------------

    def toggle_puzzle_mode(self):

        self.line_step = 0

        if self.puzzle_mode_var.get():

            self.show_arrow_var.set(
                False
            )

            self.show_solution_var.set(
                False
            )

            self.line_back_button.configure(
                state=tk.DISABLED
            )

            self.line_forward_button.configure(
                state=tk.DISABLED
            )

            self.finish_current_attempt_if_needed(
                "quit"
            )

            self.start_current_attempt()

            self.set_status(
                "Puzzle mode — your move.",
                "normal"
            )

        else:

            self.finish_current_attempt_if_needed(
                "quit"
            )

            self.line_back_button.configure(
                state=tk.NORMAL
            )

            self.line_forward_button.configure(
                state=tk.NORMAL
            )

            self.show_solution_var.set(
                True
            )

            self.set_status(
                "Review mode",
                "normal"
            )

        self.refresh_board()
        self.refresh_info()

    def toggle_legal_moves(self):

        self.board_widget.set_show_legal_moves(
            self.show_legal_var.get()
        )

    def toggle_suggestion_arrow(self):

        if (
            self.puzzle_mode_var.get()
            and self.show_arrow_var.get()
        ):

            self.mark_solution_as_revealed()

        self.refresh_board()
        self.refresh_info()

    def toggle_solution_text(self):

        if (
            self.puzzle_mode_var.get()
            and self.show_solution_var.get()
        ):

            self.mark_solution_as_revealed()

        self.refresh_info()

    def mark_solution_as_revealed(self):

        if self.training_attempt_id is None:
            return

        mark_solution_revealed(
            self.connection,
            self.training_attempt_id
        )

    def on_move_attempt(
        self,
        move
    ):
        if not self.puzzle_mode_var.get():
            return

        if (
            self.line_step
            >= len(self.line_moves)
        ):
            return

        board = self.build_board_at_step()

        player_color = (
            self.get_player_color()
        )

        if board.turn != player_color:

            self.set_status(
                "Merlin is replying...",
                "normal"
            )

            return

        expected_move = self.line_moves[
            self.line_step
        ]

        is_correct = (
            move == expected_move
        )

        # Every legal submitted move is stored.
        # Wrong moves are tracked separately.
        if self.training_attempt_id is not None:

            record_move_attempt(
                self.connection,
                self.training_attempt_id,
                is_correct
            )

        if not is_correct:

            attempted_san = board.san(
                move
            )

            self.set_status(
                f"{attempted_san} is legal, "
                f"but not Merlin's solution. "
                f"Try again.",
                "bad"
            )

            self.board_widget.clear_selection()

            self.refresh_info()

            return

        self.line_step += 1

        self.set_status(
            "Correct!",
            "good"
        )

        self.refresh_board()
        self.refresh_info()

        if (
            self.line_step
            >= len(self.line_moves)
        ):

            self.finish_puzzle()
            return

        board_after = (
            self.build_board_at_step()
        )

        if (
            board_after.turn
            != player_color
        ):

            self.board_widget.set_input_enabled(
                False
            )

            self.set_status(
                "Correct — Merlin is playing "
                "the reply...",
                "good"
            )

            self.root.after(
                550,
                self.play_merlin_reply
            )

        else:

            self.set_status(
                "Correct. Your move again.",
                "good"
            )

    def play_merlin_reply(self):

        if not self.puzzle_mode_var.get():
            return

        player_color = (
            self.get_player_color()
        )

        if (
            self.line_step
            >= len(self.line_moves)
        ):

            self.finish_puzzle()
            return

        board = self.build_board_at_step()

        if board.turn != player_color:

            self.line_step += 1

            self.refresh_board()
            self.refresh_info()

        if (
            self.line_step
            >= len(self.line_moves)
        ):

            self.finish_puzzle()
            return

        board = self.build_board_at_step()

        if board.turn == player_color:

            self.set_status(
                "Your move.",
                "normal"
            )

            self.board_widget.set_input_enabled(
                True
            )

    def finish_puzzle(self):

        self.board_widget.set_input_enabled(
            False
        )

        attempt = self.get_current_attempt()

        if attempt is not None:

            if attempt[
                "solution_revealed"
            ]:

                finish_attempt(
                    self.connection,
                    self.training_attempt_id,
                    "revealed"
                )

            else:

                finish_attempt(
                    self.connection,
                    self.training_attempt_id,
                    "solved"
                )

        finished_attempt = (
            self.get_current_attempt()
        )

        if is_perfect_solve(
            finished_attempt
        ):

            self.set_status(
                "Perfect solve! ✓",
                "good"
            )

        else:

            self.set_status(
                "Puzzle solved! ✓",
                "good"
            )

        self.refresh_board()
        self.refresh_info()

    def reset_status(self):

        if self.puzzle_mode_var.get():

            self.set_status(
                "Puzzle mode — your move.",
                "normal"
            )

        else:

            self.set_status(
                "Review mode",
                "normal"
            )

    def set_status(
        self,
        text,
        kind="normal"
    ):
        self.shell.set_status(
            text,
            kind
        )

    # -------------------------------------------------
    # BOARD REFRESH
    # -------------------------------------------------

    def refresh_board(self):

        if self.current_candidate is None:
            return

        board = self.build_board_at_step()

        player_color = (
            self.get_player_color()
        )

        self.board_widget.set_position(
            board,
            orientation=player_color
        )

        self.board_widget.set_show_legal_moves(
            self.show_legal_var.get()
        )

        previous = None
        if self.show_last_move_var.get() and self.line_step == 0 and self.context.previous_uci:
            try:
                previous = chess.Move.from_uci(self.context.previous_uci)
            except ValueError:
                pass
        self.board_widget.set_last_move(previous)

        arrows = []

        if (
            self.show_arrow_var.get()
            and self.line_step
            < len(self.line_moves)
        ):

            next_move = self.line_moves[
                self.line_step
            ]

            arrows.append({
                "from":
                    next_move.from_square,

                "to":
                    next_move.to_square,

                "style":
                    "suggestion",
            })

        self.board_widget.set_arrows(
            arrows
        )

        puzzle_input_enabled = (
            self.puzzle_mode_var.get()
            and self.line_step
            < len(self.line_moves)
            and board.turn
            == player_color
        )

        self.board_widget.set_input_enabled(
            puzzle_input_enabled
        )

        self.position_label.configure(
            text=(
                f"Line move "
                f"{self.line_step} "
                f"of "
                f"{len(self.line_moves)}"
            )
        )

    # -------------------------------------------------
    # INFO PANEL
    # -------------------------------------------------

    def refresh_info(self):

        if self.current_candidate is None:
            return

        candidate = (
            self.current_candidate
        )

        tactic_type = candidate[
            "tactic_type"
        ]

        if tactic_type == "missed_mate":

            title = "Missed Mate"

        elif tactic_type == "missed_fork":

            title = "Missed Fork"

        else:

            title = tactic_type

        self.title_label.configure(
            text=title
        )

        self.subtitle_label.configure(
            text=(
                f"{candidate['white_username']} "
                f"vs "
                f"{candidate['black_username']}\n"
                f"{candidate['source']} "
                f"{candidate['source_game_id']}"
            )
        )

        metadata = {}

        if candidate["metadata_json"]:

            try:

                metadata = json.loads(
                    candidate[
                        "metadata_json"
                    ]
                )

            except Exception:

                metadata = {}

        puzzle_mode = (
            self.puzzle_mode_var.get()
        )

        puzzle_solved = (
            len(self.line_moves) > 0
            and self.line_step
            >= len(self.line_moves)
        )

        reveal_details = (
            puzzle_solved
            or self.show_solution_var.get()
        )

        lines = []

        lines.append(
            f"Candidate "
            f"{self.current_index + 1} "
            f"of "
            f"{len(self.candidates)}"
        )

        lines.append("")

        lines.append(
            f"Game move: "
            f"{candidate['move_number']} "
            f"{candidate['color']}"
        )

        self.last_move_button.configure(text="Hide Last Move" if self.show_last_move_var.get() else "Show Last Move")
        self.game_line_button.configure(text="Hide Game Line" if self.show_game_line else "Show Game Line")
        self.practice_button.configure(text="Review Mode" if puzzle_mode else "Start Puzzle")
        for button in (self.line_back_button,self.line_forward_button):
            button.configure(state="normal" if self.show_solution_var.get() and not puzzle_mode else "disabled")
        if self.show_last_move_var.get():
            lines.extend(["", "BEFORE THE PUZZLE", "Previous actual move: " + (self.context.previous_san or "Not stored")])
        if self.show_game_line:
            lines.extend(["", "ACTUAL GAME HISTORY · not Merlin's solution", "Move   White         Black"])
            lines.extend(f"{r.number:<7}{r.white:<14}{r.black}" for r in self.context.continuation)

        if not reveal_details:

            lines.append("")

            lines.append(
                "Find the best move "
                "from this position."
            )

            lines.append("")

            lines.append(
                "Click one of your pieces, "
                "then click its destination."
            )

        else:

            lines.append(
                f"Best move: "
                f"{candidate['solution_move_san']}"
            )

            if metadata:

                fork_piece = metadata.get(
                    "fork_piece"
                )

                if fork_piece:

                    lines.append("")

                    lines.append(
                        f"Forking piece: "
                        f"{fork_piece}"
                    )

                targets = metadata.get(
                    "targets",
                    []
                )

                if targets:

                    target_text = ", ".join(
                        f"{target.get('piece')} "
                        f"on "
                        f"{target.get('square')}"

                        for target
                        in targets
                    )

                    lines.append(
                        f"Targets: "
                        f"{target_text}"
                    )

                realization = (
                    metadata.get(
                        "realization"
                    )
                )

                if realization:

                    lines.append(
                        "Conversion: "
                        f"{realization.get('conversion_move')} "
                        f"wins "
                        f"{realization.get('won_piece')} "
                        f"on "
                        f"{realization.get('won_square')}"
                    )

                avoids_mate = (
                    metadata.get(
                        "avoids_forced_mate"
                    )
                )

                gain_cp = metadata.get(
                    "gain_vs_played_cp"
                )

                if avoids_mate:

                    lines.append(
                        "Result: "
                        "avoids forced mate"
                    )

                elif gain_cp is not None:

                    lines.append(
                        f"Improvement: "
                        f"{gain_cp / 100:.2f} "
                        f"pawns"
                    )

            if candidate["notes"]:

                lines.append("")

                lines.append(
                    candidate[
                        "notes"
                    ]
                )

            if self.show_solution_var.get():

                lines.append("")

                lines.append(
                    "MERLIN SOLUTION / PROOF:"
                )

                if self.line_san:

                    lines.append(
                        " ".join(
                            self.line_san
                        )
                    )

                else:

                    lines.append(
                        candidate[
                            "solution_line"
                        ]
                        or "(none)"
                    )

        # -------------------------------------------------
        # TRAINING ATTEMPT INFO
        # -------------------------------------------------

        if puzzle_mode:

            attempt = (
                self.get_current_attempt()
            )

            if attempt is not None:

                lines.append("")
                lines.append(
                    "Training attempt:"
                )

                lines.append(
                    f"Legal moves submitted: "
                    f"{attempt['move_attempts']}"
                )

                lines.append(
                    f"Wrong legal moves: "
                    f"{attempt['wrong_move_attempts']}"
                )

                if attempt[
                    "solution_revealed"
                ]:

                    lines.append(
                        "Solution revealed: Yes"
                    )

                if attempt[
                    "result"
                ] == "solved":

                    if is_perfect_solve(
                        attempt
                    ):

                        lines.append(
                            "Result: Perfect solve"
                        )

                    else:

                        lines.append(
                            "Result: Solved"
                        )

                elif attempt[
                    "result"
                ] == "revealed":

                    lines.append(
                        "Result: Solved after reveal"
                    )

                elif attempt[
                    "result"
                ] == "quit":

                    lines.append(
                        "Result: Quit"
                    )

        self.info_text.configure(
            state=tk.NORMAL
        )

        self.info_text.delete(
            "1.0",
            tk.END
        )

        self.info_text.insert(
            "1.0",
            "\n".join(lines)
        )

        self.info_text.configure(
            state=tk.DISABLED
        )

    # -------------------------------------------------
    # LINE NAVIGATION
    # -------------------------------------------------

    def step_forward(self):

        if self.puzzle_mode_var.get() or not self.show_solution_var.get():
            return

        if (
            self.line_step
            < len(self.line_moves)
        ):

            self.line_step += 1

            self.refresh_board()
            self.refresh_info()

    def step_back(self):

        if self.puzzle_mode_var.get() or not self.show_solution_var.get():
            return

        if self.line_step > 0:

            self.line_step -= 1

            self.refresh_board()
            self.refresh_info()

    def reset_line(self):

        if self.puzzle_mode_var.get():

            self.finish_current_attempt_if_needed(
                "quit"
            )

            self.line_step = 0

            self.show_arrow_var.set(
                False
            )

            self.show_solution_var.set(
                False
            )

            self.start_current_attempt()

            self.set_status(
                "Puzzle restarted — your move.",
                "normal"
            )

        else:

            self.line_step = 0

            self.reset_status()

        self.refresh_board()
        self.refresh_info()

    # -------------------------------------------------
    # CANDIDATE NAVIGATION
    # -------------------------------------------------

    def next_candidate(self):

        if not self.candidates:
            return

        new_index = (
            self.current_index + 1
        ) % len(
            self.candidates
        )

        self.show_candidate(
            new_index
        )

    def previous_candidate(self):

        if not self.candidates:
            return

        new_index = (
            self.current_index - 1
        ) % len(
            self.candidates
        )

        self.show_candidate(
            new_index
        )

    # -------------------------------------------------
    # CLOSE
    # -------------------------------------------------

    def close(self):
        from merlin_ui.data_management_events import operation_busy
        if operation_busy(self.database_path):
            return
        try:

            self.finish_current_attempt_if_needed(
                "quit"
            )

            self.connection.close()

        finally:
            self._release_training_activity()
            self.root.destroy()


def main():

    root = tk.Tk()

    path = prepare_database(root)
    if path is None:
        return
    CandidateViewer(root, database_path=path)

    root.mainloop()


if __name__ == "__main__":
    main()
