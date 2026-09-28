"""Core-owned Tk presentation for the shared asynchronous plugin controller."""
from collections.abc import Callable
import tkinter as tk
from tkinter import ttk
from application_paths import application_data_directory
from plugin_manager_controller import DisplayedPosition, PluginManagerController
from plugin_presentation import PluginRow, TRUST_DISCLOSURE
from plugin_service import PluginService

POLL_MILLISECONDS = 100


def _text(parent: tk.Misc, height: int) -> tk.Text:
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True)
    text = tk.Text(frame, height=height, width=40, wrap="word", state="disabled")
    scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    text.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    return text


def _show(text: tk.Text, value: str) -> None:
    text.configure(state="normal")
    text.delete("1.0", "end")
    text.insert("1.0", value)
    text.configure(state="disabled")


def _size(window: tk.Toplevel, width: int, height: int) -> None:
    scale = window.winfo_fpixels("1i") / 96
    width = min(round(width * scale), round(window.winfo_screenwidth() * .9))
    height = min(round(height * scale), round(window.winfo_screenheight() * .85))
    window.geometry(f"{width}x{height}")
    window.minsize(min(width, round(620 * scale)), min(height, round(420 * scale)))


class PluginTrustDialog:
    """Require an unchecked-by-default acknowledgement for one displayed artifact.

    Args:
        parent: Owning manager window.
        row: Immutable metadata and hash being acknowledged.
        on_decision: Receives explicit approval or cancellation without running services.
    """
    def __init__(self, parent: tk.Misc, row: PluginRow, on_decision: Callable[[bool], None]) -> None:
        """Show a scrollable disclosure and explicit approval controls.

        Args:
            parent: Owning desktop window.
            row: Exact reviewed artifact.
            on_decision: Called once with the user's decision.
        """
        self.window = tk.Toplevel(parent)
        self.window.title("Enable plugin — code trust")
        self.window.transient(parent)
        _size(self.window, 680, 520)
        self._decision = on_decision
        self._closed = False
        body = ttk.Frame(self.window, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Review this plugin before enabling it.").pack(anchor="w", pady=(0, 8))
        self.disclosure = _text(body, 12)
        _show(self.disclosure, TRUST_DISCLOSURE + "\n\n" + row.trust_details)
        self.acknowledged = tk.BooleanVar(self.window, False)
        self.checkbox = ttk.Checkbutton(body, text="I understand and trust this exact plugin artifact.",
            variable=self.acknowledged, command=self._update)
        self.checkbox.pack(anchor="w", pady=10)
        actions = ttk.Frame(body)
        actions.pack(fill="x")
        self.approve_button = ttk.Button(actions, text="Enable plugin", command=lambda: self._finish(True), state="disabled")
        self.approve_button.pack(side="right")
        ttk.Button(actions, text="Cancel", command=lambda: self._finish(False)).pack(side="right", padx=8)
        self.window.protocol("WM_DELETE_WINDOW", lambda: self._finish(False))
        self.window.bind("<Escape>", lambda event: self._finish(False))
        self.window.grab_set()
        self.checkbox.focus_set()

    def _update(self) -> None:
        self.approve_button.configure(state="normal" if self.acknowledged.get() else "disabled")

    def _finish(self, approved: bool) -> None:
        if self._closed or (approved and not self.acknowledged.get()):
            return
        self._closed = True
        self.window.grab_release()
        self.window.destroy()
        self._decision(approved)


class PluginManager:
    """Render typed plugin state; all storage, discovery, and execution stay in services.

    Args:
        parent: Owning application window.
        position_provider: Reads the actual displayed Game Review position on Tk's thread.
        controller: Optional isolated controller, primarily for tests.
    """
    def __init__(self, parent: tk.Misc, position_provider: Callable[[], DisplayedPosition | None],
                 controller: PluginManagerController | None = None) -> None:
        """Open a resizable manager and request one background discovery.

        Args:
            parent: Owning application window.
            position_provider: Current Game Review board snapshot provider.
            controller: Optional existing frontend-independent controller.
        """
        self.window = tk.Toplevel(parent)
        self.window.title("ChessWizard Plugins")
        _size(self.window, 1160, 680)
        self.controller = controller or PluginManagerController(lambda: PluginService(application_data_directory()))
        self._position_provider = position_provider
        self._closed = False
        self._after: str | None = None
        self._trust: PluginTrustDialog | None = None
        body = ttk.Frame(self.window, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Installed Plugins", font="TkHeadingFont").pack(anchor="w")
        ttk.Label(body, text="Install and remove local wheels with the plugin CLI. Execution always requires trust.", wraplength=560, justify="left").pack(anchor="w", pady=(4, 8))
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(0, 8))
        self.enable_button = ttk.Button(actions, text="Enable…", command=self._enable)
        self.disable_button = ttk.Button(actions, text="Disable", command=self._disable)
        self.refresh_button = ttk.Button(actions, text="Refresh / Rescan", command=self._refresh)
        self.details_button = ttk.Button(actions, text="Details / Diagnostics", command=self._details)
        self.run_button = ttk.Button(actions, text="Run on Current Position", command=self._run)
        for index, button in enumerate((self.enable_button, self.disable_button, self.refresh_button, self.details_button, self.run_button)):
            button.grid(row=index // 3, column=index % 3, sticky="w", padx=(0, 8), pady=3)
        self.position_label = ttk.Label(body, text="")
        self.position_label.pack(anchor="w", pady=(0, 6))
        self.status = ttk.Label(body, text="", wraplength=560, justify="left")
        self.status.pack(side="bottom", fill="x", pady=(8, 0))
        panes = ttk.Panedwindow(body, orient="vertical")
        panes.pack(fill="both", expand=True)
        table = ttk.Frame(panes)
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        columns = ("name", "version", "author", "capability", "requested", "status", "compatibility", "trust")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse", height=8)
        scale = self.window.winfo_fpixels("1i") / 96
        for column, width in zip(columns, (175, 75, 120, 220, 95, 120, 120, 125)):
            self.tree.heading(column, text=column.title())
            self.tree.column(column, width=round(width * scale), minwidth=round(65 * scale))
        style = ttk.Style(self.window)
        import tkinter.font as tkfont
        style.configure("PluginManager.Treeview", rowheight=tkfont.nametofont("TkDefaultFont", self.window).metrics("linespace") + 10)
        self.tree.configure(style="PluginManager.Treeview")
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        panes.add(table, weight=2)
        detail = ttk.LabelFrame(panes, text="Details / Diagnostics", padding=6)
        self.detail_text = _text(detail, 9)
        panes.add(detail, weight=2)
        result = ttk.LabelFrame(panes, text="Validated current-position facts (not saved)", padding=6)
        self.result_text = _text(result, 4)
        panes.add(result, weight=1)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._details())
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Destroy>", self._destroyed, add=True)
        self._refresh()
        self._tick()

    def _selected(self) -> PluginRow | None:
        selection = self.tree.selection()
        return next((row for row in self.controller.rows if selection and row.view.installed.installation_id == selection[0]), None)

    def _buttons(self) -> None:
        row = self._selected()
        busy = self.controller.control_busy
        position = self._position_provider()
        self.enable_button.configure(state="normal" if row and row.can_enable and not busy else "disabled")
        self.disable_button.configure(state="normal" if row and not busy else "disabled")
        self.refresh_button.configure(state="disabled" if busy else "normal")
        self.run_button.configure(state="normal" if row and row.can_run and position is not None
                                  and not busy and not self.controller.invocation_busy else "disabled")
        self.position_label.configure(text="Uses the currently displayed Game Review board." if position is not None
                                      else "Open a game in Game Review to run a plugin on its displayed position.")

    def _refresh(self) -> None:
        self.controller.refresh()
        self._render()

    def _enable(self) -> None:
        row = self._selected()
        if row is None:
            return
        if row.needs_approval:
            def decision(approved: bool) -> None:
                self._trust = None
                if approved and not self._closed:
                    self.controller.set_enabled(row, True, acknowledged=True)
                    self._render()
            self._trust = PluginTrustDialog(self.window, row, decision)
        else:
            self.controller.set_enabled(row, True)
            self._render()

    def _disable(self) -> None:
        row = self._selected()
        if row:
            self.controller.set_enabled(row, False)
            self._render()

    def _run(self) -> None:
        row = self._selected()
        if row:
            self.controller.run(row, self._position_provider())
            self._render()

    def _details(self) -> None:
        row = self._selected()
        _show(self.detail_text, row.details if row else "Select an installed plugin to view details.")
        self._buttons()

    def _render(self) -> None:
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for row in self.controller.rows:
            values = list(row.values)
            if row.view.installed.installation_id == self.controller.running_id:
                values[5] = "Running"
            self.tree.insert("", "end", iid=row.view.installed.installation_id, values=values)
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
        elif self.tree.get_children():
            self.tree.selection_set(self.tree.get_children()[0])
        self.status.configure(text=self.controller.message)
        _show(self.result_text, self.controller.result)
        self._details()

    def _tick(self) -> None:
        if self._closed:
            return
        if self.controller.poll(self._position_provider()):
            self._render()
        else:
            self._buttons()
        self._after = self.window.after(POLL_MILLISECONDS, self._tick)

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget == self.window:
            self.close()

    def close(self) -> None:
        """Cancel callbacks and service work promptly when this view or its owner closes."""
        if self._closed:
            return
        self._closed = True
        if self._after is not None:
            self.window.after_cancel(self._after)
            self._after = None
        self.controller.close()
        if self.window.winfo_exists():
            self.window.destroy()
