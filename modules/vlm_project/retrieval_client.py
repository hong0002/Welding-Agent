from __future__ import annotations

import json
import re
import shlex
import subprocess
import io
import tarfile
import uuid
from dataclasses import dataclass
from pathlib import Path


SAMPLE_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class RetrievalConfig:
    ssh_alias: str
    remote_root: str
    remote_python: str
    top_k: int = 3
    bbox_source: str = "server_yolo"
    yolo_python: str = "/path/to/yolo-python"
    yolo_weights: str = "service/weights/work_target_v2-2/best.pt"
    confidence: float = 0.25
    margin: float = 0.10
    yolo_device: str = "0"


def remote_json(config: RetrievalConfig, command: str) -> dict:
    completed = subprocess.run(["ssh", "-o", "BatchMode=yes", config.ssh_alias, command],
                               check=False, text=True, capture_output=True)
    payload = None
    for line in reversed(completed.stdout.splitlines()):
        try:
            payload = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    if completed.returncode != 0 or not isinstance(payload, dict):
        detail = (payload.get("error") if isinstance(payload, dict) else None) or completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"서버 처리 실패(exit={completed.returncode}): {detail}")
    if payload.get("error"):
        raise RuntimeError(f"서버 처리 실패: {payload['error']}")
    return payload


def detect_images(config: RetrievalConfig, sample_id: str, images: dict[str, Path], output: Path) -> dict:
    from PIL import Image, ImageDraw
    from mask_data import CAMERAS, save_contact_sheet

    if not images or any(camera not in CAMERAS for camera in images):
        raise ValueError("유효한 카메라 이미지가 필요합니다")
    request_id = uuid.uuid4().hex
    root = config.remote_root.rstrip("/")
    remote_dir = f"{root}/incoming/yolo_requests/{request_id}"
    manifest = {"sample_id": sample_id, "request_id": request_id, "images": {}}
    for camera, path in images.items():
        if not path.is_file() or path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            raise ValueError(f"이미지 파일을 확인하세요: {path}")
        manifest["images"][camera] = camera + path.suffix.lower()
    # One stream for all views; fixed archive names, no label files or API keys.
    print(f"[UPLOAD] {len(images)} cameras → {config.ssh_alias} request={request_id}", flush=True)
    command = f"mkdir -p {shlex.quote(remote_dir)} && tar -xf - -C {shlex.quote(remote_dir)}"
    with subprocess.Popen(["ssh", "-o", "BatchMode=yes", config.ssh_alias, command], stdin=subprocess.PIPE) as process:
        try:
            with tarfile.open(fileobj=process.stdin, mode="w|") as archive:
                for camera, path in images.items():
                    archive.add(path, arcname=manifest["images"][camera], recursive=False)
                data = json.dumps(manifest).encode("utf-8")
                entry = tarfile.TarInfo("request.json"); entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
        finally:
            process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("서버 이미지 전송 실패")
    weights = config.yolo_weights if config.yolo_weights.startswith("/") else root + "/" + config.yolo_weights
    args = [config.yolo_python, "-m", "service.detect", "--request", remote_dir + "/request.json",
            "--weights", weights, "--confidence", str(config.confidence), "--margin", str(config.margin),
            "--device", config.yolo_device]
    print("[YOLO] 서버 작업 대상 탐지", flush=True)
    detections = remote_json(config, f"cd {shlex.quote(root)} && " + shlex.join(args))
    output.mkdir(parents=True, exist_ok=True)
    (output / "detections.json").write_text(json.dumps(detections, ensure_ascii=False, indent=2), encoding="utf-8")
    previews = []
    for camera, item in detections["cameras"].items():
        with Image.open(images[camera]) as original:
            image = original.convert("RGB")
        draw = ImageDraw.Draw(image)
        for box in item["boxes"]:
            draw.rectangle(box["xyxy"], outline="lime", width=4)
            draw.text(tuple(box["xyxy"][:2]), f'{box["confidence"]:.3f}', fill="yellow", stroke_width=1, stroke_fill="black")
        if item.get("crop_xyxy"):
            draw.rectangle(item["crop_xyxy"], outline="cyan", width=3)
        draw.text((16, 16), f'{camera}: {item["status"]}', fill="yellow", stroke_width=2, stroke_fill="black")
        path = output / f"{camera}.jpg"; image.save(path); previews.append(path)
        print(f'[YOLO] {camera}: {item["status"]}, boxes={len(item["boxes"])}', flush=True)
    save_contact_sheet(previews, output / "detections_all.jpg", columns=3)
    print(f'[YOLO VIEW] {output / "detections_all.jpg"}', flush=True)
    if not any(item["status"] == "detected" for item in detections["cameras"].values()):
        raise RuntimeError(f"모든 카메라에서 작업 대상 미탐지. 라벨 대체 없이 중단합니다: {output}")
    return detections


def retrieve_sample(config: RetrievalConfig, sample_id: str, *, images: dict[str, Path] | None = None,
                    output_dir: Path | None = None) -> dict:
    if not SAMPLE_ID_RE.fullmatch(sample_id):
        raise ValueError(f"잘못된 sample_id 형식입니다: {sample_id}")
    root = config.remote_root.rstrip("/")
    python = config.remote_python
    detection = None
    query_arg = ""
    if config.bbox_source == "server_yolo":
        if images is None or output_dir is None:
            raise ValueError("server_yolo 검색에는 images와 output_dir가 필요합니다")
        detection = detect_images(config, sample_id, images, output_dir / "yolo")
        query_arg = " --query-manifest " + shlex.quote(detection["manifest_path"])
    elif config.bbox_source != "database":
        raise ValueError(f"지원하지 않는 bbox_source: {config.bbox_source}")
    command = (
        f"cd {shlex.quote(root)} && "
        f"PYTHONPATH={shlex.quote(root + ':' + root + '/incoming/code')} "
        f"{shlex.quote(python)} -m service.retrieve "
        f"--sample-id {shlex.quote(sample_id)} --top-k {int(config.top_k)}{query_arg}"
    )
    payload = remote_json(config, command)
    if detection:
        payload["detection"] = detection
    leaked_ids = [
        item.get("sample_id")
        for item in payload.get("results", [])
        if item.get("sample_id") == sample_id
    ]
    if leaked_ids:
        raise RuntimeError(f"서버 검색 결과에 현재 샘플이 포함됐습니다: {sample_id}")
    return payload
