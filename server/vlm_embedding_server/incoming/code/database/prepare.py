#!/usr/bin/env python3
"""기존 YOLO 사람 라벨에서 full/crop 이미지 DB 번들을 만든다."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
from tqdm import tqdm

from .common import CAMERAS, parse_image_name, parse_sample_metadata, relative_path


SPLIT_DIRS = {"train": "Training", "valid": "Validation"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="용접 검색 DB용 이미지·crop·manifest 생성")
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--label-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", nargs="+", choices=("train", "valid"), default=["train"])
    parser.add_argument("--margin", type=float, default=0.10, help="bbox 각 방향 여백 비율")
    parser.add_argument("--dataset-version", default="welding_nia_v1")
    parser.add_argument(
        "--restart",
        action="store_true",
        help="기존 출력 폴더를 지우고 처음부터 다시 생성",
    )
    return parser.parse_args()


def read_yolo_boxes(label_path: Path, width: int, height: int) -> list[dict]:
    boxes: list[dict] = []
    for line_number, raw_line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"{label_path}:{line_number}: YOLO 값은 5개여야 합니다")
        class_id = int(parts[0])
        cx, cy, bw, bh = map(float, parts[1:])
        if not all(0.0 <= value <= 1.0 for value in (cx, cy, bw, bh)):
            raise ValueError(f"{label_path}:{line_number}: 정규화 좌표 범위 오류")
        x1 = max(0, min(width, round((cx - bw / 2.0) * width)))
        y1 = max(0, min(height, round((cy - bh / 2.0) * height)))
        x2 = max(0, min(width, round((cx + bw / 2.0) * width)))
        y2 = max(0, min(height, round((cy + bh / 2.0) * height)))
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"{label_path}:{line_number}: 빈 bbox")
        boxes.append({"class_id": class_id, "xyxy": [x1, y1, x2, y2]})
    return boxes


def expand_box(box: list[int], width: int, height: int, margin: float) -> list[int]:
    x1, y1, x2, y2 = box
    dx = (x2 - x1) * margin
    dy = (y2 - y1) * margin
    return [
        max(0, int(x1 - dx)),
        max(0, int(y1 - dy)),
        min(width, int(x2 + dx + 0.9999)),
        min(height, int(y2 + dy + 0.9999)),
    ]


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS records (
            record_id TEXT PRIMARY KEY,
            sample_id TEXT NOT NULL,
            split TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            joint_type TEXT,
            material_pair TEXT,
            thickness_mm INTEGER,
            sample_number TEXT,
            image_width INTEGER,
            image_height INTEGER,
            full_image_path TEXT,
            target_image_path TEXT,
            label_path TEXT,
            bboxes_json TEXT NOT NULL,
            primary_bbox_json TEXT,
            crop_bbox_json TEXT,
            bbox_source TEXT NOT NULL,
            bbox_status TEXT NOT NULL,
            crop_status TEXT NOT NULL,
            record_status TEXT NOT NULL,
            error_reason TEXT,
            dataset_version TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_records_camera_split
            ON records(camera_id, split, record_status);
        CREATE INDEX IF NOT EXISTS idx_records_sample ON records(sample_id);
        CREATE TABLE IF NOT EXISTS build_info (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )


def write_manifest_from_database(connection: sqlite3.Connection, manifest_path: Path) -> None:
    temporary_path = manifest_path.with_suffix(".jsonl.tmp")
    rows = connection.execute("SELECT * FROM records ORDER BY split, sample_id, camera_id")
    with temporary_path.open("w", encoding="utf-8") as manifest:
        for row in rows:
            values = dict(row)
            record = {
                "record_id": values["record_id"],
                "sample_id": values["sample_id"],
                "split": values["split"],
                "camera_id": values["camera_id"],
                "joint_type": values["joint_type"],
                "material_pair": values["material_pair"],
                "thickness_mm": values["thickness_mm"],
                "sample_number": values["sample_number"],
                "image_width": values["image_width"],
                "image_height": values["image_height"],
                "full_image_path": values["full_image_path"],
                "target_image_path": values["target_image_path"],
                "label_path": values["label_path"],
                "bboxes": json.loads(values["bboxes_json"]),
                "primary_bbox": json.loads(values["primary_bbox_json"]),
                "crop_bbox": json.loads(values["crop_bbox_json"]),
                "bbox_source": values["bbox_source"],
                "bbox_status": values["bbox_status"],
                "crop_status": values["crop_status"],
                "record_status": values["record_status"],
                "error_reason": values["error_reason"],
                "dataset_version": values["dataset_version"],
                "created_at": values["created_at"],
            }
            manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
    temporary_path.replace(manifest_path)


def upsert_record(connection: sqlite3.Connection, record: dict) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO records VALUES (
            :record_id, :sample_id, :split, :camera_id, :joint_type,
            :material_pair, :thickness_mm, :sample_number,
            :image_width, :image_height, :full_image_path,
            :target_image_path, :label_path, :bboxes_json,
            :primary_bbox_json, :crop_bbox_json, :bbox_source,
            :bbox_status, :crop_status, :record_status,
            :error_reason, :dataset_version, :created_at
        )
        """,
        {
            **record,
            "bboxes_json": json.dumps(record["bboxes"]),
            "primary_bbox_json": json.dumps(record["primary_bbox"]),
            "crop_bbox_json": json.dumps(record["crop_bbox"]),
        },
    )


