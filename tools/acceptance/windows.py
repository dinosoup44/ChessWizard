"""Windows job ownership for the acceptance process and all launched descendants."""
from __future__ import annotations
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import time


class JobOwner:
    """Bind descendants to this console process before launching any child."""

    def __init__(self) -> None:
        """Create a kill-on-close job owned for the lifetime of this process.

        Raises:
            OSError: Mandatory Windows lifetime containment cannot be established.
        """
        class Basic(ctypes.Structure):
            _fields_ = [('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),
                        ('flags',w.DWORD),('minimum',ctypes.c_size_t),('maximum',ctypes.c_size_t),
                        ('active',w.DWORD),('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [('basic',Basic),('io',ctypes.c_ulonglong*6),('process_memory',ctypes.c_size_t),
                        ('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        self.kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        signatures = {
            'CreateJobObjectW':([ctypes.c_void_p,w.LPCWSTR],w.HANDLE),
            'SetInformationJobObject':([w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD],w.BOOL),
            'AssignProcessToJobObject':([w.HANDLE,w.HANDLE],w.BOOL),
            'GetCurrentProcess':([],w.HANDLE),
            'QueryInformationJobObject':([w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.c_void_p],w.BOOL),
            'OpenProcess':([w.DWORD,w.BOOL,w.DWORD],w.HANDLE),
            'TerminateProcess':([w.HANDLE,w.UINT],w.BOOL),
            'WaitForSingleObject':([w.HANDLE,w.DWORD],w.DWORD),
            'CloseHandle':([w.HANDLE],w.BOOL)}
        for name,(args,result) in signatures.items():
            method=getattr(self.kernel,name);method.argtypes=args;method.restype=result
        self.handle=self.kernel.CreateJobObjectW(None,None)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        limits=Extended();limits.basic.flags=0x2000
        if not self.kernel.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
            self.kernel.CloseHandle(self.handle);raise ctypes.WinError(ctypes.get_last_error())
        if not self.kernel.AssignProcessToJobObject(self.handle,self.kernel.GetCurrentProcess()):
            self.kernel.CloseHandle(self.handle);raise ctypes.WinError(ctypes.get_last_error())
        # Keep this non-inheritable handle until process death. Closing it here would
        # terminate this console too; abrupt exit must kill every acceptance child.

    def children(self) -> tuple[int, ...]:
        """Return live descendant PIDs owned by this job.

        Returns:
            PIDs excluding the wizard itself.

        Raises:
            OSError: The bounded process list cannot be queried.
        """
        for capacity in (64,512,4096):
            buffer=ctypes.create_string_buffer(8+ctypes.sizeof(ctypes.c_size_t)*capacity)
            if self.kernel.QueryInformationJobObject(self.handle,3,buffer,len(buffer),None):
                count=w.DWORD.from_buffer(buffer,4).value
                pids=(ctypes.c_size_t*count).from_buffer(buffer,8)
                return tuple(int(pid) for pid in pids if pid!=os.getpid())
            if ctypes.get_last_error()!=234:break
        raise ctypes.WinError(ctypes.get_last_error())

    def stop_children(self) -> None:
        """Stop only this run's descendants and wait for their termination.

        Raises:
            TimeoutError: A child could not be stopped; no clean shutdown is claimed.
        """
        deadline=time.monotonic()+5
        while self.children():
            for pid in self.children():
                handle=self.kernel.OpenProcess(0x100001,False,pid)
                if handle:
                    try:
                        self.kernel.TerminateProcess(handle,2)
                        self.kernel.WaitForSingleObject(handle,200)
                    finally:self.kernel.CloseHandle(handle)
            if time.monotonic()>deadline:raise TimeoutError('Owned acceptance processes did not stop')
            time.sleep(.05)

def local_app_data() -> Path:
    """Read the Windows known folder instead of trusting an environment override.

    Returns:
        Canonical Local AppData directory used by the consumer installer.

    Raises:
        OSError: Windows cannot resolve the current user's known folder.
    """
    from pathlib import Path
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.SHGetFolderPathW.argtypes = [w.HWND, ctypes.c_int, w.HANDLE, w.DWORD, w.LPWSTR]
    shell.SHGetFolderPathW.restype = ctypes.c_long
    buffer = ctypes.create_unicode_buffer(32768)
    if shell.SHGetFolderPathW(None, 28, None, 0, buffer) != 0:
        raise OSError('Windows Local AppData is unavailable')
    return Path(buffer.value)
