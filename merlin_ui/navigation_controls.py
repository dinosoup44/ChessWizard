import tkinter as tk


class NavigationControls(tk.Frame):
    """
    Reusable two-level navigation for Merlin views.

    First row:
    - previous step
    - reset
    - next step

    Second row:
    - previous item
    - next item

    The view supplies callbacks and labels, so the same
    control works for training lines, game moves, opening
    variations, or other future Merlin screens.
    """

    def __init__(
        self,
        parent,
        ui_skin,
        make_button,
        on_step_back,
        on_reset,
        on_step_forward,
        on_previous_item,
        on_next_item,
        step_back_text="◀ Move",
        reset_text="Reset",
        step_forward_text="Move ▶",
        previous_item_text="← Previous",
        next_item_text="Next →",
    ):
        super().__init__(
            parent,
            bg=ui_skin["panel_bg"],
        )

        self.ui_skin = ui_skin
        self.make_button = make_button

        self._build_step_controls(
            on_step_back,
            on_reset,
            on_step_forward,
            step_back_text,
            reset_text,
            step_forward_text,
        )

        self._build_item_controls(
            on_previous_item,
            on_next_item,
            previous_item_text,
            next_item_text,
        )

    def _build_step_controls(
        self,
        on_step_back,
        on_reset,
        on_step_forward,
        step_back_text,
        reset_text,
        step_forward_text,
    ):
        step_controls = tk.Frame(
            self,
            bg=self.ui_skin["panel_bg"],
        )

        step_controls.pack(
            fill=tk.X,
            padx=14,
            pady=(10, 5),
        )

        self.step_back_button = self.make_button(
            step_controls,
            step_back_text,
            on_step_back,
        )

        self.step_back_button.pack(
            side=tk.LEFT,
            padx=3,
        )

        self.reset_button = self.make_button(
            step_controls,
            reset_text,
            on_reset,
        )

        self.reset_button.pack(
            side=tk.LEFT,
            padx=3,
        )

        self.step_forward_button = self.make_button(
            step_controls,
            step_forward_text,
            on_step_forward,
        )

        self.step_forward_button.pack(
            side=tk.LEFT,
            padx=3,
        )

    def _build_item_controls(
        self,
        on_previous_item,
        on_next_item,
        previous_item_text,
        next_item_text,
    ):
        item_controls = tk.Frame(
            self,
            bg=self.ui_skin["panel_bg"],
        )

        item_controls.pack(
            fill=tk.X,
            padx=14,
            pady=(5, 14),
        )

        self.previous_item_button = self.make_button(
            item_controls,
            previous_item_text,
            on_previous_item,
        )

        self.previous_item_button.pack(
            side=tk.LEFT,
            padx=3,
        )

        self.next_item_button = self.make_button(
            item_controls,
            next_item_text,
            on_next_item,
        )

        self.next_item_button.pack(
            side=tk.RIGHT,
            padx=3,
        )

    def set_step_navigation_enabled(
        self,
        enabled,
    ):
        state = tk.NORMAL if enabled else tk.DISABLED

        self.step_back_button.configure(
            state=state
        )

        self.step_forward_button.configure(
            state=state
        )

    def set_reset_enabled(
        self,
        enabled,
    ):
        self.reset_button.configure(
            state=(
                tk.NORMAL
                if enabled
                else tk.DISABLED
            )
        )

    def set_item_navigation_enabled(
        self,
        enabled,
    ):
        state = tk.NORMAL if enabled else tk.DISABLED

        self.previous_item_button.configure(
            state=state
        )

        self.next_item_button.configure(
            state=state
        )
