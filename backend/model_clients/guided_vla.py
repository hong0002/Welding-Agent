"""Backend-owned, one-attempt EX3 guided boundary. No native model or simulator calls."""
from dataclasses import dataclass, field
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from dotenv import dotenv_values
import httpx
import numpy as np
from PIL import Image

from backend.model_clients.config import ROOT
from backend.model_clients.contracts import ModelFault
from backend.model_clients.native import NativeBinding, read_json, sha256
from backend.model_clients.native_approval import pixel_hash
from backend.model_clients.native_rough3d import NativeRough3DClient
from backend.model_clients.trajectory_contracts import VLAPredictedTrajectory
from backend.schemas import WeldJob
from backend.services.components import detect_components


class GuidedVLAError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)  # Never include requests, headers, server bodies or point arrays.


@dataclass(frozen=True)
class GuidedVLASettings:
    server_url: str = "http://127.0.0.1:8000"
    api_token: str = field(default="", repr=False)
    timeout: float = 600
    inputs: Path = ROOT / ".cache/native-models/guided-vla-inputs.json"
    attempts: Path = ROOT / ".cache/native-models/guided-vla"

    @classmethod
    def from_env(cls):
        values = dotenv_values(ROOT / ".env", interpolate=False)
        def get(key, default=""):
            return (os.getenv(key, values.get(key) or default)).strip()
        try:
            result = cls(server_url=get("WELD_GUIDED_VLA_SERVER_URL", "http://127.0.0.1:8000"),
                         api_token=get("WELD_GUIDED_VLA_API_TOKEN", get("EX3_API_TOKEN")),
                         timeout=float(get("WELD_GUIDED_VLA_TIMEOUT", "600")),
                         inputs=Path(get("WELD_GUIDED_VLA_INPUTS", str(cls.inputs))).resolve())
            result.validate()
            return result
        except (ValueError, TypeError):
            raise GuidedVLAError("GUIDED_VLA_NOT_CONFIGURED") from None

    def validate(self):
        url = urlsplit(self.server_url)
        if (url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or
                url.query or url.fragment or url.path not in ("", "/") or
                not math.isfinite(self.timeout) or not 1 <= self.timeout <= 1800 or
                not self.inputs.resolve().is_relative_to(ROOT.resolve()) or
                not self.attempts.resolve().is_relative_to(ROOT.resolve())):
            raise GuidedVLAError("GUIDED_VLA_NOT_CONFIGURED")

    @property
    def endpoint(self):
        self.validate()
        return self.server_url.rstrip("/") + "/v1/predict-guided"


class GuidedTransport(Protocol):
    def post(self, url, *, data, files, headers, timeout) -> dict: ...


class HTTPGuidedTransport:
    def post(self, url, *, data, files, headers, timeout):
        try:
            # Do not send credentials to redirected hosts or inherited proxies. No retry loop.
            with httpx.Client(trust_env=False, follow_redirects=False, timeout=timeout) as client:
                response = client.post(url, data=data, files=files, headers=headers)
                response.raise_for_status()
                if len(response.content) > 8_000_000:
                    raise GuidedVLAError("GUIDED_VLA_RESPONSE_INVALID")
                return response.json()
        except (httpx.HTTPError, ValueError):
            raise GuidedVLAError("GUIDED_VLA_REQUEST_FAILED") from None


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)


def write_bytes(path, value):
    with Path(path).open("xb") as stream:
        stream.write(value)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def resolve_split(dataset_root, binding):
    """Exact label/source counterpart lookup, no dataset rglob or default-val assumption."""
    try:
        nia = Path(dataset_root).resolve() / "2.데이터(NIA)"
        image = binding.image.resolve()
        relative = image.relative_to(nia)
        split_name, folder, category, *tail = relative.parts
        if (split_name not in ("Training", "Validation") or folder != "01.원천데이터" or
                not category.startswith("TS_" if split_name == "Training" else "VS_") or
                image.parent.name != binding.sample_id or image.name != f"{binding.sample_id}_{binding.camera}_Color.png"):
            raise ValueError("Source identity")
        label_category = category[0] + "L" + category[2:]
        label = nia / split_name / "02.라벨링데이터" / label_category / Path(*tail[:-1]) / f"{binding.sample_id}.json"
        payload = read_json(label)
        records = [item for item in payload["rgb_images"] if item["filename"] == image.name]
        if payload["info"]["gid"] != binding.sample_id or len(records) != 1 or not image.is_file():
            raise ValueError("Label identity")
        other = "Validation" if split_name == "Training" else "Training"
        other_category = ("V" if other == "Validation" else "T") + label_category[1:]
        if (nia / other / "02.라벨링데이터" / other_category / Path(*tail[:-1]) / label.name).exists():
            raise ValueError("Ambiguous split")
        with Image.open(image) as im:
            if im.size != (records[0]["rgb_width"], records[0]["rgb_height"]):
                raise ValueError("Label dimensions")
        return {"split": "train" if split_name == "Training" else "val", "label": str(label),
                "label_sha256": sha256(label), "image": str(image), "image_sha256": sha256(image)}
    except (OSError, ValueError, TypeError, KeyError):
        raise GuidedVLAError("GUIDED_VLA_SPLIT_UNRESOLVED") from None


