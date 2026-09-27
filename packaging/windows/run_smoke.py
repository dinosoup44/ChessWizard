"""Run the non-shipped frozen validator using a disposable user profile."""
from pathlib import Path
import os
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import time
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]

def first_launch(executable, env, temporary):
    """Exercise the shipped entry before the diagnostic entry creates any database."""
    from chesswizard_version import DISPLAY_VERSION
    process = subprocess.Popen([str(executable)], env=env, cwd=temporary,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    user32 = ctypes.windll.user32
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    windows = []
    def inspect(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == process.pid:
            title = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, title, len(title))
            if DISPLAY_VERSION in title.value:
                windows.append((hwnd, title.value))
        return True
    callback = callback_type(inspect)
    try:
        deadline = time.monotonic() + 20
        db = Path(temporary) / "merlin.db"
        while time.monotonic() < deadline and process.poll() is None:
            user32.EnumWindows(callback, 0)
            if windows and db.is_file():
                break
            time.sleep(0.1)
        assert windows and db.is_file(), "First shipped launch failed"
        time.sleep(0.5)
        assert process.poll() is None
        user32.PostMessageW(windows[0][0], 0x0010, 0, 0)
        assert process.wait(timeout=10) == 0
        return dict(title=windows[0][1], db_bytes=db.stat().st_size,
                    sha256=hashlib.sha256(db.read_bytes()).hexdigest(), exit_code=0)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def main():
    from chesswizard_version import VERSION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", type=Path, default=ROOT / "dist" / ("ChessWizard-" + VERSION + "-rehearsal-import"))
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build/windows/pyinstaller-rehearsal-import/ChessWizard")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports/v1_post_import")
    args = parser.parse_args()
    report = args.report_dir.resolve() / "frozen_smoke.json"
    with tempfile.TemporaryDirectory(prefix="ChessWizard-frozen-") as temporary:
        temporary = Path(temporary)
        deployment = temporary / "app"
        profile = temporary / "profile"
        profile.mkdir()
        shutil.copytree(args.distribution, deployment)
        helper = deployment / "ChessWizardSmoke.exe"
        shutil.copyfile(args.build_dir / "ChessWizardSmoke.exe", helper)
        env = dict(os.environ, CHESSWIZARD_DATA_DIR=str(profile), LOCALAPPDATA=str(profile),
                   CHESSWIZARD_AUDIT_SOURCE_ROOT=str(ROOT),
                   PATH=os.environ["SystemRoot"] + "\\System32;" + os.environ["SystemRoot"])
        initial = first_launch(deployment / "ChessWizard.exe", env, str(profile))
        result = subprocess.run([str(helper), str(report)], env=env, cwd=profile,
            capture_output=True, text=True, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
        (args.report_dir / "frozen_smoke.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        if result.returncode == 0:
            data = json.loads(report.read_text())
            data["actual_executable_first_launch"] = initial
            data["main_profile_database_unchanged"] = initial["sha256"] == hashlib.sha256((profile / "merlin.db").read_bytes()).hexdigest()
            assert data["main_profile_database_unchanged"]
            data["deployment"] = "Copied frozen folder outside project; developer-tree file access blocked in validation entry"
            report.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(result.stdout, result.stderr)
        return result.returncode

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
