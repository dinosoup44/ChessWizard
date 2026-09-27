"""Canonical book manager; widgets delegate data operations to shared services."""
import json
import sqlite3
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from merlin_ui.opening_book_dialogs import edit_fields
from opening_library_service import OpeningLibraryService


def choose_import(parent, preview, *, whole_library=False):
    dialog=tk.Toplevel(parent);dialog.title('Import ChessWizard Book');dialog.geometry('620x430')
    result=[]
    picker=ttk.Combobox(dialog,state='readonly',values=[f'{s.book.name} · v{s.book.version}' for s in preview.books] or ['Empty library'])
    picker.pack(fill='x',padx=12,pady=12);picker.current(0)
    info=tk.Text(dialog,wrap='word',height=14);info.pack(fill='both',expand=True,padx=12)
    def show(event=None):
        if not preview.books:
            info.insert('1.0','Empty ChessWizard library. It can be added and edited in Studio.');info.configure(state='disabled');return
        s=preview.books[picker.current()];meta=json.loads(s.book.metadata_json)
        value=(f'{s.book.name} · v{s.book.version}\nAuthor: {meta.get("author", "")}\n'
               f'License: {meta.get("license", "Unspecified")}\n\n{s.book.description}\n\n'
               f'{len(s.moves)} moves · {len(s.positions)} positions · '
               f'{sum(bool(m.variation_name) for m in s.moves)} named variations\nSchema {preview.schema_version}\n\n'
               + ('All books in this library are copied into managed storage. ' if whole_library else 'One selected book is copied into managed storage. ') + 'Existing books are never overwritten. '
               'Notes and source references are retained when sharing.')
        info.configure(state='normal');info.delete('1.0','end');info.insert('1.0',value);info.configure(state='disabled')
    def accept():result.append(preview.books[picker.current()].book.book_id if preview.books else 0);dialog.destroy()
    picker.bind('<<ComboboxSelected>>',show);show()
    buttons=ttk.Frame(dialog);buttons.pack(fill='x',padx=12,pady=12)
    ttk.Button(buttons,text='Import library' if whole_library else 'Import',command=accept).pack(side='left')
    ttk.Button(buttons,text='Cancel',command=dialog.destroy).pack(side='right')
    dialog.transient(parent);dialog.grab_set();dialog.wait_window()
    return result[0] if result else None


