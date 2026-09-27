"""Small desktop theme editor using the production ChessBoard component."""
from dataclasses import asdict
from pathlib import Path
import tkinter as tk
from merlin_ui.notebook import MerlinNotebook
from tkinter import ttk, filedialog, colorchooser, messagebox
import chess
from PIL import Image, ImageTk
from theme_core import ThemeRepository, BoardColors, PIECE_ROLES, DECORATION_SLOTS
from theme_core.editor import ThemeDraft
from theme_core.preview_states import PREVIEW_STATES
from merlin_ui.chess_board import ChessBoard
from merlin_ui.appearance import DEFAULT_BOARD_STYLE, DEFAULT_PIECE_STYLE
from merlin_ui.piece_sets import create_piece_set


class ScrollPane(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent)
        self.canvas=tk.Canvas(self,highlightthickness=0)
        bar=ttk.Scrollbar(self,orient="vertical",command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right",fill="y");self.canvas.pack(side="left",fill="both",expand=True)
        self.body=ttk.Frame(self.canvas,padding=8)
        item=self.canvas.create_window(0,0,window=self.body,anchor="nw")
        self.body.bind("<Configure>",lambda event:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",lambda event:self.canvas.itemconfigure(item,width=event.width))
        self.winfo_toplevel().bind("<MouseWheel>",self._wheel,add="+")

    def _wheel(self,event):
        if (self.winfo_ismapped() and self.winfo_rootx()<=event.x_root<self.winfo_rootx()+self.winfo_width()
                and self.winfo_rooty()<=event.y_root<self.winfo_rooty()+self.winfo_height()):
            self.canvas.yview_scroll(-1 if event.delta>0 else 1,"units")


class ArtTester:
    def __init__(self,root,theme_directory=None,*,repository=None,title="ChessWizard — Art Tester"):
        self.root=root
        self.repository=repository if repository is not None else ThemeRepository(theme_directory or Path(__file__).resolve().parents[1]/"themes")
        self.draft=ThemeDraft()
        self.asset_rows={};self.saved={}
        self.name=tk.StringVar(root);self.author=tk.StringVar(root)
        self.status=tk.StringVar(root,value="Choose PNGs to begin. Missing pieces use the Unicode fallback.")
        self.completeness=tk.StringVar(root)
        self.theme_choice=tk.StringVar(root,value="Editor preview")
        self.sample=tk.StringVar(root,value=PREVIEW_STATES[1].name)
        self.coordinates=tk.BooleanVar(root,value=True);self.flipped=tk.BooleanVar(root)
        self.overlays=tk.BooleanVar(root)
        self.color_vars={k:tk.StringVar(root,value=v) for k,v in asdict(self.draft.colors).items()}
        root.title(title)
        root.geometry("1360x860");root.minsize(1000,680)
        panes=tk.PanedWindow(root,orient="horizontal",sashwidth=7,bd=0)
        panes.pack(fill="both",expand=True,padx=12,pady=12)
        editor=ttk.Frame(panes,padding=8);preview=ttk.Frame(panes,padding=8)
        panes.add(editor,minsize=430,width=495);panes.add(preview,minsize=460)
        self._build_editor(editor);self._build_preview(preview)
        self.refresh_saved();self.refresh_preview()

    def _build_editor(self,parent):
        ttk.Label(parent,text="Theme / asset editor",font=("Segoe UI",16,"bold")).pack(anchor="w",pady=(0,10))
        fields=ttk.Frame(parent);fields.pack(fill="x")
        fields.columnconfigure(1,weight=1)
        for row,(label,var) in enumerate((("Set name",self.name),("Author (optional)",self.author))):
            ttk.Label(fields,text=label).grid(row=row,column=0,sticky="w",pady=3,padx=(0,10))
            ttk.Entry(fields,textvariable=var).grid(row=row,column=1,sticky="ew",pady=3)
        actions=ttk.Frame(parent);actions.pack(fill="x",pady=10)
        self.save_button=ttk.Button(actions,text="Save Theme",command=self.save_theme)
        self.save_button.pack(side="left")
        ttk.Button(actions,text="New / clear editor",command=self.new_theme).pack(side="left",padx=8)
        ttk.Label(parent,textvariable=self.completeness,wraplength=430).pack(anchor="w",pady=(0,8))
        tabs=MerlinNotebook(parent);tabs.pack(fill="both",expand=True)
        pieces=ScrollPane(tabs);board=ScrollPane(tabs)
        tabs.add(pieces,text="12 piece roles");tabs.add(board,text="Board & decoration")
        for role in PIECE_ROLES:self._asset_row(pieces.body,role)
        for key in self.color_vars:
            row=ttk.Frame(board.body);row.pack(fill="x",pady=4)
            ttk.Label(row,text=key.replace("_"," ").title(),width=15).pack(side="left")
            field=ttk.Entry(row,textvariable=self.color_vars[key],width=12)
            field.pack(side="left",padx=5)
            field.bind("<Return>",lambda event:self.apply_colors())
            field.bind("<FocusOut>",lambda event:self.apply_colors())
            ttk.Button(row,text="Pickâ€¦",command=lambda k=key:self.pick_color(k)).pack(side="left")
        ttk.Separator(board.body).pack(fill="x",pady=12)
        ttk.Label(board.body,text="Optional PNG decorations â€” fixed slots",font=("Segoe UI",10,"bold")).pack(anchor="w")
        for role in DECORATION_SLOTS:self._asset_row(board.body,role)
        ttk.Label(parent,textvariable=self.status,wraplength=440).pack(fill="x",pady=(10,0))

    def _asset_row(self,parent,role):
        row=ttk.Frame(parent,padding=(0,6));row.pack(fill="x")
        row.columnconfigure(1,weight=1)
        thumb=ttk.Label(row,text="â€”",width=5,anchor="center")
        thumb.grid(row=0,column=0,rowspan=3,padx=(0,8))
        ttk.Label(row,text=role.replace("_"," ").title(),font=("Segoe UI",10,"bold")).grid(row=0,column=1,sticky="w")
        path=tk.StringVar(self.root)
        ttk.Entry(row,textvariable=path,state="readonly",width=22).grid(row=1,column=1,sticky="ew",pady=3)
        buttons=ttk.Frame(row);buttons.grid(row=0,column=2,rowspan=2,padx=(8,0))
        ttk.Button(buttons,text="Choose PNGâ€¦",command=lambda:self.choose_asset(role)).pack(fill="x")
        ttk.Button(buttons,text="Remove",command=lambda:self.clear_asset(role)).pack(fill="x",pady=(3,0))
        valid=tk.StringVar(self.root)
        ttk.Label(row,textvariable=valid,wraplength=330).grid(row=2,column=1,columnspan=2,sticky="w")
        self.asset_rows[role]=dict(path=path,valid=valid,thumbnail=thumb,photo=None)
        self.refresh_asset(role)

    def _build_preview(self,parent):
        ttk.Label(parent,text="Static preview",font=("Segoe UI",16,"bold")).pack(anchor="w",pady=(0,10))
        ttk.Label(parent,text="Saved set / current editor").pack(anchor="w")
        self.theme_selector=ttk.Combobox(parent,textvariable=self.theme_choice,state="readonly")
        self.theme_selector.pack(fill="x",pady=(3,10))
        self.theme_selector.bind("<<ComboboxSelected>>",lambda event:self.select_theme())
        samplebar=ttk.Frame(parent);samplebar.pack(fill="x")
        ttk.Button(samplebar,text="Previous",command=lambda:self.step_sample(-1)).pack(side="left")
        self.sample_selector=ttk.Combobox(samplebar,textvariable=self.sample,state="readonly",
                                        values=[x.name for x in PREVIEW_STATES])
        self.sample_selector.pack(side="left",fill="x",expand=True,padx=5)
        self.sample_selector.bind("<<ComboboxSelected>>",lambda event:self.show_position())
        ttk.Button(samplebar,text="Next",command=lambda:self.step_sample(1)).pack(side="left")
        controls=ttk.Frame(parent);controls.pack(fill="x",pady=8)
        for text,var in (("Flip board",self.flipped),("Coordinates",self.coordinates),("Overlay sample",self.overlays)):
            ttk.Checkbutton(controls,text=text,variable=var,command=self.show_position).pack(side="left",padx=(0,12))
        self.board_widget=ChessBoard(parent,dict(DEFAULT_BOARD_STYLE),create_piece_set(DEFAULT_PIECE_STYLE),bg="#302b35")
        self.board_widget.pack(fill="both",expand=True)
        ttk.Label(parent,text="Preview only Â· Saving never changes the active app theme",wraplength=650).pack(anchor="w",pady=(8,0))

    def refresh_asset(self,role):
        row=self.asset_rows[role]
        asset=(self.draft.pieces if role in PIECE_ROLES else self.draft.decorations).get(role)
        if asset:
            image=asset.image();image.thumbnail((38,38),Image.Resampling.LANCZOS)
            row['photo']=ImageTk.PhotoImage(image,master=self.root)
            row['thumbnail'].configure(image=row['photo'],text="")
            row['valid'].set(f"Valid Â· {asset.width}Ã—{asset.height}"+(" Â· transparency" if asset.transparent else " Â· opaque PNG"))
        else:
            row['photo']=None;row['thumbnail'].configure(image="",text="â€”")
            row['path'].set("")
            row['valid'].set("Required â€” missing; Unicode fallback" if role in PIECE_ROLES else "Optional â€” not assigned")

    def choose_asset(self,role):
        path=filedialog.askopenfilename(parent=self.root,title="Choose "+role.replace("_"," "),filetypes=[("PNG image","*.png"),("All files","*.*")])
        if path:self.assign_file(role,path)

    def assign_file(self,role,path):
        try:
            self.draft.assign(role,path)
        except (ValueError,OSError) as error:
            self.asset_rows[role]['valid'].set("Rejected selection; previous asset retained")
            self.status.set(str(error));return False
        self.asset_rows[role]['path'].set(str(path));self.refresh_asset(role)
        self.theme_choice.set("Editor preview");self.refresh_preview()
        self.status.set("PNG loaded. Save Theme to create an independent managed copy.")
        return True

    def clear_asset(self,role):
        self.draft.clear(role);self.refresh_asset(role)
        self.theme_choice.set("Editor preview");self.refresh_preview()

    def apply_colors(self):
        try:colors=BoardColors(**{k:v.get() for k,v in self.color_vars.items()})
        except ValueError as error:self.status.set(str(error));return False
        if colors!=self.draft.colors:
            self.draft.colors=colors;self.theme_choice.set("Editor preview");self.refresh_preview()
        return True

    def pick_color(self,key):
        chosen=colorchooser.askcolor(color=getattr(self.draft.colors,key),parent=self.root)[1]
        if chosen:self.color_vars[key].set(chosen);self.apply_colors()

    def refresh_preview(self):
        missing=len(self.draft.missing_roles)
        self.completeness.set(f"Draft â€” {12-missing}/12 pieces; {missing} required PNGs missing" if missing else "Complete â€” all 12 piece PNGs assigned")
        self.board_widget.set_theme(self.draft.preview());self.show_position()

    def show_position(self):
        fixture=next(x for x in PREVIEW_STATES if x.name==self.sample.get())
        self.board_widget.set_position(chess.Board(fixture.fen),orientation=not self.flipped.get())
        self.board_widget.set_show_coordinates(self.coordinates.get())
        self.board_widget.clear_overlays()
        if self.overlays.get():
            self.board_widget.selected_square=chess.D4
            self.board_widget.set_last_move(chess.Move.from_uci("e2e4"))
            self.board_widget.set_arrows([{"from":chess.G1,"to":chess.F3}])
        self.board_widget.redraw()

    def step_sample(self,delta):
        names=[x.name for x in PREVIEW_STATES]
        self.sample.set(names[(names.index(self.sample.get())+delta)%len(names)]);self.show_position()

    def refresh_saved(self,selected_id=None):
        self.saved={f"{t.name} Â· {'complete' if t.complete else 'draft'} Â· {t.theme_id[-6:]}":t.theme_id
                    for t in self.repository.list_themes()}
        self.theme_selector.configure(values=["Editor preview",*self.saved])
        if selected_id:
            self.theme_choice.set(next(k for k,v in self.saved.items() if v==selected_id))

    def select_theme(self):
        if self.theme_choice.get()=="Editor preview":return
        try:loaded=self.repository.load(self.saved[self.theme_choice.get()])
        except (ValueError,OSError) as error:
            self.theme_choice.set("Editor preview");self.status.set("Theme not loaded: "+str(error));return
        self.draft=ThemeDraft.from_loaded(loaded);self.sync_editor()
        self.status.set("Saved set loaded. Saving edits creates a new set; the original is preserved.")

    def sync_editor(self):
        self.name.set(self.draft.name);self.author.set(self.draft.author)
        for key,value in asdict(self.draft.colors).items():self.color_vars[key].set(value)
        for role in self.asset_rows:
            self.asset_rows[role]['path'].set(("pieces/" if role in PIECE_ROLES else "board/")+role+".png")
            self.refresh_asset(role)
        self.refresh_preview()

    def new_theme(self):
        if (self.draft.pieces or self.draft.decorations or self.name.get()) and not messagebox.askyesno(
                "New theme","Clear the editor? Saved sets will be preserved.",parent=self.root):return
        self.draft=ThemeDraft();self.theme_choice.set("Editor preview");self.sync_editor()
        self.status.set("New draft. Choose PNGs and enter a set name.")

    def save_theme(self):
        if not self.apply_colors():return False
        self.draft.name=self.name.get();self.draft.author=self.author.get()
        try:loaded=self.draft.save(self.repository)
        except (ValueError,OSError) as error:self.status.set("Not saved: "+str(error));return False
        self.refresh_saved(loaded.theme.theme_id)
        self.status.set("Saved "+("complete theme" if loaded.theme.complete else "draft (required pieces still missing)")+": "+loaded.theme.name)
        return True


def main():
    root=tk.Tk()
    ArtTester(root)
    root.mainloop()
