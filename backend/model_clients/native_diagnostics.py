"""Allowlisted process milestones only. No raw stdout, payload, reasoning or credentials."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from threading import Lock
import time


CAMERAS = ("B", "F", "L", "R", "S1", "S2", "S3", "S4", "T")


class NativeDiagnostics:
    def __init__(self, path, *, output_root=None, sample_id=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # An attempt log is append-only and never overwrites a previous run.
        self.path.touch(exist_ok=False)
        self.native_log = self.path.with_suffix(".native.log")
        self.native_log.touch(exist_ok=False)
        self.started = time.monotonic()
        self.lock = Lock()
        self.events = 0
        self.io_failed = False
        self.native_log_failed = False
        self.native_lines = 0
        self.last_native_line = None
        self.phase = "setup"
        self.root = Path(output_root).resolve() if output_root is not None else None
        self.sample_id = sample_id if sample_id and re.fullmatch(r"[A-Za-z0-9_]{1,128}", sample_id) else None
        self.before = set(self.sessions())
        self.observed = set()

    def sessions(self):
        if self.root is None or self.sample_id is None:
            return []
        return [p for p in self.root.glob('*_'+self.sample_id)
                if p.is_dir() and p.resolve().parent == self.root
                and re.fullmatch(r"\d{8}_\d{6}(?:_\d{6})?_" + re.escape(self.sample_id), p.name)]

    def emit(self, event, **fields):
        with self.lock:
            if self.events >= 512 or self.io_failed:
                return
            record = {"at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                      "elapsed_seconds": round(time.monotonic() - self.started, 3),
                      "event": event, **fields}
            try:
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, ensure_ascii=True) + "\n")
            except OSError:
                self.io_failed = True  # Keep draining child stdout even if the diagnostic disk fails.
                return
            self.events += 1

    def log_native(self, line, *, supervisor=False):
        """Only callers' allowlisted text enters this separate, bounded merged stdout/stderr log."""
        with self.lock:
            if not supervisor:
                self.last_native_line = line
            if self.native_lines >= 512 or self.native_log_failed:
                return
            try:
                with self.native_log.open("a", encoding="utf-8") as stream:
                    stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                    stream.write(f"{stamp} +{time.monotonic() - self.started:.3f}s {line}\n")
                self.native_lines += 1
            except OSError:
                self.native_log_failed = True

    def output(self, line):
        """Native [GPT] precedes image encoding and HTTP: it is NOT proof of an in-flight API call."""
        if re.fullmatch(r'\[GPT2_STAGE\] (start|completed)=(rough|corners)',line):
            self.log_native(line)
            action,stage=line.split(' ',1)[1].split('=')
            self.phase='gpt2_'+stage
            self.emit('gpt2_stage_'+action,stage=stage)
            return
        if line=='[GPT2_RETRIEVAL] ssh_started':
            self.log_native(line);self.emit('gpt2_ssh_started');return
        if re.fullmatch(r'\[GPT2_PROCESS_FAILED\] exception=[A-Za-z]{1,64}',line):
            self.log_native(line);self.emit('gpt2_process_failed',error_class=line.split('=')[1]);return
        match = re.fullmatch(r"\[GPT\] iteration=(\d{1,4}) camera=(B|F|L|R|S1|S2|S3|S4|T) examples=\d{1,4}", line)
        if match:
            self.log_native(line)
            self.phase = "view_" + match[2]
            self.emit("view_started", view=match[2], iteration=int(match[1]))
        elif line.startswith("[RETRIEVE] "):
            safe = re.fullmatch(r"\[RETRIEVE\] (?:image\+text\+mask )?sample=[A-Za-z0-9_]{1,128}(?:, top_k=\d{1,4})?", line)
            self.log_native(line if safe else "[RETRIEVE] [details omitted]")
            self.phase = "retrieval"
            self.emit("retrieval_started")
        elif line.startswith("[RETRIEVED] "):
            safe = re.fullmatch(r"\[RETRIEVED\] [A-Za-z0-9_]{1,128}(?:, [A-Za-z0-9_]{1,128}){0,31}", line)
            self.log_native(line if safe else "[RETRIEVED] [details omitted]")
            self.phase = "reference_preparation"
            self.emit("retrieval_completed")
        elif line.startswith("[REFINE] "):
            safe = re.fullmatch(r"\[REFINE\] sample=[A-Za-z0-9_]{1,128}, prompt=[A-Za-z0-9_-]{1,64}", line)
            self.log_native(line if safe else "[REFINE] [details omitted]")
            self.phase = "instruction_refinement"
            self.emit("instruction_refinement_started")
        elif line.startswith("[GPT] iteration="):
            safe = re.fullmatch(r"\[GPT\] iteration=\d{1,4}, references=\d{1,4}, prompt=[A-Za-z0-9_-]{1,64}", line)
            self.log_native(line if safe else "[GPT] [details omitted]")
            self.phase = "planning"
            self.emit("planning_started")
        elif line.startswith("[RESULT] "):
            safe = re.fullmatch(r"\[RESULT\] mean IoU=\d\.\d{4}, mean Dice=\d\.\d{4}", line)
            self.log_native(line if safe else "[RESULT] [details omitted]")
            self.phase = "result_written"
            self.emit("native_result_ready")
        elif line.startswith("[CLARIFY] "):
            self.log_native("[CLARIFY] [details omitted]")
            self.phase = "clarification"
            self.emit("clarification_requested")
        elif line.startswith(('[YOLO NEW]', '[YOLO REUSE]', '[YOLO]', '[UPLOAD]')):
            tag = next(t for t in ('[YOLO NEW]', '[YOLO REUSE]', '[YOLO]', '[UPLOAD]') if line.startswith(t))
            self.log_native(tag+' [details omitted]')
            self.emit('yolo_milestone', mode=tag.strip('[]'))
        elif line.startswith(("[VIEW] ", "[COT] ", "[VLA] ")):
            # Native [VLA] announces a Markdown artifact, not a VLA invocation.
            tag, raw_path = line.split(" ", 1)
            names = {"[VIEW]": {"comparison_all.jpg", "rough_trajectory_overlay.jpg", "review_all.jpg"},
                     "[COT]": {"cot_ko.md"}, "[VLA]": {"vla_prompt.md"}}
            safe = tag + " [path omitted]"
            if self.root is not None:
                try:
                    path = Path(raw_path).resolve()
                    if path.name in names[tag] and path.parent.name == "iteration_001" and path.parent.parent in self.sessions():
                        safe = tag + " " + path.relative_to(self.root).as_posix()
                except (OSError, ValueError):
                    pass
            self.log_native(safe)
        else:
            # Never retain arbitrary exception text: it can include a full HTTP body/prompt.
            error = re.match(r"^(?:(?:openai|httpx|httpcore|subprocess)\.)?(AuthenticationError|RateLimitError|APITimeoutError|APIConnectionError|ReadTimeout|ConnectTimeout|TimeoutError|EOFError|FileNotFoundError|PermissionError|OSError|RuntimeError|ValueError|ModuleNotFoundError|ImportError|BrokenPipeError|CalledProcessError):\s*(.*)$", line)
            if error:
                message = self.safe_error_message(error[2])
                self.log_native(f"{error[1]}: {message}")
                self.emit("native_error_class", error_class=error[1], safe_message=message, phase=self.phase)

    @staticmethod
    def safe_error_message(message):
        for phrase in ("Request timed out.", "Connection error.", "EOF when reading a line", "The read operation timed out"):
            if message.startswith(phrase):
                return phrase
        status = re.match(r"Error code: (\d{3})\b", message)
        if status:
            return f"HTTP {status[1]}; response body omitted"
        errno = re.match(r"\[(Errno|WinError) (\d{1,6})\]", message)
        if errno:
            return errno[0] + " [remaining message omitted]"
        return "[message omitted: outside safe allowlist]"

    def artifacts(self):
        # Bounded output lookup only. Never traverse the dataset or sibling repository.
        names = ["retrieval.json", "yolo/detections.json", "yolo/provenance.json", "query_views.jpg", "query_rough_action.json", "query_image_guidance_2d.json", "reference_trajectory_3d.json", "refiner.json", "query_masks.jpg",
                 "iteration_001/result.json", "iteration_001/plan.json", "iteration_001/cot_ko.md",
                 "iteration_001/vla_prompt.md", "iteration_001/rough_trajectory_overlay.jpg",
                 "iteration_001/image_guidance_2d_overlay.jpg", "iteration_001/rough_trajectory_3d.jpg", "iteration_001/review_all.jpg"]
        names += [f"iteration_001/{camera}_{suffix}" for camera in CAMERAS
                  for suffix in ("gt.png", "prediction.png", "comparison.jpg")]
        try:
            sessions = self.sessions()
        except OSError:
            self.emit("artifact_observation_failed")
            return
        for session in sessions:
            if session in self.before:
                continue
            for name in names:
                key = (session.name, name)
                if key in self.observed:
                    continue
                try:
                    stat = (session / name).stat()
                except OSError:
                    continue
                if not stat.st_size:
                    continue
                self.observed.add(key)
                self.emit("artifact_observed", session_id=session.name, artifact=name,
                          file_mtime_utc=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="milliseconds"),
                          size_bytes=stat.st_size)
