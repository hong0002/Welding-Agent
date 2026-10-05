"""Launcher/monitor for the existing sample queue; never accepts a web trajectory."""
from __future__ import annotations
from backend.services.project_paths import native_parent

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from typing import Protocol
from uuid import uuid4

from backend.orchestrator.state_machine import WorkflowError
from backend.services.simulator_process import FileLease, ProcessLauncher, batch_command
from backend.services.legacy_prediction_adapter import find_legacy_prediction
from backend.services.environment import backend_env_values

PROJECT = Path(__file__).resolve().parents[2]


def timestamp():
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SimulatorConfig:
    root: Path
    python: Path | None
    sample_id: str
    data_root: Path
    prediction_root: Path
    runtime_dir: Path
    startup_timeout: float = 180
    sample_timeout: float = 300
    duration: float = 15
    configuration_error: str | None = None
    launcher: Path | None = None
    samples_dir: Path | None = None
    prediction_format: str = "metadata"

    @property
    def executable(self):
        return self.launcher or self.python

    @classmethod
    def from_env(cls, env_file=None):
        error = None
        try:
            values = backend_env_values(env_file)
        except (OSError, UnicodeError):
            values = {}
            error = 'Simulator root .env must be readable UTF-8.'
        def setting(key, default=None):
            return os.getenv(key) or values.get(key) or default
        root = Path(setting("WELD_SIM_ROOT", native_parent(PROJECT) / "simulator")).resolve()
        workspace = root.parent.parent
        try:
            numbers = [float(setting(key, default)) for key, default in (
                ("WELD_SIM_STARTUP_TIMEOUT", "180"), ("WELD_SIM_SAMPLE_TIMEOUT", "300"),
                ("WELD_SIM_DURATION", "15"))]
            if any(not math.isfinite(n) or not 0 < n <= 3600 for n in numbers):
                raise ValueError()
        except ValueError:
            numbers = [180, 300, 15]
            error = "Simulator timeouts/duration must be finite and within (0, 3600] seconds."
        return cls(
            root=root, python=Path(setting("WELD_SIM_PYTHON")).resolve() if setting("WELD_SIM_PYTHON") else None,
            sample_id=setting("WELD_SIM_SAMPLE_ID", ""),
            data_root=Path(setting("WELD_SIM_DATA_ROOT", workspace / "42.용접로봇 행동 생성 데이터" / "3.개방데이터")).resolve(),
            prediction_root=Path(setting("WELD_SIM_PREDICTION_ROOT", workspace / "welding_validation_all")).resolve(),
            runtime_dir=PROJECT / ".cache" / "simulator", startup_timeout=numbers[0],
            sample_timeout=numbers[1], duration=numbers[2], configuration_error=error,
            launcher=Path(setting("WELD_SIM_LAUNCHER")).resolve() if setting("WELD_SIM_LAUNCHER") else None,
            samples_dir=Path(setting("WELD_SIM_SAMPLES_DIR")).resolve() if setting("WELD_SIM_SAMPLES_DIR") else None,
            prediction_format=setting("WELD_SIM_PREDICTION_FORMAT", "metadata"),
        )

    def start_errors(self):
        errors = [self.configuration_error] if self.configuration_error else []
        if self.executable is None or not self.executable.is_file():
            errors.append("Set WELD_SIM_LAUNCHER to the working Isaac launcher (.bat/.cmd/.exe); WELD_SIM_PYTHON is a legacy fallback.")
        elif os.name == "nt":
            if self.executable.suffix.lower() not in {".exe", ".bat", ".cmd"}:
                errors.append("Windows simulator launcher must be .exe, .bat or .cmd.")
            elif self.executable.suffix.lower() in {".bat", ".cmd"}:
                try:
                    batch_command(self.executable, PROJECT / "backend" / "simulator_runner.py")
                except ValueError as exc:
                    errors.append(str(exc))
        for name in ("run_welding_simulator.py", "run_welding_sample.py"):
            if not (self.root / name).is_file():
                errors.append(f"Missing simulator script: {name}. Check WELD_SIM_ROOT.")
        if self.runtime_dir.resolve().is_relative_to(self.root.resolve()):
            errors.append("Runtime outputs must be outside the read-only simulator repository.")
        return errors

    def sample_errors(self):
        errors = []
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", self.sample_id):
            errors.append("Set WELD_SIM_SAMPLE_ID to an existing VLA sample ID (letters, numbers, '_' or '-').")
        if self.samples_dir is not None and not self.samples_dir.is_dir():
            errors.append("WELD_SIM_SAMPLES_DIR does not exist.")
        elif self.samples_dir is None and not self.data_root.is_dir():
            errors.append("Sample data is missing. Set WELD_SIM_DATA_ROOT to the existing 3.개방데이터 directory.")
        if not self.prediction_root.is_dir():
            errors.append("VLA exports are missing. Set WELD_SIM_PREDICTION_ROOT to the existing prediction directory.")
        elif self.prediction_format == "legacy_npz":
            try:
                find_legacy_prediction(self.prediction_root, self.sample_id)
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
            if self.samples_dir is None:
                errors.append("Legacy prediction import requires WELD_SIM_SAMPLES_DIR (extracted H5 directory).")
        elif self.prediction_format == "metadata":
            if not any(self.prediction_root.glob("*/metadata.json")):
                errors.append("Prediction metadata.json is missing. Use WELD_SIM_PREDICTION_FORMAT=legacy_npz only for a verified legacy export.")
        else:
            errors.append("WELD_SIM_PREDICTION_FORMAT must be metadata or legacy_npz.")
        return errors


