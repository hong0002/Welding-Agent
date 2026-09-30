"""Thin native CLI boundary. No external imports, synthetic samples or prompt rewriting."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from threading import Lock
import time
from uuid import uuid4

import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field
import yaml

from backend.model_clients.config import ROOT, ModelSettings
from backend.model_clients.contracts import ModelArtifact, ModelFault, Provenance
from backend.model_clients.integrity import source_digest
from backend.model_clients.native_process import run_native
from backend.services.mask_service import validate_binary_mask
from backend.services.simulator_process import FileLease

CAMERAS = ("B", "F", "L", "R", "S1", "S2", "S3", "S4", "T")
NATIVE_PYTHON = Path("C:/Users/hong_/anaconda3/envs/py3_12/python.exe")


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 8_000_000:
        raise ValueError("Oversized native JSON")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def native_path(value, repository):
    value = str(value)
    # On Windows Path('/home/...').resolve() would silently become D:\home\...
    if os.name == "nt" and value.startswith("/") and not value.startswith("//"):
        raise ValueError("POSIX native path on Windows")
    path = Path(value).expanduser()
    return (path if path.is_absolute() else repository / path).resolve()


class NativeBinding(BaseModel):
    """Operator-owned identity; never accepted from HTTP or generated from an upload."""
    model_config = ConfigDict(extra="forbid")
    sample_id: str = Field(pattern=r"^[A-Za-z0-9_]{1,128}$")
    camera: str
    image: Path
    mask_session: Path | None = None
    views: list[str] | None = None


def accepted_session(path):
    try:
        path = Path(path).resolve()
        status = read_json(path / "status.json")
        iteration = status["accepted_iteration"]
        if status["status"] != "ok" or type(iteration) is not int or not 1 <= iteration <= 999:
            raise ValueError("Not approved")
        directory = path / f"iteration_{iteration:03d}"
        result = read_json(directory / "result.json")
        return directory, result
    except (OSError, ValueError, KeyError, TypeError):
        raise ModelFault("NATIVE_MASK_NOT_APPROVED") from None


@dataclass
class NativeResult:
    directory: Path
    artifact_id: str
    data: dict
    config: dict
    latency_ms: float
    source_sha256: str


class NativeRuntime:
    def __init__(self, settings: ModelSettings, *, records=None, run=run_native):
        self.settings = settings
        self.records = Path(records or ROOT / ".cache/native-models")
        self.run = run
        self.lock = Lock()
        self.running = False
        self.verified = False
        self.last_error = None
        self.last_diagnostic_id = None

    def configuration(self):
        s = self.settings
        try:
            if s.backend not in ("native", "real") or s.stage not in ("segment", "rough"):
                raise ValueError("Native mode required")
            if not s.repository or not s.python or not s.native_config:
                raise ValueError("Explicit Python and config required")
            if self.run is run_native and (s.python.resolve() != NATIVE_PYTHON.resolve() or
                    s.repository.resolve() != (ROOT.parent / ("vlm_segment" if s.stage == "segment" else "vlm_trajectory")).resolve()):
                raise ValueError("Only the parity-verified Python and native repositories may launch")
            if not s.python.is_file() or s.python.suffix.lower() in (".bat", ".cmd", ".ps1"):
                raise ValueError("Executable Python required")
            entry = s.repository / ("mask.py" if s.stage == "segment" else "cot.py")
            if not entry.is_file():
                raise ValueError("Missing entrypoint")
            config = yaml.safe_load(s.native_config.read_text(encoding="utf-8"))
            if s.stage == "segment":
                dataset = native_path(config["mask"]["dataset_root"], s.repository)
                output = native_path(config["mask"].get("output_dir", s.repository / "outputs/mask_sessions"), s.repository)
            else:
                dataset = native_path(config["data"]["root"], s.repository) / "2.데이터(NIA)"
                output = native_path(config["output"]["root"], s.repository)
            if not dataset.is_dir():
                raise ValueError("Native dataset unavailable")
            if not all(path.resolve().is_relative_to(ROOT.resolve()) for path in (output, s.native_config, self.records)):
                raise ValueError("Configs, records and generated native output must be Welding-Agent-owned")
            return config, dataset, output
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
            raise ModelFault("MODEL_NOT_CONFIGURED") from None

    def binding(self, image=None):
        try:
            _, dataset, _ = self.configuration()
            if not self.settings.native_binding:
                raise ValueError("Missing binding")
            binding = NativeBinding.model_validate(read_json(self.settings.native_binding))
            if binding.camera not in CAMERAS or (binding.views is not None and
                    (not binding.views or len(set(binding.views)) != len(binding.views) or
                     any(view not in CAMERAS for view in binding.views) or binding.camera not in binding.views)):
                raise ValueError("Invalid camera")
            if not binding.image.is_absolute() or not binding.image.is_file():
                raise ValueError("Original sample image required")
            binding.image = binding.image.resolve()
            if not binding.image.is_relative_to(dataset) or binding.image.parent.name != binding.sample_id:
                raise ValueError("Sample identity mismatch")
            if not binding.image.name.endswith(f"_{binding.camera}_Color.png"):
                raise ValueError("Camera identity mismatch")
            if binding.mask_session and not binding.mask_session.is_absolute():
                raise ValueError("Absolute approved session required")
            if image is not None:
                with Image.open(binding.image) as original:
                    original = original.convert("RGB")
                if original.size != image.size or original.tobytes() != image.convert("RGB").tobytes():
                    raise ValueError("Web RGB differs from native query")
            return binding
        except ModelFault:
            raise
        except (OSError, ValueError, TypeError):
            raise ModelFault("NATIVE_INPUT_MISMATCH") from None

    def status(self):
        try:
            self.binding()
            configured, code = True, self.last_error
        except ModelFault as exc:
            configured, code = False, exc.code
        return {"backend": "native", "configured": configured,
                "ready": configured and self.verified and code is None and not self.running,
                "state": "NOT_CONFIGURED" if not configured else "RUNNING" if self.running else "FAILED" if code else "READY" if self.verified else "UNVERIFIED",
                "code": code, "reference_mode": "native"}

    def execute(self, *, sample_id, instruction, views=None, mask_session=None):
        """CLI-only use may select a real sample without binding it to a web upload."""
        if not re.fullmatch(r"[A-Za-z0-9_]{1,128}", sample_id) or not instruction.strip() or len(instruction) > 16000 or "\x00" in instruction:
            raise ModelFault("NATIVE_INPUT_MISMATCH")
        s = self.settings
        config, _, root = self.configuration()
        command = [str(s.python), "-B", "-u", str(s.repository / ("mask.py" if s.stage == "segment" else "cot.py")),
                   "--config", str(s.native_config), "--instruction=" + instruction, "--once"]
        input_hash = None
        if s.stage == "segment":
            command += ["--sample-id", sample_id]
            if views is not None:
                if not views or len(set(views)) != len(views) or any(v not in CAMERAS for v in views):
                    raise ModelFault("NATIVE_INPUT_MISMATCH")
                command += ["--views", *views]
        else:
            if mask_session is None:
                raise ModelFault("NATIVE_MASK_NOT_APPROVED")
            directory, accepted = accepted_session(mask_session)
            if accepted["sample_id"] != sample_id:
                raise ModelFault("NATIVE_INPUT_MISMATCH")
            input_hash = sha256(directory / "result.json")
            command += ["--mask-session", str(Path(mask_session).resolve())]
        with self.lock:
            lease = None
            started = time.monotonic()
            try:
                # Serializes our launches; original CLI writes to the configured owned output root.
                lease_key = hashlib.sha256(str(s.repository.resolve()).encode()).hexdigest()
                lease = FileLease(self.records / (lease_key + ".lock"))
                before = {p.resolve() for p in root.glob(f"????????_??????_{sample_id}")} if root.exists() else set()
                config_hash = sha256(s.native_config)
                fingerprint = source_digest(s.repository)
                self.running = True
                diagnostic_id = str(uuid4())
                self.last_diagnostic_id = diagnostic_id
                diagnostic_args = {"diagnostic_path": self.records / "diagnostics" / f"{diagnostic_id}.jsonl",
                                   "output_root": root, "sample_id": sample_id} if self.run is run_native else {}
                code, views_output = self.run(command, cwd=s.repository, timeout=s.timeout, **diagnostic_args)
                if code != 0:
                    raise ModelFault("MODEL_PROCESS_FAILED")
                expected_name = "comparison_all.jpg" if s.stage == "segment" else "rough_trajectory_overlay.jpg"
                candidates = set()
                for view in views_output:
                    path = native_path(view, s.repository)
                    session = path.parent.parent
                    if (path.name == expected_name and path.parent.name == "iteration_001" and
                            session.parent == root and session not in before and
                            re.fullmatch(r"\d{8}_\d{6}_" + re.escape(sample_id), session.name)):
                        candidates.add(session)
                if len(candidates) != 1:
                    raise ModelFault("NATIVE_RESULT_INCOMPLETE")
                output = candidates.pop()
                data = read_native_result(s.stage, output, sample_id, instruction)
                if config_hash != sha256(s.native_config) or fingerprint != source_digest(s.repository):
                    raise ModelFault("MODEL_OUTPUT_INVALID")
                if input_hash is not None:
                    current_dir, _ = accepted_session(mask_session)
                    if current_dir != directory or input_hash != sha256(current_dir / "result.json"):
                        raise ModelFault("NATIVE_INPUT_MISMATCH")
                artifact_id = str(uuid4())
                # Only references/hashes live here. Images, JSON, MD remain in native output.
                files = {p.relative_to(output).as_posix(): sha256(p) for p in sorted(output.rglob("*")) if p.is_file()}
                elapsed = (time.monotonic() - started) * 1000
                record = {"schema_version": 1, "stage": s.stage, "sample_id": sample_id,
                          "artifact_id": artifact_id, "directory": str(output), "files": files,
                          "config_sha256": config_hash, "source_sha256": fingerprint,
                          "input_mask_result_sha256": input_hash, "latency_ms": elapsed,
                          "diagnostic_id": diagnostic_id if diagnostic_args else None,
                          "cwd": str(s.repository), "command": command}
                (self.records / f"{artifact_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                self.last_error = None
                self.verified = True
                return NativeResult(output, artifact_id, data, config, elapsed, fingerprint)
            except subprocess.TimeoutExpired:
                self.last_error = "MODEL_TIMEOUT"
                raise ModelFault(self.last_error) from None
            except ModelFault as exc:
                self.last_error = exc.code
                raise
            except Exception:
                self.last_error = "MODEL_PROCESS_FAILED"
                raise ModelFault(self.last_error) from None
            finally:
                self.running = False
                if lease:
                    lease.close()


def read_native_result(stage, directory, sample_id, instruction):
    """Read exact native artifacts; never manufacture approval or missing Markdown."""
    iteration = directory / "iteration_001"
    try:
        retrieval = read_json(directory / "retrieval.json")
        if retrieval["query_sample_id"] != sample_id:
            raise ValueError("Retrieval query differs")
        refs = [item["sample_id"] for item in retrieval["results"]]
        if sample_id in refs:
            raise ValueError("Self retrieval")
        if stage == "segment":
            data = read_json(iteration / "result.json")
            if data["instruction"] != instruction or data["retrieved_sample_ids"] != refs:
                raise ValueError("Segment metadata differs")
            required = ["comparison_all.jpg"]
            if not data["predictions"] or any(c not in CAMERAS for c in data["predictions"]):
                raise ValueError("Invalid camera output")
            for camera in data["predictions"]:
                required += [f"{camera}_gt.png", f"{camera}_prediction.png", f"{camera}_comparison.jpg"]
        else:
            data = read_json(iteration / "plan.json")
            if data["raw_instruction_ko"] != instruction or data["reference_sample_ids"] != refs:
                raise ValueError("Rough metadata differs")
            if data["schema_version"] != "welding-cot-v2" or data["refined_task"]["status"] != "ready" or data["plan"]["status"] != "ready":
                raise ValueError("Incomplete plan")
            if read_json(directory / "query_rough_action.json") != data["rough_trajectory"]:
                raise ValueError("Rough artifact mismatch")
            refiner = read_json(directory / "refiner.json")
            if {k: v for k, v in refiner.items() if k not in ("response_id", "prompt_version")} != data["refined_task"]:
                raise ValueError("Refiner artifact mismatch")
            required = ["cot_ko.md", "vla_prompt.md", "rough_trajectory_overlay.jpg"]
            if not (directory / "query_masks.jpg").is_file() or not refs:
                raise ValueError("Missing references/query")
        if data["sample_id"] != sample_id or any(not (iteration / f).is_file() or (iteration / f).stat().st_size == 0 for f in required):
            raise ValueError("Incomplete output")
        return data
    except (OSError, ValueError, KeyError, TypeError):
        raise ModelFault("NATIVE_RESULT_INCOMPLETE") from None


def provenance(result, stage, instruction):
    if stage == "segment":
        model = str(result.config["mask"].get("model", "gpt-6-sol"))
        version = result.data["prompt_version"]
    else:
        model = str(result.config["models"]["planner"])
        version = result.data["planner_prompt_version"]
    return Provenance(artifact_id=result.artifact_id, model_name=model, model_version=version,
                      source_sha256=result.source_sha256, latency_ms=result.latency_ms,
                      reference_mode="native", reference_manifest_sha256=sha256(result.directory / "retrieval.json"),
                      instruction=instruction, input_transform="native CLI output; original artifact preserved",
                      native_session_id=result.directory.name,
                      native_source_artifact_id=result.artifact_id if stage == "segment" else None,
                      native_artifacts={p.relative_to(result.directory).as_posix(): True for p in result.directory.rglob("*") if p.is_file()})


class NativeSegmentClient:
    def __init__(self, runtime):
        self.runtime = runtime

    def run_sample(self, sample_id, instruction, *, views=None):
        return self.runtime.execute(sample_id=sample_id, instruction=instruction, views=views)

    def segment(self, image, *, instruction="용접할 영역을 찾아주세요."):
        binding = self.runtime.binding(image)
        result = self.run_sample(binding.sample_id, instruction, views=binding.views)
        try:
            with Image.open(result.directory / "iteration_001" / f"{binding.camera}_prediction.png") as source:
                mask = source.copy()
            validate_binary_mask(mask, image.size)
            mask.info["model_provenance"] = provenance(result, "segment", instruction)
            return mask
        except Exception:
            self.runtime.last_error = "MODEL_OUTPUT_INVALID"
            raise ModelFault("MODEL_OUTPUT_INVALID") from None


class NativeRoughClient:
    stops_at_rough = True

    def __init__(self, runtime):
        self.runtime = runtime
        from backend.model_clients.native_approval import ApprovedMaskSessions
        self.approvals = ApprovedMaskSessions(runtime.records)

    def run_session(self, mask_session, instruction):
        _, accepted = accepted_session(mask_session)
        return self.runtime.execute(sample_id=accepted["sample_id"], instruction=instruction, mask_session=mask_session)

    def predict(self, image, mask, instruction, components, *, language=""):
        session, accepted, proof = self.prepare_session(image, mask, components)
        binding = self.runtime.binding(image)
        if not language.strip():
            raise ModelFault("NATIVE_INPUT_MISMATCH")
        metadata = mask.info.get("mask_artifact")
        self.approvals.verify(session, mask, metadata)
        result = self.run_session(session, language)
        self.approvals.verify(session, mask, metadata)
        try:
            from backend.model_clients.native_preview import to_preview
            trajectory = to_preview(result.data, accepted, binding.camera, image.size, instruction, components)
            meta = provenance(result, "rough", language)
            meta.region_ids = instruction.region_order
            meta.approved_mask_session_id = proof["session_id"]
            meta.input_mask_sha256 = proof["mask_pixels_sha256"]
            meta.native_source_artifact_id = proof["source_native_artifact_id"]
            trajectory.artifact = ModelArtifact(kind="rough", provenance=meta)
            return trajectory
        except Exception:
            self.runtime.last_error = "MODEL_OUTPUT_INVALID"
            raise ModelFault("MODEL_OUTPUT_INVALID") from None

    def prepare_session(self, image, mask, components):
        """Also usable for an offline edited-mask contract check; never calls a model."""
        binding = self.runtime.binding(image)
        metadata = mask.info.get("mask_artifact") if mask is not None else None
        return self.approvals.prepare(binding, mask, metadata, components)
