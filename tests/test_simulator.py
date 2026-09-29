"""Stubbed simulator contract tests: no Isaac, GPU, data or prediction loads."""
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import sys
import threading

from fastapi.testclient import TestClient
import pytest

from backend.main import create_app
from backend.orchestrator.state_machine import WorkflowError
from backend.services.simulator_client import LocalSimulatorClient, SimulatorConfig
from backend.services.simulator_process import ProcessLauncher

REQUEST_ID = "01774800000000000000_1234abcd"


class FakeProcess:
    def __init__(self, pid):
        self.pid, self.code, self.stopped = pid, None, False
        self.stdout = io.StringIO("")

    def poll(self):
        return self.code

    def stop(self):
        self.stopped = True
        self.code = self.code if self.code is not None else -1


class FakeLauncher:
    def __init__(self):
        self.calls = []
        self.processes = []
        self.options = []

    def launch(self, python, root, script, arguments, **options):
        self.calls.append((python, root, script, arguments))
        self.options.append(options)
        process = FakeProcess(500 + len(self.calls))
        self.processes.append(process)
        return process


@pytest.fixture
def bridge(tmp_path):
    root = tmp_path / "external-simulator"
    root.mkdir()
    for name in ("run_welding_simulator.py", "run_welding_sample.py"):
        (root / name).write_text("# unchanged external script", encoding="utf-8")
    data, prediction = tmp_path / "data", tmp_path / "prediction"
    data.mkdir(); prediction.mkdir()
    episode = prediction / "episode"
    episode.mkdir()
    (episode / "metadata.json").write_text(json.dumps({"episode_id": "L_PR_03_0001"}))
    config = SimulatorConfig(root=root, python=Path(sys.executable), sample_id="L_PR_03_0001",
                             data_root=data, prediction_root=prediction, runtime_dir=tmp_path / "runtime")
    client = LocalSimulatorClient(config, launcher=FakeLauncher(), clock=lambda: 100, monitor=False)
    yield client
    client.close()


def ready(bridge):
    bridge.start()
    bridge._consume_line("simulator", bridge.simulator, f"[READY] Waiting for samples in {bridge.session_dir / 'queue'}")
    assert bridge.status()["state"] == "READY"


def queued(bridge):
    ready(bridge)
    bridge.run_sample()
    bridge._consume_line("sample", bridge.sample, f"[QUEUED] {REQUEST_ID} (queued, not yet confirmed as played)")
    bridge.sample.code = 0
    assert bridge.readers_done["sample"].wait(2)


def result(bridge, state="done", artifacts=True):
    output = bridge.session_dir / "outputs" / bridge.config.sample_id / "vla_prediction" / "requests" / "unique" / "scene.usda"
    if artifacts:
        output.parent.mkdir(parents=True)
        for file in (output, output.with_suffix(".actual_weld.npz"), output.parent / "trajectory_solution.npz"):
            file.write_bytes(b"existing output")
        (output.parent / "report.json").write_text(json.dumps(dict(
            sample_id=bridge.config.sample_id, trajectory_source="vla_prediction")), encoding="utf-8")
    path = bridge.session_dir / "queue" / "results" / f"{REQUEST_ID}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(id=REQUEST_ID, sample=bridge.config.sample_id, state=state,
                                   playback_mode="model_predict", output=str(output), error="test failure")), encoding="utf-8")
    return path


def test_stopped_no_implicit_launch(bridge):
    status = bridge.status()
    assert status["state"] == "STOPPED" and status["can_start"]
    assert not status["preview_connected"] and not status["robot_execution_enabled"]
    assert bridge.launcher.calls == []


def test_start_requires_real_ready_signal_and_rejects_duplicate(bridge):
    assert bridge.start()["state"] == "STARTING"
    assert bridge.status()["state"] == "STARTING"
    with pytest.raises(WorkflowError, match="already started"):
        bridge.start()
    bridge._consume_line("simulator", bridge.simulator, "[READY] Waiting for samples in stale_queue")
    assert bridge.status()["state"] == "STARTING"
    bridge._consume_line("simulator", bridge.simulator, f"[READY] Waiting for samples in {bridge.session_dir / 'queue'}")
    assert bridge.status()["state"] == "READY"
    assert bridge.launcher.calls[0][2] == "run_welding_simulator.py"
    assert bridge.launcher.calls[0][3] == ["--queue-dir", str(bridge.session_dir / "queue")]


@pytest.mark.parametrize("state", ["STOPPED", "STARTING", "FAILED"])
def test_run_before_ready_rejected(bridge, state):
    bridge.state = state
    if state == "STARTING":
        bridge.state = "STOPPED"
        bridge.start()
    with pytest.raises(WorkflowError, match="must be READY"):
        bridge.run_sample()