def restore_manifest_checkpoints(
    connection: sqlite3.Connection, manifest_path: Path, output: Path
) -> int:
    """이전 버전이 남긴 manifest를 SQLite 체크포인트로 복구한다."""
    if not manifest_path.is_file():
        return 0
    restored = 0
    with manifest_path.open("r", encoding="utf-8") as manifest:
        for line in manifest:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if connection.execute(
                "SELECT 1 FROM records WHERE record_id = ?", (record.get("record_id"),)
            ).fetchone():
                continue
            complete = record.get("record_status") == "invalid"
            if record.get("record_status") == "valid":
                complete = all(
                    stored and (output / stored).is_file()
                    for stored in (
                        record.get("full_image_path"),
                        record.get("target_image_path"),
                    )
                )
            if complete:
                upsert_record(connection, record)
                restored += 1
    connection.commit()
    return restored


def main() -> None:
    args = parse_args()
    dataset_root = args.dataset_root.expanduser().resolve()
    label_root = args.label_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not dataset_root.is_dir():
        raise SystemExit(f"원본 데이터 폴더가 없습니다: {dataset_root}")
    if not label_root.is_dir():
        raise SystemExit(f"라벨 폴더가 없습니다: {label_root}")
    if not 0.0 <= args.margin <= 1.0:
        raise SystemExit("--margin은 0.0~1.0 범위여야 합니다")
    if args.restart and output.exists():
        shutil.rmtree(output)

    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.jsonl"
    database_path = output / "metadata.sqlite"
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    create_schema(connection)
    restored = restore_manifest_checkpoints(connection, manifest_path, output)
    if restored:
        print(f"[RESUME] 이전 manifest에서 체크포인트 {restored}개 복구")
    created_at = datetime.now(timezone.utc).isoformat()
    resumed = 0

    for split in args.split:
        split_dir = SPLIT_DIRS[split]
        label_paths = sorted((label_root / split_dir).rglob("*_Color.txt"))
        progress = tqdm(
            label_paths,
            desc=f"prepare {split}",
            unit="image",
            dynamic_ncols=True,
        )
        for label_path in progress:
            relative_label = label_path.relative_to(label_root)
            image_path = (dataset_root / relative_label).with_suffix(".png")
            record: dict = {
                "split": split,
                "label_path": relative_label.as_posix(),
                "bbox_source": "human_label",
                "dataset_version": args.dataset_version,
                "created_at": created_at,
            }
            try:
                sample_id, camera_id = parse_image_name(label_path)
                if camera_id not in CAMERAS:
                    raise ValueError(f"지원하지 않는 카메라: {camera_id}")
                record_id = f"{sample_id}:{camera_id}"
                joint_type, material_pair, thickness, sample_number = parse_sample_metadata(sample_id)
                record.update(
                    record_id=record_id,
                    sample_id=sample_id,
                    camera_id=camera_id,
                    joint_type=joint_type,
                    material_pair=material_pair,
                    thickness_mm=thickness,
                    sample_number=sample_number,
                )
                previous = connection.execute(
                    "SELECT record_status, full_image_path, target_image_path "
                    "FROM records WHERE record_id = ?",
                    (record_id,),
                ).fetchone()
                if previous is not None:
                    previous_complete = previous["record_status"] == "invalid"
                    if previous["record_status"] == "valid":
                        previous_complete = all(
                            stored and (output / stored).is_file()
                            for stored in (
                                previous["full_image_path"],
                                previous["target_image_path"],
                            )
                        )
                    if previous_complete:
                        resumed += 1
                        progress.set_postfix_str(f"resume-skip={resumed}")
                        continue

                if not image_path.is_file():
                    raise ValueError(f"원본 이미지 없음: {image_path}")
                with Image.open(image_path) as source:
                    image = source.convert("RGB")
                width, height = image.size
                boxes = read_yolo_boxes(label_path, width, height)
                if not boxes:
                    raise ValueError("라벨에 bbox가 없음")
                primary = max(
                    boxes,
                    key=lambda item: (item["xyxy"][2] - item["xyxy"][0])
                    * (item["xyxy"][3] - item["xyxy"][1]),
                )
                crop_bbox = expand_box(primary["xyxy"], width, height, args.margin)
                safe_name = f"{sample_id}__{camera_id}.png"
                full_path = output / "images" / "full" / split / camera_id / safe_name
                target_path = output / "images" / "target" / split / camera_id / safe_name
                full_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(image_path, full_path)
                image.crop(tuple(crop_bbox)).save(target_path)
                record.update(
                    image_width=width,
                    image_height=height,
                    full_image_path=relative_path(full_path, output),
                    target_image_path=relative_path(target_path, output),
                    bboxes=boxes,
                    primary_bbox=primary["xyxy"],
                    crop_bbox=crop_bbox,
                    bbox_status="valid",
                    crop_status="valid",
                    record_status="valid",
                    error_reason=None,
                )
            except (OSError, ValueError) as exc:
                fallback_token = hashlib.sha1(
                    relative_label.as_posix().encode("utf-8")
                ).hexdigest()[:12]
                fallback_id = record.get("record_id", f"invalid:{fallback_token}")
                record.update(
                    record_id=fallback_id,
                    sample_id=record.get("sample_id", label_path.parent.name),
                    camera_id=record.get("camera_id", "unknown"),
                    joint_type=record.get("joint_type"),
                    material_pair=record.get("material_pair"),
                    thickness_mm=record.get("thickness_mm"),
                    sample_number=record.get("sample_number"),
                    image_width=None,
                    image_height=None,
                    full_image_path=None,
                    target_image_path=None,
                    bboxes=[],
                    primary_bbox=None,
                    crop_bbox=None,
                    bbox_status="invalid",
                    crop_status="not_created",
                    record_status="invalid",
                    error_reason=str(exc),
                )

            upsert_record(connection, record)
            # 한 장이 완성될 때마다 체크포인트를 남겨 강제 종료 후에도 이어갈 수 있게 한다.
            connection.commit()

    status_counts = dict(
        connection.execute(
            "SELECT record_status, COUNT(*) FROM records GROUP BY record_status"
        ).fetchall()
    )
    counts = {
        "valid": int(status_counts.get("valid", 0)),
        "invalid": int(status_counts.get("invalid", 0)),
    }
    write_manifest_from_database(connection, manifest_path)

    build_info = {
        "schema_version": "1",
        "dataset_version": args.dataset_version,
        "splits": json.dumps(args.split),
        "crop_margin": str(args.margin),
        "valid_records": str(counts["valid"]),
        "invalid_records": str(counts["invalid"]),
        "created_at": created_at,
    }
    connection.executemany("INSERT OR REPLACE INTO build_info VALUES (?, ?)", build_info.items())
    connection.commit()
    connection.close()
    (output / "build_summary.json").write_text(
        json.dumps({**build_info, **counts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[OK] valid={counts['valid']} invalid={counts['invalid']}")
    print(f"[SAVE] {output}")


if __name__ == "__main__":
    main()
