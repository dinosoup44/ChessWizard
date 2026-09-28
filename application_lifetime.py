"""Windows lifetime markers shared by desktop, plugin hosts, and servicing."""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import sys

_PROCESS_HANDLES: list[int] = []


def mutex_prefix(install_root: Path) -> str:
    """Derive the same UTF-16 identity used by the Inno installer.

    Args:
        install_root: Absolute application directory, independent of profile.

    Returns:
        Cross-session Windows object prefix for this installation.
    """
    normalized = str(install_root.absolute()).rstrip("\\/").lower()
    digest = hashlib.sha256(normalized.encode("utf-16-le")).hexdigest()
    return "Global\\ChessWizard-" + digest


def windows_api() -> object:
    """Load the small, typed Win32 mutex surface without import-time effects.

    Returns:
        Configured kernel32 library.
    """
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    api.CreateMutexW.restype = wintypes.HANDLE
    api.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    api.OpenMutexW.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.ReleaseMutex.argtypes = [wintypes.HANDLE]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    return api


def retain_application_lifetime(install_root: Path | None = None) -> None:
    """Refuse startup during servicing and retain an activity handle until exit.

    The OS closes the handle after process termination, including child-host
    teardown. A gate closes the installer-check/application-start race.

    Args:
        install_root: Explicit root for tests; otherwise the frozen executable
            directory or source directory.

    Raises:
        RuntimeError: Servicing is active or the lifetime lock is unavailable.
    """
    if os.name != "nt":
        return
    root = install_root or (Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent)
    prefix, api = mutex_prefix(root), windows_api()
    gate = api.CreateMutexW(None, False, prefix + "-gate")
    if not gate:
        raise RuntimeError("Cannot establish application lifetime lock")
    acquired = False
    try:
        acquired = api.WaitForSingleObject(gate, 5000) in (0, 0x80)
        if not acquired:
            raise RuntimeError("ChessWizard servicing is busy; retry after setup finishes")
        active = api.OpenMutexW(0x100000, False, prefix + "-servicing")
        if active:
            api.CloseHandle(active)
            raise RuntimeError("ChessWizard is being installed or removed; retry after setup finishes")
        if ctypes.get_last_error() not in (0, 2):
            raise RuntimeError("Cannot check servicing lifetime lock")
        handle = api.CreateMutexW(None, False, prefix + "-activity")
        if not handle:
            raise RuntimeError("Cannot establish application activity lock")
        _PROCESS_HANDLES.append(handle)
    finally:
        if acquired:
            api.ReleaseMutex(gate)
        api.CloseHandle(gate)
