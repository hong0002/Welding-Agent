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
from uuid import UUID, uuid4

import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field
import yaml

from backend.model_clients.config import ROOT, ModelSettings
from backend.model_clients.contracts import ModelArtifact, ModelFault, Provenance
from backend.model_clients.integrity import source_digest
from backend.model_clients.native_process import run_native
from backend.model_clients.native_profiles import native_profile
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
    """Backend-owned verified dataset identity; never accepted as HTTP paths."""
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
        self.last_capture = None
        self.last_display_capture = None

    def configuration(self):
        s = self.settings
        try:
            profile = native_profile(s.stage, s.backend)
            if not s.repository or not s.python or not s.native_config:
                raise ValueError("Explicit Python and config required")
            if self.run is run_native and (s.python.resolve() != NATIVE_PYTHON.resolve() or
                    s.repository.resolve() != (ROOT.parent / profile.repository).resolve()):
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
            verified = image.info.get("native_binding") if image is not None else None
            if isinstance(verified, NativeBinding):
                binding = verified.model_copy(deep=True)
            else:
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
        self.last_capture = None
        s = self.settings
        self.last_display_capture = None
        profile = native_profile(s.stage, s.backend)
        config, _, root = self.configuration()
        entry = (Path(__file__).with_name('native_trajectory3_entry.py') if profile.name == 'native_3d_v3'
                 else s.repository / ("mask.py" if s.stage == "segment" else "cot.py"))
        command = [str(s.python), "-B", "-u", str(entry),
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
            code = None
            before = config_hash = fingerprint = diagnostic_id = artifact_id = None
            try:
                # Serializes our launches; original CLI writes to the configured owned output root.
                lease_key = hashlib.sha256(str(s.repository.resolve()).encode()).hexdigest()
                lease = FileLease(self.records / (lease_key + ".lock"))
                before = profile.sessions(root, sample_id) if root.exists() else set()
                config_hash = sha256(s.native_config)
                fingerprint = self.source_fingerprint()
                self.running = True
                diagnostic_id = str(uuid4())
                self.last_diagnostic_id = diagnostic_id
                diagnostic_args = {"diagnostic_path": self.records / "diagnostics" / f"{diagnostic_id}.jsonl",
                                   "output_root": root, "sample_id": sample_id} if self.run is run_native else {}
                code, views_output = self.run(command, cwd=s.repository, timeout=s.timeout, **diagnostic_args)
                if code != 0:
                    raise ModelFault("MODEL_PROCESS_FAILED")
                expected_name = {"segment": "comparison_all.jpg", "rough": "rough_trajectory_overlay.jpg",
                                 "rough3d": "review_all.jpg"}[s.stage]
                candidates = set()
                for view in views_output:
                    path = native_path(view, s.repository)
                    session = path.parent.parent
                    if (path.name == expected_name and path.parent.name == "iteration_001" and
                            session.parent == root and session not in before and
                            session in profile.sessions(root, sample_id)):
                        candidates.add(session)
                if len(candidates) != 1:
                    raise ModelFault("NATIVE_RESULT_INCOMPLETE")
                output = candidates.pop()
                data = read_native_result(s.stage, output, sample_id, instruction, version=profile.name)
                if profile.name == 'native_3d_v3' and Path(data['previous_mask_session']).resolve() != Path(mask_session).resolve():
                    raise ModelFault('NATIVE_INPUT_MISMATCH')
                if config_hash != sha256(s.native_config) or fingerprint != self.source_fingerprint():
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
                          "native_stack": profile.name,
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
                # Display evidence may survive acceptance/provenance failure. It
                # still belongs to exactly this launch's fresh owned session.
                if before is not None:
                    try:
                        fresh_display = profile.sessions(root, sample_id) - before
                        if len(fresh_display) == 1:
                            display_session = fresh_display.pop().resolve()
                            if display_session.parent == root.resolve():
                                self.last_display_capture = dict(artifact_id=artifact_id or str(uuid4()),
                                    sample_id=sample_id, directory=str(display_session))
                    except (OSError, ValueError):
                        pass
                # Preserve an owned attempted output even when the strict complete-result
                # reader rejects it. This is evidence, NEVER a validated trajectory.
                if s.stage == 'rough3d' and before is not None and config_hash and fingerprint and diagnostic_id:
                    try:
                        fresh = profile.sessions(root, sample_id) - before
                        if (len(fresh) == 1 and config_hash == sha256(s.native_config)
                                and fingerprint == self.source_fingerprint()):
                            current_dir, _ = accepted_session(mask_session)
                            if current_dir == directory and sha256(current_dir/'result.json') == input_hash:
                                session = fresh.pop()
                                files = {p.relative_to(session).as_posix():sha256(p)
                                         for p in sorted(session.rglob('*')) if p.is_file()}
                                capture_id = artifact_id or (self.last_display_capture or {}).get('artifact_id') or str(uuid4())
                                self.last_capture = dict(artifact_id=capture_id, stage=s.stage, native_stack=profile.name,
                                    sample_id=sample_id, directory=str(session), files=files,
                                    instruction_sha256=hashlib.sha256(instruction.encode()).hexdigest(),
                                    mask_session=str(current_dir.parent), input_mask_result_sha256=input_hash,
                                    config_sha256=config_hash, source_sha256=fingerprint, exit_code=code,
                                    diagnostic_id=diagnostic_id, trusted_input_snapshot=True)
                                # Separate immutable evidence, including incomplete runs.
                                path=self.records/f'{capture_id}.capture.json'
                                with path.open('x',encoding='utf-8') as stream:
                                    json.dump(self.last_capture,stream,ensure_ascii=False,indent=2)
                    except (OSError,ValueError,KeyError,TypeError,ModelFault):
                        self.last_capture = None  # Never relax source/input integrity for recovery.
                self.running = False
                if lease:
                    lease.close()

    def source_fingerprint(self):
        fingerprint = source_digest(self.settings.repository)
        if native_profile(self.settings.stage, self.settings.backend).name == 'native_3d_v3':
            fingerprint = hashlib.sha256((fingerprint + source_digest(ROOT.parent/'vlm_segment2') +
                sha256(Path(__file__).with_name('native_trajectory3_entry.py'))).encode()).hexdigest()
        return fingerprint

def read_native_result(stage, directory, sample_id, instruction, *, version=None, strict_aux=True):
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
            expected_schema = "welding-cot-v3" if stage == "rough3d" else "welding-cot-v2"
            if data["schema_version"] != expected_schema or data["refined_task"]["status"] != "ready" or data["plan"]["status"] != "ready":
                raise ValueError("Incomplete plan")
            if stage == "rough3d":
                if (read_json(directory / "query_image_guidance_2d.json") != data["image_guidance_2d"] or
                        read_json(directory / "reference_trajectory_3d.json") != data["rough_trajectory_3d"]):
                    raise ValueError("V3 artifacts differ")
                from backend.model_clients.trajectory_contracts import ReferenceTrajectory3D
                reference = ReferenceTrajectory3D.model_validate(data["rough_trajectory_3d"])
                selected = next(item for item in retrieval["results"] if item["sample_id"] == reference.source_sample_id)
                if ([list(s.points_xyz_mm) for s in reference.segments] !=
                        [[tuple(p) for p in s["points_start_relative_mm"]] for s in selected["rough_action"]["segments"]]):
                    raise ValueError("Reference coordinates differ from retrieval")
            elif read_json(directory / "query_rough_action.json") != data["rough_trajectory"]:
                raise ValueError("Rough artifact mismatch")
            refiner = read_json(directory / "refiner.json")
            if {k: v for k, v in refiner.items() if k not in ("response_id", "prompt_version")} != data["refined_task"]:
                raise ValueError("Refiner artifact mismatch")
            required = ["cot_ko.md", "vla_prompt.md"] + (["image_guidance_2d_overlay.jpg", "rough_trajectory_3d.jpg", "review_all.jpg"]
                                                       if stage == "rough3d" else ["rough_trajectory_overlay.jpg"])
            query_image = 'query_views.jpg' if version == 'native_3d_v3' else 'query_masks.jpg'
            if version == 'native_3d_v3':
                if (data.get('mask_available') is not True or data['image_guidance_2d'].get('mask_available') is not True
                        or not data.get('previous_mask_session') or not data.get('yolo_request_id')
                        or data['planner_prompt_version'] != 'welding-detailed-plan-v3-optional-mask'):
                    raise ValueError('Trajectory3 requires the explicit approved-mask branch')
                required_yolo = directory/'yolo/detections.json'
                detection = read_json(required_yolo)
                if detection['sample_id'] != sample_id or detection['request_id'] != data['yolo_request_id']:
                    raise ValueError('Trajectory3 YOLO lineage differs')
            if not refs or (strict_aux and not (directory / query_image).is_file()):
                raise ValueError("Missing references/query")
        if data["sample_id"] != sample_id or (strict_aux and any(not (iteration / f).is_file() or (iteration / f).stat().st_size == 0 for f in required)):
            raise ValueError("Incomplete output")
        return data
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
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
        self.last_result = None

    def run_sample(self, sample_id, instruction, *, views=None):
        self.last_result = None
        self.last_result = self.runtime.execute(sample_id=sample_id, instruction=instruction, views=views)
        return self.last_result

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

    def segment_views(self, image, *, instruction="용접할 영역을 찾아주세요."):
        binding = self.runtime.binding(image)
        # No browser-provided view selection. Preserve native F/R/S4 defaults.
        result = self.run_sample(binding.sample_id, instruction, views=None)
        masks = {}
        for view in result.data["predictions"]:
            with Image.open(result.directory / "iteration_001" / f"{view}_prediction.png") as source:
                mask = source.copy()
            mask.info["model_provenance"] = provenance(result, "segment", instruction)
            masks[view] = mask
        return masks


NativeSegmentV1Client = NativeSegmentClient


class NativeSegmentV2Client(NativeSegmentClient):
    """Same native mask contract, server-YOLO retrieval and microsecond sessions."""


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
            meta.approved_mask_session_id = UUID(proof["session_id"])
            meta.input_mask_sha256 = proof["mask_pixels_sha256"]
            meta.native_source_artifact_id = UUID(proof["source_native_artifact_id"])
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
