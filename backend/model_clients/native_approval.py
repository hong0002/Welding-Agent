"""Human-confirmed raster → native mask-session boundary, without skeleton/path inference.

cot.data.load_accepted_session reads status.json and iteration_NNN/result.json polylines,
NOT a PNG. Preserve native vector geometry; only clip it against the current binary mask.
New painted geometry cannot be inferred here and is rejected before any model call.
"""
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
from PIL import Image

from backend.model_clients.contracts import ModelFault


def pixel_hash(mask):
    return hashlib.sha256(mask.mode.encode() + str(mask.size).encode() + mask.tobytes()).hexdigest()


def clipped_predictions(prediction, original, current, components, region_order=None):
    """Clip existing line segments only. Native cot remains the sole rough-point generator."""
    def reject():
        raise ModelFault("NATIVE_MASK_EDIT_UNSUPPORTED")

    if original.mode != current.mode or original.size != current.size:
        reject()
    if np.any((np.asarray(current) == 255) & (np.asarray(original) != 255)):
        reject()  # No inferred centerline for newly painted geometry.
    output, region_ids = [], []
    for polyline in prediction["polylines"]:
        points = np.asarray([[p["x"], p["y"]] for p in polyline["points"]], dtype=float)
        if len(points) < 2:
            continue
        if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
            reject()
        if np.any(points < 0) or np.any(points >= np.asarray(current.size)):
            reject()
        # Dense probes only locate raster clipping boundaries; no route search/skeleton.
        probes = []
        for index, (a, b) in enumerate(zip(points[:-1], points[1:])):
            count = max(1, int(np.ceil(np.max(np.abs(b - a)) * 4)))
            probes.extend(np.linspace(a, b, count + 1)[0 if index == 0 else 1:])
        probes = np.asarray(probes)
        pixels = np.rint(probes).astype(int)
        if np.any(pixels < 0) or np.any(pixels >= np.asarray(current.size)):
            reject()
        labels = components.labels[pixels[:, 1], pixels[:, 0]]
        if len(set(labels.tolist())) == 1 and labels[0] >= 0:
            runs = [(int(labels[0]), points)]  # Unedited paths retain EXACT original vertices.
        else:
            boundaries = np.r_[0, np.flatnonzero(np.diff(labels)) + 1, len(labels)]
            runs = [(int(labels[a]), probes[a:b]) for a, b in zip(boundaries[:-1], boundaries[1:])
                    if labels[a] >= 0 and b - a >= 2]
        for region, vertices in runs:
            # Remove only collinear clipping probes; keep corners and original direction.
            kept = [vertices[0]]
            for i in range(1, len(vertices) - 1):
                a, b = vertices[i] - kept[-1], vertices[i + 1] - vertices[i]
                if abs(a[0] * b[1] - a[1] * b[0]) > 1e-7 or np.dot(a, b) < 0:
                    kept.append(vertices[i])
            kept.append(vertices[-1])
            # For fully retained lines keep even collinear native control points unchanged.
            if len(runs) == 1 and np.array_equal(vertices, points):
                kept = points
            if np.linalg.norm(np.asarray(kept[-1]) - kept[0]) < 1e-7:
                reject()
            output.append({"points": [{"x": float(x), "y": float(y)} for x, y in kept]})
            region_ids.append(region)
    expected = {r.region_id for r in components.regions}
    if not output or len(region_ids) != len(set(region_ids)) or set(region_ids) != expected:
        reject()  # No bridged paths, missing painted islands, or multiple paths per component.
    if region_order is not None:
        if not region_order or len(region_order)!=len(set(region_order)) or not set(region_order)<=expected:reject()
        by_region=dict(zip(region_ids,output));output=[by_region[r] for r in region_order]
    return {"camera_id": prediction["camera_id"], "polylines": output}


