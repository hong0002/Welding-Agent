#!/usr/bin/env python3
"""Sample-level 9-view GPU retrieval service CLI."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
from PIL import Image

CAMERAS = ("B", "F", "L", "R", "S1", "S2", "S3", "S4", "T")
ROOT = Path("/NHNHOME/WORKSPACE/26moe002_B/IDEA/JuyoungKim/VLA_TEST/server/vlm_embedding_server")
DEFAULT_DB = ROOT / "incoming/database_source/welding_train_v1"
DEFAULT_INDEX = ROOT / "index/welding_train_v1/dinov2_base_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="9-view welding sample retrieval")
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--query-manifest", type=Path, help="YOLO detections for uploaded query images")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--full-weight", type=float, default=0.3)
    parser.add_argument("--target-weight", type=float, default=0.7)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--index-root", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--faiss-device", type=int, default=0)
    return parser.parse_args()


def encode(images, processor, model, torch, device) -> np.ndarray:
    inputs = processor(images=images, return_tensors="pt")
    inputs = {key: value.to(device, non_blocking=True) for key, value in inputs.items()}
    with torch.inference_mode():
        outputs = model(**inputs)
    if getattr(outputs, "pooler_output", None) is not None:
        vectors = outputs.pooler_output
    elif getattr(outputs, "image_embeds", None) is not None:
        vectors = outputs.image_embeds
    else:
        vectors = outputs.last_hidden_state[:, 0]
    vectors = torch.nn.functional.normalize(vectors.float(), p=2, dim=1)
    return vectors.cpu().numpy().astype("float32")


def load_rgb(path: Path) -> Image.Image:
    with Image.open(path) as source:
        return source.convert("RGB")


def main() -> None:
    args = parse_args()
    if args.top_k < 1:
        raise SystemExit("--top-k must be at least 1")
    total_weight = args.full_weight + args.target_weight
    if args.full_weight < 0 or args.target_weight < 0 or total_weight <= 0:
        raise SystemExit("weights must be non-negative and have a positive sum")

    db_root = args.db.expanduser().resolve()
    index_root = args.index_root.expanduser().resolve()
    metadata_path = db_root / "metadata.sqlite"
    index_manifest_path = index_root / "index_manifest.json"
    if not metadata_path.is_file() or not index_manifest_path.is_file():
        raise SystemExit("database or index manifest is missing")

    try:
        import faiss
        import torch
        from transformers import AutoImageProcessor, AutoModel
    except ImportError as exc:
        raise SystemExit(f"missing server dependency: {exc}") from exc
    if not torch.cuda.is_available():
        raise SystemExit("PyTorch CUDA is unavailable")
    if not hasattr(faiss, "StandardGpuResources"):
        raise SystemExit("FAISS GPU build is unavailable")

    connection = sqlite3.connect(metadata_path)
    connection.row_factory = sqlite3.Row
    query_manifest = None
    if args.query_manifest:
        manifest_path = args.query_manifest.resolve()
        manifest_path.relative_to((ROOT / "incoming/yolo_requests").resolve())
        query_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if query_manifest.get("sample_id") != args.sample_id or query_manifest.get("bbox_source") != "server_yolo":
            raise ValueError("query manifest identity/source mismatch")
        by_camera = {}
        for camera, item in query_manifest["cameras"].items():
            if camera not in CAMERAS or item["status"] != "detected":
                continue
            for key in ("full_image_path", "target_image_path"):
                path = Path(item[key]).resolve()
                path.relative_to(manifest_path.parent)
                if not path.is_file():
                    raise FileNotFoundError(path)
            by_camera[camera] = item
        if not by_camera:
            raise ValueError("No YOLO detections; no stored-label fallback")
    else:
        rows = connection.execute(
            "SELECT * FROM records WHERE sample_id = ? AND record_status = 'valid' ORDER BY camera_id",
            (args.sample_id,),
        ).fetchall()
        by_camera = {row["camera_id"]: row for row in rows if row["camera_id"] in CAMERAS}
        if not by_camera:
            raise ValueError(f"sample not found: {args.sample_id}")

    index_manifest = json.loads(index_manifest_path.read_text(encoding="utf-8"))
    device = torch.device(args.device)
    processor = AutoImageProcessor.from_pretrained(index_manifest["encoder_name"])
    model = AutoModel.from_pretrained(index_manifest["encoder_name"]).to(device).eval()

    cameras = [camera for camera in CAMERAS if camera in by_camera]
    full_images = [load_rgb(db_root / by_camera[camera]["full_image_path"]) for camera in cameras]
    target_images = [load_rgb(db_root / by_camera[camera]["target_image_path"]) for camera in cameras]
    full_queries = encode(full_images, processor, model, torch, device)
    target_queries = encode(target_images, processor, model, torch, device)

    resources = faiss.StandardGpuResources()
    sample_scores: dict[str, dict] = {}
    for query_position, camera in enumerate(cameras):
        camera_root = index_root / camera
        record_ids = json.loads((camera_root / "record_ids.json").read_text(encoding="utf-8"))
        full_index = faiss.index_cpu_to_gpu(
            resources, args.faiss_device, faiss.read_index(str(camera_root / "full.faiss"))
        )
        target_index = faiss.index_cpu_to_gpu(
            resources, args.faiss_device, faiss.read_index(str(camera_root / "target.faiss"))
        )
        count = len(record_ids)
        full_values, full_positions = full_index.search(full_queries[query_position : query_position + 1], count)
        target_values, target_positions = target_index.search(
            target_queries[query_position : query_position + 1], count
        )
        full_by_position = {
            int(position): float(score)
            for score, position in zip(full_values[0], full_positions[0])
            if position >= 0
        }
        target_by_position = {
            int(position): float(score)
            for score, position in zip(target_values[0], target_positions[0])
            if position >= 0
        }
        for position, record_id in enumerate(record_ids):
            sample_id = record_id.rsplit(":", 1)[0]
            if sample_id == args.sample_id:
                continue
            full_score = full_by_position[position]
            target_score = target_by_position[position]
            combined = (
                args.full_weight * full_score + args.target_weight * target_score
            ) / total_weight
            entry = sample_scores.setdefault(
                sample_id,
                {"sample_id": sample_id, "camera_scores": {}, "score": 0.0},
            )
            entry["camera_scores"][camera] = {
                "full": full_score,
                "target": target_score,
                "combined": combined,
            }

    results = []
    for entry in sample_scores.values():
        values = [value["combined"] for value in entry["camera_scores"].values()]
        entry["score"] = float(sum(values) / len(values))
        entry["camera_coverage"] = len(values) / len(cameras)
        results.append(entry)
    results.sort(key=lambda item: item["score"], reverse=True)
    results = results[: args.top_k]
    if any(result["sample_id"] == args.sample_id for result in results):
        raise RuntimeError("self-sample leakage detected")

    for result in results:
        metadata = connection.execute(
            """
            SELECT joint_type, material_pair, thickness_mm
            FROM records WHERE sample_id = ? LIMIT 1
            """,
            (result["sample_id"],),
        ).fetchone()
        if metadata:
            result["joint_type"] = metadata["joint_type"]
            result["material_pair"] = metadata["material_pair"]
            result["thickness_mm"] = metadata["thickness_mm"]

    connection.close()
    payload = {
        "query_sample_id": args.sample_id,
        "bbox_source": "server_yolo" if query_manifest else "database",
        "query_request_id": query_manifest.get("request_id") if query_manifest else None,
        "skipped_cameras": [camera for camera, item in query_manifest["cameras"].items()
                            if item["status"] != "detected"] if query_manifest else [],
        "query_cameras": cameras,
        "index_split": index_manifest.get("split", "unknown"),
        "self_sample_excluded": True,
        "weights": {"full": args.full_weight, "target": args.target_weight},
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        sys.exit(1)
