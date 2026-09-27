"""Data-management presentation; typed services own planning, deletion and validation."""
import queue
import threading
import tkinter as tk
from merlin_ui.notebook import MerlinNotebook
from tkinter import ttk, messagebox
from data_management_repository import DataManagementRepository
from theme_core.management import ThemeManagementService
from merlin_ui import data_management_events


class DataActionWindow:
    def __init__(self, root, database_path):
        self.root = root
        self.database_path = database_path
        self.repository = DataManagementRepository(database_path)
        self.busy = False
        self.closed = False
        data_management_events.register_operation(self)
        self.events = queue.SimpleQueue()
        self.status = tk.StringVar(root)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Destroy>", self._destroyed, add="+")
        self.poll_id = root.after(80, self.poll)

    def _destroyed(self, event):
        if event.widget == self.root:
            self.closed = True
            self.root.after_cancel(self.poll_id)

    def close(self):
        if self.busy:
            self.status.set("Wait for the current data operation to finish.")
        else:
            self.root.destroy()

    def work(self, operation, completed):
        if self.busy:
            return
        self.busy = True
        self.status.set("Checking data...")
        def run():
            try:
                self.events.put((completed, operation(), None))
            except Exception as error:
                self.events.put((completed, None, str(error)))
        threading.Thread(target=run, name="data-management", daemon=False).start()

    def poll(self):
        try:
            callback, result, error = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            if error:
                self.status.set("Not completed: " + error)
            else:
                self.status.set("")
                callback(result)
        if not self.closed:
            self.poll_id = self.root.after(80, self.poll)

    def confirm_plan(self, plan, *, ignore=False):
        if not messagebox.askyesno("Confirm data removal", plan.summary(ignore_future_imports=ignore),
                                   icon="warning", default="no", parent=self.root):
            self.status.set("Cancelled. No data changed.")
            return
        try:
            data_management_events.require_idle(self.database_path)
        except ValueError as error:
            self.status.set(str(error))
            return
        self.work(lambda: self.repository.execute_game_deletion(plan, ignore_future_imports=ignore),
                  self.completed)

    def completed(self, result):
        data_management_events.changed(self.database_path)
        self.status.set("Completed. Deleted data is no longer available in open views.")