def latest_approval(storage, binding):
    """Only explicit dated confirmations of this exact RGB qualify; no legacy/dummy approvals."""
    candidates = []
    try:
        with Image.open(binding.image) as im:
            original = im.convert("RGB")
        for path in sorted((storage / "jobs").glob("*.json")):
            if not re.fullmatch(r"[0-9a-f-]{36}\.json", path.name):
                continue
            raw = read_json(path)
            mask = raw.get("mask") or {}
            if not mask.get("approved") or not mask.get("approved_at"):
                continue
            job = WeldJob.model_validate(raw)
            if (job.scene is None or job.mask is None or job.mask.scene_id != job.scene.id or
                    job.mask.mask_source not in ("vlm_segment", "manual_edited") or
                    (job.scene.width, job.scene.height) != original.size):
                continue
            scene_path = storage / "scenes" / f"{job.scene.id}.png"
            with Image.open(scene_path) as im:
                if im.convert("RGB").tobytes() != original.tobytes():
                    continue
            candidates.append((job.mask.approved_at, job, path))
        candidates.sort(key=lambda item: item[0], reverse=True)
        if not candidates or (len(candidates) > 1 and candidates[0][0] == candidates[1][0]):
            raise ValueError("No unique latest approval")
        _, job, job_path = candidates[0]
        mask_path = storage / "masks" / f"{job.mask.id}.png"
        with Image.open(mask_path) as im:
            mask_image = im.copy()
            if im.format != "PNG" or im.mode != "L" or im.size != original.size:
                raise ValueError("Mask encoding")
        values = np.asarray(mask_image)
        if not np.all((values == 0) | (values == 255)) or not np.any(values):
            raise ValueError("Mask binary")
        if job.mask.width != original.width or job.mask.height != original.height:
            raise ValueError("Mask metadata dimensions")
        expected = job.rough_trajectory.artifact.provenance.input_mask_sha256 if job.rough_trajectory and job.rough_trajectory.artifact else None
        if expected is not None and expected != pixel_hash(mask_image):
            raise ValueError("Approved mask hash differs")
        return job, job_path, mask_path, mask_image
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise GuidedVLAError("GUIDED_VLA_MASK_NOT_APPROVED") from None


