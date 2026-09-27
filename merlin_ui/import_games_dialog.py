"""Tk import controls; worker/service owns network, normalization and persistence."""
from merlin_ui.information_panel import style_information
import queue
import threading
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from chesswizard_version import window_title
from game_import_models import SOURCE_LABELS, ImportResult
from game_import_service import GameImportService

POLL_INTERVAL_MS = 100


class ImportGamesDialog:
    def __init__(self, root, database_path, *, on_complete=lambda result: None, service=None):
        self.root = root
        self.service = service if service is not None else GameImportService(database_path)
        self.on_complete = on_complete
        self.busy = False
        self.closed = False
        self.cancel = threading.Event()
        self.events = queue.SimpleQueue()
        self.accounts = ()
        root.title(window_title("Import Games"))
        root.geometry("560x480")
        root.minsize(440, 360)
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Import Games", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Public games only. No password or analysis required.").pack(anchor="w", pady=(4, 14))
        self.source = tk.StringVar(root, value="Chess.com")
        self.username = tk.StringVar(root)
        self.source_picker = ttk.Combobox(frame, textvariable=self.source, values=tuple(SOURCE_LABELS.values()), state="readonly")
        ttk.Label(frame, text="Source").pack(anchor="w")
        self.source_picker.pack(fill="x", pady=(2, 8))
        self.source_picker.bind("<<ComboboxSelected>>", self.source_changed)
        ttk.Label(frame, text="Username").pack(anchor="w")
        self.username_picker = ttk.Combobox(frame, textvariable=self.username)
        self.username_picker.pack(fill="x", pady=(2, 12))
        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        self.import_button = ttk.Button(bar, text="Import Games", command=self.start)
        self.import_button.pack(side="left")
        self.stop_button = ttk.Button(bar, text="Stop", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=8)
        self.status = tk.StringVar(root, value="Choose a source and enter your username.")
        ttk.Label(frame, textvariable=self.status, wraplength=500).pack(anchor="w", pady=12)
        self.output = ScrolledText(frame, height=9, wrap="word", state="disabled")
        style_information(self.output)
        self.output.pack(fill="both", expand=True)
        self.load_accounts()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Destroy>", self.destroyed, add="+")
        self.poll_id = root.after(POLL_INTERVAL_MS, self.poll)

    def load_accounts(self):
        try:
            self.accounts = self.service.accounts()
            if self.accounts and not self.username.get():
                source, username = self.accounts[0]
                self.source.set(SOURCE_LABELS[source])
                self.username.set(username)
            self.source_changed()
        except Exception:
            self.status.set("Could not read saved accounts. You can still enter a username.")

    def source_changed(self, event=None):
        key = next(key for key, label in SOURCE_LABELS.items() if label == self.source.get())
        names = tuple(name for source, name in self.accounts if source == key)
        self.username_picker.configure(values=names)
        if event is not None or not self.username.get():
            self.username.set(names[0] if names else "")

    def start(self):
        if self.busy:
            return
        source = next(key for key, label in SOURCE_LABELS.items() if label == self.source.get())
        username = self.username.get().strip()
        if not username:
            self.status.set("Enter your username first.")
            return
        self.busy = True
        self.cancel.clear()
        self.source_picker.configure(state="disabled")
        self.username_picker.configure(state="disabled")
        self.import_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status.set("Connecting to " + self.source.get() + "...")
        self.show_text("")
        def worker():
            try:
                result = self.service.run(source, username, progress=lambda event: self.events.put(("progress", event)), cancel=self.cancel)
            except Exception:
                result = ImportResult(source, username, errors=1, details=("Import stopped unexpectedly. Existing games are safe; try again.",))
            self.events.put(("result", result))
        threading.Thread(target=worker, daemon=True, name="game-import").start()

    def stop(self):
        self.cancel.set()
        self.status.set("Stopping after the current download/read or game transaction...")
        self.stop_button.configure(state="disabled")

    def show_text(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")

    def poll(self):
        if self.closed:
            return
        while not self.events.empty():
            kind, value = self.events.get()
            if kind == "progress":
                if not self.cancel.is_set():
                    self.status.set(value.message + f" Added: {value.added:,} · Already had: {value.existing:,} · Ignored: {value.ignored:,} · Errors: {value.errors:,}")
            else:
                self.busy = False
                self.source_picker.configure(state="readonly")
                self.username_picker.configure(state="normal")
                self.import_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self.status.set("Import stopped." if value.cancelled else "Import finished with errors." if value.errors else "Import complete.")
                self.show_text(value.summary())
                self.load_accounts()
                self.on_complete(value)
        self.poll_id = self.root.after(POLL_INTERVAL_MS, self.poll)

    def close(self):
        if self.busy:
            self.stop()
            return
        self.root.destroy()

    def destroyed(self, event):
        if event.widget == self.root:
            self.closed = True
            self.cancel.set()
            self.root.after_cancel(self.poll_id)