class SimulatorClient(Protocol):
    def status(self) -> dict: ...
    def start(self) -> dict: ...
    def run_sample(self) -> dict: ...
    def run_current_vla_prediction(self, package) -> dict: ...
    def stop(self) -> dict: ...
    def logs(self) -> dict: ...
    def close(self) -> None: ...


class LocalSimulatorClient:
    def __init__(self, config: SimulatorConfig | None = None, *, launcher=None, clock=time.monotonic, monitor=True):
        self.config = config or SimulatorConfig.from_env()
        self.launcher = launcher or ProcessLauncher()
        self.clock, self.monitor_enabled = clock, monitor
        self.lock = threading.RLock()
        self.state = "STOPPED"
        self.error = None
        self.latest_sample = None
        self.simulator = self.sample = None
        self.lease = None
        self.session_dir = None
        self.ready_seen = False
        self.started_at = self.sample_started_at = 0.0
        self.readers_done = {}
        self.entries = deque(maxlen=200)
        self.sequence = 0
        self.wake = threading.Event()
        self.monitor_thread = None
        self.closed = False

    def _log(self, source, text):
        self.sequence += 1
        self.entries.append(dict(id=self.sequence, at=timestamp(), source=source, text=text[:2000]))

    def _consume_line(self, source, process, line):
        with self.lock:
            # Ignore delayed stdout from a previous run, including its READY/QUEUED.
            if process is not (self.simulator if source == "simulator" else self.sample):
                return
            line = line.rstrip("\r\n")
            self._log(source, line)
            if source == "simulator" and self.state == "STARTING":
                self.ready_seen |= line == f"[READY] Waiting for samples in {self.session_dir / 'queue'}"
            if source == "sample" and self.latest_sample:
                match = re.fullmatch(r"\[QUEUED\] ([0-9]{20}_[a-f0-9]{8}) \(queued, not yet confirmed as played\)", line)
                if match:
                    self.latest_sample.update(request_id=match[1], status="QUEUED")

    def _read(self, source, process, finished):
        try:
            while line := process.stdout.readline(4096):
                self._consume_line(source, process, line)
        finally:
            process.stdout.close()
            finished.set()

    def _launch(self, source, script, args, *, legacy_prediction=None, current_prediction=None):
        options = {"legacy_prediction": legacy_prediction} if legacy_prediction else {}
        if current_prediction:
            options["current_prediction"] = current_prediction
        process = self.launcher.launch(self.config.executable, self.config.root, script, args, **options)
        if source == "simulator":
            self.simulator = process
        else:
            self.sample = process
        finished = threading.Event()
        self.readers_done[source] = finished
        threading.Thread(target=self._read, args=(source, process, finished), daemon=True).start()
        self._log("bridge", f"Started {script}, owned PID {process.pid}")
        return process

    def _release(self):
        errors = []
        for name in ("sample", "simulator"):
            process = getattr(self, name)
            if process is not None:
                try:
                    process.stop()
                    setattr(self, name, None)
                except Exception as exc:
                    errors.append(f"Could not stop owned {name}: {exc}")
        if not errors and self.lease:
            self.lease.close()
            self.lease = None
        if errors:
            raise RuntimeError("; ".join(errors))

    def _fail(self, message):
        self.state, self.error = "FAILED", message
        if self.latest_sample and self.latest_sample["status"] in {"PREPARING", "QUEUED", "RUNNING"}:
            self.latest_sample.update(status="FAILED", error=message, finished_at=timestamp())
        self._log("bridge", message)
        try:
            self._release()
        except Exception as exc:
            self.error += f"; {exc}"
            self._log("bridge", str(exc))

    def tick(self):
        """One monitor iteration, also used by tests without real processes or timers."""
        with self.lock:
            try:
                self._tick()
            except Exception as exc:
                self._fail(f"Simulator monitor failed: {type(exc).__name__}: {exc}")

    def _tick(self):
        if self.state not in {"STARTING", "READY", "RUNNING_SAMPLE"}:
            return
        code = self.simulator.poll()
        if code is not None:
            self._fail(f"Simulator exited unexpectedly (exit code {code}). See simulator logs.")
            return
        if self.state == "STARTING":
            if self.clock() - self.started_at > self.config.startup_timeout:
                self._fail("Simulator readiness timeout: no matching [READY] signal.")
            elif self.ready_seen:
                self.state = "READY"
                self._log("bridge", "READY confirmed by the current simulator's queue-ready message.")
        elif self.state == "RUNNING_SAMPLE":
            if self.clock() - self.sample_started_at > self.config.sample_timeout:
                self._fail("Sample timeout. Owned simulator stopped to cancel pending playback.")
                return
            code = self.sample.poll()
            if code is not None:
                self.latest_sample["exit_code"] = code
                if code != 0:
                    self._fail(f"Sample preparation failed (exit code {code}). See sample logs.")
                    return
            if not self.readers_done["sample"].is_set() or code is None:
                return
            request_id = self.latest_sample["request_id"]
            if not request_id:
                self._fail("Sample exited without an explicit [QUEUED] request ID.")
                return
            result_path = self.session_dir / "queue" / "results" / f"{request_id}.json"
            if not result_path.is_file():
                return
            result = json.loads(result_path.read_text(encoding="utf-8"))
            selected_sample = self.latest_sample["sample_id"]
            if (result.get("id") != request_id or result.get("sample") != selected_sample
                    or result.get("playback_mode") != "model_predict"):
                self._fail("Simulator result does not match the submitted VLA sample.")
                return
            state = result.get("state")
            if state in {"failed", "interrupted"}:
                self._fail(f"Simulator playback {state}: {result.get('error', 'No error detail')}")
            elif state == "running":
                self.latest_sample["status"] = "RUNNING"
            elif state == "done":
                output = Path(result.get("output", "")).resolve()
                output_root = (self.session_dir / "outputs" / selected_sample / "vla_prediction" / "requests").resolve()
                if not output.is_relative_to(output_root) or output.name != "scene.usda":
                    self._fail("Simulator returned an unexpected output path.")
                    return
                artifacts = [output, output.with_suffix(".actual_weld.npz"),
                             output.parent / "trajectory_solution.npz", output.parent / "report.json"]
                if not all(p.is_file() and p.stat().st_size > 0 for p in artifacts):
                    self._fail("Simulator reported done but expected output artifacts are missing/empty.")
                    return
                report = json.loads(artifacts[-1].read_text(encoding="utf-8"))
                if report.get("sample_id") != selected_sample or report.get("trajectory_source") != "vla_prediction":
                    self._fail("Preparation report does not identify the selected VLA prediction.")
                    return
                if self.latest_sample.get("mode") == "current_guided_vla_prediction":
                    prediction = report.get("prediction") or {}
                    if (report.get("point_count") != 9 or report.get("tracking_point") != "mounted_fixture_v2" or
                            Path(report.get("source_h5") or "").resolve() != Path(self.latest_sample["source_h5"]) or
                            Path(prediction.get("source_directory") or "").resolve() != Path(self.latest_sample["prediction_directory"]) or
                            prediction.get("position_source") != "VLA predicted_path_m"):
                        self._fail("Current Guided VLA playback report does not match the admitted artifact.")
                        return
                self.sample.stop()  # Release the finished child's tree/job handles too.
                self.sample = None
                self.latest_sample.update(status="SUCCEEDED", finished_at=timestamp(),
                                          artifacts=[str(p) for p in artifacts])
                self.state = "READY"
                self._log("bridge", f"Sample {request_id} completed: exit=0, result=done, artifacts present.")
            elif state not in {None}:
                self._fail(f"Unknown simulator result state: {state}")

    def _monitor(self):
        while not self.wake.wait(0.2):
            self.tick()

    def _snapshot(self):
        start_errors = self.config.start_errors()
        sample_errors = self.config.sample_errors()
        return dict(
            state=self.state, error=self.error, configured=not start_errors,
            configuration_errors=start_errors, sample_configuration_errors=sample_errors,
            existing_replay=dict(configured=not (start_errors or sample_errors), errors=start_errors+sample_errors),
            can_start=not start_errors and self.state in {"STOPPED", "FAILED"} and self.simulator is None,
            can_run_sample=self.state == "READY" and not sample_errors,
            can_stop=self.state != "STOPPED" or self.simulator is not None,
            simulator_pid=self.simulator.pid if self.simulator else None,
            sample_pid=self.sample.pid if self.sample else None,
            sample_id=self.config.sample_id or None, sample_mode="existing_vla_prediction",
            latest_sample=dict(self.latest_sample) if self.latest_sample else None,
            readiness="current_process_stdout_ready_message", preview_connected=False,
            robot_execution_enabled=False, session_dir=str(self.session_dir) if self.session_dir else None,
            configuration_diagnostics=self.configuration_diagnostics(),
        )

    def configuration_diagnostics(self):
        # Pure file inspection. GET status must never launch/import Isaac.
        from backend.services.simulator_diagnostics import read_import_check
        launcher = self.config.executable
        return dict(isaac_launcher_configured=launcher is not None and launcher.is_file(),
                    isaac_launcher=str(launcher) if launcher else None,
                    launcher_kind="windows_batch" if launcher and launcher.suffix.lower() in {".bat", ".cmd"} else "executable",
                    isaac_import_check=read_import_check(self.config),
                    prediction_format=self.config.prediction_format,
                    prediction_root=str(self.config.prediction_root),
                    samples_dir=str(self.config.samples_dir) if self.config.samples_dir else None,
                    metadata_present=any(self.config.prediction_root.glob("*/metadata.json")))

    def status(self):
        self.tick()
        with self.lock:
            return self._snapshot()

    def logs(self):
        with self.lock:
            return {"entries": list(self.entries)}

    def start(self):
        with self.lock:
            if self.closed:
                raise WorkflowError("Simulator client is closed.", 409)
            if self.state not in {"STOPPED", "FAILED"} or self.simulator or self.sample:
                raise WorkflowError("Simulator is already started. Stop the owned session first.", 409)
            if errors := self.config.start_errors():
                raise WorkflowError(" ".join(errors), 503)
            try:
                self.lease = FileLease(self.config.runtime_dir / "owner.lock")
            except RuntimeError as exc:
                raise WorkflowError(str(exc), 409) from exc
            except OSError as exc:
                self._fail(f"Cannot initialize simulator runtime: {exc}")
                raise WorkflowError(self.error, 503) from exc
            try:
                self.session_dir = (self.config.runtime_dir / "sessions" / uuid4().hex).resolve()
                (self.session_dir / "queue").mkdir(parents=True)
                self.state, self.error, self.ready_seen = "STARTING", None, False
                self.started_at = self.clock()
                self._launch("simulator", "run_welding_simulator.py", ["--queue-dir", str(self.session_dir / "queue")])
                if self.monitor_enabled and self.monitor_thread is None:
                    self.monitor_thread = threading.Thread(target=self._monitor, daemon=True)
                    self.monitor_thread.start()
            except Exception as exc:
                self._fail(f"Simulator launch failed: {exc}")
                raise WorkflowError(self.error, 503) from exc
            return self._snapshot()

    def run_sample(self):
        self.tick()
        with self.lock:
            if self.state != "READY":
                raise WorkflowError("Simulator must be READY; only one sample may run at a time.", 409)
            if errors := self.config.sample_errors():
                raise WorkflowError(" ".join(errors), 503)
            self.state = "RUNNING_SAMPLE"
            self.sample_started_at = self.clock()
            self.latest_sample = dict(sample_id=self.config.sample_id, status="PREPARING", request_id=None,
                                      mode="existing_vla_prediction",
                                      started_at=timestamp(), finished_at=None, exit_code=None, error=None, artifacts=[])
            try:
                prediction_root = self.config.prediction_root
                legacy = None
                if self.config.prediction_format == "legacy_npz":
                    prediction_root = self.session_dir / "predictions" / uuid4().hex
                    legacy = dict(prediction_root=str(self.config.prediction_root), samples_dir=str(self.config.samples_dir),
                                  sample_id=self.config.sample_id, output_root=str(prediction_root))
                data_args = (["--samples-dir", str(self.config.samples_dir)] if self.config.samples_dir is not None
                             else ["--data-root", str(self.config.data_root)])
                self._launch("sample", "run_welding_sample.py", [
                    "--send", "--prediction", "--sample", self.config.sample_id,
                    *data_args, "--prediction-root", str(prediction_root),
                    "--queue-dir", str(self.session_dir / "queue"),
                    "--output-dir", str(self.session_dir / "outputs"), "--duration-sec", str(self.config.duration),
                ], legacy_prediction=legacy)
            except Exception as exc:
                self._fail(f"Sample launch failed: {exc}")
                raise WorkflowError(self.error, 503) from exc
            return self._snapshot()

    def run_current_vla_prediction(self, package):
        # Called only after the separate backend adapter admission. It never starts Isaac.
        from backend.services.simulator_prediction_package import SimulatorPredictionPackage
        from backend.services.simulator_prediction_package import sha
        if not isinstance(package, SimulatorPredictionPackage) or package.preflight.get("fixture_ready") is not True:
            raise WorkflowError("Current VLA fixture preflight must pass before playback.", 409)
        self.tick()
        with self.lock:
            if self.state != "READY":
                raise WorkflowError("Simulator must be READY; current VLA playback never starts it automatically.", 409)
            self.state = "RUNNING_SAMPLE"
            self.sample_started_at = self.clock()
            self.latest_sample = dict(sample_id=package.sample_id, status="PREPARING", request_id=None,
                mode="current_guided_vla_prediction", artifact_id=str(package.artifact_id), package_id=str(package.package_id),
                source_h5=str(package.h5), prediction_directory=str(package.prediction_root / package.sample_id),
                ade_mm=package.ade_mm, fde_mm=package.fde_mm, simulation_only=True, physical_robot_executable=False,
                orientation_policy=package.orientation_policy, orientation_source=package.orientation_source,
                started_at=timestamp(), finished_at=None, exit_code=None, error=None, artifacts=[])
            try:
                self._launch("sample", "run_welding_sample.py", [
                    "--send", "--prediction", "--sample", package.sample_id,
                    "--samples-dir", str(package.h5.parent), "--prediction-root", str(package.prediction_root),
                    "--queue-dir", str(self.session_dir / "queue"),
                    "--output-dir", str(self.session_dir / "outputs"), "--duration-sec", str(self.config.duration),
                ], current_prediction=dict(package=str(package.directory / "package.json"),
                                           sha256=sha(package.directory / "package.json")))
            except Exception as exc:
                self._fail(f"Current VLA sample launch failed: {exc}")
                raise WorkflowError(self.error, 503) from exc
            return self._snapshot()

    def stop(self):
        with self.lock:
            if self.latest_sample and self.latest_sample["status"] in {"PREPARING", "QUEUED", "RUNNING"}:
                self.latest_sample.update(status="CANCELLED", finished_at=timestamp(), error="Stopped by user/backend shutdown.")
            try:
                self._release()
            except Exception as exc:
                self._fail(str(exc))
                raise WorkflowError(self.error, 503) from exc
            self.state, self.error, self.ready_seen = "STOPPED", None, False
            self._log("bridge", "Owned simulator session stopped. External/manual processes were not touched.")
            return self._snapshot()

    def close(self):
        self.wake.set()
        try:
            self.stop()
        finally:
            self.closed = True
            if self.monitor_thread:
                self.monitor_thread.join(timeout=2)
