"""Functional desktop authoring; graph, legality, export and opening facts live in core."""
import sqlite3
from pathlib import Path
from collections.abc import Callable
from line_playback import LinePlaybackState
from opening_engine_service import OpeningEngineService
from opening_engine_models import OpeningEngineAnchor, saved_opening_anchor
from opening_engine_authoring import OpeningEngineAuthoringService
import tkinter as tk
from merlin_ui.notebook import MerlinNotebook
from merlin_ui.information_panel import style_information, style_information_tree
from merlin_ui.opening_book_delete_dialog import choose_deletion
from tkinter import ttk, filedialog, messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText
import chess
from opening_studio_handoff import OpeningStudioHandoff
from merlin_ui.view_shell import MerlinViewShell
from merlin_ui.opening_book_dialogs import edit_fields, SourceReferenceDialog
from opening_book_models import BookDetails, MoveDetails
from opening_book_repository import OpeningBookRepository, READ_ONLY_LIBRARY_MESSAGE
from opening_book_service import OpeningBookService
from opening_book_navigation import BranchNavigation
from opening_book_session import OpeningBookSession
from opening_book_polyglot import export_polyglot
from opening_book_application import apply_stored_game


STUDIO_QUICK_START = """YOUR OPENINGS, IN ONE STUDIO

Choose an opening from Opening at the top. Your managed openings are editable immediately. Studio opens your opening library automatically; no file chooser or import is needed for your own openings.

NEW OPENING

Click New Opening. The board resets to move zero and a blank Opening title is focused. Enter a title such as King's Gambit, play e4, then Save Move. The first save creates the opening and its move together. Or press Enter / Create Opening to save an empty opening. Continue e5, Save Move, f4, Save Move. No Save Library, install or publish step is required.

SWITCH OPENINGS

Use the Opening dropdown to switch between The French, London, Pirc Defense and your other openings. Save, Discard or Cancel protects any pending move or unsaved edit. Duplicate friendly names are distinguished by their existing library names.

EDIT AND NAVIGATE

Branch Browser is your map. Click a line or an individual move. The arrows step within that active line. Opening start returns to move zero. Edit Move opens the selected move's notes, weight and preferred flag; Save Changes preserves its identity. Position note and sources describe the displayed position. Move sources describe the selected move.

ADD AN ALTERNATIVE

Select the move you want to replace, then Add Alternative to This Move. Studio returns to the position BEFORE that move and tells you whose turn it is. Play the alternative and Save Move. You can also navigate to any branch point and play a different continuation.

NAME A LINE

Select a line or one of its moves, then Rename Line. This also works for automatic labels such as Line from 5… O-O or Opening trunk. A blank name restores the automatic label. Rename changes presentation, never the chess moves or Polyglot entries.

OPENING DETAILS AND DELETION

Opening Details changes the friendly title, description, version, status, author or license. Names can change without changing opening identity. Delete Opening offers Export / Share First, Delete or Cancel. Deleting removes the opening from normal Studio and Game Review choices; no games are deleted. Its original graph is retained in managed storage for recovery.

EXTERNAL SHARING

Import / Export → Import External Openings previews received material, including versions, authors and duplicate/name conflicts. Choose openings to import; they appear in this dropdown immediately. Identical content reuses an existing opening; different openings with the same name never overwrite each other.

Export / Share Opening writes a new portable .cwbook copy and keeps your working opening in place. Export Polyglot .bin contains active move/weight data only; keep .cwbook for notes, names and sources.

Advanced → External Preview is intentionally read-only. Import into My ChessWizard Library switches directly to the editable copy. Physical paths and technical IDs are available under Advanced → Library Details.

Game Review sees new openings and edits immediately according to the existing status rules. Active/enabled openings can auto-match; Draft and Archived remain manually selectable. Stockfish runs only when you explicitly request Analyze Position, Refresh Analysis or Analyze Deeper in the Stockfish Lines tab.

STOCKFISH LINES — ADVICE, NOT AUTHORED TRUTH

Select a saved move/position in Branch Browser, then open Stockfish Lines. Normal requests three candidate lines. Analyze Position reuses exact compatible evidence; Refresh Analysis explicitly requests a fresh search. Quick returns one line; Deep requests five. Eval is from White's point of view; M3 / -M4 remain mate distances, never opening weights or Opening Accuracy.

Click a candidate to enter STOCKFISH PREVIEW. Use the arrows to step its continuation, then Return to Opening Position. The highlighted authored anchor never moves with this preview. Add as Variation shows the exact destination, complete SAN line and existing/new moves before you confirm. An optional name applies only to the first new edge. New moves use normal weight 50 and are not Preferred. Existing notes, names, weights and preferences stay unchanged.

Stop cancels only this Studio request. Changing the selected opening/branch cancels stale work. Unsaved drafts/move previews must be saved or discarded before analysis. External Preview may inspect advice, but import into My ChessWizard Library before adding it. No automatic gap repair or repertoire editing occurs.
"""


