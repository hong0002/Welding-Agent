from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from trajectory import CAMERAS


@dataclass(frozen=True)
class SampleData:
    sample_id: str
    images: dict[str, Path]
    gt_polylines: dict[str, list[list[list[float]]]]
    metadata: dict


@dataclass(frozen=True)
class AcceptedMaskSession:
    path: Path
    sample_id: str
    instruction: str
    accepted_iteration: int
    polylines: dict[str, list[list[list[float]]]]


def camera_from_filename(filename: str) -> str | None:
    for camera in CAMERAS:
        if filename.endswith(f"_{camera}_Color.png"):
            return camera
    return None


def load_sample(data_root: Path, sample_id: str) -> SampleData:
    nia_root = data_root / "2.데이터(NIA)"
    matches = list(nia_root.rglob(f"{sample_id}.json"))
    if len(matches) != 1:
        raise RuntimeError(f"JSON을 하나로 결정할 수 없습니다: {sample_id} ({len(matches)}개)")
    json_path = matches[0]
    payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
    split_root = next(parent for parent in json_path.parents if parent.name in {"Training", "Validation"})
    source_root = split_root / "01.원천데이터"
    sample_dirs = [path for path in source_root.rglob(sample_id) if path.is_dir()]
    if len(sample_dirs) != 1:
        raise RuntimeError(f"이미지 폴더를 하나로 결정할 수 없습니다: {sample_id}")
    sample_dir = sample_dirs[0]
    images = {}
    for item in payload.get("rgb_images", []):
        filename = str(item.get("filename", ""))
        camera = camera_from_filename(filename)
        path = sample_dir / filename
        if camera and path.is_file():
            images[camera] = path
    polylines = {}
    for annotation in payload.get("annotation_image", []):
        camera = camera_from_filename(str(annotation.get("image_filename", "")))
        if not camera:
            continue
        paths = []
        for label in annotation.get("image_label", []):
            if label.get("type") == "polyline" and label.get("label") == "full_welding":
                points = label.get("points", [])
                if len(points) >= 2:
                    paths.append([[float(x), float(y)] for x, y in points])
        if paths:
            polylines[camera] = paths
    return SampleData(sample_id, images, polylines, dict(payload.get("categories", {})))


def load_accepted_session(path: Path) -> AcceptedMaskSession:
    path = path.expanduser().resolve()
    status_path = path / "status.json"
    if not status_path.is_file():
        raise RuntimeError(f"승인 상태 파일이 없습니다: {status_path}")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if status.get("status") != "ok":
        raise RuntimeError(f"승인되지 않은 마스크 세션입니다: {path}")
    iteration = int(status["accepted_iteration"])
    result_path = path / f"iteration_{iteration:03d}" / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    polylines = {}
    for camera, prediction in result.get("predictions", {}).items():
        paths = []
        for polyline in prediction.get("polylines", []):
            points = polyline.get("points", [])
            if len(points) >= 2:
                paths.append([[float(point["x"]), float(point["y"])] for point in points])
        if paths:
            polylines[camera] = paths
    if not polylines:
        raise RuntimeError("승인된 예측 마스크에 polyline이 없습니다")
    return AcceptedMaskSession(
        path=path,
        sample_id=str(result["sample_id"]),
        instruction=str(result["instruction"]),
        accepted_iteration=iteration,
        polylines=polylines,
    )


def list_accepted_sessions(root: Path) -> list[Path]:
    result = []
    if not root.is_dir():
        return result
    for path in sorted(root.iterdir(), reverse=True):
        status = path / "status.json"
        if not status.is_file():
            continue
        try:
            payload = json.loads(status.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("status") == "ok":
            result.append(path)
    return result


def image_data_url(path: Path, max_side: int = 1800, quality: int = 90) -> str:
    with Image.open(path) as source:
        image = source.convert("RGB")
    if max(image.size) > max_side:
        scale = max_side / max(image.size)
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
