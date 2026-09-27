"""Restrained read-only Tk console; services own queries, diagnostics and export."""
from merlin_ui.information_panel import style_information
from dataclasses import replace
from datetime import datetime
from functools import partial
import json
import queue
import threading
import tkinter as tk
from merlin_ui.notebook import MerlinNotebook
from tkinter import ttk, filedialog
from tkinter.scrolledtext import ScrolledText
from admin_service import AdminService
from chesswizard_version import window_title
from merlin_ui.startup import prepare_database
from merlin_ui.appearance import DEFAULT_UI_SKIN
from theme_core.active import get_active_theme_service

SECTIONS = ("Overview","Analysis","Analyzers","Engine","Data / Storage","Diagnostics","Settings")


def display(value):
    return "Unavailable" if value is None else str(value)


def byte_size(value):
    return "Unavailable" if value is None else f"{value:,} bytes ({value/1048576:.2f} MiB)"


class AdminConsole:
    def __init__(self, root, service=None):
        self.root = root
        self.service = service if service is not None else AdminService()
        self.snapshot = None
        self.closed = False
        self.busy = False
        self.results = queue.SimpleQueue()
        self.theme_window = None
        self.reset_window = None
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.title(window_title("Admin Console"))
        root.geometry("1080x780")
        root.minsize(820,580)
        root.configure(bg=DEFAULT_UI_SKIN["window_bg"])
        self.frame = ttk.Frame(root,padding=14)
        self.frame.pack(fill="both",expand=True)
        ttk.Label(self.frame,text="ChessWizard Admin",font=("Segoe UI",18,"bold")).pack(anchor="w")
        self.theme_label = tk.StringVar(root)
        ttk.Label(self.frame,textvariable=self.theme_label).pack(anchor="w",pady=(2,8))
        bar = ttk.Frame(self.frame);bar.pack(fill="x")
        self.buttons = []
        for label, callback in (("Refresh Status",lambda:self.load(False)),):
            button=ttk.Button(bar,text=label,command=callback);button.pack(side="left",padx=(0,7))
            self.buttons.append(button)
        self.status=tk.StringVar(root,value="Reading current system state...")
        ttk.Label(self.frame,textvariable=self.status,wraplength=1000).pack(anchor="w",pady=8)
        self.notebook=MerlinNotebook(self.frame);self.notebook.pack(fill="both",expand=True)
        self.pages={}
        self.preset=tk.StringVar(root,value="normal")
        for name in SECTIONS:
            page=ttk.Frame(self.notebook,padding=8)
            self.notebook.add(page,text=name)
            if name=="Analysis":
                ttk.Label(page,text="Inspect a built-in preset (read-only; does not activate it)").pack(anchor="w")
                self.preset_picker=ttk.Combobox(page,textvariable=self.preset,state="readonly")
                self.preset_picker.pack(anchor="w",pady=6)
                self.preset_picker.bind("<<ComboboxSelected>>",lambda event:self.render_analysis())
            if name == "Data / Storage":
                self.reset_button = ttk.Button(page, text="Reset Chess Data...", command=self.open_reset)
                self.reset_button.pack(anchor="w", pady=(0,8))
                self.buttons.append(self.reset_button)
            if name == "Diagnostics":
                diagnostics = ttk.Frame(page)
                diagnostics.pack(fill="x",pady=(0,8))
                for label, callback in (("Run Diagnostics",lambda:self.load(True)),("Check Stockfish",self.probe),("Export Diagnostic Report",self.export)):
                    button = ttk.Button(diagnostics,text=label,command=callback)
                    button.pack(side="left",padx=(0,8))
                    self.buttons.append(button)
            text=ScrolledText(page,wrap="word",font=("Consolas",11),padx=12,pady=12,
                              bg=DEFAULT_UI_SKIN["panel_bg"],fg=DEFAULT_UI_SKIN["text"],relief="flat")
            style_information(text)
            text.pack(fill="both",expand=True);text.configure(state="disabled")
            self.pages[name]=text
        self.notebook.bind("<<NotebookTabChanged>>",lambda event:self.render() if self.snapshot else None)
        self.unsubscribe=self.service.themes.subscribe(self.theme_changed)
        self.theme_changed(self.service.themes.current)
        root.bind("<Destroy>",self.destroyed,add="+")
        root.bind("<FocusIn>",self.focused,add="+")
        self.poll_id=root.after(80,self.poll)
        self.load(False)

    def close(self):
        from merlin_ui.data_management_events import operation_busy
        if operation_busy(self.service.database_path):
            self.status.set("Wait for the data operation to finish before closing.")
            return
        self.root.destroy()

    def open_reset(self):
        if self.reset_window is not None and self.reset_window.winfo_exists():
            self.reset_window.lift()
            return
        from merlin_ui.manage_data_dialog import ResetChessDataDialog
        self.reset_window = tk.Toplevel(self.root)
        self.reset_dialog = ResetChessDataDialog(self.reset_window, self.service.database_path,
                                                 on_complete=lambda: self.load(False))

    def theme_changed(self, resolution):
        self.theme_label.set("Appearance: "+resolution.loaded.theme.name+
                             (" (default fallback)" if resolution.error else ""))

    def focused(self,event):
        if event.widget==self.root:
            self.service.themes.refresh()

    def destroyed(self,event):
        if event.widget==self.root:
            self.closed=True
            self.unsubscribe()
            self.root.after_cancel(self.poll_id)

    def _start(self, action, operation):
        if self.closed or self.busy:
            return
        self.busy=True
        for button in self.buttons:button.configure(state="disabled")
        self.status.set(action)
        results = self.results
        def work():
            try:results.put((operation(),None))
            except Exception as error:results.put((None,type(error).__name__+": "+str(error)))
        threading.Thread(target=work,daemon=True).start()

    def load(self, diagnostics=False):
        self._start("Running read-only diagnostics..." if diagnostics else "Reading current system state...",
                    partial(self.service.snapshot,diagnostics=diagnostics))

    def probe(self):
        if self.snapshot is None:
            return
        self._start("Testing UCI readiness (no chess search)...",self.service.test_engine)

    def poll(self):
        if self.closed:return
        try:
            value,error=self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy=False
            for button in self.buttons:button.configure(state="normal")
            if error:
                self.status.set("Unable to complete: "+error)
            else:
                from admin_models import EngineStatus
                if isinstance(value,EngineStatus):
                    self.snapshot=replace(self.snapshot,engine=value)
                else:
                    self.snapshot=value
                self.render()
                self.status.set("Read-only snapshot: "+self.snapshot.captured_at+
                                " | Engine test: "+self.snapshot.engine.diagnostic)
        self.poll_id=self.root.after(80,self.poll)

    def write(self, page, lines):
        widget=self.pages[page];widget.configure(state="normal")
        widget.delete("1.0","end");widget.insert("1.0","\n".join(lines));widget.configure(state="disabled")

    def render(self):
        s=self.snapshot;db=s.database;e=s.engine
        health=f"quick_check: {db.quick_check}; foreign-key violations: {display(db.foreign_key_violations)}"
        self.write("Overview",[
            "Build/version: "+s.build["release_version"],
            "Source fingerprint (selected modules): "+s.build["source_fingerprint"],
            "Database: "+db.path, "Accessible: "+str(db.available),
            f"SQLite schema_version: {display(db.schema_version)} | user_version: {display(db.user_version)}",
            "Database size: "+byte_size(db.size_bytes),health,"",
            *[name+": "+display(db.counts.get(name)) for name in ("games","moves","tactic_candidates","tactic_occurrences","training_attempts","engine_position_cache","engine_candidate_line_cache")],
            "", "Active theme ID: "+s.application["theme_resolved_id"],
            "Stockfish: "+("Found (presence only)" if e.found else "Missing"),
            "No live scheduler or running-analysis state is available."])
        self.preset_picker.configure(values=list(s.profiles["presets"]))
        self.render_analysis()
        lines=["CENTRAL CRAWLER REGISTRATIONS","Maturity is not inferred from candidate counts or registry membership.",""]
        for item in s.capabilities["registered_analyzers"]:
            lines.extend([item["name"]+" | "+item["key"],
                f"  Heavy {item['analyzer_version']} | screener {item['screener_version']} | scout {item['scout_version']}",
                "  "+item["activation"],"  Maturity: "+item["maturity"],
                "  Candidate rows (all statuses): "+display(item["candidate_rows"]),
                "  Specialist: "+item["implementation"],""])
        for item in s.capabilities["other_capabilities"]:
            lines.extend([item["name"]+" ["+item["kind"]+"]",
                "  Available: "+str(item["available"])+" | "+item["activation"],
                "  Version: "+item["version"],"  "+item["status"],"  "+item.get("description",""),"  Source: "+item["source"],""])
        lines.extend(["OPTIONAL WORKFLOWS (not global activation)",
                      json.dumps(s.capabilities["candidate_verifiers"],indent=2),
                      json.dumps(s.capabilities["opt_in_discovery_workflows"],indent=2)])
        self.write("Analyzers",lines)
        self.write("Engine",["Configured executable: "+e.path,
            "Found: "+str(e.found),"Executable size: "+byte_size(e.size_bytes),
            "Configured/cache identity version: "+e.configured_version,
            "Reported UCI name: "+display(e.reported_name),"Test result: "+e.diagnostic,e.error,"",
            "Test Engine sends only uci, isready and quit, with a five-second timeout.",
            "No position/go commands, searches, production cache access or analyzer calls.",
            "Existing position-cache profiles:",json.dumps(s.profiles["position_cache_profiles"],indent=2)])
        self.write("Data / Storage",[
            "Database: "+byte_size(db.size_bytes),
            f"Pages: {display(db.page_count)} | page size: {display(db.page_size)} | journal: {display(db.journal_mode)}",
            "", "TABLE ROWS (coverage rows are not distinct moves)",
            *[name+": "+display(count) for name,count in db.counts.items()],
            "", "ALLOCATED TABLE + INDEX BYTES (dbstat, when available)",
            *[name+": "+byte_size(size) for name,size in db.allocated_bytes.items()],
            "", "CACHE TEXT/BLOB CONTENT BYTES (Run Diagnostics; not total disk footprint)",
            *[name+": "+byte_size(db.cache_payload_bytes.get(name)) for name in ("engine_position_cache","engine_candidate_line_cache")],
            "Excludes SQLite record/index/page overhead and free space; no payloads are exported.",
            "", "OCCURRENCE STORAGE",json.dumps(db.occurrence,indent=2),
            "", "Reset Chess Data removes all chess history and caches only after an exact preview and confirmation."])
        self.write("Diagnostics",[
            "Version: "+s.build["release_version"],health,"Python: "+s.build["python"],"SQLite library: "+s.build["sqlite"],
            "Snapshot time: "+s.captured_at,"Database: "+db.path,
            "", "Observed path availability/writability hints (no test files created)",
            json.dumps({k:s.application[k] for k in ("project","application_data","settings_path","theme_repository")},indent=2),
            "Settings validation: "+(s.application["settings_error"] or "ok"),
            "Theme validation: "+(s.application["theme_error"] or "ok"),
            "", "Read/query errors:",*(db.errors or ("None",)),
            "", "Export contains aggregate counts, versions, health and necessary local paths.",
            "It excludes raw games/FENs/moves, candidate IDs, usernames, credentials, cache payloads and theme contents.",
            "Review paths before sharing an export. Nothing is uploaded."])
        self.write("Settings",[
            "Existing application settings (read-only here):",
            json.dumps(s.application["settings"],indent=2),
            "Requested theme: "+s.application["theme_requested_id"],
            "Resolved theme: "+s.application["theme_resolved_id"],
            "", "Use View > Appearance in the application for theme changes.",
            s.profiles["selection"],s.profiles["editing"],
            "Stockfish path is the existing engine_cache constant; no unsupported path editor."])

    def render_analysis(self):
        if self.snapshot is None:return
        p=self.snapshot.profiles
        selected=p["presets"].get(self.preset.get(),p["default_model"])
        generator=selected["generator"];escalation=selected["escalation"]
        lines=["ANALYSIS PROFILE", "Preset: " + selected["label"], "",
            f"Candidate lines        {generator['candidate_line_count']}",
            f"Search depth           {generator['engine']['depth']}",
            f"Verification depth     {escalation['verification']['engine']['depth']}",
            f"Settlement window      {escalation['proof']['settlement_plies']} plies (verification)",
            f"Branch cap             {escalation['max_escalated_branches_per_candidate']}",
            f"Request cap            {escalation['max_requests_per_candidate']}",
            "",p["selection"],"", "ADVANCED READ-ONLY DETAILS", selected["profile_id"],
            "Breadth engine settings: "+json.dumps(generator["engine"],sort_keys=True),
            "Candidate lines / MultiPV: "+str(generator["candidate_line_count"]),
            "Baseline proof: "+json.dumps(selected["proof"],sort_keys=True),
            "Escalation enabled in this preset: "+str(escalation["enabled"]),
            "Verification: "+json.dumps(escalation["verification"]["engine"],sort_keys=True),
            "Verification proof: "+json.dumps(escalation["proof"],sort_keys=True),
            "Branch cap: "+str(escalation["max_escalated_branches_per_candidate"]),
            "Request cap: "+str(escalation["max_requests_per_candidate"]),
            "Selective settlement: "+json.dumps(escalation["settlement_extension"],sort_keys=True),
            "",p["editing"],"", "PERSISTED COVERAGE BY TACTIC / STATUS / VERSION"]
        lines.extend(f"{r['analysis_type']} | {r['coverage_status']} | v{r['analyzer_version']}: {r['count']:,}" for r in self.snapshot.database.coverage)
        lines.extend(["","STORED CANDIDATE VERSIONS (not the current registry version)",
                      *[f"{r['tactic_type']} | v{r['detector_version']}: {r['count']:,}" for r in self.snapshot.database.stored_versions]])
        self.write("Analysis",lines)

    def export(self):
        if self.snapshot is None:return
        path=filedialog.asksaveasfilename(parent=self.root,title="Export diagnostic report",
            defaultextension=".json",filetypes=[("Diagnostic JSON","*.json")],
            initialfile="ChessWizard-diagnostics-"+datetime.now().strftime("%Y%m%d-%H%M%S")+".json")
        if not path:return
        try:
            self.service.export(self.snapshot,path)
            self.status.set("Exported aggregate diagnostic report: "+path)
        except (ValueError,OSError) as error:
            self.status.set("Export not written: "+str(error))



def main():
    root=tk.Tk()
    path=prepare_database(root)
    if path is None:
        return
    AdminConsole(root,AdminService(database_path=path))
    root.mainloop()
