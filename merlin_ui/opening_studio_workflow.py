"""Opening workspace presentation; persistence and identity rules live in core services."""
from dataclasses import replace
import json
from tkinter import filedialog, messagebox, simpledialog
from opening_book_models import BookDetails, MoveDetails
from opening_library_metadata import managed_book_headers, header_labels
from opening_book_repository import OpeningBookRepository
from opening_book_service import OpeningBookService
from opening_book_session import OpeningBookSession
from opening_studio_service import OpeningStudioService, WORKSPACE_NAME
from merlin_ui.opening_studio_dialogs import choose_action, choose_books
from merlin_ui.opening_book_dialogs import edit_fields


class StudioWorkflow:
    @property
    def workspace(self):return OpeningStudioService(self.library_service)

    def open_workspace(self, selected_id: str | None = None) -> None:
        """Open the authoring shell using metadata and just one selected graph.

        Args:
            selected_id: Preferred managed reference; falls back to the existing authoring default.
        """
        items=managed_book_headers(self.library_service.repository)
        default=next((b for b in items if b.primary),
                     next((b for b in items if b.book.status=="active"),items[0] if items else None))
        item=next((b for b in items if b.installation_id==selected_id),default)
        if item:self.load_book(item)
        else:
            if self.repository:self.repository.close()
            self.repository=self.service=self.session=None
            self.drafting=False;self.external_readonly=False
            self.library_context.configure(text=WORKSPACE_NAME)
            self.refresh_books();self.render()

    def load_book(self, item: object) -> None:
        """Open just the selected managed book through the authoring repository.

        Args:
            item: Managed metadata header or explicitly resolved installed book.
        """
        book=item.book if hasattr(item,'book') else item.snapshot.book
        repository=OpeningBookRepository.open(item.path)
        self.use_repository(repository,book_id=book.book_id)

    def refresh_books(self) -> None:
        """Refresh selector metadata without loading any unselected opening graph."""
        self.books=self.repository.books() if self.repository else ()
        self.book_items=() if self.external_readonly else managed_book_headers(self.library_service.repository)
        self.local_authoring=bool(self.repository and not self.drafting and not self.external_readonly
                                  and not any(b.path==self.repository.path for b in self.book_items))
        labels=tuple(b.name for b in self.books) if self.external_readonly or self.local_authoring else header_labels(self.book_items)
        self.book_picker.configure(values=labels)

    def selected_reference(self) -> str | None:
        """Read the loaded opening's managed identity without disk or graph work.

        Returns:
            Stable reference, or None for drafts, external and unmanaged files.
        """
        if not self.session or self.drafting or self.external_readonly:return None
        return next((b.installation_id for b in self.book_items
                     if b.path==self.repository.path and b.book.book_id==self.session.book_id),None)

    def sync_picker(self) -> None:
        """Project the loaded selection without changing its identity."""
        if self.drafting:self.book_picker.set("New Opening")
        elif (self.external_readonly or self.local_authoring) and self.session:
            self.book_picker.current(next(i for i,b in enumerate(self.books) if b.book_id==self.session.book_id))
        elif self.session:
            ref=self.selected_reference()
            index=next((i for i,b in enumerate(self.book_items) if b.installation_id==ref),None)
            if index is not None:self.book_picker.current(index)
        else:self.book_picker.set("")

    def select_book(self, event: object | None = None) -> None:
        """Load the explicit opening while preserving the unsaved-change guard.

        Args:
            event: Optional combobox selection event.
        """
        index=self.book_picker.current()
        if index<0:return
        local=self.external_readonly or self.local_authoring
        target=self.books[index].book_id if local else self.book_items[index]
        if not self.guard():self.sync_picker();return
        def select() -> None:
            if local:
                self.session=OpeningBookSession(self.service,target);self.render()
            else:self.load_book(target)
        self.run(select)

    def guard(self, *, include_draft=True):
        unsaved=(self.drafting and include_draft) or self.dirty or (self.session and self.session.pending)
        if unsaved:
            choice=choose_action(self.root,"Unsaved changes","You have unsaved changes.",
                                 (("Save","save"),("Discard","discard"),("Cancel","cancel")))
            if choice=="cancel":return False
            if choice=="save":
                self.save_editor()
                if self.drafting or self.dirty or (self.session and self.session.pending):return False
            else:self.discard()
        elif self.editing:self.discard()
        return True

    def new_book(self):
        if self.external_readonly and not self.require_editable():return
        if not self.guard():return
        def create():
            repo=self.workspace.draft()
            self.use_repository(repo,draft=True)
            self.draft_title.set("");self.dirty=False
            self.title_entry.focus_set()
        self.run(create)

    def commit_new_book(self):
        # Validate the title before a Save can alter even the temporary draft.
        BookDetails(self.draft_title.get().strip())
        if self.session.pending:self.session.save(self.details())
        item=self.workspace.commit_draft(self.session.snapshot,self.draft_title.get())
        self.load_book(item)
        if self.session.snapshot.moves:
            # A new draft has one saved first move; keep the board at its result.
            self.session.follow(self.session.snapshot.moves[0].move_id)
            self.navigation.sync();self.render()
        self.notify_library_changed()

    def save_editor(self):
        if self.drafting:return self.run(self.commit_new_book)
        if not self.require_editable():return
        if self.session and self.session.pending:self.save_pending()
        elif self.editing:self.update_selected()

    def discard(self):
        if self.drafting:
            self.drafting=False;self.dirty=False;self.editing=False
            self.open_workspace(self.previous_reference)
        else:
            if self.session:self.session.discard()
            self.editing=False;self.dirty=False;self.render()

    def delete_book(self):
        if not self.session or self.drafting or not self.require_editable() or not self.guard():return
        reference=self.selected_reference()
        if not reference:return
        def delete():
            preview=self.library_service.preview_removal(reference)
            name=self.session.snapshot.book.name
            choice=choose_action(self.root,"Delete Opening",f'Delete "{name}"?\n\nRemoves this opening from My ChessWizard Opening Library. Chess games are not deleted. Opening assessments and reference links to this opening will no longer be available. Export first if you want a portable copy.',
                                 (("Export / Share First","export"),("Delete","delete"),("Cancel","cancel")))
            if choice=="export":self.export_book();return
            if choice!="delete":return
            self.library_service.delete_book(preview)
            self.open_workspace();self.notify_library_changed()
        self.run(delete)

    def import_books(self, path=None):
        if not self.guard():return
        path=path or filedialog.askopenfilename(parent=self.root,title="Import External Opening / Library",filetypes=[("ChessWizard openings","*.cwbook")])
        if not path:return
        def perform():
            preview=self.library_service.preview_import(path)
            if not preview.books:
                messagebox.showinfo("Empty library","There are no openings to import.",parent=self.root);return
            selected=choose_books(self.root,self.workspace.preview(preview))
            if not selected:return
            items=self.workspace.import_selected(path,preview,selected)
            self.load_book(items[0]);self.notify_library_changed()
        self.run(perform)

    def export_book(self):
        if not self.session or self.drafting or not self.guard():return
        ref=self.selected_reference()
        if not ref:return
        path=filedialog.asksaveasfilename(parent=self.root,title="Export / Share Opening",defaultextension=".cwbook",filetypes=[("ChessWizard opening","*.cwbook")],confirmoverwrite=False)
        if path:self.run(lambda:self.library_service.export_book(ref,path))

    def edit_book(self) -> None:
        """Edit explicit opening intent and metadata through normal authoring."""
        if not self.session or not self.require_editable() or not self.guard():return
        book=self.session.snapshot.book;metadata=json.loads(book.metadata_json)
        fields={k:getattr(book,k) for k in ("name","description","version","status")}
        fields.update(author=metadata.get("author",""),license=metadata.get("license",""),
                      repertoire_side=metadata.get("repertoire_side","unspecified"))
        result=edit_fields(self.root,"Opening Details",fields,multiline=("description",),choices={"status":("draft","active","archived"),
                "repertoire_side":("unspecified","white","black","both")},labels={"repertoire_side":"Opening Side"})
        if result is None:return
        def save():
            metadata.update(author=result.pop("author",metadata.get("author","")),license=result.pop("license",metadata.get("license","")))
            from opening_repertoire import with_repertoire_side
            side=result.pop("repertoire_side",metadata.get("repertoire_side","unspecified"))
            if side=="unspecified":metadata.pop("repertoire_side",None)
            else:metadata.update(json.loads(with_repertoire_side(json.dumps(metadata),side)))
            self.repository.update_book(book.book_id,BookDetails(**result,metadata_json=json.dumps(metadata)))
            self.session.refresh();self.refresh_books();self.render()
        self.run(save)

    def rename_line(self):
        if not self.navigation or not self.navigation.active or not self.require_editable() or not self.guard():return
        anchor=self.navigation.active.anchor[-1]
        edge=next(m for m in self.session.snapshot.moves if m.move_id==anchor)
        name=simpledialog.askstring("Rename Line","Line name (leave blank for the automatic label):",initialvalue=edge.variation_name,parent=self.root)
        if name is None:return
        def save():
            details=MoveDetails(**{k:getattr(edge,k) for k in MoveDetails.__dataclass_fields__})
            self.service.edit_move(self.session.book_id,anchor,replace(details,variation_name=name.strip()))
            self.session.refresh();self.navigation.sync();self.render()
        self.run(save)

    def add_alternative(self) -> None:
        """Return to the parent move and show the exact branch point."""
        if not self.session or not self.require_editable() or not self.guard():return
        self.navigation.alternative_to_current();self.render()
        self.shell.set_status(self.navigation.alternative_prompt(),"normal")
        self.notation.focus_set()

    def show_storage_details(self):
        if self.repository:
            messagebox.showinfo("Advanced Library Details",f"{self.repository.path}\nOpening ID: {self.session.book_id if self.session else 'none'}",parent=self.root)

    def notify_library_changed(self):
        from merlin_ui.opening_library_events import changed
        changed(self.library_service.repository.root)