class ManageDataDialog(DataActionWindow):
    def __init__(self, root, database_path, theme_service):
        super().__init__(root, database_path)
        self.themes = ThemeManagementService(theme_service)
        root.title("ChessWizard · Manage Data")
        root.geometry("960x560"); root.minsize(700, 420)
        frame = ttk.Frame(root, padding=12); frame.pack(fill="both", expand=True)
        tabs = MerlinNotebook(frame); tabs.pack(fill="both", expand=True)
        self.games = self._table(tabs, "Games",
            ("Date", "White", "Black", "Result", "Source", "Source game ID", "Moves"))
        self.ignored = self._table(tabs, "Ignored Games", ("Source", "Source game ID", "Ignored at"))
        self.theme_table = self._table(tabs, "Themes", ("Theme", "ID", "Assets", "Bytes", "Active"))
        self._button(self.games.master, "Delete Selected Games...", lambda: self.delete_games(False))
        self._button(self.games.master, "Delete & Ignore Future Imports...", lambda: self.delete_games(True))
        ttk.Label(self.games.master, text="Delete allows later re-import. Delete & Ignore suppresses these exact source identities.").pack(anchor="w")
        self._button(self.ignored.master, "Allow Import Again", self.allow_import)
        ttk.Label(self.ignored.master, text="Removing an ignored identity does not download anything. Import manually when ready.").pack(anchor="w")
        self._button(self.theme_table.master, "Delete Theme...", self.delete_theme)
        ttk.Label(self.theme_table.master, text="Merlin Classic is built in and cannot be deleted. Active-theme deletion restores it.").pack(anchor="w")
        ttk.Label(frame, textvariable=self.status, wraplength=880).pack(fill="x", pady=8)
        self.refresh()

    @staticmethod
    def _table(tabs, name, columns):
        page = ttk.Frame(tabs, padding=8); tabs.add(page, text=name)
        region = ttk.Frame(page); region.pack(fill="both", expand=True)
        table = ttk.Treeview(page, columns=columns, show="headings", selectmode="extended", height=10)
        # Table remains a child of page so its action bar shares that page.
        table.pack(in_=region, side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(region, orient="vertical", command=table.yview)
        scroll.pack(side="right", fill="y"); table.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(page, orient="horizontal", command=table.xview)
        horizontal.pack(fill="x"); table.configure(xscrollcommand=horizontal.set)
        for column in columns:
            table.heading(column, text=column); table.column(column, width=115, minwidth=70)
        return table

    @staticmethod
    def _button(parent, title, callback):
        ttk.Button(parent, text=title, command=callback).pack(anchor="w", pady=4)

    def refresh(self):
        try:
            for table in (self.games, self.ignored, self.theme_table):
                table.delete(*table.get_children())
            for row in self.repository.games():
                self.games.insert("", "end", iid=str(row[0]), values=tuple(v if v is not None else "" for v in row[1:]))
            self.ignored_rows = self.repository.ignored()
            for index, row in enumerate(self.ignored_rows):
                self.ignored.insert("", "end", iid=str(index), values=row)
            for plan in self.themes.themes():
                self.theme_table.insert("", "end", iid=plan.theme_id,
                    values=(plan.name, plan.theme_id, plan.asset_count, plan.total_bytes, "Yes" if plan.active else "No"))
            if not self.repository.ignore_available():
                self.status.set("Ignore support needs the explicit additive database migration. Ordinary deletion is available.")
        except Exception as error:
            self.status.set("Cannot load data: " + str(error))

    def delete_games(self, ignore):
        if self.busy:
            return
        ids = tuple(int(i) for i in self.games.selection())
        if not ids:
            self.status.set("Select one or more games."); return
        if ignore and not self.repository.ignore_available():
            self.status.set("First apply the approved ignored-import migration with a verified backup."); return
        try:
            data_management_events.require_idle(self.database_path)
        except ValueError as error:
            self.status.set(str(error)); return
        self.work(lambda: self.repository.plan_game_deletion(ids),
                  lambda plan: self.confirm_plan(plan, ignore=ignore))

    def allow_import(self):
        if self.busy: return
        identities = tuple(self.ignored_rows[int(i)][:2] for i in self.ignored.selection())
        if identities and messagebox.askyesno("Allow Import Again",
                f"Allow these {len(identities)} identities on the next manual import? Nothing will download now.",
                parent=self.root, default="no"):
            self.work(lambda: self.repository.allow_import_again(identities), lambda result: self.refresh())

    def delete_theme(self):
        if self.busy: return
        selected = self.theme_table.selection()
        if len(selected) != 1:
            self.status.set("Select exactly one user theme."); return
        try:
            plan = self.themes.plan(selected[0])
            text = f"Delete {plan.name}?\n{plan.asset_count} assets, {plan.total_bytes:,} bytes."
            if plan.active: text += "\nMerlin Classic will become active first."
            if messagebox.askyesno("Delete Theme", text, parent=self.root, icon="warning", default="no"):
                # Theme subscribers are UI callbacks and must run on the Tk thread.
                self.themes.delete(plan); self.refresh()
        except Exception as error:
            self.status.set("Theme not deleted: " + str(error))

    def completed(self, result):
        super().completed(result)
        self.refresh()


class ResetChessDataDialog(DataActionWindow):
    def __init__(self, root, database_path, *, on_complete=lambda: None):
        super().__init__(root, database_path)
        self.on_complete = on_complete
        root.title("ChessWizard · Reset Chess Data")
        root.geometry("540x270")
        frame = ttk.Frame(root, padding=18); frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Reset Chess Data", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Remove all games, tactics, training, accounts and analysis caches.\nThemes, appearance and app settings remain.", wraplength=480).pack(anchor="w", pady=12)
        self.clear_ignored = tk.BooleanVar(root, value=False)
        ttk.Checkbutton(frame, text="Also clear ignored-game list", variable=self.clear_ignored).pack(anchor="w")
        self.preview_button = ttk.Button(frame, text="Preview Reset...", command=self.preview)
        self.preview_button.pack(anchor="w", pady=10)
        ttk.Label(frame, textvariable=self.status, wraplength=480).pack(fill="x")

    def preview(self):
        if self.busy: return
        try:
            data_management_events.require_idle(self.database_path)
        except ValueError as error:
            self.status.set(str(error)); return
        clear = self.clear_ignored.get()
        self.work(lambda: self.repository.plan_reset(clear_ignored=clear), self.confirm_plan)

    def completed(self, result):
        super().completed(result)
        self.on_complete()
