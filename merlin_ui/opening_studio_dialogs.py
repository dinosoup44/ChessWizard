"""Small confirmations and external interchange previews for the Studio workspace."""
import tkinter as tk
from tkinter import ttk


from merlin_ui.action_dialog import choose_action


def choose_books(parent, entries):
    window=tk.Toplevel(parent);window.title("Import External Openings");window.geometry("700x400")
    window.transient(parent);window.columnconfigure(0,weight=1);window.rowconfigure(1,weight=1)
    ttk.Label(window,text="Choose openings to import. Identical openings reuse your existing copy.\nSame-name openings with different content stay separate; nothing is overwritten.",wraplength=650).grid(row=0,column=0,sticky="w",padx=12,pady=12)
    tree=ttk.Treeview(window,columns=("version","author","match"),show="tree headings",selectmode="extended")
    tree.heading("#0",text="Opening");tree.column("#0",width=230)
    for key,label in (("version","Version"),("author","Author"),("match","Already in your library")):
        tree.heading(key,text=label);tree.column(key,width=130)
    tree.grid(row=1,column=0,sticky="nsew",padx=12)
    for entry in entries:
        match="Identical — reuse" if entry.duplicate_id else "Same name — separate opening" if entry.name_conflict else "New book"
        tree.insert("","end",iid=str(entry.book_id),text=entry.name,values=(entry.version,entry.author,match))
    tree.selection_set(tree.get_children());result=[]
    def accept():
        selected=tuple(int(i) for i in tree.selection())
        if selected:result.append(selected);window.destroy()
    buttons=ttk.Frame(window);buttons.grid(row=2,column=0,padx=12,pady=12,sticky="ew")
    ttk.Button(buttons,text="Import selected",command=accept).pack(side="left")
    ttk.Button(buttons,text="Cancel",command=window.destroy).pack(side="right")
    window.grab_set();parent.wait_window(window)
    return result[0] if result else ()