class ApprovedMaskSessions:
    def __init__(self, records):
        self.records = Path(records).resolve()
        self.root = self.records / "approved"

    def prepare(self, binding, mask, metadata, components, *, carry_yolo=False, region_order=None):
        from backend.model_clients.native import read_json, sha256

        if metadata is None or not metadata.approved or metadata.approved_at is None:
            raise ModelFault("NATIVE_MASK_NOT_APPROVED")
        meta = metadata.artifact.provenance if metadata.artifact else None
        if not meta or not meta.native_source_artifact_id:
            raise ModelFault("NATIVE_MASK_EDIT_UNSUPPORTED")
        try:
            record = read_json(self.records / f"{UUID(str(meta.native_source_artifact_id))}.json")
            source = Path(record["directory"]).resolve()
            if record["stage"] != "segment" or record["sample_id"] != binding.sample_id:
                raise ValueError("Wrong native lineage")
            result_name = "iteration_001/result.json"
            mask_name = f"iteration_001/{binding.camera}_prediction.png"
            for name in (result_name, mask_name):
                if sha256(source / name) != record["files"][name]:
                    raise ValueError("Native artifact changed")
            native = read_json(source / result_name)
            with Image.open(source / mask_name) as im:
                original = im.copy()
            prediction = clipped_predictions(native["predictions"][binding.camera], original, mask, components,region_order)
            # Only reviewed views enter the input. The map supports more approved views later.
            payload = {"sample_id": binding.sample_id, "instruction": native["instruction"],
                       "predictions": {binding.camera: prediction}}
            session_id = uuid4()
            session = self.root / str(session_id)
            iteration = session / "iteration_001"
            iteration.mkdir(parents=True, exist_ok=False)
            def write(path, value):
                with path.open("x", encoding="utf-8") as stream:
                    json.dump(value, stream, ensure_ascii=False, indent=2)
            write(iteration / "result.json", payload)
            # Real recorded confirmation above is required. Native --once alone never reaches here.
            write(session / "status.json", {"status": "ok", "accepted_iteration": 1})
            proof = {"schema_version": 1, "session_id": str(session_id), "sample_id": binding.sample_id,
                     "approved_views": [binding.camera], "source_native_artifact_id": str(meta.native_source_artifact_id),
                     "source_native_session_id": source.name, "mask_id": str(metadata.id),
                     "mask_source": metadata.mask_source, "approved_at": metadata.approved_at.isoformat(),
                     "mask_pixels_sha256": pixel_hash(mask), "min_component_area": metadata.min_component_area,
                     "transform": "native_polylines_clipped_to_confirmed_binary; no skeleton or rough generation",
                     "region_order":region_order,
                     "files": {name: sha256(session / name) for name in ("status.json", result_name)}}
            yolo_name = 'yolo/detections.json'
            if carry_yolo and (source/yolo_name).is_file():
                if sha256(source/yolo_name) != record['files'][yolo_name]:
                    raise ValueError('Native YOLO artifact changed')
                detection = read_json(source/yolo_name)
                if detection.get('sample_id') != binding.sample_id or detection.get('bbox_source') != 'server_yolo':
                    raise ValueError('Native YOLO identity differs')
                (session/'yolo').mkdir()
                with (session/yolo_name).open('xb') as stream:
                    stream.write((source/yolo_name).read_bytes())
                proof['files'][yolo_name] = sha256(session/yolo_name)
                proof['yolo_source_sha256'] = record['files'][yolo_name]
            # Provenance is outside the native-format session. No fabricated native metrics/response IDs.
            write(self.root / f"{session_id}.json", proof)
            return session, payload, proof
        except ModelFault:
            raise
        except (OSError, ValueError, KeyError, TypeError):
            raise ModelFault("NATIVE_INPUT_MISMATCH") from None

    def verify(self, session, mask, metadata):
        from backend.model_clients.native import read_json, sha256
        try:
            session = Path(session).resolve()
            if session.parent != self.root:
                raise ValueError("Not an owned approved session")
            proof = read_json(self.root / f"{UUID(session.name)}.json")
            if (not metadata.approved or proof["mask_id"] != str(metadata.id)
                    or proof["mask_pixels_sha256"] != pixel_hash(mask)
                    or proof["approved_at"] != metadata.approved_at.isoformat()):
                raise ValueError("Approval differs")
            for name in proof['files']:
                if sha256(session / name) != proof["files"][name]:
                    raise ValueError("Approved session changed")
            return proof
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise ModelFault("NATIVE_INPUT_MISMATCH") from None
