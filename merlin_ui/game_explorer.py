"""Dedicated search window; widgets render portable search results only."""
import queue
import threading
import tkinter as tk
from tkinter import ttk, font, messagebox
from game_collection_service import GameCollectionService
from merlin_ui.game_collections import CollectionManager, add_games_to_collection
from game_search_models import GameSearchCriteria, MOTIFS, RELATIONSHIPS, sorted_games
from game_search_service import GameSearchService

COLUMNS = (
    ('game_id', 'Game ID', 75), ('played_at', 'Date', 140),
    ('white', 'White', 130), ('black', 'Black', 130), ('user_color', 'Your Color', 85),
    ('result', 'Result', 70), ('move_count', 'Moves', 65), ('source', 'Source', 90),
    ('time_control', 'Time Control', 95), ('accuracy', 'User Accuracy', 100), ('tactic_count', 'Tactics', 65),
)
RELATION_LABELS = ('Played by me', 'Missed by me', 'Played by opponent', 'Missed by opponent', 'Unknown')


class GameExplorerWindow:
    def __init__(self, root, database_path, *, on_open_game):
        self.root, self.on_open_game = root, on_open_game
        self.service = GameSearchService(database_path)
        self.collection_service = GameCollectionService(database_path)
        self.collection_ids = [None]
        self.collection_filter = tk.StringVar(root, value='All Games')
        self.current_criteria = GameSearchCriteria()
        self.refresh_pending = False
        self.results, self.busy, self.closed = {}, False, False
        self.messages = queue.Queue()
        self.sort_column, self.descending = 'played_at', True
        root.title('ChessWizard — Game Explorer')
        root.geometry('1180x760')
        root.minsize(960, 620)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        filters = ttk.LabelFrame(root, text='Search stored games', padding=10)
        filters.grid(row=0, column=0, sticky='ew', padx=10, pady=10)
        self.variables = {}
        options = self.service.options()
        fields = (
            ('game_id', 'Game ID', None), ('opponent', 'Opponent contains', None),
            ('source_game_id', 'Source game ID contains', None),
            ('color', 'Your color', ('All', 'White', 'Black')),
            ('result', 'Your result', ('All', 'Win', 'Loss', 'Draw')),
            ('source', 'Source', ('All', *options['source'])),
            ('date_from', 'From (YYYY-MM-DD)', None), ('date_to', 'To (inclusive)', None),
            ('time_control', 'Time control', ('All', *options['time_control'])),
            ('min_moves', 'Min moves', None), ('max_moves', 'Max moves', None),
            ('min_accuracy', 'Min user accuracy %', None), ('max_accuracy', 'Max user accuracy %', None),
        )
        for index, (name, label, choices) in enumerate(fields):
            row, group = divmod(index, 3)
            col = group*2
            filters.columnconfigure(col+1, weight=1)
            ttk.Label(filters, text=label).grid(row=row, column=col, sticky='w', padx=(4, 7), pady=3)
            variable = tk.StringVar(root, value='All' if choices else '')
            self.variables[name] = variable
            widget = (ttk.Combobox(filters, textvariable=variable, values=choices, state='readonly', width=17)
                      if choices else ttk.Entry(filters, textvariable=variable, width=18))
            widget.grid(row=row, column=col+1, sticky='ew', padx=(0, 12), pady=3)
            widget.bind('<Return>', lambda event: self.search())
            if name == 'game_id':
                self.game_id_entry = widget
        ttk.Label(filters, text='Collection').grid(row=4, column=2, sticky='w', padx=(4, 7))
        self.collection_picker = ttk.Combobox(filters, textvariable=self.collection_filter,
            state='readonly', width=22, postcommand=self.refresh_collections)
        self.collection_picker.grid(row=4, column=3, sticky='ew', padx=(0, 12))
        self.collection_picker.bind('<<ComboboxSelected>>', self.collection_changed)
        ttk.Button(filters, text='Collections…', command=self.manage_collections).grid(row=4, column=4, columnspan=2, sticky='w')
        self.refresh_collections()
        self.motifs = self._checks(filters, 5, 'Motif (any selected)', MOTIFS,
                                   ('Fork', 'Mate', 'Pin', 'Skewer', 'X-ray'))
        self.relationships = self._checks(filters, 6, 'Relationship (any)', RELATIONSHIPS, RELATION_LABELS)
        actions = ttk.Frame(filters)
        actions.grid(row=7, column=0, columnspan=6, sticky='ew', pady=(8, 0))
        self.search_button = ttk.Button(actions, text='Search', command=self.search)
        self.search_button.pack(side='left')
        self.reset_button = ttk.Button(actions, text='Clear filters', command=self.reset)
        self.reset_button.pack(side='left', padx=8)
        ttk.Label(actions, text='IDs belong to this database. Unknown/partial accuracy is excluded from accuracy ranges.').pack(side='left')
        table = ttk.Frame(root)
        table.grid(row=1, column=0, sticky='nsew', padx=10)
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        table_font = font.nametofont('TkDefaultFont', root=root)
        scale = max(1.0, table_font.measure('0') / 7)
        ttk.Style(root).configure('GameExplorer.Treeview', rowheight=table_font.metrics('linespace')+8)
        self.tree = ttk.Treeview(table, columns=[c[0] for c in COLUMNS], show='headings', selectmode='extended',
                                 style='GameExplorer.Treeview')
        for key, label, width in COLUMNS:
            self.tree.heading(key, text=label, command=lambda key=key: self.sort(key))
            self.tree.column(key, width=round(width*scale), minwidth=round(width*scale), stretch=key in ('white', 'black'))
        self.tree.grid(row=0, column=0, sticky='nsew')
        yscroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        yscroll.grid(row=0, column=1, sticky='ns')
        xscroll = ttk.Scrollbar(table, orient='horizontal', command=self.tree.xview)
        xscroll.grid(row=1, column=0, sticky='ew')
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.bind('<Double-1>', self.open_selected)
        self.tree.bind('<Return>', self.open_selected)
        self.tree.bind('<<TreeviewSelect>>', self.selection_changed)
        footer = ttk.Frame(root, padding=10)
        footer.grid(row=2, column=0, sticky='ew')
        self.status = tk.StringVar(root, value='Loading games…')
        ttk.Label(footer, textvariable=self.status, wraplength=390).pack(side='left', fill='x', expand=True)
        self.open_button = ttk.Button(footer, text='Open in Game Review', command=self.open_selected, state='disabled')
        self.open_button.pack(side='right')
        self.add_button = ttk.Button(footer, text='Add selected to collection…', command=self.add_selected, state='disabled')
        self.add_button.pack(side='right', padx=6)
        self.remove_button = ttk.Button(footer, text='Remove from collection', command=self.remove_selected, state='disabled')
        self.remove_button.pack(side='right')
        self.poll_id = root.after(50, self.poll)
        self.game_id_entry.focus_set()
        self.search()

    def _checks(self, parent, row, label, keys, labels):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, columnspan=6, sticky='w', pady=3)
        ttk.Label(frame, text=label).pack(side='left', padx=(4, 10))
        values = {}
        for key, text in zip(keys, labels):
            values[key] = tk.BooleanVar(self.root)
            ttk.Checkbutton(frame, text=text, variable=values[key]).pack(side='left', padx=(0, 8))
        return values

    def criteria(self):
        values = {key: variable.get().strip() for key, variable in self.variables.items()}
        for key in ('game_id', 'min_moves', 'max_moves'):
            try:
                values[key] = int(values[key]) if values[key] else None
            except ValueError:
                raise ValueError(f'{key.replace("_", " ").capitalize()} must be an integer.') from None
        for key in ('min_accuracy', 'max_accuracy'):
            try:
                values[key] = float(values[key]) if values[key] else None
            except ValueError:
                raise ValueError('Accuracy must be numeric.') from None
        for key in ('color', 'result', 'source', 'time_control'):
            values[key] = '' if values[key] == 'All' else values[key]
        for key in ('color', 'result'):
            values[key] = values[key].lower()
        selected = self.selected_collection()
        return GameSearchCriteria(**values, collection_id=selected if isinstance(selected, int) else None,
            uncollected=selected == 'uncollected',
            motifs=tuple(key for key, var in self.motifs.items() if var.get()),
            relationships=tuple(key for key, var in self.relationships.items() if var.get()))

    def search(self):
        if self.busy or self.closed:
            return
        try:
            criteria = self.criteria()
        except ValueError as error:
            self.status.set(str(error))
            return
        self.busy = True
        self.selection_changed()
        self.search_button.configure(state='disabled')
        self.reset_button.configure(state='disabled')
        self.status.set('Searching stored facts…')
        def work():
            try:
                self.messages.put(self.service.search(criteria))
            except Exception as error:
                self.messages.put(error)
        threading.Thread(target=work, daemon=True, name='game-explorer-read').start()

    def poll(self):
        try:
            result = self.messages.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.search_button.configure(state='normal')
            self.reset_button.configure(state='normal')
            if isinstance(result, Exception):
                self.status.set('Search unavailable: '+str(result))
            else:
                self.render(result)
            self.selection_changed()
            if self.refresh_pending:
                self.refresh_pending = False
                self.search()
        if not self.closed:
            self.poll_id = self.root.after(50, self.poll)

    def render(self, result):
        self.current_criteria = result.criteria
        self.results = {row.game_id: row for row in result.games}
        self.tree.delete(*self.tree.get_children())
        for row in result.games:
            values = []
            for key, _, _ in COLUMNS:
                value = getattr(row, key)
                if key == 'accuracy' and value is not None:
                    value = f'{value:.1f}%'
                values.append('Unknown' if value is None or value == '' else value)
            self.tree.insert('', 'end', iid=str(row.game_id), values=values)
        self._apply_sort()
        if len(result.games) == 1:
            iid = str(result.games[0].game_id)
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)
        self.selection_changed()
        self.status.set(result.summary)

    def sort(self, column):
        self.descending = not self.descending if self.sort_column == column else False
        self.sort_column = column
        self._apply_sort()

    def _apply_sort(self):
        for index, row in enumerate(sorted_games(self.results.values(), self.sort_column, self.descending)):
            self.tree.move(str(row.game_id), '', index)

    def selection_changed(self, event=None):
        selected = self.tree.selection()
        self.open_button.configure(state='normal' if len(selected) == 1 and not self.busy else 'disabled')
        if hasattr(self, 'add_button'):
            self.add_button.configure(state='normal' if selected and not self.busy and self.collection_ready else 'disabled')
            self.remove_button.configure(state='normal' if selected and not self.busy and self.current_criteria.collection_id is not None else 'disabled')

    def open_selected(self, event=None):
        if event is not None and getattr(event, 'num', None) == 1 and not self.tree.identify_row(event.y):
            return
        selected = self.tree.selection()
        if len(selected) == 1 and not self.busy:
            self.on_open_game(int(selected[0]))

    def selected_collection(self):
        index = self.collection_picker.current()
        return self.collection_ids[index] if 0 <= index < len(self.collection_ids) else None

    def refresh_collections(self):
        selected = self.selected_collection()
        self.collection_ready = self.collection_service.available()
        collections = self.collection_service.list_collections()
        self.collection_ids = [None, 'uncollected', *[c.collection_id for c in collections]] if self.collection_ready else [None]
        labels = ['All Games', 'Games not in a collection', *[f'{c.name} ({c.member_count})' for c in collections]] if self.collection_ready else ['All Games']
        self.collection_picker.configure(values=labels, state='readonly' if self.collection_ready else 'disabled')
        self.collection_picker.current(self.collection_ids.index(selected) if selected in self.collection_ids else 0)

    def collection_changed(self, event=None):
        if self.closed:
            return
        self.refresh_collections()
        if self.busy:
            self.refresh_pending = True
        else:
            self.search()

    def manage_collections(self):
        window = tk.Toplevel(self.root)
        self.collection_manager = CollectionManager(window, self.service.path,
            on_open_game=self.on_open_game, on_change=self.collection_changed)

    def add_selected(self):
        selected = tuple(map(int, self.tree.selection()))
        if not selected or self.busy:
            return
        try:
            result = add_games_to_collection(self.root, self.collection_service, selected)
            if result is not None:
                self.collection_changed()
        except Exception as error:
            messagebox.showerror('Collections', str(error), parent=self.root)

    def remove_selected(self):
        selected = tuple(map(int, self.tree.selection()))
        collection_id = self.current_criteria.collection_id
        if not selected or collection_id is None or self.busy:
            return
        try:
            self.collection_service.remove_games(collection_id, selected)
            self.collection_changed()
        except Exception as error:
            messagebox.showerror('Collections', str(error), parent=self.root)

    def reset(self):
        self.collection_picker.current(0)
        for key, variable in self.variables.items():
            variable.set('All' if key in ('color', 'result', 'source', 'time_control') else '')
        for variable in (*self.motifs.values(), *self.relationships.values()):
            variable.set(False)
        self.sort_column, self.descending = 'played_at', True
        self.search()

    def close(self):
        self.closed = True
        self.root.after_cancel(self.poll_id)
        self.root.destroy()
