"""Isolated Phase 3 service/controller/UI contracts; no engine or owner fixtures."""
from dataclasses import replace
import ast
import json
from pathlib import Path
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch
import chess
from chesswizard_plugin_api import PositionContext
from merlin_ui.plugin_manager import PluginManager, PluginTrustDialog
from merlin_ui.game_review_view import GameReviewView
from plugin_manager_controller import DisplayedPosition, PluginManagerController
from plugin_models import CompatibilityCode, DiscoverySnapshot, PluginLimits, RuntimeState
from plugin_presentation import TRUST_DISCLOSURE, present_plugin
from plugin_service import PluginService
from plugin_runtime import PluginWorkerError
from support.plugin_fixture import PluginFixture
from support.plugin_wheels import FEN, GOOD_CODE, PLUGIN_ID, make_wheel

POSITION = DisplayedPosition(FEN, 1)


def wait_controller(controller, position=POSITION, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        controller.poll(position)
        if not controller.control_busy and not controller.invocation_busy:
            return
        time.sleep(.01)
    raise AssertionError("Controller did not finish within its bounded test deadline")


class ManagerControllerTests(PluginFixture):
    def controller(self):
        value = PluginManagerController(lambda: self.service)
        self.addCleanup(value.close)
        value.refresh()
        wait_controller(value)
        return value

    def test_empty_and_latest_rescan_without_startup_worker(self):
        factory = MagicMock(return_value=self.service)
        value = PluginManagerController(factory)
        self.addCleanup(value.close)
        factory.assert_not_called()
        value.refresh(); wait_controller(value)
        self.assertFalse(value.rows)
        self.assertIn("No plugins", value.message)
        self.install()
        value.refresh(); wait_controller(value)
        self.assertEqual(value.rows[0].values[4:6], ("Disabled", "Needs approval"))
        self.assertTrue(value.rows[0].needs_approval)

    def test_enable_disable_run_and_no_chess_data_writes(self):
        self.install()
        value = self.controller()
        value.set_enabled(value.rows[0], True)
        wait_controller(value)
        self.assertFalse(value.rows[0].can_run)
        value.set_enabled(value.rows[0], True, acknowledged=True)
        wait_controller(value)
        self.assertEqual(value.rows[0].values[5], "Ready")
        state_before = (self.repository.root / "state.json").read_bytes()
        value.run(value.rows[0], POSITION); wait_controller(value)
        self.assertIn("Material Inventory", value.result)
        self.assertIn("e1 white king", value.result)
        self.assertEqual((self.repository.root / "state.json").read_bytes(), state_before)
        value.set_enabled(value.rows[0], False); wait_controller(value)
        self.assertEqual(value.rows[0].values[5], "Disabled")
        self.assertFalse(value.rows[0].can_run)
        self.assertFalse(value.run(value.rows[0], POSITION))

    def test_changed_artifact_cannot_inherit_open_dialog_approval(self):
        self.install()
        value = self.controller(); original = value.rows[0]
        self.service.replace(PLUGIN_ID, make_wheel(self.root, code=GOOD_CODE+"\n# changed artifact\n"))
        value.set_enabled(original, True, acknowledged=True); wait_controller(value)
        self.assertTrue(value.rows[0].needs_approval)
        self.assertFalse(value.rows[0].view.requested.enabled)
        self.assertFalse(value.rows[0].can_run)

    def test_duplicate_and_incompatible_presentation(self):
        self.install(); view = self.service.scan().plugins[0]
        incompatible = replace(view, compatibility=CompatibilityCode.API,
            descriptor=replace(view.descriptor, compatible=False), reason="Unsupported plugin API version")
        row = present_plugin(incompatible)
        self.assertEqual(row.values[5], "Incompatible")
        self.assertIn("Unsupported plugin API", row.details)
        self.assertFalse(row.can_enable)
        self.publish_collision()
        value = self.controller()
        self.assertEqual([r.values[5] for r in value.rows], ["Conflict", "Conflict"])

    def test_stale_result_ignored_even_after_navigation_away_and_back(self):
        self.install(); self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        value = self.controller()
        value.run(value.rows[0], POSITION)
        value.observe_position(DisplayedPosition("8/8/4k3/8/8/4K3/8/8 b - - 0 1", 2))
        returned = DisplayedPosition(FEN, 3)
        wait_controller(value, returned)
        self.assertEqual(value.result, "")
        self.assertIn("discarded", value.message)

    def test_no_position_no_worker_and_prior_result_clears(self):
        self.install(); self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        value = self.controller()
        with patch.object(self.service, "analyze") as analyze:
            self.assertFalse(value.run(value.rows[0], None))
            analyze.assert_not_called()
        value.result = "prior facts"
        value.observe_position(None)
        value.observe_position(POSITION)
        self.assertEqual(value.result, "")

    def test_disable_is_nonblocking_and_cancels_hung_plugin(self):
        self.install(code="import time\ntime.sleep(60)\n"+GOOD_CODE)
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        value = self.controller(); value.run(value.rows[0], POSITION)
        time.sleep(.2)
        before = time.monotonic()
        self.assertTrue(value.set_enabled(value.rows[0], False))
        self.assertLess(time.monotonic()-before, .2)
        wait_controller(value)
        self.assertFalse(value.rows[0].view.requested.enabled)
        self.assertFalse(value.result)
        self.assertFalse(self.service.supervisor.running(value.rows[0].view.installed.installation_id))

    def test_worker_crash_and_bad_facts_are_safe_and_other_plugins_remain(self):
        for code in ("import os\nos._exit(7)\n", GOOD_CODE.replace("return MaterialFacts(", "raise ValueError('private context must not show'); return MaterialFacts(")):
            with self.subTest(code=code[:20]):
                if self.repository.read().installations:
                    self.service.replace(PLUGIN_ID, make_wheel(self.root, code=code))
                else:
                    self.install(code=code)
                self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
                value = PluginManagerController(lambda: self.service)
                value.refresh(); wait_controller(value)
                value.run(value.rows[0], POSITION); wait_controller(value)
                self.assertEqual(value.rows[0].values[5], "Failed")
                self.assertNotIn("private context", value.message + value.rows[0].details)
                self.assertFalse(value.result)

    def test_core_validation_failure_is_failed_not_facts(self):
        self.install(code=GOOD_CODE.replace("context.request_id, context.fen", "context.request_id, 'bad'"))
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        value = self.controller(); value.run(value.rows[0], POSITION); wait_controller(value)
        self.assertEqual(value.rows[0].values[5], "Failed")
        self.assertFalse(value.result)

    def test_corrupt_state_is_bounded_and_preserved(self):
        self.repository.root.mkdir(parents=True)
        (self.repository.root / "state.json").write_text("broken private context", encoding="utf-8")
        value = self.controller()
        self.assertFalse(value.rows)
        self.assertIn("recovery", value.message)
        self.assertNotIn("private context", value.message)
        self.assertEqual((self.repository.root / "state.json").read_text(), "broken private context")

    def test_diagnostics_do_not_render_stored_free_text(self):
        self.install(); receipt = self.receipt()
        self.service.diagnostics.record(receipt, "invoke", "timeout", "ignored")
        path = self.repository.root / "diagnostics/events.json"
        rows = json.loads(path.read_text()); rows[0]['message'] = "private FEN traceback " * 100
        rows[0]['error_type'] = "timeout"
        path.write_text(json.dumps(rows))
        records = self.service.diagnostics.read(receipt)
        self.assertEqual(records[0].message, "The worker exceeded its time limit.")
        self.assertNotIn("private", present_plugin(self.service.scan().plugins[0], records).details)
        path.write_bytes(b'x' * (self.service.limits.max_diagnostics * (self.service.limits.max_diagnostic_message + 1024)+1))
        self.assertEqual(self.service.diagnostics.read(receipt), ())

    def test_no_retry_storm_after_factory_failure(self):
        factory = MagicMock(side_effect=ValueError("private path"))
        value = PluginManagerController(factory)
        self.addCleanup(value.close)
        value.refresh(); wait_controller(value)
        for _ in range(100): value.poll(None)
        self.assertEqual(factory.call_count, 1)
        self.assertNotIn("private path", value.message)


    def test_metadata_timeout_does_not_hide_healthy_installation(self):
        self.install()
        self.service.install(make_wheel(self.root, plugin_id="org.example.second"))
        from plugin_service import inspect_installation
        def inspect(repository, receipt, supervisor, limits):
            if receipt.plugin_id == PLUGIN_ID:
                raise PluginWorkerError("discovery", "timeout", "safe timeout")
            return inspect_installation(repository, receipt, supervisor, limits)
        with patch("plugin_service.inspect_installation", side_effect=inspect):
            value = self.controller()
        self.assertEqual(len(value.rows), 2)
        self.assertEqual([row.values[5] for row in value.rows], ["Failed", "Needs approval"])
        self.assertIn("time limit", value.rows[0].details)

    def test_incompatible_real_metadata_survives_rescan(self):
        self.install()
        from plugin_compatibility import current_versions
        # Replay a host upgrade/downgrade compatibility decision in its metadata helper.
        from plugin_discovery import discover
        descriptor = discover(self.repository.location(self.receipt().installation_id),
            replace(current_versions(), api="0.9.0"))
        with patch("plugin_service.inspect_installation", return_value=descriptor):
            value = self.controller()
        self.assertEqual(value.rows[0].values[5], "Incompatible")
        self.assertFalse(value.rows[0].can_enable)
        self.assertIn("SDK dependency", value.rows[0].details)

    def test_close_during_pending_discovery_never_schedules_invocation(self):
        entered, release = threading.Event(), threading.Event()
        def factory():
            entered.set(); release.wait(2); return self.service
        value=PluginManagerController(factory)
        value.refresh(); self.assertTrue(entered.wait(1))
        before=time.monotonic(); value.close()
        self.assertLess(time.monotonic()-before,.2)
        release.set(); time.sleep(.1)
        self.assertFalse(value.refresh())


class ManagerUITests(PluginFixture):
    def setUp(self):
        super().setUp()
        self.tk = tk.Tk()
        self.addCleanup(self.tk.destroy)
        self.position = POSITION
        self.windows = []

    def manager(self):
        controller = PluginManagerController(lambda: self.service)
        ui = PluginManager(self.tk, lambda: self.position, controller)
        self.windows.append(ui)
        self.addCleanup(ui.close)
        self.pump(lambda: not controller.control_busy)
        return ui

    def pump(self, condition, timeout=8):
        deadline = time.monotonic()+timeout
        while time.monotonic()<deadline:
            self.tk.update()
            if condition(): return
            time.sleep(.01)
        self.fail("UI operation exceeded bounded deadline")

    def test_empty_manager_no_position_run_disabled(self):
        self.position = None
        ui = self.manager()
        self.assertFalse(ui.tree.get_children())
        self.assertTrue(ui.run_button.instate(['disabled']))
        self.assertIn("Open a game", ui.position_label['text'])

    def test_trust_cancel_acknowledgement_enable_and_disable(self):
        self.install(); ui = self.manager()
        ui.enable_button.invoke(); self.tk.update()
        dialog = ui._trust
        self.assertIn(TRUST_DISCLOSURE, dialog.disclosure.get('1.0','end'))
        self.assertFalse(dialog.acknowledged.get())
        self.assertTrue(dialog.approve_button.instate(['disabled']))
        dialog._finish(False)
        self.assertFalse(self.repository.read().requested[PLUGIN_ID].enabled)
        ui.enable_button.invoke(); dialog = ui._trust
        dialog.checkbox.invoke(); dialog.approve_button.invoke()
        self.pump(lambda: not ui.controller.control_busy)
        self.assertEqual(ui.controller.rows[0].values[5], 'Ready')
        ui.run_button.invoke()
        self.pump(lambda: not ui.controller.invocation_busy and not ui.controller.control_busy)
        self.assertIn('Material Inventory',ui.result_text.get('1.0','end'))
        ui.disable_button.invoke()
        self.pump(lambda: not ui.controller.control_busy)
        self.assertEqual(ui.controller.rows[0].values[5], 'Disabled')

    def test_metadata_deadline_and_hung_import_leave_tk_responsive(self):
        self.install(code="import time\ntime.sleep(60)\n"+GOOD_CODE)
        self.service.limits = replace(self.service.limits, import_timeout_seconds=.5)
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        ui = self.manager()
        heartbeat = []
        ui.run_button.invoke()
        self.tk.after(30, lambda: heartbeat.append(True))
        self.pump(lambda: bool(heartbeat),timeout=.5)
        self.pump(lambda: not ui.controller.invocation_busy and not ui.controller.control_busy)
        self.assertEqual(ui.controller.rows[0].values[5], 'Failed')
        calls=[]
        original=self.service.scan
        def delayed():
            calls.append(threading.get_ident()); time.sleep(.35); return original()
        with patch.object(self.service,'scan',side_effect=delayed):
            ui.refresh_button.invoke()
            heartbeat.clear(); self.tk.after(30, lambda: heartbeat.append(True))
            self.pump(lambda: bool(heartbeat),timeout=.25)
            self.assertTrue(ui.controller.control_busy)
            self.pump(lambda: not ui.controller.control_busy)
        self.assertNotEqual(calls[0], threading.get_ident())

    def test_position_change_clears_displayed_facts(self):
        self.install(); self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        ui = self.manager(); ui.run_button.invoke()
        self.pump(lambda: not ui.controller.invocation_busy and not ui.controller.control_busy)
        self.position = DisplayedPosition(FEN, 3)
        self.pump(lambda: not ui.result_text.get('1.0','end').strip())

    def test_100_125_150_layout_no_resize_loop_or_clipped_actions(self):
        self.install()
        for scale in (1, 1.25, 1.5):
            with self.subTest(scale=scale):
                self.tk.tk.call('tk','scaling',96/72*scale)
                import tkinter.font as tkfont
                for name in tkfont.names(self.tk):
                    font=tkfont.nametofont(name,self.tk)
                    font.configure(size=font.cget('size'))
                ui = self.manager(); ui.window.update()
                dimensions=[]
                for _ in range(5):
                    self.tk.update(); dimensions.append((ui.window.winfo_width(),ui.window.winfo_height()))
                self.assertEqual(len(set(dimensions)),1)
                for button in (ui.enable_button,ui.disable_button,ui.refresh_button,ui.details_button,ui.run_button,ui.status):
                    self.assertGreater(button.winfo_height(),10*scale)
                    self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),ui.window.winfo_rootx()+ui.window.winfo_width())
                    self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),ui.window.winfo_rooty()+ui.window.winfo_height())
                dialog=PluginTrustDialog(ui.window,ui.controller.rows[0],lambda approved:None)
                self.tk.update()
                self.assertLessEqual(dialog.approve_button.winfo_rooty()+dialog.approve_button.winfo_height(),dialog.window.winfo_rooty()+dialog.window.winfo_height())
                self.assertLessEqual(dialog.checkbox.winfo_rootx()+dialog.checkbox.winfo_width(),dialog.window.winfo_rootx()+dialog.window.winfo_width())
                self.assertGreater(dialog.disclosure.winfo_height(),120*scale)
                dialog._finish(False)
                ui.close()
                # Each manager owns a service lifetime; reopening uses a new supervisor.
                self.service=PluginService(self.profile)

    def test_view_and_controller_have_no_subprocess_or_chess_storage_logic(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('merlin_ui/plugin_manager.py','plugin_manager_controller.py','plugin_presentation.py'):
            source=(root/name).read_text(encoding='utf-8')
            tree=ast.parse(source)
            imports={node.names[0].name if isinstance(node,ast.Import) else node.module for node in ast.walk(tree) if isinstance(node,(ast.Import,ast.ImportFrom))}
            self.assertFalse(imports & {'sqlite3','subprocess','plugin_process','plugin_repository'})
            self.assertNotIn('state.json',source)
            self.assertNotIn('Popen',source)
            if not name.startswith('merlin_ui'):
                self.assertFalse(any(item.startswith('tkinter') for item in imports if item))

    def test_game_review_handoff_returns_displayed_board_not_actual_game_anchor(self):
        review=object.__new__(GameReviewView)
        review.current_game={'game_id':1}; review._plugin_position_revision=4
        board=chess.Board(); board.push_uci('e2e4')
        review.board_widget=MagicMock(board=board)
        self.assertEqual(review.plugin_current_position(),DisplayedPosition(board.fen(),4))
        review.current_game=None
        self.assertIsNone(review.plugin_current_position())


class ReviewPluginIntegrationTests(unittest.TestCase):
    def test_menu_navigation_revision_and_readonly_game_database(self):
        from contextlib import closing
        import hashlib
        import sqlite3
        import tempfile
        from tests.test_game_review_tactics import fixture_db
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"synthetic-review.db"
            with closing(fixture_db()) as source, closing(sqlite3.connect(path)) as target:
                source.backup(target)
            before=hashlib.sha256(path.read_bytes()).hexdigest()
            root=tk.Tk()
            review=GameReviewView(root,path)
            try:
                current=review.plugin_current_position()
                review.next_move(); review.previous_move()
                returned=review.plugin_current_position()
                self.assertEqual(current.fen,returned.fen)
                self.assertGreater(returned.revision,current.revision)
                with patch("merlin_ui.plugin_manager.PluginManager") as manager:
                    review.open_plugins()
                    manager.assert_called_once_with(root,review.plugin_current_position)
                    review.open_plugins()
                    manager.assert_called_once()
                    manager.return_value.window.lift.assert_called_once()
                self.assertEqual(review.connection.total_changes,0)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
            finally:
                review.close()
