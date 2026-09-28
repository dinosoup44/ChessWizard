"""Platform process lifetime controls; Windows jobs own workers and descendants."""
from __future__ import annotations
import ctypes
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import BinaryIO


class ManagedProcess:
    """Start an isolated worker whose descendants share its managed lifetime.

    Args:
        command: Absolute executable and bounded arguments.
        environment: Explicit child environment.
        cwd: Working directory outside plugin implementation directories.

    Windows workers start suspended and join a kill-on-close job before any code
    runs. This controls lifetime, not the permissions of trusted plugin code.
    """

    def __init__(self, command: list[str], environment: dict[str, str], cwd: Path) -> None:
        """Create pipes and establish lifetime ownership before starting execution.

        Args:
            command: Absolute executable and arguments.
            environment: Child environment.
            cwd: Explicit working directory.

        Raises:
            OSError: Process creation or mandatory job assignment fails.
        """
        self._closed = False
        self._job = None
        self._handle = None
        self._process = None
        if os.name == "nt":
            self._windows_start(command, environment, cwd)
        else:
            self._process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE, cwd=cwd, env=environment,
                                             start_new_session=True)
            self.pid = self._process.pid
            self.stdin = self._process.stdin
            self.stdout = self._process.stdout
            self.stderr = self._process.stderr

    def _windows_start(self, command: list[str], environment: dict[str, str], cwd: Path) -> None:
        import _winapi
        import msvcrt
        from ctypes import wintypes as w

        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                        ("flags", w.DWORD), ("minimum", ctypes.c_size_t), ("maximum", ctypes.c_size_t),
                        ("active", w.DWORD), ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", ctypes.c_ulonglong * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        kernel.CreateJobObjectW.restype = w.HANDLE
        kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        kernel.SetInformationJobObject.restype = w.BOOL
        kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        kernel.AssignProcessToJobObject.restype = w.BOOL
        kernel.ResumeThread.argtypes = [w.HANDLE]
        kernel.ResumeThread.restype = w.DWORD
        kernel.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        kernel.TerminateJobObject.restype = w.BOOL
        self._kernel = kernel
        job = kernel.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        self._job = job
        handles, descriptors = [], []
        try:
            limits = Extended()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
            if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            child_in, parent_in = os.pipe()
            descriptors.extend((child_in, parent_in))
            parent_out, child_out = os.pipe()
            descriptors.extend((parent_out, child_out))
            parent_err, child_err = os.pipe()
            descriptors.extend((parent_err, child_err))
            startup = subprocess.STARTUPINFO()
            startup.dwFlags = subprocess.STARTF_USESTDHANDLES
            handles = [msvcrt.get_osfhandle(fd) for fd in (child_in, child_out, child_err)]
            for handle in handles:
                os.set_handle_inheritable(handle, True)
            startup.hStdInput, startup.hStdOutput, startup.hStdError = handles
            startup.lpAttributeList = {"handle_list": handles}
            process, thread, pid, _ = _winapi.CreateProcess(
                command[0], subprocess.list2cmdline(command), None, None, True,
                subprocess.CREATE_NO_WINDOW | 0x00000004, environment, str(cwd), startup)
            self._handle, self.pid = process, pid
            try:
                if not kernel.AssignProcessToJobObject(job, process):
                    raise ctypes.WinError(ctypes.get_last_error())
                if kernel.ResumeThread(thread) == 0xFFFFFFFF:
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                _winapi.CloseHandle(thread)
            for fd in (child_in, child_out, child_err):
                os.close(fd); descriptors.remove(fd)
            self.stdin: BinaryIO = os.fdopen(parent_in, "wb", buffering=0)
            descriptors.remove(parent_in)
            self.stdout: BinaryIO = os.fdopen(parent_out, "rb", buffering=0)
            descriptors.remove(parent_out)
            self.stderr: BinaryIO = os.fdopen(parent_err, "rb", buffering=0)
            descriptors.remove(parent_err)
        except BaseException:
            if self._handle:
                _winapi.TerminateProcess(self._handle, 1)
                _winapi.CloseHandle(self._handle)
                self._handle = None
            _winapi.CloseHandle(job)
            self._job = None
            raise
        finally:
            for fd in descriptors:
                os.close(fd)

    def poll(self) -> int | None:
        """Read the worker exit code without waiting.

        Returns:
            Exit code, or None while the worker is active.
        """
        if self._process is not None:
            return self._process.poll()
        import _winapi
        if _winapi.WaitForSingleObject(self._handle, 0) == _winapi.WAIT_TIMEOUT:
            return None
        return _winapi.GetExitCodeProcess(self._handle)

    def terminate_tree(self) -> None:
        """Terminate the entire owned process tree, including surviving children."""
        if self._job is not None:
            self._kernel.TerminateJobObject(self._job, 1)
        elif self._process is not None:
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def wait(self, timeout: float) -> int:
        """Wait a bounded duration for process termination.

        Args:
            timeout: Maximum seconds to wait.

        Returns:
            Process exit code.

        Raises:
            TimeoutError: Process remains active beyond the deadline.
        """
        deadline = time.monotonic() + timeout
        while (code := self.poll()) is None:
            if time.monotonic() >= deadline:
                raise TimeoutError("Worker termination deadline exceeded")
            time.sleep(0.01)
        return code

    def close(self) -> None:
        """Kill remaining descendants and release process/job handles once."""
        if self._closed:
            return
        self._closed = True
        self.terminate_tree()
        self.wait(1.0)
        if os.name == "nt":
            import _winapi
            if self._job is not None:
                _winapi.CloseHandle(self._job); self._job = None
            if self._handle is not None:
                _winapi.CloseHandle(self._handle); self._handle = None
