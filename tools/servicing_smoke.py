"""Bounded health probes for a disposable frozen desktop; no engine workload."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
import time
from application_lifetime import mutex_prefix, windows_api
from servicing_paths import FIXTURE_MARKER, validate_roots


def activity_present(app: Path) -> bool:
    """Read a Windows activity marker without taking ownership of it.

    Args:
        app: Explicit installed application directory.

    Returns:
        Whether a desktop or host retains a lifetime marker.
    """
    api=windows_api()
    handle=api.OpenMutexW(0x100000,False,mutex_prefix(app)+'-activity')
    if handle: api.CloseHandle(handle)
    return bool(handle)


def launch_desktop(root: Path, environment: dict[str, str], version: str) -> dict:
    """Launch only a marked test app and close its own responsive window cleanly.

    Args:
        root: Marked disposable servicing root.
        environment: Explicit isolated profile and Windows-only search path.
        version: Expected synthetic display version.

    Returns:
        Window title, normal exit, and released-lifetime observations.

    Raises:
        AssertionError: Desktop fails startup or does not close within the bound.
    """
    app, profile=validate_roots(root/'app',root/'profile',root/FIXTURE_MARKER)
    if environment.get('CHESSWIZARD_DATA_DIR')!=str(profile):
        raise ValueError('Desktop probe requires its disposable profile override')
    startup=subprocess.STARTUPINFO()
    startup.dwFlags=subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow=0
    process=subprocess.Popen([str(app/'ChessWizard.exe')],cwd=root,env=environment,startupinfo=startup)
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user.EnumWindows.argtypes=[callback_type,wintypes.LPARAM]
    windows=[]
    def visit(handle: int, unused: int) -> bool:
        pid=wintypes.DWORD()
        user.GetWindowThreadProcessId(handle,ctypes.byref(pid))
        if pid.value==process.pid:
            text=ctypes.create_unicode_buffer(512)
            user.GetWindowTextW(handle,text,512)
            if 'ChessWizard' in text.value: windows.append((handle,text.value))
        return True
    callback=callback_type(visit)
    try:
        deadline=time.monotonic()+25
        while time.monotonic()<deadline and process.poll() is None:
            windows.clear();user.EnumWindows(callback,0)
            if any(version in title for _,title in windows) and (profile/'merlin.db').is_file(): break
            time.sleep(0.1)
        assert process.poll() is None and windows and any(version in title for _,title in windows), ('desktop startup failed',process.poll(),windows)
        assert activity_present(app), 'Desktop failed lifetime participation'
        title=next(title for _,title in windows if version in title)
        for handle,_ in windows: user.PostMessageW(handle,0x10,0,0)
        assert process.wait(timeout=15)==0
        assert not activity_present(app), 'Desktop/host activity survived exit'
        return {'title':title,'normal_exit':True,'lifetime_released':True}
    finally:
        # A failed probe only cleans up the exact process it started in this fixture.
        if process.poll() is None:
            process.terminate();process.wait(timeout=10)
