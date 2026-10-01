"""Owned process trees. A stdin gate prevents children escaping before job assignment."""
from __future__ import annotations

import os
import json
from pathlib import Path
import signal
import subprocess
import sys


def batch_command(launcher: Path, runner: Path, *, system_root: Path | None = None):
    """cmd parses this twice (python.bat uses CALL). Never pass sample arguments here."""
    for path in (launcher, runner):
        if any(char in str(path) for char in '\"%!^&|<>\r\n'):
            raise ValueError("Batch launcher/runner paths cannot contain cmd expansion or control characters.")
    cmd = (system_root or Path(os.environ["SystemRoot"])) / "System32" / "cmd.exe"
    # Explicit CreateProcess command line: preserve cmd's outer quote pair with /S /C.
    return f'"{cmd}" /D /V:OFF /S /C ""{launcher}" -B -u "{runner}""'


class FileLease:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("Another Welding-Agent process owns the simulator runtime.") from None

    def close(self):
        if self.file.closed:
            return
        if os.name == "nt":
            import msvcrt
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        self.file.close()


class WindowsJob:
    """Kill-on-close job covers descendants, including a backend crash/reload."""
    def __init__(self, process):
        import ctypes as c
        from ctypes import wintypes as w

        class Basic(c.Structure):
            _fields_ = [("process_time", c.c_int64), ("job_time", c.c_int64),
                        ("flags", w.DWORD), ("min_ws", c.c_size_t), ("max_ws", c.c_size_t),
                        ("active", w.DWORD), ("affinity", c.c_size_t),
                        ("priority", w.DWORD), ("scheduling", w.DWORD)]

        class Counters(c.Structure):
            _fields_ = [(name, c.c_uint64) for name in ("ro", "wo", "oo", "rb", "wb", "ob")]

        class Limits(c.Structure):
            _fields_ = [("basic", Basic), ("io", Counters), ("process_memory", c.c_size_t),
                        ("job_memory", c.c_size_t), ("peak_process", c.c_size_t), ("peak_job", c.c_size_t)]

        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = w.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        self.kernel.SetInformationJobObject.restype = w.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = w.BOOL
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.CloseHandle.restype = w.BOOL
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise c.WinError(c.get_last_error())
        limits = Limits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (not self.kernel.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits))
                or not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle))):
            error = c.WinError(c.get_last_error())
            self.close()
            raise error

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class OwnedProcess:
    def __init__(self, process, job=None):
        self.process, self.job = process, job
        self.stdout = process.stdout
        self.pid = process.pid

    def poll(self):
        return self.process.poll()

    def stop(self):
        if self.job:
            self.job.close()
        elif os.name != "nt":
            # Only this launcher's new session/process group, never discovered PIDs.
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif self.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)


class ProcessLauncher:
    def launch(self, python: Path, root: Path, script: str, arguments: list[str], *, legacy_prediction=None, current_prediction=None):
        if script not in {"run_welding_simulator.py", "run_welding_sample.py"}:
            raise ValueError("Script is not allowlisted")
        return self._launch(python, root, dict(mode="script", script=str(root / script),
                                              arguments=arguments, legacy_prediction=legacy_prediction,
                                              current_prediction=current_prediction))

    def probe(self, launcher: Path, root: Path):
        return self._launch(launcher, root, dict(mode="probe"))

    def _launch(self, launcher: Path, root: Path, manifest: dict):
        runner = Path(__file__).parents[1] / "simulator_runner.py"
        bootstrap = runner.with_name("simulator_bootstrap.py")
        env = os.environ.copy()
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        env["WELD_SIM_RUN_MANIFEST"] = json.dumps(manifest, ensure_ascii=True)
        if launcher.suffix.lower() in {".bat", ".cmd"}:
            if os.name != "nt":
                raise ValueError("Batch launchers require Windows")
            command = batch_command(launcher, runner)
            # python.bat's documented override must not accidentally select Anaconda/base.
            env.pop("PYTHONEXE", None)
        else:
            command = [str(launcher), "-B", "-u", str(runner)]
        env["WELD_SIM_LAUNCH_COMMAND"] = json.dumps(command, ensure_ascii=True)
        if os.name == "nt":
            compat = str(Path(__file__).parents[1] / "simulator_compat")
            env["PYTHONPATH"] = compat + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        process = subprocess.Popen(
            # This lightweight backend-Python gate owns the entire cmd -> kit tree
            # before any external batch setup code is allowed to execute.
            [sys.executable, "-B", "-u", str(bootstrap)],
            cwd=root, env=env, shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        owned = OwnedProcess(process)
        try:
            if os.name == "nt":
                owned.job = WindowsJob(process)
            process.stdin.write("START\n")
            process.stdin.flush()
            process.stdin.close()
            return owned
        except BaseException:
            owned.stop()
            process.stdout.close()
            raise