def serialize_guidance(sample_id, guidance, plan):
    """Round-trip float serialization. Preserve native point order, carry direction separately."""
    try:
        camera = guidance["primary_camera"]
        size = guidance["image_size"]
        if guidance.get('mask_available', True) is not True:
            raise ValueError('Approved mask guidance required')
        if (camera != "F" or guidance["schema_version"] != "welding-image-guidance-v1" or
                guidance["coordinate_frame_pixel"] != f"image_pixel:{camera}" or
                guidance["coordinate_frame_normalized"] != f"image_normalized:{camera}" or
                type(size["width"]) is not int or type(size["height"]) is not int or min(size.values()) <= 0 or
                len(guidance["segments"]) != 1):
            raise ValueError("Only one confirmed F segment is supported")
        segment = guidance["segments"][0]
        if segment["connected_to_next"] is not False or segment["source_mask_id"] != "F:polyline_0":
            raise ValueError("Disconnected contract")
        pixels, points = segment["points_pixel"], segment["points_normalized"]
        for array in (pixels, points):
            if (not isinstance(array, list) or not 2 <= len(array) <= 128 or
                    any(not isinstance(p, list) or len(p) != 2 or
                        any(type(v) not in (float, int) or not math.isfinite(v) for v in p) for p in array)):
                raise ValueError("Invalid points")
        if (len(pixels) != len(points) or not np.allclose(np.asarray(pixels) / [size["width"], size["height"]], points, atol=1e-6, rtol=0) or
                any(not 0 <= x < size["width"] or not 0 <= y < size["height"] for x, y in pixels) or
                any(not 0 <= v <= 1 for p in points for v in p) or guidance["actual_point_count"] != len(points)):
            raise ValueError("Pixel/normalized inconsistency")
        decisions = plan["segment_decisions"]
        if (plan["status"] != "ready" or len(decisions) != 1 or decisions[0]["segment_id"] != segment["segment_id"] or
                decisions[0]["direction"] not in ("forward", "reverse") or decisions[0]["weld_enabled"] is not True or
                segment["source_mask_id"] not in plan["grounded_mask_ids"]):
            raise ValueError("Incomplete semantic plan")
        direction = decisions[0]["direction"]
        lines = ["# 가궤적", "", f"- sample/query identity: `{sample_id}`", f"- 좌표계: `mask_normalized:{camera}`",
                 f"- 기준 카메라: `{camera}`", f"- 진행 방향: `{direction}`", ""]
        for index, (x, y) in enumerate(points):
            x_text, y_text = json.dumps(x, allow_nan=False), json.dumps(y, allow_nan=False)
            lines.append(f"{index + 1}. `P{index} = ({x_text}, {y_text})`")
        return "\n".join(lines) + "\n", direction
    except (ValueError, KeyError, TypeError, OverflowError):
        raise GuidedVLAError("GUIDED_VLA_GUIDANCE_INVALID") from None


def validate_cot_delivery(value):
    """Validate observed server telemetry without inventing missing delivery evidence."""
    if value is None:
        return {"status": "NOT_PROVIDED"}
    if not isinstance(value, dict):
        raise GuidedVLAError("GUIDED_VLA_GUIDANCE_NOT_CONFIRMED")
    def get(*names):
        return next((value[name] for name in names if name in value), None)
    original = get("original_cot_tokens", "original_token_count", "original_tokens")
    delivered = get("delivered_cot_tokens", "delivered_token_count", "delivered_tokens")
    truncated = get("truncated", "was_truncated", "is_truncated")
    if truncated is True or (original is not None and delivered is not None and original != delivered):
        raise GuidedVLAError("GUIDED_VLA_COT_TRUNCATED")
    if type(original) is not int or type(delivered) is not int or min(original, delivered) < 0 or truncated is not False:
        raise GuidedVLAError("GUIDED_VLA_GUIDANCE_NOT_CONFIRMED")
    chunks, count = value.get("chunk_token_counts"), value.get("chunk_count")
    if chunks is not None:
        if not isinstance(chunks, list) or not chunks or any(type(n) is not int or n < 0 for n in chunks):
            raise GuidedVLAError("GUIDED_VLA_GUIDANCE_NOT_CONFIRMED")
        if sum(chunks) != delivered:
            raise GuidedVLAError("GUIDED_VLA_COT_TRUNCATED")
        if count is not None and (type(count) is not int or count != len(chunks)):
            raise GuidedVLAError("GUIDED_VLA_GUIDANCE_NOT_CONFIRMED")
    elif type(count) is not int or count < 1:
        raise GuidedVLAError("GUIDED_VLA_GUIDANCE_NOT_CONFIRMED")
    return {"status": "PASS", "original_tokens": original, "delivered_tokens": delivered,
            "chunk_count_field_present": count is not None, "view_chunk_slots_derived": len(chunks) if chunks is not None else None,
            "nonempty_chunks_derived": sum(n > 0 for n in chunks) if chunks is not None else None, "truncated": False}


def validate_response(value, sample_id, split):
    try:
        if not isinstance(value, dict) or value["sample_id"] != sample_id or value["split"] != split:
            raise ValueError("Identity")
        for key in ("predicted_path_xyz_mm", "ground_truth_path_xyz_mm"):
            array = value[key]
            if (not isinstance(array, list) or len(array) != 9 or
                    any(not isinstance(p, list) or len(p) != 3 or
                        any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > float(np.finfo(np.float32).max) for v in p) for p in array)):
                raise ValueError("XYZ")
        if not isinstance(value["coordinate_frame"], str) or not value["coordinate_frame"].strip():
            raise ValueError("Frame")
        for key in ("ade_mm", "fde_mm"):
            if type(value[key]) not in (int, float) or not math.isfinite(value[key]):
                raise ValueError("Metric")
        if "guidance_mode" in value and (not isinstance(value["guidance_mode"], str) or
                not value["guidance_mode"].strip() or value["guidance_mode"].strip().lower() == "none"):
            raise ValueError("Guidance not used")
        if not isinstance(value["task_metadata"], dict):
            raise ValueError("Task metadata")
        json.dumps(value["task_metadata"], allow_nan=False)
        validate_cot_delivery(value.get("cot_delivery"))
        fields = set(VLAPredictedTrajectory.model_fields) - {"is_robot_executable", "units", "artifact_id"}
        return VLAPredictedTrajectory.model_validate({k: v for k, v in value.items() if k in fields})
    except (ValueError, KeyError, TypeError, OverflowError):
        raise GuidedVLAError("GUIDED_VLA_RESPONSE_INVALID") from None