def test_sample_fixed_prediction_command_and_duplicate_rejected(bridge):
    ready(bridge)
    response = bridge.run_sample()
    assert response["state"] == "RUNNING_SAMPLE"
    assert response["latest_sample"]["status"] == "PREPARING"
    python, root, script, args = bridge.launcher.calls[-1]
    assert python == bridge.config.python and root == bridge.config.root
    assert script == "run_welding_sample.py" and "--prediction" in args and "--send" in args
    assert args[args.index("--sample") + 1] == bridge.config.sample_id
    assert not Path(args[args.index("--output-dir") + 1]).is_relative_to(root)
    with pytest.raises(WorkflowError):
        bridge.run_sample()


def test_sample_success_needs_exit_response_and_artifacts(bridge):
    queued(bridge)
    assert bridge.status()["state"] == "RUNNING_SAMPLE"  # exit=0 is just queued
    result(bridge, "running")
    assert bridge.status()["latest_sample"]["status"] == "RUNNING"
    path = bridge.session_dir / "queue" / "results" / f"{REQUEST_ID}.json"
    record = json.loads(path.read_text()); record["state"] = "done"
    path.write_text(json.dumps(record))
    status = bridge.status()
    assert status["state"] == "READY" and status["latest_sample"]["status"] == "SUCCEEDED"
    assert len(status["latest_sample"]["artifacts"]) == 4
    assert bridge.sample is None and not bridge.simulator.stopped
    assert bridge.run_sample()["state"] == "RUNNING_SAMPLE"


@pytest.mark.parametrize("state,artifacts", [("failed", True), ("interrupted", True), ("done", False)])
def test_playback_failure_stops_owned_session(bridge, state, artifacts):
    queued(bridge); result(bridge, state, artifacts)
    assert bridge.status()["state"] == "FAILED"
    assert bridge.latest_sample["status"] == "FAILED"
    assert all(p.stopped for p in bridge.launcher.processes)


@pytest.mark.parametrize("code", [0, 1])
def test_sample_exit_without_queue_or_nonzero_fails(bridge, code):
    ready(bridge); bridge.run_sample()
    bridge.sample.code = code
    assert bridge.readers_done["sample"].wait(2)
    assert bridge.status()["state"] == "FAILED"


@pytest.mark.parametrize("phase", ["start", "sample"])
def test_timeouts_cancel_owned_tree(bridge, phase):
    if phase == "sample":
        queued(bridge)
    else:
        bridge.start()
    bridge.clock = lambda: 10000
    assert bridge.status()["state"] == "FAILED"
    assert "timeout" in bridge.error
    assert all(p.stopped for p in bridge.launcher.processes)


def test_unexpected_simulator_exit(bridge):
    ready(bridge)
    bridge.simulator.code = 0
    assert bridge.status()["state"] == "FAILED"
    assert "exited unexpectedly" in bridge.error


def test_stop_cancels_sample_and_restart_ignores_old_queue_and_stdout(bridge):
    queued(bridge)
    previous_process, previous_session = bridge.simulator, bridge.session_dir
    assert bridge.stop()["latest_sample"]["status"] == "CANCELLED"
    assert bridge.stop()["state"] == "STOPPED"
    bridge.start()
    assert bridge.session_dir != previous_session
    bridge._consume_line("simulator", previous_process, f"[READY] Waiting for samples in {bridge.session_dir / 'queue'}")
    assert bridge.status()["state"] == "STARTING"


def test_exclusive_ownership_across_clients(bridge):
    other = LocalSimulatorClient(bridge.config, launcher=FakeLauncher(), monitor=False)
    try:
        ready(bridge)
        with pytest.raises(WorkflowError, match="Another Welding-Agent"):
            other.start()
        other.stop()
        assert not bridge.simulator.stopped  # never stop somebody else's PID
        bridge.stop()
        assert other.start()["state"] == "STARTING"
    finally:
        other.close()


def test_launch_failure_releases_ownership(bridge):
    class BrokenLauncher:
        def launch(self, *_args):
            raise OSError("bad Python environment")
    bridge.launcher = BrokenLauncher()
    with pytest.raises(WorkflowError, match="bad Python"):
        bridge.start()
    assert bridge.state == "FAILED" and bridge.lease is None


def test_configuration_errors_do_not_break_preview(bridge):
    bridge.config = replace(bridge.config, python=None, sample_id="../../bad")
    assert not bridge.status()["configured"]
    with pytest.raises(WorkflowError, match="WELD_SIM_PYTHON"):
        bridge.start()
    app = create_app(bridge.config.runtime_dir / "preview", simulator=bridge)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.post("/api/simulator/start", json={}).status_code == 503


def test_invalid_env_timeout_reported_not_import_crash(monkeypatch):
    monkeypatch.setenv("WELD_SIM_STARTUP_TIMEOUT", "NaN")
    assert SimulatorConfig.from_env().configuration_error


