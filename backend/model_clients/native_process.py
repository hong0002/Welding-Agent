"""Bounded native CLI process tree, including its SSH descendants."""
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread

from backend.services.simulator_process import OwnedProcess, WindowsJob
from backend.model_clients.native_diagnostics import NativeDiagnostics
from backend.model_clients.native_watchdog import NativeWatchdog


def run_native(command, *, cwd, timeout, diagnostic_path=None, output_root=None, sample_id=None, watchdog_policy=None,
               preserve_openai_api_key=False):
    trace = NativeDiagnostics(diagnostic_path, output_root=output_root, sample_id=sample_id) if diagnostic_path else None
    watchdog = NativeWatchdog(timeout, watchdog_policy)
    env = os.environ.copy()
    # Preserve native API-key lookup, SSH environment, prompts and SDK retry defaults.
    # In particular, do NOT inject the Welding-Agent .env API key.
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    # Parity was verified with the native project's existing key file, not an inherited key.
    # An explicit backend-owned GPT predictor may use the native env-key contract.
    # Segment/Rough parity continues to remove inherited keys by default.
    if not preserve_openai_api_key:
        env.pop("OPENAI_API_KEY", None)
    process = subprocess.Popen(
        [sys.executable, "-B", "-u", str(Path(__file__).with_name("native_gate.py"))],
        cwd=cwd, env=env, shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        start_new_session=os.name != "nt",
    )
    owned = OwnedProcess(process)
    views = []

    def drain():
        # Never persist raw SDK errors, prompts or authentication output.
        start_of_line = True
        try:
            for chunk in iter(lambda: process.stdout.readline(8192), ""):
                if start_of_line and chunk.endswith("\n"):
                    watchdog.output(chunk)
                    if chunk.startswith("[VIEW] ") and len(views) < 16:
                        views.append(chunk[7:].strip())
                    if trace:
                        trace.output(chunk.rstrip("\r\n"))
                start_of_line = chunk.endswith("\n")
        except Exception:
            if trace:
                trace.emit("stdout_reader_failed")

    thread = Thread(target=drain, daemon=True)
    outcome = "supervisor_exception"
    try:
        if trace:
            trace.emit("process_started", pid=process.pid, timeout_seconds=timeout,
                       python=str(command[0]), gate_python=sys.executable, cwd=str(cwd),
                       unbuffered_cli="-u" in command, inherited_openai_api_key_removed=not preserve_openai_api_key)
            trace.emit("watchdog_policy", setup=watchdog.policy.setup, retrieval=watchdog.policy.retrieval,
                       per_view=watchdog.policy.model_stage, overall=timeout)
        if os.name == "nt":
            owned.job = WindowsJob(process)
            if trace:
                trace.emit("job_object_assigned")
        thread.start()
        if trace:
            trace.emit("gate_released")
        process.stdin.write(json.dumps(command, ensure_ascii=True) + "\n")
        process.stdin.flush()
        process.stdin.close()
        while True:
            if trace:
                trace.artifacts()
            # Prefer a completed process to an expired supervisor tick, as parity did.
            code = process.poll()
            if code is not None:
                break
            remaining, timeout_stage = watchdog.remaining()
            if remaining <= 0:
                outcome = "timeout"
                if trace:
                    trace.emit("timeout", watchdog_stage=timeout_stage, last_observed_phase=trace.phase,
                               last_sanitized_native_line=trace.last_native_line)
                    trace.log_native(f"[SUPERVISOR] timeout stage={timeout_stage}", supervisor=True)
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                code = process.wait(timeout=min(0.25, remaining))
                break
            except subprocess.TimeoutExpired:
                pass
        thread.join(timeout=5)
        if trace:
            trace.emit("process_exited", exit_code=code)
            trace.log_native(f"[PROCESS_EXIT] code={code}", supervisor=True)
        outcome = "process_exit"
        return code, views
    finally:
        # Keep ownership through cleanup, including timeout and successful parent exit.
        owned.stop()
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        if thread.ident:
            thread.join(timeout=5)
        process.stdout.close()
        if trace:
            trace.artifacts()
            trace.log_native(f"[CLEANUP] supervisor_returncode={process.returncode} reason={outcome}", supervisor=True)
            trace.emit("cleanup_completed", supervisor_returncode=process.returncode, termination_reason=outcome,
                       last_sanitized_native_line=trace.last_native_line, native_log_failed=trace.native_log_failed,
                       stdout_reader_alive=thread.is_alive())
