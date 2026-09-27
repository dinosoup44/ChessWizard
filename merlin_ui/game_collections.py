"""Small collection dialogs; portable services own validation and persistence."""
import sqlite3
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from game_collection_models import CollectionDetails
from game_collection_schema import MIGRATION_REQUIRED
from game_collection_service import GameCollectionService


class CollectionEditor(simpledialog.Dialog):
    def __init__(self, parent, details=None):
        self.details = details or CollectionDetails("New Collection")
        super().__init__(parent, "Collection details")

    def body(self, master):
        ttk.Label(master, text="Name").grid(row=0, column=0, sticky="w")
        self.name = ttk.Entry(master, width=50)
        self.name.insert(0, self.details.name)
        self.name.grid(row=0, column=1, sticky="ew")
        ttk.Label(master, text="Description").grid(row=1, column=0, sticky="nw")
        self.description = tk.Text(master, width=50, height=5, wrap="word")
        self.description.insert("1.0", self.details.description)
        self.description.grid(row=1, column=1, pady=8)
        self.name.select_range(0, "end")
        return self.name

    def validate(self):
        try:
            self.value = CollectionDetails(self.name.get(), self.description.get("1.0", "end-1c"))
            return True
        except ValueError as error:
            messagebox.showerror("Collection details", str(error), parent=self)
            return False

    def apply(self):
        self.result = self.value


class CollectionPicker(simpledialog.Dialog):
    def __init__(self, parent, collections):
        self.collections = collections
        super().__init__(parent, "Add selected games to collection")

    def body(self, master):
        ttk.Label(master, text="Choose a collection. Duplicate memberships are ignored.").pack(pady=8)
        self.picker = ttk.Combobox(master, state="readonly", width=48,
                                  values=[item.name for item in self.collections])
        self.picker.pack(fill="x", pady=8)
        self.picker.current(0)
        return self.picker

    def apply(self):
        self.result = self.collections[self.picker.current()].collection_id


def add_games_to_collection(parent, service, game_ids):
    """Return the selected collection and changed count, or None on cancel."""
    collections = service.list_collections()
    if not collections:
        if not service.available():
            raise ValueError(MIGRATION_REQUIRED)
        details = CollectionEditor(parent).result
        if details is None:
            return None
        collection_id = service.create(details)
    else:
        collection_id = CollectionPicker(parent, collections).result
        if collection_id is None:
            return None
    return collection_id, service.add_games(collection_id, game_ids)


