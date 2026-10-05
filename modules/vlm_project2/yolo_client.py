"""Use the same server detector as vlm_project; reuse only explicit upstream input."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from PIL import Image


def detector_module():
    name = "welding_shared_yolo_client"
    if name not in sys.modules:
        sibling = Path(__file__).resolve().parents[1] / "vlm_project"
        if not (sibling / "retrieval_client.py").is_file():
            raise RuntimeError("공유 YOLO 클라이언트가 필요합니다: ../vlm_project/retrieval_client.py")
        if str(sibling) not in sys.path:
            sys.path.append(str(sibling))
        spec = importlib.util.spec_from_file_location(name, sibling / "retrieval_client.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def prepare_yolo(config: dict, sample, output: Path, previous_stage: Path | None = None) -> dict:
    module = detector_module()
    server, yolo = config["server"], config.get("yolo", {})
    settings = module.RetrievalConfig(
        ssh_alias=server["ssh_alias"], remote_root=server["remote_root"],
        remote_python=server["remote_python"],
        yolo_python=yolo.get("remote_python", "/path/to/yolo-python"),
        yolo_weights=yolo.get("weights", "service/weights/work_target_v2-2/best.pt"),
        confidence=float(yolo.get("confidence", .25)), margin=float(yolo.get("margin", .1)),
        yolo_device=str(yolo.get("device", "0")),
    )
    # Never search old sessions or caches by sample ID. Only the caller-supplied
    # accepted upstream session is eligible. Old sessions without YOLO run it now.
    previous = previous_stage / "yolo/detections.json" if previous_stage else None
    if previous is not None and previous.is_file():
        detection = json.loads(previous.read_text(encoding="utf-8"))
        if detection.get("sample_id") != sample.sample_id or detection.get("bbox_source") != "server_yolo":
            raise ValueError("이전 단계 YOLO 결과의 샘플/출처가 일치하지 않습니다")
        if set(detection["cameras"]) != set(sample.images):
            raise ValueError("이전 단계 YOLO의 카메라 구성이 현재 입력과 다릅니다")
        for camera, item in detection["cameras"].items():
            with Image.open(sample.images[camera]) as image:
                if image.size != (item["width"], item["height"]):
                    raise ValueError(f"이전 YOLO 이미지 크기가 다릅니다: {camera}")
        manifest = Path(detection["manifest_path"])
        manifest.relative_to(Path(server["remote_root"]) / "incoming/yolo_requests")
        if not any(v["status"] == "detected" for v in detection["cameras"].values()):
            raise ValueError("이전 YOLO 결과가 모두 미탐지입니다")
        print(f"[YOLO REUSE] explicit previous stage: {previous_stage}", flush=True)
        output.mkdir(parents=True, exist_ok=True)
        (output / "detections.json").write_text(json.dumps(detection, ensure_ascii=False, indent=2), encoding="utf-8")
        mode = "explicit_previous_stage"
    else:
        print("[YOLO NEW] 이전 YOLO 결과를 자동 검색하지 않고 새로 추론합니다", flush=True)
        detection = module.detect_images(settings, sample.sample_id, sample.images, output)
        mode = "new_inference"
    provenance = {"mode": mode, "previous_stage": str(previous_stage) if previous_stage else None,
                  "ssh_alias": server["ssh_alias"], "manifest_path": detection["manifest_path"]}
    (output / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    return detection
