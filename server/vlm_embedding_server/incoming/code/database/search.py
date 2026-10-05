#!/usr/bin/env python3
"""카메라 하나의 full/crop 이미지 쌍으로 유사 train 레코드를 검색한다."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from .common import CAMERAS, open_metadata
from .embed import encode_images


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="용접 이미지 DB 검색")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--index-root", type=Path)
    parser.add_argument("--embedding-root", type=Path)
    parser.add_argument("--encoder-id", default="dinov2_base_v1")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--camera", choices=CAMERAS, required=True)
    parser.add_argument("--bbox", nargs=4, type=int, metavar=("X1", "Y1", "X2", "Y2"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=30)
    parser.add_argument("--full-weight", type=float, default=0.3)
    parser.add_argument("--target-weight", type=float, default=0.7)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--faiss-device", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_root = args.db.expanduser().resolve()
    image_path = args.image.expanduser().resolve()
    if not image_path.is_file():
        raise SystemExit(f"질의 이미지가 없습니다: {image_path}")
    if args.top_k < 1 or args.candidate_k < args.top_k:
        raise SystemExit("candidate-k는 top-k 이상이어야 합니다")
    if args.full_weight < 0 or args.target_weight < 0:
        raise SystemExit("검색 가중치는 0 이상이어야 합니다")

    index_root = (
        args.index_root.expanduser().resolve()
        if args.index_root
        else db_root / "indexes" / args.encoder_id
    )
    manifest_path = index_root / "index_manifest.json"
    camera_root = index_root / args.camera
    if not manifest_path.is_file() or not camera_root.is_dir():
        raise SystemExit(f"인덱스가 없습니다: {camera_root}")
    index_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    embedding_root = (
        args.embedding_root.expanduser().resolve()
        if args.embedding_root
        else Path(index_manifest["embedding_root"])
    )

    try:
        import faiss
        import torch
        from transformers import AutoImageProcessor, AutoModel
    except ImportError as exc:
        raise SystemExit("requirements-database.txt 패키지를 먼저 설치하세요") from exc
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise SystemExit("CUDA를 요청했지만 torch에서 GPU를 사용할 수 없습니다")
    if not hasattr(faiss, "StandardGpuResources"):
        raise SystemExit("현재 faiss는 CPU 빌드입니다. Conda의 faiss-gpu를 설치하세요")

    with Image.open(image_path) as source:
        full_image = source.convert("RGB")
    device = torch.device(args.device)
    processor = AutoImageProcessor.from_pretrained(index_manifest["encoder_name"])
    model = AutoModel.from_pretrained(index_manifest["encoder_name"]).to(device).eval()
    with tempfile.TemporaryDirectory(prefix="welding_query_") as temporary:
        query_dir = Path(temporary)
        full_query_path = query_dir / "full.png"
        full_image.save(full_query_path)
        target_query_path: Path | None = None
        if args.bbox:
            x1, y1, x2, y2 = args.bbox
            width, height = full_image.size
            x1, x2 = sorted((max(0, min(width, x1)), max(0, min(width, x2))))
            y1, y2 = sorted((max(0, min(height, y1)), max(0, min(height, y2))))
            if x2 <= x1 or y2 <= y1:
                raise SystemExit("--bbox가 빈 영역입니다")
            target_query_path = query_dir / "target.png"
            full_image.crop((x1, y1, x2, y2)).save(target_query_path)
        full_vector = encode_images([full_query_path], processor, model, torch, device, 1)
        target_vector = (
            encode_images([target_query_path], processor, model, torch, device, 1)
            if target_query_path
            else None
        )
    resources = faiss.StandardGpuResources()
    full_index = faiss.index_cpu_to_gpu(
        resources, args.faiss_device, faiss.read_index(str(camera_root / "full.faiss"))
    )
    target_index = faiss.index_cpu_to_gpu(
        resources, args.faiss_device, faiss.read_index(str(camera_root / "target.faiss"))
    )
    record_ids = json.loads((camera_root / "record_ids.json").read_text(encoding="utf-8"))
    candidate_k = min(args.candidate_k, len(record_ids))
    full_scores, full_indices = full_index.search(full_vector, candidate_k)
    candidates: dict[int, dict[str, float]] = {
        int(index): {"full_score": float(score)}
        for score, index in zip(full_scores[0], full_indices[0])
        if index >= 0
    }
    if target_vector is not None:
        target_scores, target_indices = target_index.search(target_vector, candidate_k)
        for score, index in zip(target_scores[0], target_indices[0]):
            if index >= 0:
                candidates.setdefault(int(index), {})["target_score"] = float(score)

        # 후보 합집합의 full/crop 점수를 GPU에서 한 번에 다시 계산한다.
        positions = np.asarray(sorted(candidates), dtype=np.int64)
        full_embeddings = np.load(embedding_root / args.camera / "full.npy", mmap_mode="r")
        target_embeddings = np.load(embedding_root / args.camera / "target.npy", mmap_mode="r")
        full_candidates = torch.from_numpy(np.asarray(full_embeddings[positions])).to(device)
        target_candidates = torch.from_numpy(np.asarray(target_embeddings[positions])).to(device)
        full_query = torch.from_numpy(full_vector[0]).to(device)
        target_query = torch.from_numpy(target_vector[0]).to(device)
        full_candidate_scores = torch.mv(full_candidates, full_query).cpu().tolist()
        target_candidate_scores = torch.mv(target_candidates, target_query).cpu().tolist()
        for offset, index in enumerate(positions.tolist()):
            candidates[index]["full_score"] = float(full_candidate_scores[offset])
            candidates[index]["target_score"] = float(target_candidate_scores[offset])

    for index, scores in candidates.items():
        weighted_sum = args.full_weight * scores.get("full_score", 0.0)
        available_weight = args.full_weight if "full_score" in scores else 0.0
        if "target_score" in scores:
            weighted_sum += args.target_weight * scores["target_score"]
            available_weight += args.target_weight
        scores["score"] = weighted_sum / available_weight if available_weight else -1.0

    ranked = sorted(candidates.items(), key=lambda item: item[1]["score"], reverse=True)[: args.top_k]
    connection = open_metadata(db_root / "metadata.sqlite")
    results = []
    for position, scores in ranked:
        record_id = record_ids[position]
        row = connection.execute("SELECT * FROM records WHERE record_id = ?", (record_id,)).fetchone()
        if row is None:
            continue
        results.append(
            {
                "record_id": record_id,
                "sample_id": row["sample_id"],
                "camera_id": row["camera_id"],
                "score": scores["score"],
                "full_score": scores.get("full_score"),
                "target_score": scores.get("target_score"),
                "full_image_path": row["full_image_path"],
                "target_image_path": row["target_image_path"],
                "primary_bbox": json.loads(row["primary_bbox_json"]),
                "joint_type": row["joint_type"],
                "material_pair": row["material_pair"],
                "thickness_mm": row["thickness_mm"],
            }
        )
    connection.close()
    print(json.dumps({"camera_id": args.camera, "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