def private_metadata(value, token):
    """Preserve metadata structure while excluding credentials/hidden reasoning."""
    if isinstance(value, dict):
        def permitted(key, item):
            name = key.lower().replace("-", "_")
            if any(t in name for t in ("api_key", "authorization", "hidden_reasoning", "api_token", "access_token", "refresh_token", "id_token")):
                return False
            if "token" not in name:
                return True
            # Numeric token-count telemetry is not an authentication credential.
            if not any(t in name for t in ("count", "tokens", "length")):
                return False
            counts = item if isinstance(item, list) else [item]
            return all(type(v) is int and v >= 0 for v in counts)
        return {k: private_metadata(v, token) for k, v in value.items()
                if permitted(k, v)}
    if isinstance(value, (list, tuple)):
        return [private_metadata(v, token) for v in value]
    if isinstance(value, str) and token:
        return value.replace(token, "[REDACTED]")
    return value


class GuidedVLAClient:
    def __init__(self, settings=None, *, transport: GuidedTransport | None = None):
        self.settings = settings or GuidedVLASettings.from_env()
        self.settings.validate()
        self.transport = transport

    def inputs(self):
        try:
            config = read_json(self.settings.inputs)
            if set(config) != {"dataset_root", "binding", "storage_root", "rough_session"}:
                raise ValueError("Backend-owned input contract")
            binding_path, storage = Path(config["binding"]).resolve(), Path(config["storage_root"]).resolve()
            if not binding_path.is_relative_to(ROOT.resolve()) or not storage.is_relative_to(ROOT.resolve()):
                raise ValueError("Inputs must be owned")
            binding = NativeBinding.model_validate(read_json(binding_path))
            if binding.camera != "F":
                raise ValueError("F-only approval contract")
            return config, binding, storage
        except (OSError, ValueError, KeyError, TypeError):
            raise GuidedVLAError("GUIDED_VLA_NOT_CONFIGURED") from None

    def prepare(self):
        config, binding, storage = self.inputs()
        split = resolve_split(config["dataset_root"], binding)
        job, job_path, mask_path, mask = latest_approval(storage, binding)
        try:
            rough = NativeRough3DClient.load_saved(config["rough_session"], binding.sample_id)
        except (OSError, ValueError, KeyError, TypeError, ModelFault):
            raise GuidedVLAError("GUIDED_VLA_GUIDANCE_INVALID") from None
        markdown, direction = serialize_guidance(binding.sample_id, rough.image_guidance_2d, rough.plan)
        if rough.image_guidance_2d["image_size"] != {"width": mask.width, "height": mask.height}:
            raise GuidedVLAError("GUIDED_VLA_GUIDANCE_INVALID")
        components = detect_components(mask, job.mask.min_component_area)
        if len(components.regions) != 1:
            raise GuidedVLAError("GUIDED_VLA_GUIDANCE_INVALID")  # Never flatten separate weld regions.
        points = np.rint(rough.image_guidance_2d["segments"][0]["points_pixel"]).astype(int)
        labels = components.labels
        region = components.regions[0].region_id
        near = [np.any(labels[max(0,y-2):y+3, max(0,x-2):x+3] == region) for x, y in points]
        if sum(near) / len(near) < .8:
            raise GuidedVLAError("GUIDED_VLA_GUIDANCE_INVALID")
        source_names = ("query_image_guidance_2d.json", "reference_trajectory_3d.json", "iteration_001/plan.json")
        source_hashes = {name: sha256(rough.directory / name) for name in source_names}
        mask_data = mask_path.read_bytes()
        attempt = self.settings.attempts.resolve() / str(uuid4())
        attempt.mkdir(parents=True, exist_ok=False)
        (attempt / "masks").mkdir()
        write_bytes(attempt / "guidance.md", markdown.encode("utf-8"))
        write_bytes(attempt / "masks/F_mask.png", mask_data)
        # Byte-copy native geometry artifacts. The 3D reference is never a multipart field.
        for name in source_names[:2]:
            write_bytes(attempt / name, (rough.directory / name).read_bytes())
        files = {name: sha256(attempt / name) for name in
                 ("guidance.md", "masks/F_mask.png", *source_names[:2])}
        manifest = {"schema_version": 1, "attempt_id": attempt.name, "endpoint": self.settings.endpoint,
                    "sample_id": binding.sample_id, "split": split["split"], "primary_camera": "F",
                    "frame": "mask_normalized:F", "direction": direction,
                    "point_count": len(points), "mask_views": ["F"], "files": files,
                    "source_job": str(job_path), "source_job_sha256": sha256(job_path),
                    "source_mask": str(mask_path), "source_mask_id": str(job.mask.id),
                    "source_mask_sha256": digest(mask_data), "mask_pixels_sha256": pixel_hash(mask),
                    "mask_source": job.mask.mask_source, "approved_at": job.mask.approved_at.isoformat(),
                    "native_source_artifact_id": str(job.mask.artifact.provenance.native_source_artifact_id) if job.mask.artifact else None,
                    "rough_session": str(rough.directory), "rough_source_files": source_hashes,
                    "split_resolution": split, "inputs_sha256": sha256(self.settings.inputs),
                    "reference_registered_to_query": False, "reference_in_request": False,
                    "is_robot_executable": False, "live_called": False}
        write_json(attempt / "request_manifest.json", manifest)
        return attempt

    def verify(self, attempt):
        try:
            attempt = Path(attempt).resolve()
            if attempt.parent != self.settings.attempts.resolve() or str(UUID(attempt.name)) != attempt.name:
                raise ValueError("Owned attempt required")
            manifest = read_json(attempt / "request_manifest.json")
            expected_names = {"guidance.md", "masks/F_mask.png", "query_image_guidance_2d.json", "reference_trajectory_3d.json"}
            if (manifest["schema_version"] != 1 or manifest["attempt_id"] != attempt.name or
                    manifest["endpoint"] != self.settings.endpoint or manifest["primary_camera"] != "F" or
                    manifest["reference_registered_to_query"] is not False or manifest["reference_in_request"] is not False or
                    manifest["is_robot_executable"] is not False or manifest["live_called"] is not False or
                    set(manifest["files"]) != expected_names or manifest["mask_views"] != ["F"] or
                    manifest["inputs_sha256"] != sha256(self.settings.inputs)):
                raise ValueError("Request package differs")
            package = {name: (attempt / name).read_bytes() for name in expected_names}
            if any(digest(data) != manifest["files"][name] for name, data in package.items()):
                raise ValueError("Package hash differs")
            config, binding, storage = self.inputs()
            job, job_path, mask_path, mask = latest_approval(storage, binding)
            resolved_split = resolve_split(config["dataset_root"], binding)
            if (manifest["sample_id"] != binding.sample_id or manifest["split"] != resolved_split["split"] or
                    manifest["approved_at"] != job.mask.approved_at.isoformat() or
                    manifest["source_mask"] != str(mask_path) or
                    str(job_path) != manifest["source_job"] or str(job.mask.id) != manifest["source_mask_id"] or
                    manifest["mask_source"] != job.mask.mask_source or manifest["mask_pixels_sha256"] != pixel_hash(mask) or
                    sha256(job_path) != manifest["source_job_sha256"] or sha256(mask_path) != manifest["source_mask_sha256"] or
                    resolved_split != manifest["split_resolution"] or
                    manifest["rough_session"] != str(Path(config["rough_session"]).resolve()) or
                    set(manifest["rough_source_files"]) != {"query_image_guidance_2d.json", "reference_trajectory_3d.json", "iteration_001/plan.json"}):
                raise ValueError("Approval or dataset changed")
            if any(sha256(Path(manifest["rough_session"]) / name) != expected
                   for name, expected in manifest["rough_source_files"].items()):
                raise ValueError("Native source changed")
            guidance = read_json(attempt / "query_image_guidance_2d.json")
            plan = read_json(Path(manifest["rough_session"]) / "iteration_001/plan.json")["plan"]
            markdown, direction = serialize_guidance(binding.sample_id, guidance, plan)
            if (package["guidance.md"] != markdown.encode("utf-8") or manifest["direction"] != direction or
                    manifest["point_count"] != guidance["actual_point_count"] or manifest["frame"] != "mask_normalized:F" or
                    package["masks/F_mask.png"] != mask_path.read_bytes() or
                    any(package[name] != (Path(manifest["rough_session"]) / name).read_bytes()
                        for name in ("query_image_guidance_2d.json", "reference_trajectory_3d.json"))):
                raise ValueError("Serialized input differs")
            return manifest, package
        except (OSError, ValueError, KeyError, TypeError):
            raise GuidedVLAError("GUIDED_VLA_ATTEMPT_CHANGED") from None

    def execute(self, attempt, *, live=False):
        real_http = self.transport is None or isinstance(self.transport, HTTPGuidedTransport)
        if real_http and not live:
            raise GuidedVLAError("GUIDED_VLA_LIVE_DISABLED")
        if real_http and not self.settings.api_token:
            raise GuidedVLAError("GUIDED_VLA_TOKEN_REQUIRED")
        manifest, package = self.verify(attempt)
        attempt = Path(attempt).resolve()
        try:
            write_json(attempt / "submission.json", {"attempt_id": attempt.name, "live_called": real_http})
        except FileExistsError:
            raise GuidedVLAError("GUIDED_VLA_ATTEMPT_ALREADY_SUBMITTED") from None
        files = [("cot", ("guidance.md", BytesIO(package["guidance.md"]), "text/markdown")),
                 ("masks", ("F_mask.png", BytesIO(package["masks/F_mask.png"]), "image/png"))]
        headers = {"X-API-Key": self.settings.api_token} if self.settings.api_token else {}
        try:
            response = (self.transport or HTTPGuidedTransport()).post(
                self.settings.endpoint, data={"sample_id": manifest["sample_id"], "split": manifest["split"]},
                files=files, headers=headers, timeout=self.settings.timeout)
            result = validate_response(response, manifest["sample_id"], manifest["split"])
            result_data = private_metadata(result.model_dump(mode="json"), self.settings.api_token)
            write_json(attempt / "response.json", result_data)
            with (attempt / "trajectory.npz").open("xb") as stream:
                np.savez(stream, predicted_path_m=np.asarray(result.predicted_path_xyz_mm, dtype=np.float32) * np.float32(.001),
                         ground_truth_path_m=np.asarray(result.ground_truth_path_xyz_mm, dtype=np.float32) * np.float32(.001))
            metadata = {"episode_id": result.sample_id, "split": result.split,
                        "artifact_id": str(result.artifact_id), "artifact_type": "VLAPredictedTrajectory",
                        "source_units": "mm", "scale_to_meters": .001,
                        "coordinate_frame": result.coordinate_frame, "is_robot_executable": False,
                        "task_metadata": result_data["task_metadata"], "input_sources": result_data["input_sources"],
                        "guidance": result_data["guidance"], "guidance_mode": result.guidance_mode,
                        "cot_delivery": result_data["cot_delivery"],
                        "source_mask_id": manifest["source_mask_id"], "source_mask_sha256": manifest["source_mask_sha256"],
                        "attempt_id": attempt.name}
            write_json(attempt / "metadata.json", private_metadata(metadata, self.settings.api_token))
            write_json(attempt / "completion.json", {"attempt_id": attempt.name, "response_validated": True,
                                                     "files": {name: sha256(attempt / name) for name in ("response.json", "trajectory.npz", "metadata.json")}})
            return result
        except GuidedVLAError:
            raise
        except Exception:
            raise GuidedVLAError("GUIDED_VLA_REQUEST_FAILED") from None

    def summary(self, attempt):
        manifest, _ = self.verify(attempt)
        return {"attempt_id": manifest["attempt_id"], "sample_id": manifest["sample_id"], "split": manifest["split"],
                "guidance_point_count": manifest["point_count"], "direction": manifest["direction"],
                "mask_views": manifest["mask_views"], "server_url": self.settings.server_url,
                "endpoint": self.settings.endpoint, "source_mask_id": manifest["source_mask_id"],
                "approved_at": manifest["approved_at"], "token_configured": bool(self.settings.api_token),
                "response_expectations": {"sample_id": manifest["sample_id"], "split": manifest["split"],
                                          "xyz_shape": [9, 3], "units": "mm", "finite": True,
                                          "coordinate_frame": "non-empty; not yet simulator-validated"}}