class CollectionManager:
    def __init__(self, root, database_path, *, on_open_game, on_change=lambda: None):
        self.root, self.on_open_game, self.on_change = root, on_open_game, on_change
        self.service = GameCollectionService(database_path)
        self.collections = {}
        root.title("ChessWizard — Collections")
        root.geometry("940x590");root.minsize(760, 480)
        root.columnconfigure(0, weight=1);root.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(root, padding=10);toolbar.grid(row=0, column=0, sticky="ew")
        self.new_button = ttk.Button(toolbar, text="New Collection", command=self.create)
        self.new_button.pack(side="left")
        self.edit_button = ttk.Button(toolbar, text="Rename / Description…", command=self.edit)
        self.edit_button.pack(side="left", padx=6)
        self.delete_button = ttk.Button(toolbar, text="Delete Collection…", command=self.delete)
        self.delete_button.pack(side="left")
        ttk.Button(toolbar, text="Refresh", command=self.refresh).pack(side="right")
        content = ttk.Panedwindow(root, orient="horizontal");content.grid(row=1, column=0, sticky="nsew", padx=10)
        left = ttk.Frame(content);right = ttk.Frame(content)
        content.add(left, weight=1);content.add(right, weight=3)
        self.list = self._table(left, (("name", "Collection", 220), ("count", "Games", 65)), "browse")
        self.list.bind("<<TreeviewSelect>>", self.select)
        self.description = tk.StringVar(root)
        ttk.Label(right, textvariable=self.description, wraplength=450).pack(fill="x", pady=6)
        self.members = self._table(right, (("game_id", "Game ID", 65), ("date", "Date", 130),
            ("white", "White", 110), ("black", "Black", 110), ("result", "Result", 70)), "extended")
        self.members.bind("<<TreeviewSelect>>", self.selection_changed)
        self.members.bind("<Double-1>", self.open_selected)
        self.members.bind("<Return>", self.open_selected)
        actions = ttk.Frame(root, padding=10);actions.grid(row=2, column=0, sticky="ew")
        self.remove_button = ttk.Button(actions, text="Remove selected from collection", command=self.remove)
        self.remove_button.pack(side="left")
        self.open_button = ttk.Button(actions, text="Open in Game Review", command=self.open_selected)
        self.open_button.pack(side="right")
        self.status = tk.StringVar(root)
        ttk.Label(root, textvariable=self.status, wraplength=740, padding=10).grid(row=3, column=0, sticky="ew")
        self.refresh()

    @staticmethod
    def _table(parent, columns, selectmode):
        frame = ttk.Frame(parent);frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1);frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", selectmode=selectmode)
        for key, text, width in columns:
            tree.heading(key, text=text);tree.column(key, width=width, minwidth=50)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview);vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview);horizontal.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        return tree

    def selected_id(self):
        selected = self.list.selection()
        return int(selected[0]) if selected else None

    def refresh(self, selected_id=None):
        selected_id = selected_id or self.selected_id()
        try:
            ready = self.service.available()
            self.collections = {c.collection_id: c for c in self.service.list_collections()}
            self.list.delete(*self.list.get_children())
            for c in self.collections.values():
                self.list.insert("", "end", iid=str(c.collection_id), values=(c.name, c.member_count))
            if selected_id in self.collections:
                self.list.selection_set(str(selected_id))
            self.new_button.configure(state="normal" if ready else "disabled")
            self.select()
            if not ready:
                self.status.set(MIGRATION_REQUIRED)
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
            self.status.set(str(error))

    def select(self, event=None):
        collection_id = self.selected_id()
        self.members.delete(*self.members.get_children())
        self.description.set("")
        for button in (self.edit_button, self.delete_button):
            button.configure(state="normal" if collection_id else "disabled")
        if collection_id:
            try:
                collection = self.collections[collection_id]
                self.description.set(collection.description or "No description.")
                members = self.service.members(collection_id)
                for m in members:
                    self.members.insert("", "end", iid=str(m.game_id), values=(m.game_id, m.played_at or "Unknown", m.white, m.black, m.result))
                self.status.set(f"{len(members)} games. Removing membership never deletes a game." if members else "No games in this collection.")
            except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
                self.status.set(str(error))
        else:
            self.status.set("Select a collection, or create one. Add games from Game Explorer.")
        self.selection_changed()

    def selection_changed(self, event=None):
        selected = self.members.selection()
        self.remove_button.configure(state="normal" if selected else "disabled")
        self.open_button.configure(state="normal" if len(selected) == 1 else "disabled")

    def _mutate(self, action, selected_id=None):
        try:
            result = action()
            self.refresh(selected_id)
            self.on_change()
            return result
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
            messagebox.showerror("Collections", str(error), parent=self.root)

    def create(self):
        details = CollectionEditor(self.root).result
        if details is not None:
            collection_id = self._mutate(lambda: self.service.create(details))
            if collection_id:
                self.refresh(collection_id)

    def edit(self):
        collection_id = self.selected_id()
        if collection_id:
            c = self.collections[collection_id]
            details = CollectionEditor(self.root, CollectionDetails(c.name, c.description)).result
            if details is not None:
                self._mutate(lambda: self.service.edit(collection_id, details), collection_id)

    def delete(self):
        collection_id = self.selected_id()
        if collection_id and messagebox.askyesno("Delete collection", "Delete this collection and its memberships?\nThe games themselves will be kept.", parent=self.root):
            self._mutate(lambda: self.service.delete(collection_id))

    def remove(self):
        collection_id, selected = self.selected_id(), tuple(map(int, self.members.selection()))
        if collection_id and selected:
            self._mutate(lambda: self.service.remove_games(collection_id, selected), collection_id)

    def open_selected(self, event=None):
        if event is not None and getattr(event, "num", None) == 1 and not self.members.identify_row(event.y):
            return
        selected = self.members.selection()
        if len(selected) == 1:
            self.on_open_game(int(selected[0]))
