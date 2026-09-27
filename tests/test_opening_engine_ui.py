"""On-demand, stale-worker and non-mutating board projection contracts on temp books."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import threading
import time
import tkinter as tk
from unittest.mock import patch
from analysis_control import AnalysisCancelled
from analysis_settings import BUILTIN_PROFILES
from opening_book_reader import open_readonly_library
from opening_engine_models import OpeningEngineAnalysis
from merlin_ui.opening_book_studio import OpeningBookStudio
from tests.test_opening_engine import engine_lines
from tests.test_opening_studio_workflow import WorkspaceFixture


class FakeAdvice:
    def __init__(self):
        self.calls=[]
        self.entered=threading.Event()
        self.release=threading.Event();self.release.set()
        self.fail=False
        self.ignore_cancel=False

    def analyze_opening_position(self, anchor, profile, *, refresh=False, cancel=None):
        self.calls.append((anchor,profile,refresh,cancel));self.entered.set()
        if not self.release.wait(3):raise RuntimeError('Test worker timed out')
        if cancel.is_set() and not self.ignore_cancel:raise AnalysisCancelled()
        if self.fail:raise RuntimeError('Fixture engine failure')
        settings=BUILTIN_PROFILES[profile]
        return OpeningEngineAnalysis(anchor,settings,engine_lines(anchor.fen,settings.generator),
            '2026-09-26T12:00:00+00:00',False,1,0,.01)


class OpeningEngineUITests(WorkspaceFixture):
    def setUp(self):
        super().setUp()
        source=self.authored_file(titles=('French','London'))
        preview=self.library.preview_import(source)
        self.items=self.workspace.import_selected(source,preview,(1,2))
        self.fake=FakeAdvice()
        self.root=tk.Tk();self.root.withdraw()
        self.studio=OpeningBookStudio(self.root,engine_service=self.fake)
        self.panel=self.studio.engine_panel
        self.addCleanup(self.close)
        self.studio.load_book(self.items[0]);self.root.update()

    def close(self):
        self.fake.release.set()
        self.panel.close()
        if self.panel.worker:self.panel.worker.join(4)
        if self.studio.repository:self.studio.repository.close()
        self.root.destroy()

    def finish(self):
        deadline=time.monotonic()+4
        while self.panel.busy and time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.root.update()
        self.assertFalse(self.panel.busy)

    def analyze(self):
        self.panel.start_analysis();self.finish()
        self.assertIsNotNone(self.panel.analysis)
        return self.panel.analysis

    def select_line(self, rank):
        self.panel.lines.selection_set(str(rank));self.panel.select_line();self.root.update()

    def test_navigation_and_tabs_are_idle_then_preview_keeps_authored_anchor(self):
        s=self.studio;p=self.panel
        self.assertEqual([s.tabs.tab(t,'text') for t in s.tabs.tabs()],['Branch Browser','Stockfish Lines','How To'])
        s.tabs.select(p);self.root.update()
        p.profile.set('Deep');s.load_book(self.items[1]);s.load_book(self.items[0])
        path=next(path for path in s.paths.values() if len(path)==3)
        s.session.go_to(path);s.render();p.profile.set('Normal');self.root.update()
        self.assertEqual(self.fake.calls,[])
        before=s.repository.path.read_bytes();anchor=s.engine_anchor();history=s.session.history
        self.analyze();self.assertEqual(len(p.lines.get_children()),3)
        self.select_line(2);self.assertTrue(s.engine_preview)
        p.step(1);self.assertEqual(p.playback.ply,1)
        self.assertIn('STOCKFISH PREVIEW',s.position_label.cget('text'))
        self.assertEqual(s.engine_anchor(),anchor);self.assertEqual(s.session.history,history)
        p.step(100);end=p.playback;p.step(1);self.assertEqual(p.playback,end)
        p.step(-100);p.step(-1);self.assertEqual(p.playback.ply,0)
        p.return_to_anchor();self.assertFalse(s.engine_preview)
        self.assertEqual(s.session.board.fen(),anchor.fen)
        self.assertEqual(s.repository.path.read_bytes(),before)

    def test_add_whole_selected_line_requires_confirmation_at_selected_saved_position(self):
        s=self.studio;p=self.panel
        path=next(path for path in s.paths.values() if len(path)==5)
        s.session.go_to(path);s.render()
        result=self.analyze();self.select_line(1)
        before=s.repository.path.read_bytes()
        with patch('merlin_ui.opening_engine_panel.confirm_engine_variation',return_value=None):p.add_variation()
        self.assertEqual(s.repository.path.read_bytes(),before)
        with patch('merlin_ui.opening_engine_panel.confirm_engine_variation',return_value='Owner chosen variation') as confirm:
            p.add_variation();confirm.assert_called_once()
        snapshot=s.repository.snapshot(s.session.book_id)
        edge=next(m for m in snapshot.moves if m.variation_name=='Owner chosen variation')
        self.assertEqual(edge.from_position_id,result.anchor.position_id)
        self.assertEqual(edge.move_uci,result.lines.lines[0].move_uci)
        self.assertEqual(edge.weight,50);self.assertFalse(edge.preferred)
        self.assertIsNone(p.analysis)
        self.assertEqual(s.session.history[:s.session.cursor],path)

    def test_late_worker_after_branch_and_book_switch_is_discarded(self):
        self.fake.release.clear();self.fake.ignore_cancel=True
        self.panel.start_analysis();self.assertTrue(self.fake.entered.wait(1))
        old=self.panel.anchor
        path=next(p for p in self.studio.paths.values() if len(p)==2)
        self.studio.session.go_to(path);self.studio.render()
        self.assertTrue(self.fake.calls[-1][3].is_set())
        self.studio.load_book(self.items[1])
        self.assertNotEqual(self.panel.anchor,old)
        before=self.studio.repository.path.read_bytes()
        self.fake.release.set();self.finish()
        self.assertIsNone(self.panel.analysis);self.assertEqual(self.panel.lines.get_children(),())
        self.assertEqual(str(self.panel.add_button.cget('state')),'disabled')
        self.assertEqual(self.studio.repository.path.read_bytes(),before)
        self.assertEqual(len(self.fake.calls),1)

    def test_stop_and_engine_error_keep_studio_usable_and_old_complete_advice(self):
        p=self.panel;s=self.studio;result=self.analyze();before=s.repository.path.read_bytes()
        self.fake.release.clear();p.start_analysis(deeper=True)
        self.assertEqual(p.analysis,result)
        p.stop();self.fake.release.set();self.finish()
        self.assertEqual(p.analysis,result);self.assertIn('Stopped',p.status.get())
        self.fake.fail=True;p.start_analysis(refresh=True);self.finish()
        self.assertIn('Fixture engine failure',p.status.get());self.assertEqual(p.analysis,result)
        self.assertEqual(s.repository.path.read_bytes(),before)
        self.fake.fail=False;p.start_analysis();self.finish()
        self.assertEqual(len(p.lines.get_children()),5)

    def test_draft_unsaved_and_readonly_external_authoring_guards(self):
        s=self.studio;p=self.panel
        s.stage('e4');self.root.update()
        self.assertIsNone(p.anchor);p.start_analysis();self.assertEqual(self.fake.calls,[])
        self.assertIn('UNSAVED',s.position_label.cget('text'))
        s.session.discard();s.dirty=False;s.render()
        s.new_book();self.assertIsNone(p.anchor)
        p.start_analysis();self.assertEqual(self.fake.calls,[])
        external=self.authored_file('readonly.cwbook',('Read only',))
        s.use_repository(open_readonly_library(external),book_id=1)
        before=external.read_bytes();self.analyze();self.select_line(1)
        self.assertFalse(p.editable);self.assertEqual(str(p.add_button.cget('state')),'disabled')
        p.add_variation();self.assertEqual(external.read_bytes(),before)

    def test_close_cancels_owned_worker(self):
        self.fake.release.clear();self.panel.start_analysis()
        self.assertTrue(self.fake.entered.wait(1));self.panel.close()
        self.assertTrue(self.panel.cancel.is_set());self.fake.release.set()
        self.panel.worker.join(3);self.assertFalse(self.panel.worker.is_alive())

    def test_core_imports_without_tkinter(self):
        code="import sys;sys.modules['tkinter']=None;import opening_engine_models,opening_engine_service,opening_engine_authoring,opening_engine_presentation,opening_book_line"
        result=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_advisory_tab_has_space_and_restores_authoring_at_common_scales(self):
        s=self.studio;p=self.panel
        self.root.attributes('-alpha',0)
        self.root.deiconify()
        for scale in (1,1.25,1.5):
            with self.subTest(scale=scale):
                self.root.tk.call('tk','scaling',96*scale/72)
                self.root.geometry('1280x860')
                s.tabs.select(p);self.root.update()
                self.assertTrue(all(not panel.winfo_ismapped() for panel in s.authoring_panels))
                self.assertTrue(p.analyze_button.winfo_ismapped())
                self.assertGreater(p.lines.winfo_height(),100)
                for widget in (p.analyze_button,p.stop_button,p.add_button,p.return_button):
                    self.assertGreater(widget.winfo_width(),20)
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),p.winfo_rooty()+p.winfo_height())
                s.tabs.select(s.browser_frame);self.root.update()
                self.assertTrue(all(panel.winfo_ismapped() for panel in s.authoring_panels))
        self.assertEqual(self.fake.calls,[])

    def test_confirmation_dialog_contains_destination_full_line_and_custom_name(self):
        from tkinter import ttk
        from merlin_ui.opening_engine_dialog import confirm_engine_variation
        result=self.analyze()
        plan=self.studio.engine_authoring().preview_add(result,1,self.studio.engine_anchor())
        inspected=[]
        def descendants(widget):
            yield widget
            for child in widget.winfo_children():yield from descendants(child)
        def accept_fixture_dialog():
            window=next(w for w in self.panel.winfo_children() if isinstance(w,tk.Toplevel))
            widgets=list(descendants(window))
            labels=[w.cget('text') for w in widgets if isinstance(w,ttk.Label)]
            text=next(w for w in widgets if isinstance(w,tk.Text)).get('1.0','end')
            entry=next(w for w in widgets if isinstance(w,ttk.Entry))
            entry.insert(0,'Explicit fixture name')
            inspected.append((labels,text))
            next(w for w in widgets if isinstance(w,ttk.Button) and w.cget('text')=='Add Variation').invoke()
        before=self.studio.repository.path.read_bytes()
        self.root.after(10,accept_fixture_dialog)
        name=confirm_engine_variation(self.panel,result,1,plan)
        self.assertEqual(name,'Explicit fixture name')
        self.assertIn(result.anchor.label,inspected[0][0][0])
        self.assertIn(result.lines.lines[0].pv_san[-1],inspected[0][1])
        self.assertTrue(any('new move edges' in text for text in inspected[0][0]))
        self.assertEqual(self.studio.repository.path.read_bytes(),before)
