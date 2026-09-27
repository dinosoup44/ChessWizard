"""Tactic-agnostic widgets consuming TacticalMoment values only."""
import tkinter as tk
from tkinter import ttk
from merlin_ui.proof_line_table import ProofLineTable


class TacticalMomentsPanel(tk.Frame):
    def __init__(self, parent, *, ui_skin, make_button, on_select, load_moment=None, on_train_candidate=None, on_line_toggle=None, on_selection_changed=None):
        super().__init__(parent,bg=ui_skin["panel_bg"])
        self.skin, self.on_select = ui_skin,on_select
        self.load_moment = load_moment
        self.on_line_toggle = on_line_toggle
        self.on_selection_changed = on_selection_changed
        self.moments, self.selected, self.show_line = [],None,False
        self.columnconfigure(0,weight=1); self.rowconfigure(4,weight=1)
        self.count_label = tk.Label(self,text="0 tactical moments",anchor="w",bg=ui_skin["panel_bg"],fg=ui_skin["muted_text"])
        self.count_label.grid(row=0,column=0,sticky="ew",padx=10,pady=(10,5))
        listing = tk.Frame(self,bg=ui_skin["panel_bg"])
        listing.grid(row=1,column=0,sticky="ew",padx=10); listing.columnconfigure(0,weight=1)
        self.listbox = tk.Listbox(listing,height=3,exportselection=False,activestyle="none",
            bg=ui_skin["panel_bg"],fg=ui_skin["text"],font=("Segoe UI",10),relief=tk.FLAT)
        self.listbox.grid(row=0,column=0,sticky="ew")
        scrollbar = ttk.Scrollbar(listing,orient="vertical",command=self.listbox.yview)
        scrollbar.grid(row=0,column=1,sticky="ns"); self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.bind("<<ListboxSelect>>",self._select)
        self.title_label = tk.Label(self,text="Select a tactical moment",anchor="w",justify="left",
            bg=ui_skin["panel_bg"],fg=ui_skin["text"],font=("Segoe UI",15,"bold"),wraplength=390)
        self.title_label.grid(row=2,column=0,sticky="ew",padx=10,pady=(12,5))
        self.motifs_label = tk.Label(self, text="", anchor="w", justify="left",
            bg=ui_skin["panel_bg"], fg=ui_skin["text"], wraplength=390)
        self.motifs_label.grid(row=3,column=0,sticky="ew",padx=10)
        body = tk.Frame(self,bg=ui_skin["panel_bg"])
        body.grid(row=4,column=0,sticky="nsew",padx=10)
        body.columnconfigure(0,weight=1); body.rowconfigure(0,weight=1)
        self.detail = tk.Text(body,wrap="word",height=8,relief=tk.FLAT,font=("Segoe UI",10),
            bg=ui_skin["panel_bg"],fg=ui_skin["text"],padx=0,pady=4,state="disabled")
        self.detail.grid(row=0,column=0,sticky="nsew")
        scroll = ttk.Scrollbar(body,orient="vertical",command=self.detail.yview)
        scroll.grid(row=0,column=1,sticky="ns"); self.detail.configure(yscrollcommand=scroll.set)
        self.proof_frame = tk.LabelFrame(self, text="Merlin line", bg=ui_skin["panel_bg"],
            fg=ui_skin["text"], padx=6,pady=4)
        self.proof_frame.grid(row=5,column=0,sticky="ew",padx=10,pady=4)
        self.proof_frame.columnconfigure(0,weight=1)
        self.proof_text = ProofLineTable(self.proof_frame, skin=ui_skin)
        self.proof_text.grid(row=0,column=0,sticky="ew")
        proof_scroll = ttk.Scrollbar(self.proof_frame,orient="vertical",command=self.proof_text.yview)
        proof_scroll.grid(row=0,column=1,sticky="ns")
        self.proof_text.configure(yscrollcommand=proof_scroll.set)
        controls = tk.Frame(self,bg=ui_skin["panel_bg"])
        controls.grid(row=6,column=0,sticky="ew",padx=7,pady=5)
        self.line_button = make_button(controls,"Show Line",self.toggle_line)
        self.line_button.pack(side="left",padx=3)
        self.train_button = None
        if on_train_candidate is not None:
            self.train_button = make_button(controls,"Train this",lambda:on_train_candidate(self.selected.candidate_id) if self.selected else None)
            self.train_button.pack(side="left",padx=3)
        self.bind("<Configure>",self._resize_labels)
        self.clear_selection()

    def set_moments(self, moments):
        self.moments = list(moments)
        count = len(self.moments)
        self.count_label.configure(text=f"{count} tactical moment{'s' if count!=1 else ''}")
        self.listbox.delete(0,"end")
        for index,moment in enumerate(self.moments):
            self.listbox.insert("end",moment.list_label)
            if moment.presentation_level in {"secondary_motif","positional_note"}:
                self.listbox.itemconfigure(index,foreground=self.skin["muted_text"])
        self.clear_selection()

    def _resize_labels(self, event):
        width = max(150,event.width-24)
        self.title_label.configure(wraplength=width)
        self.motifs_label.configure(wraplength=width)

    @property
    def selected_candidate_id(self):
        return self.selected.candidate_id if self.selected else None

    def clear_selection(self):
        self.selected, self.show_line = None,False
        self.listbox.selection_clear(0,"end")
        self.render_feedback_result()
        if self.on_selection_changed:
            self.on_selection_changed(None)

    def _select(self, event=None):
        indices = self.listbox.curselection()
        if not indices: return
        moment = self.moments[indices[0]]
        # Reload one complete result; never combine optional fields from the old
        # selection with a new board position or a cached list-row snapshot.
        fresh = self.load_moment(moment.candidate_id) if self.load_moment else moment
        self.selected, self.show_line = fresh,False
        self.on_select(fresh)
        self.render_feedback_result()
        if self.on_selection_changed:
            self.on_selection_changed(fresh)

    @staticmethod
    def _replace_text(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0","end")
        widget.insert("1.0",text)
        widget.yview_moveto(0)
        widget.configure(state="disabled")

    def render_feedback_result(self):
        """The only detail renderer, including empty and collapsed states."""
        moment = self.selected
        result = moment.feedback if moment else None
        muted = result and result.presentation_level in {"secondary_motif","positional_note"}
        title = result.title if result else "Select a tactical moment" if self.moments else "No tactical moments"
        self.title_label.configure(text=title,fg=self.skin["muted_text"] if muted else self.skin["text"])
        motifs, lines = [],[]
        if result:
            if result.motif_labels: motifs.append("Motifs: " + ", ".join(result.motif_labels))
            if result.context_motif_labels: motifs.append("Context only: " + ", ".join(result.context_motif_labels))
            lines = [f"Move {moment.move_number} · {moment.color.capitalize()}",
                     result.played_move_label,result.recommended_move_label]
            if result.outcome_label: lines.append("Outcome: " + result.outcome_label)
            lines += ["",result.explanation]
            if result.attribution_labels: lines += ["", "Attribution: " + "; ".join(result.attribution_labels)]
            if result.relationship_labels: lines += ["", *result.relationship_labels]
            if result.teaching_note: lines += ["",result.teaching_note]
            if result.warning_note: lines += ["",result.warning_note]
        else:
            lines = ["Choose a moment above to revisit the decision." if self.moments else "No stored active tactics for this game."]
        self.motifs_label.configure(text="\n".join(motifs))
        self._replace_text(self.detail,"\n".join(lines))
        has_proof = bool(result and result.proof_summary and moment.stored_line.raw_text)
        self.show_line = self.show_line and has_proof
        self.proof_text.set_line(moment.stored_line if has_proof else None)
        if self.show_line: self.proof_frame.grid()
        else: self.proof_frame.grid_remove()
        self.line_button.configure(state="normal" if has_proof else "disabled",text="Hide Line" if self.show_line else "Show Line")
        if self.train_button: self.train_button.configure(state="normal" if result else "disabled")

    def toggle_line(self):
        self.show_line = not self.show_line
        self.render_feedback_result()
        if self.on_line_toggle:
            self.on_line_toggle(self.show_line)
