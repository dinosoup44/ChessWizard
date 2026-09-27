"""Small authoring metadata dialogs; all storage remains in the shared repository."""
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
from opening_book_models import SourceDetails


def edit_fields(parent: tk.Misc, title: str, values: dict[str, object], *,
                multiline: tuple[str, ...] = (), choices: dict[str, tuple[str, ...]] | None = None,
                description: str | None = None, labels: dict[str, str] | None = None) -> dict[str, str] | None:
    """Edit metadata while keeping friendly field labels separate from storage keys.

    Args:
        parent: Dialog owner.
        title: Window title.
        values: Initial values indexed by stable storage key.
        multiline: Fields accepting several lines.
        choices: Optional allowed values for selection fields.
        description: Optional introductory text.
        labels: Optional user-facing labels, independent of storage keys.

    Returns:
        Edited strings, or None if the user cancels.
    """
    window = tk.Toplevel(parent)
    window.title(title); window.transient(parent); window.grab_set()
    window.columnconfigure(1, weight=1)
    widgets, result = {}, []
    offset = 1 if description else 0
    if description:
        ttk.Label(window,text=description,wraplength=500).grid(row=0,column=0,columnspan=2,sticky="w",padx=8,pady=8)
    for index, (key,value) in enumerate(values.items(),offset):
        ttk.Label(window, text=(labels or {}).get(key,key.replace("_"," ").capitalize())).grid(row=index,column=0,sticky="nw",padx=8,pady=5)
        if key in multiline:
            widget = tk.Text(window, height=4, width=55, wrap="word")
            widget.insert("1.0",str(value))
        elif choices and key in choices:
            widget = ttk.Combobox(window, values=choices[key], state="readonly")
            widget.set(str(value))
        else:
            widget = ttk.Entry(window, width=55)
            widget.insert(0,str(value))
        widget.grid(row=index,column=1,sticky="ew",padx=8,pady=5)
        widgets[key]=widget
    def save():
        result.append({k:(w.get("1.0","end-1c") if isinstance(w,tk.Text) else w.get()) for k,w in widgets.items()})
        window.destroy()
    buttons=ttk.Frame(window);buttons.grid(row=len(values)+offset,column=0,columnspan=2,pady=8)
    ttk.Button(buttons,text="Save",command=save).pack(side="left",padx=5)
    ttk.Button(buttons,text="Cancel",command=window.destroy).pack(side="left")
    parent.wait_window(window)
    return result[0] if result else None


class SourceReferenceDialog:
    def __init__(self, parent, repository, book_id, position_id, move_id=None):
        self.repository, self.book_id, self.position_id, self.move_id = repository,book_id,position_id,move_id
        self.root=tk.Toplevel(parent);self.root.title("Move sources" if move_id else "Position sources")
        self.root.geometry("760x540");self.root.transient(parent);self.root.grab_set()
        self.root.columnconfigure(0,weight=1);self.root.rowconfigure(0,weight=1)
        self.tree=ttk.Treeview(self.root,columns=("title","author","locator"),show="headings",selectmode="browse")
        for key in ("title","author","locator"):self.tree.heading(key,text=key.capitalize())
        self.tree.grid(row=0,column=0,sticky="nsew",padx=8,pady=8)
        buttons=ttk.Frame(self.root);buttons.grid(row=1,column=0,sticky="ew",padx=8,pady=8)
        for label,command in (("Add source",self.add),("Edit selected",self.edit),("Delete selected",self.delete),("Close",self.root.destroy)):
            ttk.Button(buttons,text=label,command=command).pack(side="left",padx=3)
        ttk.Label(self.root,text="References and your original private notes only; no automatic prose import.").grid(row=2,column=0,pady=5)
        self.refresh()

    def refresh(self):
        self.sources={s.source_ref_id:s for s in self.repository.snapshot(self.book_id).sources
                      if s.position_id==self.position_id and s.move_id==self.move_id}
        self.tree.delete(*self.tree.get_children())
        for key,source in self.sources.items():
            self.tree.insert("","end",iid=str(key),values=(source.title,source.author,
                " · ".join(v for v in (source.edition,source.chapter,source.page) if v)))

    def selected(self):
        selection=self.tree.selection()
        return self.sources[int(selection[0])] if selection else None

    def add(self):self._edit(None)

    def edit(self):
        source=self.selected()
        if source:self._edit(source)

    def _edit(self, source):
        values={k:(getattr(source,k) if source else "") for k in SourceDetails.__dataclass_fields__}
        values=edit_fields(self.root,"Source reference",values,multiline=("private_note",))
        if values is None:return
        try:
            self.repository.save_source(self.book_id,self.position_id,self.move_id,
                SourceDetails(**values),source.source_ref_id if source else None)
            self.refresh()
        except (ValueError,sqlite3.Error) as error:
            messagebox.showerror("Source not saved",str(error),parent=self.root)

    def delete(self):
        source=self.selected()
        if source and messagebox.askyesno("Delete source","Delete this reference only?",parent=self.root):
            self.repository.delete_source(self.book_id,source.source_ref_id);self.refresh()

