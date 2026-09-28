"""Bounded synthetic worker failures, protocol guards, cancellation and process trees."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
from chesswizard_plugin_api import PositionContext
from plugin_locking import PluginBusyError
from plugin_models import PluginLimits, RuntimeState
from plugin_process import ManagedProcess
from plugin_protocol import encode_message, validate_context
from plugin_runtime import PluginCancelledError, PluginWorkerError, host_command, run_worker
from plugin_service import PluginService
from support.plugin_fixture import PluginFixture
from support.plugin_wheels import FEN, GOOD_CODE, PACKAGE, PLUGIN_ID, make_wheel


def process_alive(pid: int) -> bool:
    """Probe only a PID created by this test without terminating arbitrary processes.

    Args:
        pid: Synthetic child process identity.

    Returns:
        Whether the owned process still runs.
    """
    if os.name == "nt":
        import _winapi
        try:
            handle = _winapi.OpenProcess(0x100000, False, pid)
        except OSError:
            return False
        try:
            return _winapi.WaitForSingleObject(handle, 0) == _winapi.WAIT_TIMEOUT
        finally:
            _winapi.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class PluginWorkerTests(PluginFixture):
    def _start_hanging_tree(self, *, timeout: float = 5.0):
        marker = self.root / "owned-pids.json"
        code = ("import subprocess, sys, os, json, time\nfrom pathlib import Path\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                f"marker=Path({str(marker)!r})\n"
                "temporary=marker.with_suffix('.tmp')\n"
                "temporary.write_text(json.dumps([os.getpid(), child.pid]))\n"
                "temporary.replace(marker)\n"
                "while True: time.sleep(0.05)\n")
        self.install(code=code)
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        self.service.limits = replace(PluginLimits(), timeout_seconds=timeout)
        errors = []
        def invoke():
            try:
                self.service.analyze(PLUGIN_ID, PositionContext("tree", FEN))
            except Exception as error:
                errors.append(error)
        thread = threading.Thread(target=invoke)
        thread.start()
        deadline = time.monotonic() + 5
        while not marker.exists() and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(marker.exists(), errors)
        pids = json.loads(marker.read_text())
        self.assertTrue(all(process_alive(pid) for pid in pids))
        return thread, errors, pids

    def _assert_tree_stopped(self, thread, errors, pids):
        thread.join(timeout=4)
        self.assertFalse(thread.is_alive())
        self.assertTrue(errors)
        deadline = time.monotonic() + 2
        while any(process_alive(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(any(process_alive(pid) for pid in pids))

    def test_disable_cancels_worker_and_descendants(self):
        thread, errors, pids = self._start_hanging_tree()
        self.assertTrue(self.service.set_enabled(PLUGIN_ID, False))
        self._assert_tree_stopped(thread, errors, pids)
        self.assertIsInstance(errors[0], PluginCancelledError)
        with patch.object(self.service.supervisor, "call", side_effect=AssertionError("disabled code must not run")):
            with self.assertRaises(ValueError):
                self.service.analyze(PLUGIN_ID, PositionContext("disabled", FEN))

    def test_timeout_cleans_worker_and_descendants(self):
        thread, errors, pids = self._start_hanging_tree(timeout=1.0)
        self._assert_tree_stopped(thread, errors, pids)
        self.assertIsInstance(errors[0], PluginWorkerError)
        self.assertEqual(errors[0].kind, "timeout")

    def test_application_close_cleans_worker_and_descendants(self):
        thread, errors, pids = self._start_hanging_tree()
        self.service.close()
        self._assert_tree_stopped(thread, errors, pids)
        self.assertTrue(self.repository.read().requested[PLUGIN_ID].enabled)

    def test_removal_cleans_worker_and_descendants(self):
        thread, errors, pids = self._start_hanging_tree()
        self.assertTrue(self.service.remove(PLUGIN_ID))
        self._assert_tree_stopped(thread, errors, pids)
        self.assertFalse(self.repository.read().installations)

    def test_replacement_cancels_old_tree_before_atomic_switch(self):
        thread, errors, pids = self._start_hanging_tree()
        old = self.receipt()
        self.service.replace(PLUGIN_ID, make_wheel(self.root))
        self._assert_tree_stopped(thread, errors, pids)
        self.assertNotEqual(self.receipt().installation_id, old.installation_id)
        self.assertFalse(self.repository.read().requested[PLUGIN_ID].enabled)

    def test_cross_process_disable_observed_without_state_lock_deadlock(self):
        thread, errors, pids = self._start_hanging_tree()
        result = subprocess.run(host_command()+["disable", PLUGIN_ID, "--profile", str(self.profile)],
                                capture_output=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stdout)
        self._assert_tree_stopped(thread, errors, pids)
        self.assertIsInstance(errors[0], PluginCancelledError)

    def test_runtime_failure_matrix_is_bounded_and_session_latched(self):
        cases = {
            "import": "raise RuntimeError('PRIVATE_CONTEXT_SECRET')",
            "system_exit": "raise SystemExit('PRIVATE_CONTEXT_SECRET')",
            "hung_import": "while True: pass",
            "hung_call": GOOD_CODE.replace("        names =", "        while True: pass\n        names ="),
            "hung_close": GOOD_CODE.replace("        pass", "        while True: pass"),
            "abnormal_exit": "import os; os._exit(17)",
            "malformed_json": "import os; os.write(1, b'not-json\\n')\n" + GOOD_CODE,
            "oversized_output": 'while True: print("x"*4096)',
            "wrong_context": GOOD_CODE.replace("MaterialFacts(context.request_id", "MaterialFacts('stale-request'"),
            "wrong_fen": GOOD_CODE.replace("context.fen, tuple(squares)", "'wrong-fen', tuple(squares)"),
            "nonfinite": GOOD_CODE.replace("sum(f.color==color and f.piece==piece for f in squares)", "float('nan')"),
            "unsupported_result": GOOD_CODE.replace("return MaterialFacts(context.request_id, context.fen, tuple(squares), counts)", "return {'arbitrary': 'object'}"),
        }
        for label, code in cases.items():
            with self.subTest(label=label):
                self.service.limits = PluginLimits()
                self.install(code=code)
                self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
                self.service.limits = replace(PluginLimits(), timeout_seconds=0.7)
                before = time.monotonic()
                with self.assertRaises((ValueError, PluginWorkerError)):
                    self.service.analyze(PLUGIN_ID, PositionContext("failure", FEN))
                self.assertLess(time.monotonic() - before, 4)
                with patch.object(self.service.supervisor, "call", side_effect=AssertionError("no automatic retry")):
                    with self.assertRaisesRegex(ValueError, "session"):
                        self.service.analyze(PLUGIN_ID, PositionContext("retry", FEN))
                diagnostics = (self.repository.root / "diagnostics/events.json").read_text()
                self.assertNotIn("PRIVATE_CONTEXT_SECRET", diagnostics)
                self.assertNotIn(FEN, diagnostics)
                self.service.remove(PLUGIN_ID)

    def test_explicit_reenable_clears_session_failure_without_import(self):
        self.install(code="raise RuntimeError('failed')")
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        with self.assertRaises(PluginWorkerError):
            self.service.analyze(PLUGIN_ID, PositionContext("fail", FEN))
        self.assertEqual(self.service.scan().plugins[0].runtime_state, RuntimeState.FAILED)
        self.service.set_enabled(PLUGIN_ID, True)
        self.assertEqual(self.service.scan().plugins[0].runtime_state, RuntimeState.READY)

    def test_unknown_contract_version_rejected_before_metadata(self):
        payload = dict(protocol_version=999, nonce="0"*32, operation="discover", site=str(self.root))
        result = subprocess.run(host_command()+["worker"], input=json.dumps(payload).encode(), capture_output=True,
                                timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 1)
        response = json.loads(result.stdout)
        self.assertEqual(response["kind"], "error")
        self.assertEqual(response["phase"], "discovery")

    def test_unknown_response_identity_is_not_accepted(self):
        frame = json.dumps(dict(protocol_version=999, nonce="wrong", kind="result", payload={})).encode()+b"\n"
        code = "import os; os.write(1, "+repr(frame)+")\n"+GOOD_CODE
        self.install(code=code)
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        with self.assertRaises(PluginWorkerError) as error:
            self.service.analyze(PLUGIN_ID, PositionContext("bad-protocol", FEN))
        self.assertEqual(error.exception.kind, "protocol_error")

    def test_metadata_activity_does_not_claim_implementation_running(self):
        self.install()
        identity = self.receipt().installation_id
        entered, release = threading.Event(), threading.Event()
        errors = []
        def fake_worker(*args, **kwargs):
            entered.set()
            if not release.wait(timeout=3):
                raise RuntimeError("Synthetic synchronization timed out")
            return {}
        def invoke(operation):
            try:
                self.service.supervisor.call(identity, {"operation": operation}, self.service.limits)
            except Exception as error:
                errors.append(error)
        for operation, expected in (("discover", False), ("analyze", True)):
            entered.clear(); release.clear()
            with patch("plugin_runtime.run_worker", side_effect=fake_worker):
                thread = threading.Thread(target=invoke, args=(operation,))
                thread.start()
                try:
                    self.assertTrue(entered.wait(timeout=2))
                    self.assertEqual(self.service.supervisor.running(identity), expected)
                finally:
                    release.set(); thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertFalse(self.service.supervisor.running(identity))
        self.assertEqual(errors, [])

    def test_disabled_intent_during_drain_is_never_effectively_enabled(self):
        self.install()
        with patch.object(self.service.supervisor, "running", return_value=True):
            view = self.service.list_plugins()[0]
        self.assertFalse(view["enabled"])
        self.assertFalse(view["effective_enabled"])

    def test_worker_count_bound_shared_across_service_instances(self):
        self.install()
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        other = PluginService(self.profile)
        self.assertIs(other.supervisor, self.service.supervisor)
        with self.service.supervisor._slot(self.service.limits), other.supervisor._slot(other.limits):
            with self.assertRaises(PluginBusyError):
                self.service.analyze(PLUGIN_ID, PositionContext("busy", FEN))
        self.assertIsNone(self.service.supervisor.failure(self.receipt().installation_id))
        self.assertEqual(len(self.service.analyze(PLUGIN_ID, PositionContext("free", FEN)).squares), 32)

    def test_diagnostics_bounded_and_repeated_error_does_not_churn(self):
        self.install()
        receipt = self.receipt()
        diagnostics = self.service.diagnostics
        diagnostics.limits = replace(PluginLimits(), max_diagnostics=4, max_diagnostic_message=80)
        for index in range(12):
            diagnostics.record(receipt, "invoke", "synthetic_"+str(index), "Safe core explanation "+"x"*1000)
        path = self.repository.root / "diagnostics/events.json"
        rows = json.loads(path.read_text())
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(len(row["message"]) <= 80 for row in rows))
        before = path.read_bytes(), path.stat().st_mtime_ns
        diagnostics.record(receipt, "invoke", "synthetic_11", "Safe core explanation "+"x"*1000)
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))

    def test_metadata_helper_deadline_is_separate_and_bounded(self):
        helper = self.root / "hung-metadata.py"
        helper.write_text("import time; time.sleep(60)\n")
        limits = replace(PluginLimits(), metadata_timeout_seconds=0.3)
        before = time.monotonic()
        with patch("plugin_runtime.host_command", return_value=[sys.executable, "-B", str(helper)]):
            with self.assertRaises(PluginWorkerError) as error:
                run_worker({"operation": "discover", "site": str(self.root)}, limits)
        self.assertEqual(error.exception.phase, "discovery")
        self.assertEqual(error.exception.kind, "timeout")
        self.assertLess(time.monotonic()-before, 3)

    def test_frozen_desktop_uses_separate_console_host(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(self.root / "ChessWizard.exe")):
            self.assertEqual(host_command(), [str(self.root / "ChessWizardPluginHost.exe")])

    def test_normal_worker_completion_terminates_remaining_descendants(self):
        marker = self.root / "success-child.json"
        prefix = ("import subprocess, sys, json\nfrom pathlib import Path\n"
                  "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
                  f"Path({str(marker)!r}).write_text(json.dumps(child.pid))\n")
        self.install(code=prefix+GOOD_CODE)
        self.service.set_enabled(PLUGIN_ID, True, acknowledge_trust=True)
        self.assertEqual(len(self.service.analyze(PLUGIN_ID, PositionContext("normal", FEN)).squares), 32)
        self.assertFalse(process_alive(json.loads(marker.read_text())))

    def test_context_and_finite_transport_guards(self):
        for context in (PositionContext("x"*129, FEN), PositionContext("id", "bad-fen"), PositionContext("", FEN)):
            with self.assertRaises(ValueError):
                validate_context(context)
        with self.assertRaises(ValueError):
            encode_message({"number": float("inf")}, 1000)
        with self.assertRaises(ValueError):
            encode_message({"data": "x"*1000}, 100)

    @unittest.skipUnless(os.name == "nt", "Windows kill-on-parent-close contract")
    def test_abnormal_controller_exit_closes_job_and_kills_worker(self):
        marker = self.root / "parent-death.json"
        child_code = "import time; time.sleep(60)"
        controller = ("import os, sys, json\nfrom pathlib import Path\nfrom plugin_process import ManagedProcess\n"
                      f"p=ManagedProcess([sys.executable,'-c',{child_code!r}],dict(os.environ),Path(sys.executable).parent)\n"
                      f"Path({str(marker)!r}).write_text(json.dumps(p.pid))\n"
                      "os._exit(7)\n")
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        result = subprocess.run([sys.executable, "-B", "-c", controller], cwd=self.root, env=environment,
                                capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 7, result.stderr)
        pid = json.loads(marker.read_text())
        deadline = time.monotonic() + 2
        while process_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(process_alive(pid))
