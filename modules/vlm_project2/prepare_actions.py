#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import h5py
import numpy as np
import yaml
from tqdm import tqdm

from trajectory import (
    CAMERAS,
    SplitConfig,
    dominant_direction,
    mask_descriptor,
    polyline_length,
    serialize_points,
    simplify_segments,
    split_discontinuous,
    trajectory_shape,
)


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = PROJECT_DIR / "config" / "config.yaml"

JOINT_KO = {"butt": "맞대기", "lap": "겹치기", "tee": "T형", "t": "T형", "corner": "모서리"}
MATERIAL_KO = {"plate": "평판", "round": "원형 부품", "structural": "구조용 부재"}
SIZE_KO = {"S": "소형", "M": "중형", "L": "대형"}
SPLIT_DIR = {"train": "Training", "valid": "Validation"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="용접 H5 액션·검색 텍스트 번들 생성")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--split", nargs="+", choices=("train", "valid"), default=("train", "valid"))
    return parser.parse_args()


def camera_from_filename(filename: str) -> str | None:
    for camera in CAMERAS:
        if filename.endswith(f"_{camera}_Color.png"):
            return camera
    return None


def extract_masks(payload: dict) -> tuple[dict, dict]:
    image_sizes = {}
    for item in payload.get("rgb_images", []):
        camera = camera_from_filename(str(item.get("filename", "")))
        if camera:
            image_sizes[camera] = (int(item.get("rgb_width", 1)), int(item.get("rgb_height", 1)))
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
    return polylines, image_sizes


def material_phrases(parent_metal: str) -> tuple[str, str]:
    parts = parent_metal.lower().split("-")
    en = " and ".join(parts) + " workpieces"
    ko_parts = [MATERIAL_KO.get(part, part) for part in parts]
    ko = "과 ".join(ko_parts)
    return ko, en


def build_texts(categories: dict, interpolation: str, segments: list[np.ndarray]) -> dict:
    joint = str(categories.get("metal_position", "weld")).lower()
    joint_ko = JOINT_KO.get(joint, joint)
    material_ko, material_en = material_phrases(str(categories.get("parent_metal", "unknown")))
    thickness = str(categories.get("metal_thickness", "unknown"))
    size_code = str(categories.get("object_size", "unknown"))
    thickness_ko = "혼합 두께" if thickness == "M" else f"공칭 두께 {thickness} mm"
    thickness_en = "mixed thickness" if thickness == "M" else f"nominal thickness {thickness} mm"
    size_ko = SIZE_KO.get(size_code, size_code)
    shape_id, shape_ko, shape_en = trajectory_shape(np.concatenate(segments), interpolation)
    _, direction_ko, direction_en = dominant_direction(np.concatenate(segments))
    if len(segments) == 1:
        continuity_ko = "하나의 연속된"
        continuity_en = "one continuous"
    else:
        continuity_ko = f"서로 떨어진 {len(segments)}개의"
        continuity_en = f"{len(segments)} disconnected"
    task_ko = f"{material_ko} 사이의 {joint_ko} 접합부를 용접한다. {size_ko}, {thickness_ko}."
    task_en = f"Weld the {joint} joint between {material_en}. {size_code} size, {thickness_en}."
    action_ko = f"{continuity_ko} {shape_ko} 경로를 따르며, 전체 진행은 주로 {direction_ko}이다."
    action_en = f"Follow {continuity_en} {shape_en} path segment(s), traveling primarily in {direction_en}."
    return {
        "task_text_ko": task_ko,
        "task_text_en": task_en,
        "action_text_ko": action_ko,
        "action_text_en": action_en,
        "search_text_ko": f"{task_ko} {action_ko}",
        "search_text_en": f"{task_en} {action_en}",
        "path_shape": shape_id,
    }


