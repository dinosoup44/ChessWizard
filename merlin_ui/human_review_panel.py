"""Compact desktop controls for the separate human QA review repository."""
import tkinter as tk
from tkinter import ttk

from human_analyzer_reviews import MAX_NOTE_LENGTH, ReviewVerdict
from human_analyzer_review_repository import ReviewStorageError
from review_audit_status import audit_status_for_case


class HumanReviewPanel(tk.LabelFrame):
    def __init__(self, parent, *, ui_skin, repository, on_select_case=None):
        super().__init__(parent, text="Human Review · local QA", bg=ui_skin["panel_bg"], fg=ui_skin["text"], padx=6, pady=4)
        self.repository = repository
        self.on_select_case = on_select_case
        self.case = None
        self.targets = ()
        self.columnconfigure(1, weight=1)
        self.target_picker = ttk.Combobox(self, state="readonly", width=40)
        self.target_picker.grid(row=0,column=0,columnspan=2,sticky="ew",pady=(0,4))
        self.target_picker.bind("<<ComboboxSelected>>", self._choose_target)
        self.audit_status = tk.Label(self, anchor="w", justify="left",
                                     font=("Segoe UI", 10, "bold"), wraplength=480,
                                     bg=ui_skin["panel_bg"], fg=ui_skin["text"])
        self.audit_status.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.audit_explanation = tk.Label(self, anchor="w", justify="left", wraplength=480,
                                          bg=ui_skin["panel_bg"], fg=ui_skin["muted_text"])
        self.audit_explanation.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0,4))
        self.verdict_var = tk.StringVar(master=self)
        self.note_var = tk.StringVar(master=self)
        self.verdict_picker = ttk.Combobox(self, textvariable=self.verdict_var, state="readonly",
                                          values=[v.value for v in ReviewVerdict], width=17)
        self.verdict_picker.grid(row=3, column=0, sticky="w", padx=(0,6))
        self.save_button = ttk.Button(self, text="Save Review", command=self.save_review)
        self.save_button.grid(row=3, column=1, sticky="e")
        self.note_entry = ttk.Entry(self, textvariable=self.note_var)
        tk.Label(self, text=f"Note (optional, {MAX_NOTE_LENGTH} max):", bg=ui_skin["panel_bg"], fg=ui_skin["text"]).grid(row=4,column=0,sticky="w",pady=(4,0))
        self.note_entry.grid(row=4,column=1,sticky="ew",pady=(4,0))
        self.status = tk.Label(self, anchor="w", justify="left", bg=ui_skin["panel_bg"], fg=ui_skin["muted_text"], wraplength=480)
        self.status.grid(row=5,column=0,columnspan=2,sticky="ew",pady=(3,0))
        self.details_button = ttk.Button(self, text="Details", command=self._toggle_details)
        self.details_button.grid(row=6,column=0,columnspan=2,sticky="w")
        self.details_frame = tk.Frame(self, bg=ui_skin["panel_bg"])
        self.details_frame.grid(row=7,column=0,columnspan=2,sticky="ew")
        self.details_frame.columnconfigure(0,weight=1)
        self.details_text = tk.Text(self.details_frame, height=7, width=30, wrap="word", state="disabled",
                                    bg=ui_skin["panel_bg"], fg=ui_skin["text"])
        self.details_text.grid(row=0,column=0,sticky="ew")
        scroll = ttk.Scrollbar(self.details_frame,orient="vertical",command=self.details_text.yview)
        scroll.grid(row=0,column=1,sticky="ns")
        self.details_text.configure(yscrollcommand=scroll.set)
        self.details_frame.grid_remove()
        self.bind("<Configure>", self._wrap_labels)
        self.set_case(None)

    def _wrap_labels(self, event):
        for label in (self.audit_status, self.audit_explanation, self.status):
            label.configure(wraplength=max(150, event.width - 16))

    def _render_audit_status(self, case):
        status = audit_status_for_case(case)
        self.details_frame.grid_remove()
        self.details_button.configure(text="Details")
        self.details_text.configure(state="normal")
        self.details_text.delete("1.0", "end")
        self.details_text.insert("1.0", status.details if status else "")
        self.details_text.configure(state="disabled")
        if status and status.details:
            self.details_button.grid()
        else:
            self.details_button.grid_remove()
        for widget, text in ((self.audit_status, status.label if status else ""),
                             (self.audit_explanation, status.explanation if status else "")):
            widget.configure(text=text)
            if status:
                widget.grid()
            else:
                widget.grid_remove()

    def _toggle_details(self):
        if self.details_frame.winfo_manager():
            self.details_frame.grid_remove()
            self.details_button.configure(text="Details")
        else:
            self.details_frame.grid()
            self.details_button.configure(text="Hide Details")

    def set_targets(self, candidate_case, audit_cases):
        """Prefer the selected tactic; require a choice when several audits exist."""
        self.targets = ((candidate_case,) if candidate_case else ()) + tuple(audit_cases)
        self.target_picker.configure(values=[case.label for case in self.targets],
                                     state="readonly" if self.targets else "disabled")
        target = candidate_case
        if target is None and self.case is not None:
            target = next((case for case in audit_cases if case.identity == self.case.identity), None)
        if target is None and len(audit_cases) == 1:
            target = audit_cases[0]
        if target is None:
            self.target_picker.set("Choose an audit case" if self.targets else "No review target")
        else:
            self.target_picker.current(self.targets.index(target))
        if target != self.case or target is None:
            self.set_case(target)

    def _choose_target(self, event=None):
        index = self.target_picker.current()
        if index >= 0:
            self.set_case(self.targets[index])
            if self.on_select_case is not None:
                self.on_select_case(self.case)

    def set_case(self, case):
        """Selection changes clear unsaved fields; line playback leaves them alone."""
        self.case = case
        self._render_audit_status(case)
        self.verdict_var.set(""); self.note_var.set("")
        self.verdict_picker.configure(state="readonly" if case else "disabled")
        self.note_entry.configure(state="normal" if case else "disabled")
        self.save_button.configure(state="normal" if case else "disabled")
        if case is None:
            self.status.configure(text="Choose an audit case above or select a stored Tactical Moment.")
            return
        try:
            saved = self.repository.get(case)
        except ReviewStorageError as exc:
            self.status.configure(text=str(exc))
            self.save_button.configure(state="disabled")
            return
        if saved:
            self.verdict_var.set(saved.verdict.value); self.note_var.set(saved.note)
            self.status.configure(text=f"Saved: {saved.verdict.value} · {saved.reviewed_at[:16]} · {saved.case.review_set}")
        else:
            self.status.configure(text="Not reviewed · Choose a verdict and save before leaving this moment.")

    def save_review(self):
        if self.case is None:
            return
        try:
            saved = self.repository.save(self.case, ReviewVerdict(self.verdict_var.get()), self.note_var.get())
        except (ReviewStorageError, ValueError) as exc:
            self.status.configure(text=f"Review not saved: {exc}")
            return
        self.note_var.set(saved.note)
        self.status.configure(text=f"Saved: {saved.verdict.value} · {saved.reviewed_at[:16]}")