from merlin_ui.opening_studio_workflow import StudioWorkflow


class OpeningBookStudio(StudioWorkflow):
    """Present opening authoring and explicit Stockfish advice through shared core services.

    Args:
        root: Owning Tk window.
        game_database_path: Optional exact-evidence read source.
        theme_service: Existing board theme provider.
        engine_service: Optional injected advisory service for isolated tools/tests.
    """
    def __init__(self, root: tk.Misc, *, game_database_path: str | Path | None = None,
                 theme_service: object | None = None, engine_service: OpeningEngineService | None = None) -> None:
        """Build the authoring workspace without running an engine request.

        Args:
            root: Owning Tk window.
            game_database_path: Optional game evidence source, read-only for advice.
            theme_service: Existing shared theme provider.
            engine_service: Optional test/tool advisory-service injection.
        """
        from application_paths import resolve_database_path
        self.engine_service = engine_service or OpeningEngineService(resolve_database_path(game_database_path))
        self.engine_preview = False
        self.root, self.game_database_path = root, game_database_path
        self.repository = self.service = self.session = None
        from opening_library_service import OpeningLibraryService
        self.library_service=OpeningLibraryService()
        self.external_readonly=False
        self.drafting=False;self.previous_reference=None;self.book_items=()
        self.selected_move = None
        self.navigation = None
        self.editing = False
        self.metadata_json = "{}"
        self.dirty = self.loading = False
        self.shell=MerlinViewShell(root,on_move_attempt=self.stage_board_move,
            title="ChessWizard — Opening Studio",geometry="1280x860",min_size=(1050,750),
            theme_service=theme_service)
        self.board_widget=self.shell.board_widget
        self.root.protocol("WM_DELETE_WINDOW",self.close)
        self._build()
        self.run(self.open_workspace)

    def _build(self):
        right = self.shell.right_panel
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)
        library = ttk.Frame(right);library.grid(row=0,column=0,sticky="ew",padx=6,pady=6)
        library_buttons=ttk.Frame(library);library_buttons.pack(fill="x")
        self.library_buttons={}
        for title, command in (("New book",self.new_book),("Book details",self.edit_book),("Delete book",self.delete_book)):
            button=ttk.Button(library_buttons,text=title.title().replace("Book","Opening"),command=command)
            button.pack(side="left",padx=2);self.library_buttons[title]=button
        menu_button=ttk.Menubutton(library_buttons,text="Import / Export")
        menu_button.pack(side="left",padx=3)
        menu=tk.Menu(menu_button,tearoff=False);menu_button.configure(menu=menu)
        menu.add_command(label="Import External Openings…",command=self.import_books)
        menu.add_command(label="Export / Share Opening…",command=self.export_book)
        menu.add_command(label="Export / Share Current Library…",command=self.export_library)
        advanced=tk.Menu(menu,tearoff=False);menu.add_cascade(label="Advanced",menu=advanced)
        advanced.add_command(label="External Preview — Read Only…",command=self.open_library)
        advanced.add_command(label="Return to My Opening Library",command=lambda:self.guard() and self.run(self.open_workspace))
        advanced.add_command(label="Library Details…",command=self.show_storage_details)
        self.library_context=ttk.Label(library,text='My ChessWizard Opening Library',wraplength=470)
        self.library_context.pack(fill='x',pady=4)
        self.preview_import=ttk.Button(library,text='Import into My ChessWizard Library',command=lambda:self.import_books(self.repository.path))
        self.title_frame=ttk.Frame(library)
        ttk.Label(self.title_frame,text="Opening title:").pack(side="left")
        self.draft_title=tk.StringVar(self.root)
        self.title_entry=ttk.Entry(self.title_frame,textvariable=self.draft_title)
        self.title_entry.pack(side="left",fill="x",expand=True,padx=5)
        self.title_entry.bind("<Return>",lambda event:self.save_editor())
        ttk.Button(self.title_frame,text="Create Opening",command=self.save_editor).pack(side="left")
        selector=ttk.Frame(right);selector.grid(row=1,column=0,sticky="ew",padx=6)
        selector.columnconfigure(1,weight=1)
        ttk.Label(selector,text="Opening:").grid(row=0,column=0,padx=(0,6))
        self.book_picker=ttk.Combobox(selector,state="readonly")
        self.book_picker.grid(row=0,column=1,sticky="ew")
        self.book_picker.bind("<<ComboboxSelected>>",self.select_book)
        self.side_label=ttk.Label(selector,text='Opening Side: Not set')
        self.side_label.grid(row=1,column=0,columnspan=2,sticky='w',pady=(3,0))
        self.position_label=ttk.Label(right,wraplength=520)
        self.position_label.grid(row=2,column=0,sticky="ew",padx=6,pady=5)
        self.tabs=MerlinNotebook(right)
        self.tabs.grid(row=3,column=0,sticky="nsew",padx=6,pady=4)
        self.browser_frame=ttk.Frame(self.tabs)
        self.tabs.add(self.browser_frame,text="Branch Browser")
        from merlin_ui.opening_studio_handoff import StagedReviewLine
        self.staged_review = StagedReviewLine(self.browser_frame, self)
        self.step_controls=ttk.Frame(self.browser_frame)
        self.step_controls.pack(fill="x",pady=4)
        self.left_step=ttk.Button(self.step_controls,text="←",width=4,command=lambda:self.step_branch(-1))
        self.right_step=ttk.Button(self.step_controls,text="→",width=4,command=lambda:self.step_branch(1))
        self.left_step.pack(side="left",padx=3);self.right_step.pack(side="left",padx=3)
        ttk.Label(self.step_controls,text="Step within active branch").pack(side="left",padx=5)
        tree_frame=ttk.Frame(self.browser_frame);tree_frame.pack(fill="both",expand=True)
        self.tree=self._tree(tree_frame,(),show="tree")
        from merlin_ui.information_panel import CURRENT
        self.tree.tag_configure("active_branch",background=CURRENT,foreground="white")
        self.tree.bind("<ButtonRelease-1>",self.click_tree)
        self.tree.bind("<Double-1>",self.double_click_tree)
        for key in ("Up","Down","Home","End","Return"):
            self.tree.bind(f"<KeyRelease-{key}>",self.select_tree)
        from merlin_ui.opening_engine_panel import OpeningEnginePanel
        self.engine_panel = OpeningEnginePanel(self.tabs, service=self.engine_service,
            anchor_provider=self.engine_anchor, authoring_provider=self.engine_authoring,
            show_preview=self.show_engine_preview, restore_board=self.restore_engine_board,
            on_added=self.engine_line_added, skin=self.shell.ui_skin)
        self.tabs.add(self.engine_panel, text="Stockfish Lines")
        self.guide=ScrolledText(self.tabs,wrap="word",width=45,height=10)
        style_information(self.guide);self.guide.insert("1.0",STUDIO_QUICK_START);self.guide.configure(state="disabled")
        self.tabs.add(self.guide,text="How To")
        actions=ttk.Frame(right);actions.grid(row=4,column=0,sticky="ew",padx=6)
        self.edit_button=ttk.Button(actions,text="Edit Move",command=self.edit_move)
        self.edit_button.pack(side="left")
        self.delete_button=ttk.Button(actions,text="Delete Move / Variation",command=self.delete_branch)
        self.delete_button.pack(side="left",padx=4)
        branch_actions=ttk.Frame(self.browser_frame);branch_actions.pack(fill="x",before=self.step_controls,pady=3)
        self.rename_line_button=ttk.Button(branch_actions,text="Rename Line…",command=self.rename_line)
        self.rename_line_button.pack(side="left")
        self.alternative_button=ttk.Button(branch_actions,text="Add Alternative to This Move",command=self.add_alternative)
        self.alternative_button.pack(side="left",padx=4)
        self.editor=ttk.LabelFrame(right,text="VIEWING SAVED POSITION",padding=6)
        self.editor.grid(row=5,column=0,sticky="ew",padx=6,pady=5)
        self.editor.columnconfigure(1,weight=1)
        self.fields={};self.option_widgets=[]
        self.weight=tk.StringVar(self.root,value="50")
        self.preferred=tk.BooleanVar(self.root);self.active=tk.BooleanVar(self.root,value=True)
        for variable in (self.weight,self.preferred,self.active):variable.trace_add("write",self.mark_dirty)
        options=ttk.Frame(self.editor);options.grid(row=0,column=0,columnspan=2,sticky="ew")
        ttk.Label(options,text="Weight 1–100").pack(side="left")
        for widget in (ttk.Spinbox(options,from_=1,to=100,textvariable=self.weight,width=5),
                       ttk.Checkbutton(options,text="Preferred",variable=self.preferred),
                       ttk.Checkbutton(options,text="Active",variable=self.active)):
            widget.pack(side="left",padx=4);self.option_widgets.append(widget)
        for row,key in enumerate(("variation_name","variation_description","move_note","instructional_note"),1):
            ttk.Label(self.editor,text=key.replace("_"," ").capitalize()).grid(row=row,column=0,sticky="nw",pady=3)
            value=tk.Text(self.editor,height=2 if key.endswith("note") else 1,width=35,wrap="word")
            value.grid(row=row,column=1,sticky="ew",pady=3)
            value.bind("<<Modified>>",self.text_modified);self.fields[key]=value
        self.advanced_button=ttk.Button(self.editor,text="Advanced metadata (JSON)…",command=self.advanced_metadata)
        self.advanced_button.grid(row=5,column=0,columnspan=2,sticky="w")
        buttons=ttk.Frame(self.editor);buttons.grid(row=6,column=0,columnspan=2,sticky="ew",pady=4)
        self.save_button=ttk.Button(buttons,command=self.save_editor);self.save_button.pack(side="left")
        self.cancel_button=ttk.Button(buttons,command=self.discard);self.cancel_button.pack(side="left",padx=5)
        notes=ttk.Frame(right);notes.grid(row=6,column=0,sticky="ew",padx=6,pady=4)
        self.note_buttons=[]
        for label,command in (("Position note",self.position_note),("Position sources",lambda:self.sources(False)),("Move sources",lambda:self.sources(True))):
            button=ttk.Button(notes,text=label,command=command)
            button.pack(side="left",padx=2);self.note_buttons.append(button)
        output=ttk.Frame(right);output.grid(row=7,column=0,sticky="ew",padx=6,pady=4)
        ttk.Button(output,text="Export Polyglot .bin",command=self.export).pack(side="left")
        ttk.Button(output,text="Apply to game ID…",command=self.apply_game).pack(side="left",padx=4)
        self.authoring_panels = (actions, self.editor, notes, output)
        self.tabs.bind('<<NotebookTabChanged>>', self._advisory_tab_changed, add='+')
        controls=self.shell.left_controls
        ttk.Button(controls,text="Opening start",command=self.book_start).pack(anchor="w",pady=4)
        notation=ttk.Frame(controls);notation.pack(fill="x",pady=4)
        ttk.Label(notation,text="Move (SAN/UCI)").pack(side="left")
        self.notation=ttk.Entry(notation,width=14);self.notation.pack(side="left",padx=5)
        self.notation.bind("<Return>",lambda event:self.stage_text())
        self.preview_button=ttk.Button(notation,text="Preview move",command=self.stage_text)
        self.preview_button.pack(side="left")
        ttk.Label(controls,text="Click a branch or move to navigate. Play on the board to author.\nA preview is unsaved until you choose Save Move.",wraplength=560).pack(fill="x",pady=4)

    def _advisory_tab_changed(self, event: tk.Event | None = None) -> None:
        """Give advice its own space; keep the authored editor on the authoring tab."""
        advisory = self.tabs.select() == str(self.engine_panel)
        for panel in self.authoring_panels:
            panel.grid_remove() if advisory else panel.grid()
        if not advisory:
            self.engine_panel.return_to_anchor()

    def _tree(self,parent,columns,show="headings"):
        parent.rowconfigure(0,weight=1);parent.columnconfigure(0,weight=1)
        tree=ttk.Treeview(parent,columns=columns,show=show,selectmode="browse",height=7)
        style_information_tree(tree)
        tree.grid(row=0,column=0,sticky="nsew")
        scroll=ttk.Scrollbar(parent,orient="vertical",command=tree.yview);scroll.grid(row=0,column=1,sticky="ns")
        horizontal=ttk.Scrollbar(parent,orient="horizontal",command=tree.xview);horizontal.grid(row=1,column=0,sticky="ew")
        tree.configure(yscrollcommand=scroll.set,xscrollcommand=horizontal.set)
        return tree

    def mark_dirty(self,*args):
        if not self.loading:self.dirty=True

    def text_modified(self,event):
        if event.widget.edit_modified():
            self.mark_dirty();event.widget.edit_modified(False)

    def require_editable(self) -> bool:
        """Check authoring access and leave advisory preview before normal edits.

        Returns:
            Whether the selected library is editable.
        """
        if self.engine_preview:
            self.engine_panel.return_to_anchor()
        if self.repository is None:return False
        if self.repository.read_only:
            messagebox.showinfo("Read-only library",READ_ONLY_LIBRARY_MESSAGE,parent=self.root)
            return False
        return True

    def run(self, operation: Callable[[], object]) -> object:
        """Run a UI action and notify only after a committed library change.

        Args:
            operation: Zero-argument authoring or navigation callback.

        Returns:
            Callback result, or None after a displayed expected error.
        """
        from opening_library_metadata import library_fingerprint
        before=library_fingerprint(self.library_service.repository)
        try:
            result=operation()
            if before!=library_fingerprint(self.library_service.repository):
                self.notify_library_changed()
            return result
        except (ValueError,OSError,sqlite3.Error) as error:
            readonly = (getattr(error,"sqlite_errorcode",0) & 0xff) == sqlite3.SQLITE_READONLY
            message = READ_ONLY_LIBRARY_MESSAGE if readonly else str(error)
            messagebox.showerror("Opening Studio",message,parent=self.root)
            return None

    def use_repository(self, repository: OpeningBookRepository, *, book_id: int | None = None,
                       draft: bool = False) -> None:
        """Switch authoring repositories and discard only uncommitted Review staging.

        Args:
            repository: Open destination repository owned by Studio after this call.
            book_id: Optional opening within that repository.
            draft: Whether this repository is a temporary new-opening draft.
        """
        self.staged_review.cancel()
        if draft:self.previous_reference=self.selected_reference()
        if self.repository:self.repository.close()
        self.drafting=draft
        self.external_readonly=repository.read_only
        self.repository=repository;self.service=OpeningBookService(repository);self.session=None
        self.library_context.configure(text="External Preview — Read Only" if self.external_readonly else "My ChessWizard Opening Library")
        self.refresh_books()
        if self.books:
            self.session=OpeningBookSession(self.service,book_id or self.books[0].book_id)
            self.tabs.select(0)
        self.render()

    def open_library(self):
        if not self.guard():return
        path=filedialog.askopenfilename(parent=self.root,filetypes=[('ChessWizard library','*.cwbook')])
        if path:
            def open_file():
                from opening_book_reader import open_readonly_library
                from opening_library_package import inspect_package
                managed=self.library_service.library_for_path(path)
                if not managed:inspect_package(path,allow_empty=True)
                self.use_repository(OpeningBookRepository.open(path) if managed else open_readonly_library(path))
            self.run(open_file)

    def export_library(self):
        if not self.repository or not self.guard():return
        library=self.library_service.library_for_path(self.repository.path)
        if library is None:
            messagebox.showinfo('External Library','Add this library to My ChessWizard Library before sharing from here.',parent=self.root);return
        path=filedialog.asksaveasfilename(parent=self.root,title='Export / Share Library (new file)',
            defaultextension='.cwbook',filetypes=[('ChessWizard library','*.cwbook')],confirmoverwrite=False)
        if path:self.run(lambda:self.library_service.export_library(library.library_id,path))

    def set_details(self,details):
        self.loading=True
        self.weight.set(str(details.weight));self.preferred.set(details.preferred);self.active.set(details.active)
        self.metadata_json=details.metadata_json
        for key,widget in self.fields.items():
            widget.configure(state="normal")
            widget.delete("1.0","end");widget.insert("1.0",getattr(details,key));widget.edit_modified(False)
        self.loading=False;self.dirty=False

    def details(self):
        return MoveDetails(int(self.weight.get()),self.preferred.get(),self.active.get(),
                           metadata_json=self.metadata_json,**{k:w.get("1.0","end-1c") for k,w in self.fields.items()})

    def current_move(self):
        if not self.session:return None
        return next((m for m in self.session.snapshot.moves if m.move_id==self.selected_move),None)

    def render_editor(self) -> None:
        """Render authoring controls and publish the current saved-position eligibility."""
        pending=bool(self.session and self.session.pending)
        editable=bool(self.repository and not self.repository.read_only)
        writable=editable and (pending or self.editing)
        self.library_buttons["New book"].configure(state="disabled" if self.external_readonly else "normal")
        self.library_buttons["Book details"].configure(state="normal" if editable and self.session and not self.drafting else "disabled")
        self.library_buttons["Delete book"].configure(state="normal" if self.selected_reference() else "disabled")
        for button in self.note_buttons:button.configure(state="normal" if editable and self.session else "disabled")
        self.preview_button.configure(state="normal" if editable and self.session else "disabled")
        self.notation.configure(state="normal" if editable and self.session else "disabled")
        move=self.current_move()
        title=("UNSAVED MOVE" if pending else f"EDITING SAVED MOVE · {move.san}" if self.editing and move else "VIEWING SAVED POSITION")
        self.editor.configure(text=title)
        if writable:self.editor.grid()
        else:self.editor.grid_remove()
        for widget in self.fields.values():widget.configure(state="normal" if writable and not self.external_readonly else "disabled")
        for widget in self.option_widgets:widget.configure(state="normal" if writable and not self.external_readonly else "disabled")
        self.advanced_button.configure(state="normal" if writable and not self.external_readonly else "disabled")
        self.edit_button.configure(state="normal" if editable and move and not writable else "disabled")
        self.delete_button.configure(state="normal" if editable and move and not pending else "disabled")
        self.save_button.configure(text="Save Move" if pending else "Save Changes",state="normal" if writable and not self.external_readonly else "disabled")
        self.cancel_button.configure(text="Cancel Move" if pending else "Cancel",state="normal" if writable and not self.external_readonly else "disabled")
        active=self.navigation.active if self.navigation else None
        self.rename_line_button.configure(state="normal" if editable and active else "disabled")
        self.alternative_button.configure(state="normal" if editable and move else "disabled")
        self.left_step.configure(state="normal" if active and self.navigation.index>0 else "disabled")
        self.right_step.configure(state="normal" if active and self.navigation.index<len(active.steps)-1 else "disabled")
        self._sync_engine_position()

    def render(self) -> None:
        """Update selection details, reusing branch widgets until the snapshot changes."""
        self.loading=True
        side=self.session.snapshot.book.repertoire_side if self.session else None
        label={'white':'White','black':'Black','both':'Both / Reference'}.get(side,'Not set — Opening Details')
        self.side_label.configure(text='Opening Side: '+label)
        if self.drafting:self.title_frame.pack(fill="x",pady=4)
        else:self.title_frame.pack_forget()
        if self.external_readonly:self.preview_import.pack(anchor="w",pady=4)
        else:self.preview_import.pack_forget()
        if self.session:
            s=self.session
            if self.navigation is None or self.navigation.session is not s:self.navigation=BranchNavigation(s)
            path=s.history[:s.cursor]
            self.selected_move=path[-1] if path else None
            self.sync_picker()
            self._render_branches(path)
            self.position_label.configure(text=f"{s.snapshot.book.name}\n{self.navigation.status()}")
            self.board_widget.set_position(s.board);self.board_widget.set_input_enabled(not self.external_readonly)
            self.shell.set_status(READ_ONLY_LIBRARY_MESSAGE if self.external_readonly else
                "NEW OPENING · Enter a title, play a move, then Save Move." if self.drafting else
                "VIEWING SAVED POSITION · Click Edit Move to change saved details.","normal")
        else:
            self.navigation=None;self.selected_move=None;self.book_picker.set("")
            self.tree.delete(*self.tree.get_children());self.branch_nodes={};self.paths={}
            self._tree_snapshot=None
            self.position_label.configure(text="Your opening library is empty. Choose New Opening to start.")
            self.tabs.select(self.browser_frame);self.board_widget.set_position(chess.Board());self.board_widget.set_input_enabled(False)
        move=self.current_move()
        self.loading=False;self.editing=False
        self.set_details(MoveDetails(**{k:getattr(move,k) for k in MoveDetails.__dataclass_fields__}) if move else MoveDetails())
        self.render_editor()
        self.staged_review.refresh()

    def _render_branches(self, path: tuple[int, ...]) -> None:
        branches=self.navigation.branches()
        rebuild=(getattr(self,'_tree_snapshot',None) is not self.session.snapshot
                 or branches!=getattr(self,'_tree_branches',None))
        if rebuild:
            previous_open={key:self.tree.item(key,'open') for key in getattr(self,'branch_nodes',{}) if self.tree.exists(key)}
            self.tree.delete(*self.tree.get_children());self.branch_nodes={};self.paths={}
            self._move_nodes={};self._tree_labels={}
            for branch in branches:
                header='b'+'_'.join(map(str,branch.anchor))
                parent=self._move_nodes.get(branch.parent_path,'')
                self.tree.insert(parent,'end',iid=header,text=branch.label,open=previous_open.get(header,True))
                self._tree_labels[header]=branch.label
                self.branch_nodes[header]=(branch,0);self.paths[header]=branch.anchor
                for index,step in enumerate(branch.steps):
                    key='m'+'_'.join(map(str,step.path));self._move_nodes[step.path]=key
                    label=step.label+(' ↪ shared' if step.shared else '')
                    self.tree.insert(header,'end',iid=key,text=label,open=previous_open.get(key,True))
                    self._tree_labels[key]=label
                    self.branch_nodes[key]=(branch,index);self.paths[key]=step.path
            self._tree_snapshot=self.session.snapshot;self._tree_branches=branches
            self._tree_highlights=()
        for key in getattr(self,'_tree_highlights',()):
            if self.tree.exists(key):self.tree.item(key,text=self._tree_labels[key],tags=())
        active=self.navigation.active
        header='b'+'_'.join(map(str,active.anchor)) if active else None
        selected=self._move_nodes.get(path)
        self._tree_highlights=tuple(k for k in (header,selected) if k and self.tree.exists(k))
        if header and self.tree.exists(header):
            self.tree.item(header,text='● '+self._tree_labels[header],tags=('active_branch',));self.tree.see(header)
        if selected:
            self.tree.item(selected,text='▶ '+self._tree_labels[selected])
            self.tree.selection_set(selected);self.tree.see(selected)
        elif self.tree.selection():self.tree.selection_remove(*self.tree.selection())

    def edit_move(self):
        if not self.require_editable():return
        if self.current_move() and not self.session.pending:
            self.editing=True;self.render_editor()
            self.shell.set_status("EDITING SAVED MOVE · Save Changes or Cancel.","normal")

    def advanced_metadata(self):
        if not self.require_editable():return
        if not self.editing and not (self.session and self.session.pending):return
        from opening_book_models import json_metadata
        result=edit_fields(self.root,"Advanced metadata (JSON)",
                           {"metadata_json":self.metadata_json},multiline=("metadata_json",),
                           description="Optional developer/extension metadata. Most users should leave this unchanged.")
        if result is not None:
            def validate():
                self.metadata_json=json_metadata(result["metadata_json"]);self.dirty=True
            self.run(validate)

    def stage_board_move(self,move):
        if self.session and self.guard(include_draft=False):self.run(lambda:self.stage(move.uci()))

    def stage_text(self):
        if self.session and self.guard(include_draft=False):self.run(lambda:self.stage(self.notation.get().strip()))

    def stage(self,notation):
        if not self.require_editable():return
        label=self.session.stage_notation(notation)
        self.editing=False
        existing=next((m for m in self.session.snapshot.branches(self.session.position_id) if m.move_uci==self.session.pending),None)
        self.set_details(MoveDetails(**{k:getattr(existing,k) for k in MoveDetails.__dataclass_fields__}) if existing else MoveDetails())
        preview=self.session.board.copy();preview.push_uci(self.session.pending)
        self.board_widget.set_position(preview);self.board_widget.set_input_enabled(False)
        self.position_label.configure(text=f"{self.session.snapshot.book.name}\nUNSAVED preview after {label}")
        self.shell.set_status(f"PENDING {label} · Save Move or Cancel Move. Nothing written.","normal")
        self.render_editor()

    def save_pending(self):
        if not self.require_editable():return
        if self.session:
            def save():
                self.session.save(self.details());self.navigation.sync();self.refresh_books();self.render()
            self.run(save)

    def update_selected(self):
        if not self.require_editable():return
        if self.selected_move is not None and self.editing and self.session.pending is None:
            def save():
                self.service.edit_move(self.session.book_id,self.selected_move,self.details())
                self.session.refresh();self.navigation.sync();self.refresh_books();self.render()
            self.run(save)

    def delete_branch(self):
        if not self.require_editable():return
        if self.selected_move is None or not self.guard():return
        def delete():
            plan=choose_deletion(self.root,self.service,self.session.book_id,self.selected_move)
            if plan is not None:
                parent=self.session.history[:self.session.cursor-1]
                self.service.delete(plan)
                self.session.history=parent;self.session.cursor=len(parent)
                self.session.refresh();self.navigation.active=None;self.navigation.sync()
                self.refresh_books()
            self.render()
        self.run(delete)

    def book_start(self):
        if self.session and self.guard(include_draft=False):
            self.run(lambda:(self.navigation.root(),self.render()))

    def step_branch(self,offset):
        if self.session and self.guard(include_draft=False):
            self.run(lambda:(self.navigation.step(offset),self.render()))

    def activate_node(self,key):
        if key not in self.branch_nodes:return
        branch,index=self.branch_nodes[key]
        if self.guard(include_draft=False):self.run(lambda:(self.navigation.activate(branch,index),self.render()))
        else:
            path=self.session.history[:self.session.cursor]
            previous=next((k for k,p in self.paths.items() if p==path and k.startswith("m")),None)
            if previous:self.tree.selection_set(previous)
            else:self.tree.selection_remove(*self.tree.selection())

    def double_click_tree(self,event):
        self._ignore_click_release=True
        return "break"

    def click_tree(self,event):
        if getattr(self,"_ignore_click_release",False):
            self._ignore_click_release=False
            return
        key=self.tree.identify_row(event.y)
        disclosure="indicator" in self.tree.identify_element(event.x,event.y)
        if key and not (disclosure and self.tree.get_children(key)):self.activate_node(key)

    def select_tree(self,event=None):
        selected=self.tree.selection()
        if selected and not self.loading:self.activate_node(selected[0])

    def position_note(self):
        if not self.require_editable():return
        if not self.session or not self.guard():return
        position=self.session.snapshot.position(self.session.position_id)
        result=edit_fields(self.root,"Position commentary",dict(position_note=position.position_note),multiline=("position_note",))
        if result is not None:
            def save():
                self.repository.set_position_note(self.session.book_id,self.session.position_id,**result,metadata_json=position.metadata_json)
                self.session.refresh();self.render()
            # Repository names the text 'note'; presentation keeps its clearer field label.
            result["note"]=result.pop("position_note")
            self.run(save)

    def sources(self,move):
        if not self.require_editable():return
        if not self.session or (move and self.selected_move is None) or not self.guard():return
        position_id=self.current_move().from_position_id if move else self.session.position_id
        dialog=SourceReferenceDialog(self.root,self.repository,self.session.book_id,position_id,self.selected_move if move else None)
        self.root.wait_window(dialog.root);self.session.refresh();self.render()

    def export(self):
        if not self.session or not self.guard():return
        path=filedialog.asksaveasfilename(parent=self.root,title="Export active opening moves (new file only)",
            defaultextension=".bin",filetypes=[("Polyglot opening","*.bin")],confirmoverwrite=False)
        if path:
            def write():
                self.session.refresh()
                receipt=export_polyglot(self.session.snapshot,path)
                messagebox.showinfo("Export verified",f"{receipt.entry_count} legal entries · {receipt.byte_count} bytes\nSHA256: {receipt.sha256}",parent=self.root)
            self.run(write)

    def apply_game(self):
        if not self.session or self.game_database_path is None:return
        if not self.guard():return
        game_id=simpledialog.askinteger("Read-only opening lookup","Game ID in the active game database:",parent=self.root,minvalue=1)
        if game_id is None:return
        def apply():
            self.session.refresh()
            result=apply_stored_game(self.game_database_path,game_id,self.session.snapshot)
            window=tk.Toplevel(self.root);window.title("Opening membership — not move quality");window.geometry("900x560")
            output=tk.Text(window,wrap="word");output.pack(fill="both",expand=True)
            output.insert("end",f"Opening {self.session.snapshot.book.name} v{result.book_version}, revision {result.book_revision}\nGame ID {game_id}\n"
                f"In-opening moves: {result.in_book_move_count}; known position visits: {result.known_position_count}\n"
                f"First deviation ply: {result.first_deviation_ply or 'None'}; side: {result.deviating_side or 'None'}; {result.deviation_relation or 'unknown perspective'}\n"
                f"Last known position after ply: {result.last_known_position_ply}\nNot in opening does not mean a bad move. No game data was changed.\n\n")
            for row in result.moves:
                options=", ".join(f"{m.san} ({m.weight})"+(" preferred" if m.preferred else "") for m in row.available_moves)
                output.insert("end",f"{row.move_number} {row.actor_color}: {row.played_san} — {row.state.replace('_',' ')}; weight {row.weight if row.weight else '—'}\nOpening moves: {options or 'none'}\n")
            output.configure(state="disabled")
        self.run(apply)

    def close(self) -> bool:
        """Close after unsaved-change handling and cancel the owned advisory worker.

        Returns:
            True when closing, or False when the user retains unsaved work.
        """
        if not self.guard():return False
        self.engine_panel.close()
        if self.repository:self.repository.close()
        self.root.destroy()
        return True


    def receive_handoff(self, handoff: "OpeningStudioHandoff") -> None:
        """Open exact managed theory and stage missing moves without writing.

        Args:
            handoff: Validated Review identity, branch and actual-game anchor.

        Raises:
            ValueError: The opening changed or the destination is no longer managed.
        """
        if not self.guard():return
        library = self.library_service.get_library(handoff.anchor.library_identity)
        item = next((book for book in library.books
                     if book.snapshot and book.snapshot.book.book_id == handoff.anchor.book_id), None)
        if item is None:raise ValueError('The selected opening is no longer managed.')
        from opening_engine_models import saved_opening_anchor
        current = saved_opening_anchor(item.snapshot, item.library_id, handoff.anchor.path)
        if current != handoff.anchor:
            raise ValueError('The opening changed. Refresh Opening Review before opening Studio.')
        self.load_book(item)
        self.session.go_to(handoff.anchor.path)
        self.navigation.sync()
        self.render()
        self.tabs.select(self.browser_frame)
        self.staged_review.show(handoff)
        self.shell.set_status(f'GAME {handoff.source_game_id} / PLY {handoff.source_ply} '
                              + ' - ' + handoff.anchor.label, 'normal')

    def engine_anchor(self) -> OpeningEngineAnchor:
        """Read the saved selection independently of the displayed preview board.

        Returns:
            Current saved opening/path/position anchor.

        Raises:
            ValueError: The selection is a draft, unsaved move or edit.
        """
        if not self.session or self.drafting:
            raise ValueError('Save a opening and select a saved position before analysis.')
        if self.session.pending or self.editing or self.dirty:
            raise ValueError('Save or discard the unsaved move/edit before analysis.')
        header = next((b for b in self.book_items if b.path==self.repository.path),None)
        identity = header.library_id if header else 'external:' + str(self.repository.path.resolve()).casefold()
        return saved_opening_anchor(self.session.snapshot, identity, self.session.history[:self.session.cursor])

    def engine_authoring(self) -> OpeningEngineAuthoringService:
        """Resolve the explicit authoring destination for the current saved selection.

        Returns:
            Shared ID-preserving authoring service.

        Raises:
            ValueError: No suitable saved position is selected.
        """
        anchor = self.engine_anchor()
        return OpeningEngineAuthoringService(self.repository, anchor.library_identity)

    def _sync_engine_position(self) -> None:
        try:
            anchor, reason = self.engine_anchor(), ''
        except ValueError as error:
            anchor, reason = None, str(error)
        self.engine_panel.set_position(anchor, bool(self.repository and not self.repository.read_only), reason)

    def show_engine_preview(self, state: LinePlaybackState) -> None:
        """Project the isolated engine cursor without moving the authored selection.

        Args:
            state: Shared legal playback cursor for the selected advisory line.
        """
        self.engine_preview = True
        self.board_widget.set_position(chess.Board(state.fen))
        self.board_widget.set_input_enabled(False)
        self.position_label.configure(text=f'STOCKFISH PREVIEW · ply {state.ply}/{state.total_plies}\n'
                                           + self.engine_panel.analysis.anchor.label)
        self.shell.set_status('STOCKFISH PREVIEW · The authored opening position is preserved. Return to Opening Position to author.', 'normal')

    def restore_engine_board(self) -> None:
        """Return only an active advisory projection to the saved opening board."""
        if self.engine_preview:
            self.engine_preview = False
            if self.session and not self.session.pending:
                self.board_widget.set_position(self.session.board)
                self.board_widget.set_input_enabled(not self.external_readonly)
                self.position_label.configure(text=self.session.breadcrumb())
                self.shell.set_status('VIEWING SAVED POSITION · Stockfish advice does not change your opening.', 'normal')

    def engine_line_added(self) -> None:
        """Refresh the shared authored graph after a confirmed atomic line addition."""
        self.session.refresh()
        self.navigation.sync()
        self.refresh_books()
        self.render()
        self.notify_library_changed()
