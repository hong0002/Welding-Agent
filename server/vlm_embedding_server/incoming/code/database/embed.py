#!/usr/bin/env python3
"""DB 번들의 full/crop 이미지를 임베딩하고 카메라별 FAISS 인덱스를 만든다."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from tqdm import tqdm

from .common import CAMERAS, load_records, resolve_db_path


class ProcessedImageDataset:
    """Load and preprocess images inside DataLoader worker processes."""

    def __init__(self, paths: list[Path], processor) -> None:
        self.paths = paths
        self.processor = processor

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, index: int) -> dict[str, object]:
        with Image.open(self.paths[index]) as source:
            image = source.convert("RGB")
        processed = self.processor(images=image, return_tensors="pt")
        return {key: value.squeeze(0) for key, value in processed.items()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DINOv2 임베딩 및 FAISS exact index 생성")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--embedding-output", type=Path)
    parser.add_argument("--index-output", type=Path)
    parser.add_argument("--model", default="facebook/dinov2-base")
    parser.add_argument("--encoder-id", default="dinov2_base_v1")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--num-workers", type=int, default=8,
        help="Parallel image decode/preprocessing workers (default: 8; use 0 for serial loading)",
    )
    parser.add_argument(
        "--prefetch-factor", type=int, default=2,
        help="Batches prefetched by each worker when --num-workers > 0 (default: 2)",
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--faiss-device", type=int, default=0)
    parser.add_argument("--split", choices=("train", "valid"), default="train")
    return parser.parse_args()


def encode_images(
    paths: list[Path],
    processor,
    model,
    torch,
    device,
    batch_size: int,
    desc: str | None = None,
    *,
    num_workers: int = 0,
    prefetch_factor: int = 2,
) -> np.ndarray:
    chunks: list[np.ndarray] = []
    loader_options = {
        "batch_size": batch_size,
        "shuffle": False,
        "num_workers": num_workers,
        "pin_memory": device.type == "cuda",
    }
    if num_workers > 0:
        loader_options.update(
            {
                "persistent_workers": True,
                "prefetch_factor": prefetch_factor,
            }
        )
    loader = torch.utils.data.DataLoader(
        ProcessedImageDataset(paths, processor),
        **loader_options,
    )
    batches = loader
    if desc:
        batches = tqdm(loader, total=len(loader), desc=desc)
    for inputs in batches:
        inputs = {
            key: value.to(device, non_blocking=device.type == "cuda")
            for key, value in inputs.items()
        }
        with torch.inference_mode():
            outputs = model(**inputs)
        if getattr(outputs, "pooler_output", None) is not None:
            vectors = outputs.pooler_output
        elif getattr(outputs, "image_embeds", None) is not None:
            vectors = outputs.image_embeds
        else:
            vectors = outputs.last_hidden_state[:, 0]
        vectors = torch.nn.functional.normalize(vectors.float(), p=2, dim=1)
        chunks.append(vectors.cpu().numpy().astype("float32"))
    return np.concatenate(chunks, axis=0)


def main() -> None:
    args = parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size는 1 이상이어야 합니다")
    if args.num_workers < 0:
        raise SystemExit("--num-workers는 0 이상이어야 합니다")
    if args.prefetch_factor < 1:
        raise SystemExit("--prefetch-factor는 1 이상이어야 합니다")
    db_root = args.db.expanduser().resolve()
    manifest_path = db_root / "manifest.jsonl"
    if not manifest_path.is_file():
        raise SystemExit(f"manifest가 없습니다: {manifest_path}")
    embedding_root = (
        args.embedding_output.expanduser().resolve()
        if args.embedding_output
        else db_root / "embeddings" / args.encoder_id
    )
    index_root = (
        args.index_output.expanduser().resolve()
        if args.index_output
        else db_root / "indexes" / args.encoder_id
    )
    for result_root in (embedding_root, index_root):
        if result_root.exists() and any(result_root.iterdir()):
            raise SystemExit(f"결과 폴더가 이미 존재합니다: {result_root}")

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
    device = torch.device(args.device)
    processor = AutoImageProcessor.from_pretrained(args.model)
    model = AutoModel.from_pretrained(args.model).to(device).eval()
    records = [r for r in load_records(manifest_path) if r["split"] == args.split]
    embedding_root.mkdir(parents=True)
    index_root.mkdir(parents=True)
    camera_counts: dict[str, int] = {}
    embedding_dim: int | None = None

    for camera in CAMERAS:
        camera_records = [r for r in records if r["camera_id"] == camera]
        if not camera_records:
            continue
        full_paths = [resolve_db_path(db_root, r["full_image_path"]) for r in camera_records]
        target_paths = [resolve_db_path(db_root, r["target_image_path"]) for r in camera_records]
        full_vectors = encode_images(
            full_paths,
            processor,
            model,
            torch,
            device,
            args.batch_size,
            f"{camera} full",
            num_workers=args.num_workers,
            prefetch_factor=args.prefetch_factor,
        )
        target_vectors = encode_images(
            target_paths,
            processor,
            model,
            torch,
            device,
            args.batch_size,
            f"{camera} target",
            num_workers=args.num_workers,
            prefetch_factor=args.prefetch_factor,
        )
        embedding_camera_root = embedding_root / camera
        index_camera_root = index_root / camera
        embedding_camera_root.mkdir(parents=True)
        index_camera_root.mkdir(parents=True)
        np.save(embedding_camera_root / "full.npy", full_vectors)
        np.save(embedding_camera_root / "target.npy", target_vectors)
        resources = faiss.StandardGpuResources()
        full_index_gpu = faiss.index_cpu_to_gpu(
            resources, args.faiss_device, faiss.IndexFlatIP(full_vectors.shape[1])
        )
        target_index_gpu = faiss.index_cpu_to_gpu(
            resources, args.faiss_device, faiss.IndexFlatIP(target_vectors.shape[1])
        )
        full_index_gpu.add(full_vectors)
        target_index_gpu.add(target_vectors)
        # FAISS 파일 형식은 CPU index이므로 저장할 때만 변환한다.
        faiss.write_index(
            faiss.index_gpu_to_cpu(full_index_gpu), str(index_camera_root / "full.faiss")
        )
        faiss.write_index(
            faiss.index_gpu_to_cpu(target_index_gpu), str(index_camera_root / "target.faiss")
        )
        (index_camera_root / "record_ids.json").write_text(
            json.dumps([r["record_id"] for r in camera_records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        embedding_dim = int(full_vectors.shape[1])
        camera_counts[camera] = len(camera_records)
        print(f"[INDEX] camera={camera} records={len(camera_records)}")

    index_manifest = {
        "index_version": args.encoder_id,
        "encoder_name": args.model,
        "encoder_id": args.encoder_id,
        "preprocessing": "transformers_auto_image_processor_v1",
        "embedding_dim": embedding_dim,
        "metric": "cosine_via_l2_normalized_inner_product",
        "faiss_index": "IndexFlatIP",
        "faiss_build_device": f"cuda:{args.faiss_device}",
        "split": args.split,
        "database_root": str(db_root),
        "embedding_root": str(embedding_root),
        "camera_counts": camera_counts,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (index_root / "index_manifest.json").write_text(
        json.dumps(index_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[SAVE] embeddings={embedding_root}")
    print(f"[SAVE] index={index_root}")


if __name__ == "__main__":
    main()