def build_record(json_path: Path, h5_path: Path, split: str, settings: dict) -> dict:
    payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
    sample_id = str(payload.get("info", {}).get("gid") or json_path.stem)
    categories = payload.get("categories", {})
    polylines, image_sizes = extract_masks(payload)
    with h5py.File(h5_path, "r") as handle:
        raw = np.asarray(handle["trajectory"], dtype=np.float64)
        interpolation = handle["interpolation_type"][()]
    if isinstance(interpolation, bytes):
        interpolation = interpolation.decode("utf-8")
    if raw.ndim != 2 or raw.shape[0] < 2 or raw.shape[1] not in (3, 6):
        raise ValueError(f"unexpected trajectory shape {raw.shape}")
    xyz = raw[:, :3]
    split_config = SplitConfig(
        absolute_jump=float(settings["discontinuity"]["absolute_jump_mm"]),
        relative_jump_ratio=float(settings["discontinuity"]["relative_jump_ratio"]),
        duplicate_epsilon=float(settings["discontinuity"].get("duplicate_epsilon_mm", 1e-6)),
    )
    source_segments, split_info = split_discontinuous(xyz, split_config)
    rough_segments, budget_info = simplify_segments(source_segments, int(settings["target_points"]))
    origin = xyz[0]
    rough = []
    for index, (source, simplified) in enumerate(zip(source_segments, rough_segments)):
        direction_id, direction_ko, direction_en = dominant_direction(source)
        rough.append(
            {
                "segment_id": f"segment_{index}",
                "connected_to_next": False,
                "source_point_count": int(len(source)),
                "source_length_mm": round(polyline_length(source), 4),
                "direction": direction_id,
                "direction_ko": direction_ko,
                "direction_en": direction_en,
                "points_source_mm": serialize_points(simplified),
                "points_start_relative_mm": serialize_points(simplified - origin),
            }
        )
    texts = build_texts(categories, str(interpolation), source_segments)
    thickness = str(categories.get("metal_thickness", ""))
    return {
        "schema_version": "welding-action-record-v1",
        "sample_id": sample_id,
        "split": split,
        "metadata": {
            "joint_type": str(categories.get("metal_position", "")).lower(),
            "material_pair": str(categories.get("parent_metal", "")).lower(),
            "object_size": str(categories.get("object_size", "")),
            "thickness_code": thickness,
            "thickness_mm": None if thickness == "M" or not thickness.isdigit() else int(thickness),
            "interpolation_type": str(interpolation),
            "path_shape": texts.pop("path_shape"),
        },
        "mask": {
            "available_views": [camera for camera in CAMERAS if camera in polylines],
            "descriptor": mask_descriptor(polylines, image_sizes),
        },
        "source_trajectory": {
            "point_count": int(raw.shape[0]),
            "dimension": int(raw.shape[1]),
            "xyz_length_mm": round(sum(polyline_length(segment) for segment in source_segments), 4),
            "segment_count": len(source_segments),
            **split_info,
        },
        "rough_action": {
            **budget_info,
            "coordinate_frame": "source_start_relative_mm",
            "segments": rough,
        },
        "texts": texts,
    }


def main() -> None:
    args = parse_args()
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    data_root = Path(config["data"]["root"]).expanduser().resolve()
    output = (args.output or Path(config["action_bundle"]["output"])).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    h5_root = data_root / "1.데이터" / "Other"
    nia_root = data_root / "2.데이터(NIA)"
    h5_index = {path.stem: path for path in h5_root.rglob("*.h5")}
    records = []
    failures = []
    counts = Counter()
    for split in args.split:
        json_root = nia_root / SPLIT_DIR[split] / "02.라벨링데이터"
        paths = sorted(json_root.rglob("*.json"))
        for json_path in tqdm(paths, desc=f"prepare {split}", unit="sample"):
            h5_path = h5_index.get(json_path.stem)
            if h5_path is None:
                failures.append({"sample_id": json_path.stem, "error": "missing_h5"})
                continue
            try:
                record = build_record(json_path, h5_path, split, config["rough_trajectory"])
            except Exception as exc:
                failures.append({"sample_id": json_path.stem, "error": str(exc)})
                continue
            records.append(record)
            counts[split] += 1
    records.sort(key=lambda item: item["sample_id"])
    with (output / "actions.jsonl").open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    summary = {
        "schema_version": "welding-action-bundle-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_root": str(data_root),
        "record_counts": dict(counts),
        "records": len(records),
        "failures": failures,
        "rough_trajectory_config": config["rough_trajectory"],
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[SAVE] {output / 'actions.jsonl'}")
    print(f"[SUMMARY] records={len(records)} failures={len(failures)} counts={dict(counts)}")


if __name__ == "__main__":
    main()