class OpeningLibraryManager:
    def __init__(self,root,*,service=None,on_change=None,on_open_studio=None,selected_id=None):
        self.root=root;self.service=service or OpeningLibraryService()
        self.on_change=on_change or (lambda:None);self.on_open_studio=on_open_studio
        self.selected_id=selected_id or (lambda:None)
        root.title('My ChessWizard Library');root.geometry('960x560')
        ttk.Label(root,text='My ChessWizard Library — Libraries contain books. Studio edits the same managed files.').pack(anchor='w',padx=10,pady=10)
        columns=('version','author','enabled','primary','status')
        body=ttk.Frame(root);body.pack(fill='both',expand=True,padx=10)
        self.tree=ttk.Treeview(body,columns=columns,show='tree headings',selectmode='browse')
        self.tree.heading('#0',text='Library / Book');self.tree.column('#0',width=250,minwidth=170)
        for name in columns:
            self.tree.heading(name,text=name.title());self.tree.column(name,width=200 if name=='name' else 95,minwidth=65)
        self.tree.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(body,command=self.tree.yview);scroll.pack(side='right',fill='y');self.tree.configure(yscrollcommand=scroll.set)
        self.status=ttk.Label(root,text='',wraplength=860);self.status.pack(fill='x',padx=10,pady=8)
        actions=ttk.Frame(root);actions.pack(fill='x',padx=10,pady=4)
        for label,action in [('Import External Book…',self.import_book),('Export / Share…',self.export),('Clone…',self.clone),
                             ('Enable / Disable',self.toggle),('Set Primary',self.primary),('Clear Primary',lambda:self.service.set_primary())]:
            ttk.Button(actions,text=label,command=lambda f=action:self.run(f)).pack(side='left',padx=2)
        more=ttk.Frame(root);more.pack(fill='x',padx=10,pady=8)
        for label,action in [('Metadata…',self.metadata),('Status…',self.change_status),('Open in Studio',self.studio),('Remove…',self.remove),('Refresh',lambda:None)]:
            ttk.Button(more,text=label,command=lambda f=action:self.run(f)).pack(side='left',padx=2)
        self.tree.bind('<<TreeviewSelect>>',lambda e:self.describe())
        self.refresh()
        self.focus_pending=False
        root.bind('<FocusIn>',self.on_focus,add='+')
        from merlin_ui.opening_library_events import register
        register(self)

    def on_focus(self,event):
        if not self.focus_pending:
            self.focus_pending=True;self.root.after_idle(self._focus_refresh)

    def _focus_refresh(self):
        self.focus_pending=False
        if self.root.winfo_exists():self.refresh()

    def winfo_exists(self):return self.root.winfo_exists()

    def managed_root(self):return self.service.repository.root

    def library_changed(self):self.refresh()

    def selected(self):
        ids=self.tree.selection()
        if not ids or ids[0].startswith('library:'):raise ValueError('Select a book beneath its library.')
        return self.service.get(ids[0])

    def refresh(self):
        if not self.root.winfo_exists():return
        selected=self.tree.selection();self.tree.delete(*self.tree.get_children())
        for library in self.service.list_libraries():
            parent='library:'+library.library_id
            self.tree.insert('','end',iid=parent,text=library.name,open=True,
                values=('','','','',library.error or library.origin))
            for item in library.books:
                book=item.snapshot.book;meta=json.loads(book.metadata_json)
                self.tree.insert(parent,'end',iid=item.installation_id,text=book.name,
                    values=(book.version,meta.get('author',''),'Yes' if item.enabled else 'No',
                            'Yes' if item.primary else 'No',book.status))
        if selected and self.tree.exists(selected[0]):self.tree.selection_set(selected)

    def describe(self):
        try:
            item=self.selected();book=item.snapshot.book if item.snapshot else None
            self.status.configure(text=(f'{item.label} · {len(item.snapshot.moves)} moves · '
                f'{len(item.snapshot.positions)} positions\n{book.description}' if book else item.error))
        except ValueError:self.status.configure(text='')

    def run(self, action):
        try:
            action();self.refresh();self.on_change()
            from merlin_ui.opening_library_events import changed
            changed(self.service.repository.root)
        except (ValueError,OSError,sqlite3.Error) as error:messagebox.showerror('Opening Library',str(error),parent=self.root)

    def import_book(self):
        path=filedialog.askopenfilename(parent=self.root,title='Import External Book / Library',filetypes=[('ChessWizard library','*.cwbook')])
        if not path:return
        preview=self.service.preview_import(path)
        if choose_import(self.root,preview,whole_library=True) is None:return
        overlap=self.service.partial_overlap(preview)
        if overlap and not messagebox.askyesno('Existing book overlap',', '.join(overlap)+'\n\nImport as a separate library, including separate copies of these books?',parent=self.root,default='no'):return
        existing={lib.library_id for lib in self.service.list_libraries()}
        library=self.service.import_library(path,preview,allow_partial_overlap=bool(overlap))
        self.refresh();self.tree.selection_set('library:'+library.library_id)
        if library.library_id in existing:messagebox.showinfo('My ChessWizard Library','This content is already in My ChessWizard Library.',parent=self.root)

    def export(self):
        selected=self.tree.selection()
        if not selected:raise ValueError('Select a library or book.')
        path=filedialog.asksaveasfilename(parent=self.root,title='Export / Share (new file)',defaultextension='.cwbook',filetypes=[('ChessWizard library','*.cwbook')],confirmoverwrite=False)
        if path:
            if selected[0].startswith('library:'):self.service.export_library(selected[0].split(':',1)[1],path)
            else:self.service.export_book(selected[0],path)

    def clone(self):
        item=self.selected();name=simpledialog.askstring('Clone Book','Name for your independent editable copy:',parent=self.root)
        if name:
            result=self.service.clone_book(item.installation_id,name);self.refresh();self.tree.selection_set(result.installation_id)

    def toggle(self):
        item=self.selected();self.service.set_enabled(item.installation_id,not item.enabled)

    def primary(self):self.service.set_primary(self.selected().installation_id)

    def metadata(self):
        item=self.selected()
        if item.snapshot is None:raise ValueError(item.error)
        metadata=json.loads(item.snapshot.book.metadata_json)
        result=edit_fields(self.root,'Sharing metadata',dict(author=metadata.get('author',''),license=metadata.get('license',''),description=item.snapshot.book.description),multiline=('description',))
        if result is not None:self.service.update_metadata(item.installation_id,**result)

    def change_status(self):
        item=self.selected();book=item.snapshot.book
        result=edit_fields(self.root,'Book lifecycle',dict(status=book.status),choices={'status':('draft','active','archived')})
        if result:self.service.set_status(item.installation_id,result['status'])

    def studio(self):
        selected=self.tree.selection()
        if not selected:raise ValueError('Select a library or book.')
        item=(self.service.get_library(selected[0].split(':',1)[1]) if selected[0].startswith('library:') else self.selected())
        if self.on_open_studio:self.on_open_studio(item)

    def remove(self):
        item=self.selected()
        preview=self.service.preview_removal(item.installation_id,selected_id=self.selected_id())
        message=(f'{preview.label}\nEnabled: {preview.enabled} · Primary: {preview.primary}\n'
                 f'Selected in Game Review: {preview.selected_in_review}\nOrigin: {preview.origin}\n'
                 f'{preview.cached_assessments}\n\nRemove/archive this book and clear its primary state? '
                 'In a multi-book library it becomes Archived; a single-book library moves to opening_books/removed. No games are deleted.')
        if messagebox.askyesno('Remove installed book',message,parent=self.root):
            self.service.remove(preview,clear_primary=True)