@pytest.mark.parametrize("change", ["request", "sample", "mode", "output", "corrupt", "report"])
def test_untrusted_or_mismatched_result_rejected(bridge, change):
    queued(bridge); path = result(bridge)
    record = json.loads(path.read_text())
    if change == "corrupt":
        path.write_text("not json")
    elif change == "report":
        (Path(record["output"]).parent / "report.json").write_text('{}')
    else:
        key = {"request": "id", "sample": "sample", "mode": "playback_mode", "output": "output"}[change]
        record[key] = "unexpected"
        path.write_text(json.dumps(record))
    assert bridge.status()["state"] == "FAILED"


def test_bounded_logs(bridge):
    ready(bridge)
    for i in range(240):
        bridge._consume_line("simulator", bridge.simulator, str(i) + "x" * 5000)
    logs = bridge.logs()["entries"]
    assert len(logs) == 200 and all(len(row["text"]) <= 2000 for row in logs)


def test_legacy_import_is_part_of_owned_sample_process_and_uses_samples_dir(bridge):
    episode = bridge.config.prediction_root / "0000_L_PR_03_0001"
    episode.mkdir()
    (episode / "trajectory.npz").write_bytes(b"stub")
    bridge.config = replace(bridge.config, prediction_format="legacy_npz", samples_dir=bridge.config.data_root)
    ready(bridge); bridge.run_sample()
    args = bridge.launcher.calls[-1][3]
    assert "--data-root" not in args and "--samples-dir" in args
    legacy = bridge.launcher.options[-1]["legacy_prediction"]
    assert legacy["sample_id"] == "L_PR_03_0001"
    assert legacy["prediction_root"] == str(bridge.config.prediction_root)
    assert args[args.index("--prediction-root") + 1] == legacy["output_root"]
    assert Path(legacy["output_root"]).is_relative_to(bridge.session_dir)


def test_status_checks_configuration_without_launching_or_importing_isaac(bridge):
    for _ in range(3):
        diagnostic = bridge.status()["configuration_diagnostics"]
        assert diagnostic["isaac_launcher_configured"]
        assert diagnostic["isaac_import_check"]["status"] == "not_run"
    assert not bridge.launcher.calls


def test_missing_metadata_requires_explicit_legacy_mode(bridge):
    (bridge.config.prediction_root / "episode" / "metadata.json").unlink()
    assert "metadata.json is missing" in " ".join(bridge.config.sample_errors())


def test_launcher_priority_and_missing_launcher(bridge):
    bridge.config = replace(bridge.config, launcher=bridge.config.root / "missing.bat")
    assert "WELD_SIM_LAUNCHER" in " ".join(bridge.config.start_errors())
    assert bridge.config.executable != bridge.config.python


def test_api_empty_action_contract_and_lifespan_cleanup(bridge):
    with TestClient(create_app(bridge.config.runtime_dir / "storage", simulator=bridge)) as client:
        assert client.get("/api/simulator/status").json()["state"] == "STOPPED"
        for endpoint in ("start", "run-sample", "stop"):
            assert client.post(f"/api/simulator/{endpoint}", json={"command": "anything"}).status_code == 422
            assert client.post(f"/api/simulator/{endpoint}?script=anything", json={}).status_code == 400
            assert client.post(f"/api/simulator/{endpoint}", json={}, headers={"Origin": "https://untrusted.example"}).status_code == 403
        assert client.post("/api/simulator/run-sample", json={}).status_code == 409
        assert client.post("/api/simulator/start", json={}).status_code == 202
        assert client.post("/api/simulator/start", json={}).status_code == 409
        assert client.get("/api/simulator/logs").json()["entries"]
    assert bridge.closed and all(p.stopped for p in bridge.launcher.processes)


def test_real_launcher_with_lightweight_stub_and_child_cleanup(tmp_path):
    # This launches Python stub code only, never any real simulator script.
    script = tmp_path / "run_welding_simulator.py"
    script.write_text("""
import os, subprocess, sys, time
if os.name == 'nt':
    import fcntl
    a = open('test.lock', 'a')
    b = open('test.lock', 'a')
    fcntl.flock(a, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        fcntl.flock(b, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raise AssertionError('Expected exclusive lock')
    except BlockingIOError:
        pass
    fcntl.flock(a, fcntl.LOCK_UN)
    fcntl.flock(b, fcntl.LOCK_EX | fcntl.LOCK_NB)
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
print(child.pid, flush=True)
while True: time.sleep(.1)
""", encoding="utf-8")
    process = ProcessLauncher().launch(Path(sys.executable), tmp_path, script.name, [])
    lines, done = [], threading.Event()
    def read():
        for line in process.stdout:
            lines.append(line)
            if line.strip().isdigit():
                done.set()
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    child_handle = None
    try:
        assert done.wait(8), "".join(lines)
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            child_handle = kernel.OpenProcess(0x100000, False, int(next(line for line in lines if line.strip().isdigit())))
            assert child_handle
        process.stop()
        assert process.poll() is not None
        if child_handle:
            assert kernel.WaitForSingleObject(child_handle, 5000) == 0
    finally:
        process.stop()
        reader.join(timeout=3)
        process.stdout.close()
        if child_handle:
            kernel.CloseHandle(child_handle)
