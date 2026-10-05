#!/usr/bin/env python3
"""Resident copy of retrieve_action scoring logic; restart service after index updates."""
from __future__ import annotations

import json
from functools import lru_cache
import sqlite3
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from service.retrieve import CAMERAS, encode as encode_images, load_rgb

ROOT = Path('/NHNHOME/WORKSPACE/26moe002_B/IDEA/JuyoungKim/VLA_TEST/server/vlm_embedding_server')
IMAGE_DB = ROOT / 'incoming/database_source/welding_train_v1'
IMAGE_INDEX = ROOT / 'index/welding_train_v1/dinov2_base_v1'
ACTION_SOURCE = ROOT / 'incoming/action_source/welding_actions_v1/actions.jsonl'
ACTION_INDEX = ROOT / 'index/welding_actions_v1/multilingual_e5_base_v1'


def load_request():
    payload = json.load(sys.stdin)
    required = {'sample_id', 'refined_search_text_ko', 'top_k', 'candidate_pool', 'weights'}
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f'missing request fields: {missing}')
    return payload


@lru_cache(maxsize=1)
def load_action_records():
    records = {}
    with ACTION_SOURCE.open(encoding='utf-8') as stream:
        for line in stream:
            item = json.loads(line)
            records[item['sample_id']] = item
    return records


def mean_pool(last_hidden_state, attention_mask, torch):
    mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    return (last_hidden_state * mask).sum(1) / mask.sum(1).clamp(min=1e-9)


def encode_query_text(text, tokenizer, model, torch, device):
    inputs = tokenizer(['query: ' + text], padding=True, truncation=True, max_length=256, return_tensors='pt')
    inputs = {key: value.to(device, non_blocking=True) for key, value in inputs.items()}
    with torch.inference_mode():
        output = model(**inputs)
        pooled = mean_pool(output.last_hidden_state, inputs['attention_mask'], torch)
        pooled = torch.nn.functional.normalize(pooled.float(), p=2, dim=1)
    return pooled.cpu().numpy().astype('float32')


@lru_cache(maxsize=1)
def resources():
    import faiss
    return faiss.StandardGpuResources()


@lru_cache(maxsize=32)
def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def image_encoder():
    from transformers import AutoImageProcessor, AutoModel
    name = load_json(IMAGE_INDEX / 'index_manifest.json')['encoder_name']
    return AutoImageProcessor.from_pretrained(name), AutoModel.from_pretrained(name).to('cuda:0').eval()


@lru_cache(maxsize=1)
def text_encoder():
    from transformers import AutoTokenizer, AutoModel
    name = load_json(ACTION_INDEX / 'index_manifest.json')['encoder_name']
    return AutoTokenizer.from_pretrained(name), AutoModel.from_pretrained(name).to('cuda:0').eval()


@lru_cache(maxsize=32)
def gpu_index(path, device_id=0):
    import faiss
    return faiss.index_cpu_to_gpu(resources(), device_id, faiss.read_index(str(path)))


def gpu_search(index_path, query, count, faiss, resources, device_id):
    values, positions = gpu_index(index_path, device_id).search(query, count)
    return [(int(position), float(score)) for score, position in zip(values[0], positions[0]) if position >= 0]


def warmup():
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError('PyTorch CUDA is unavailable')
    image_encoder()
    text_encoder()
    load_action_records()
    for camera in CAMERAS:
        load_json(IMAGE_INDEX / camera / 'record_ids.json')
        for kind in ('full', 'target'):
            gpu_index(IMAGE_INDEX / camera / (kind + '.faiss'))
    load_json(ACTION_INDEX / 'index_manifest.json')
    load_json(ACTION_INDEX / 'sample_ids.json')
    for kind in ('task', 'action', 'mask'):
        gpu_index(ACTION_INDEX / (kind + '.faiss'))


def rank_from_index(index_path, query, sample_ids, query_id, valid_ids, faiss, resources, device_id):
    ranked = []
    for position, score in gpu_search(index_path, query, len(sample_ids), faiss, resources, device_id):
        sample_id = sample_ids[position]
        if sample_id != query_id and sample_id in valid_ids:
            ranked.append((sample_id, score))
    return ranked


def image_rankings(query_id, valid_ids, candidate_pool, faiss, torch, resources, device_id, query_manifest=None):
    from transformers import AutoImageProcessor, AutoModel

    connection = sqlite3.connect(IMAGE_DB / 'metadata.sqlite')
    connection.row_factory = sqlite3.Row
    if query_manifest:
        path = Path(query_manifest).resolve()
        path.relative_to((ROOT / 'incoming/yolo_requests').resolve())
        query = json.loads(path.read_text(encoding='utf-8'))
        if query.get('sample_id') != query_id or query.get('bbox_source') != 'server_yolo':
            raise ValueError('YOLO query identity/source mismatch')
        by_camera = {}
        for camera, item in query['cameras'].items():
            if camera not in CAMERAS or item['status'] != 'detected':
                continue
            for key in ('full_image_path', 'target_image_path'):
                image = Path(item[key]).resolve()
                image.relative_to(path.parent)
                if not image.is_file():
                    raise FileNotFoundError(f'Previous YOLO image no longer available: {image}')
            by_camera[camera] = item
        if not by_camera:
            raise ValueError('No YOLO detections; stored query crop fallback is disabled')
    else:
        rows = connection.execute(
            "SELECT sample_id, camera_id, full_image_path, target_image_path FROM records WHERE sample_id = ? AND record_status = 'valid' ORDER BY camera_id",
            (query_id,),
        ).fetchall()
        by_camera = {row['camera_id']: row for row in rows if row['camera_id'] in CAMERAS}
        if not by_camera:
            raise ValueError(f'image query sample not found: {query_id}')
    manifest = load_json(IMAGE_INDEX / 'index_manifest.json')
    device = torch.device('cuda:0')
    processor, model = image_encoder()
    cameras = [camera for camera in CAMERAS if camera in by_camera]
    full_images = [load_rgb(IMAGE_DB / by_camera[camera]['full_image_path']) for camera in cameras]
    target_images = [load_rgb(IMAGE_DB / by_camera[camera]['target_image_path']) for camera in cameras]
    full_queries = encode_images(full_images, processor, model, torch, device)
    target_queries = encode_images(target_images, processor, model, torch, device)
    full_scores = {}
    target_scores = {}
    for query_position, camera in enumerate(cameras):
        camera_root = IMAGE_INDEX / camera
        record_ids = load_json(camera_root / 'record_ids.json')
        full_results = gpu_search(camera_root / 'full.faiss', full_queries[query_position:query_position + 1], len(record_ids), faiss, resources, device_id)
        target_results = gpu_search(camera_root / 'target.faiss', target_queries[query_position:query_position + 1], len(record_ids), faiss, resources, device_id)
        for position, score in full_results:
            sample_id = record_ids[position].rsplit(':', 1)[0]
            if sample_id != query_id and sample_id in valid_ids:
                full_scores.setdefault(sample_id, []).append(score)
        for position, score in target_results:
            sample_id = record_ids[position].rsplit(':', 1)[0]
            if sample_id != query_id and sample_id in valid_ids:
                target_scores.setdefault(sample_id, []).append(score)
    connection.close()
    full_ranked = sorted(
        ((sample_id, sum(values) / len(values)) for sample_id, values in full_scores.items()),
        key=lambda item: item[1], reverse=True,
    )[:candidate_pool]
    target_ranked = sorted(
        ((sample_id, sum(values) / len(values)) for sample_id, values in target_scores.items()),
        key=lambda item: item[1], reverse=True,
    )[:candidate_pool]
    return full_ranked, target_ranked, cameras


def normalize_mask(vector):
    array = np.asarray(vector, dtype='float32').reshape(1, -1)
    norm = float(np.linalg.norm(array))
    if norm <= 1e-12:
        return array
    return array / norm


def search(request):
    import faiss
    import torch
    from transformers import AutoModel, AutoTokenizer

    if not torch.cuda.is_available():
        raise RuntimeError('PyTorch CUDA is unavailable')
    if not hasattr(faiss, 'StandardGpuResources'):
        raise RuntimeError('FAISS GPU build is unavailable')
    manifest = load_json(ACTION_INDEX / 'index_manifest.json')
    sample_ids = load_json(ACTION_INDEX / 'sample_ids.json')
    records = load_action_records()
    valid_ids = {sample_id for sample_id in sample_ids if sample_id in records and records[sample_id]["mask"]["available_views"]}
    query_id = str(request['sample_id'])
    gpu_resources = resources()
    candidate_pool = max(int(request['candidate_pool']), int(request['top_k']))

    full_ranked, target_ranked, query_cameras = image_rankings(
        query_id, valid_ids, candidate_pool, faiss, torch, gpu_resources, 0, request.get('query_manifest')
    )

    tokenizer, text_model = text_encoder()
    text_query = encode_query_text(
        str(request['refined_search_text_ko']), tokenizer, text_model, torch, torch.device('cuda:0')
    )
    task_ranked = rank_from_index(
        ACTION_INDEX / 'task.faiss', text_query, sample_ids, query_id, valid_ids, faiss, gpu_resources, 0
    )[:candidate_pool]
    action_ranked = rank_from_index(
        ACTION_INDEX / 'action.faiss', text_query, sample_ids, query_id, valid_ids, faiss, gpu_resources, 0
    )[:candidate_pool]
    mask_available = bool(request.get('mask_available', request.get('mask_descriptor') is not None))
    mask_ranked = []
    if mask_available:
        mask_query = normalize_mask(request.get('mask_descriptor', []))
        if mask_query.shape[1] != int(manifest['mask_embedding_dim']):
            raise ValueError(f"mask descriptor dimension {mask_query.shape[1]} != {manifest['mask_embedding_dim']}")
        mask_ranked = rank_from_index(
            ACTION_INDEX / 'mask.faiss', mask_query, sample_ids, query_id, valid_ids, faiss, gpu_resources, 0
        )[:candidate_pool]

    rankings = {
        'full_image': full_ranked,
        'target_image': target_ranked,
        'task_text': task_ranked,
        'action_text': action_ranked,
        'mask_shape': mask_ranked,
    }
    weights = {key: float(value) for key, value in request['weights'].items()}
    if not mask_available:
        rankings.pop('mask_shape')
    weights = {key: weights.get(key, 0.) for key in rankings}
    if any(not np.isfinite(v) or v < 0 for v in weights.values()) or sum(weights.values()) <= 0:
        raise ValueError('active retrieval weights must be finite, non-negative and sum to > 0')
    total = sum(weights.values())
    weights = {key: value / total for key, value in weights.items()}

    rrf_constant = float(request.get('rrf_constant', 60))
    rank_maps = {
        name: {sample_id: rank for rank, (sample_id, _) in enumerate(items, 1)}
        for name, items in rankings.items()
    }
    fused = {}
    for name, rank_map in rank_maps.items():
        weight = weights.get(name, 0.0)
        if weight == 0:
            continue
        for sample_id, rank in rank_map.items():
            fused[sample_id] = fused.get(sample_id, 0.0) + weight / (rrf_constant + rank)
    ordered = sorted(fused, key=lambda sample_id: fused[sample_id], reverse=True)
    results = []
    for sample_id in ordered[: int(request['top_k'])]:
        record = records[sample_id]
        results.append(
            {
                'sample_id': sample_id,
                'fused_score': fused[sample_id],
                'ranks': {name: rank_maps[name].get(sample_id) for name in rankings},
                'metadata': record['metadata'],
                'mask': {'available_views': record['mask']['available_views']},
                'source_trajectory': record['source_trajectory'],
                'rough_action': record['rough_action'],
                'texts': record['texts'],
            }
        )
    if any(item['sample_id'] == query_id for item in results):
        raise RuntimeError('self-sample leakage detected')
    payload = {
        'query_sample_id': query_id,
        'bbox_source': 'server_yolo' if request.get('query_manifest') else 'database',
        'query_manifest': request.get('query_manifest'),
        'query_cameras': query_cameras,
        'mask_available': mask_available,
        'active_modalities': list(rankings),
        'query_text_ko': request['refined_search_text_ko'],
        'index_split': manifest['split'],
        'self_sample_excluded': True,
        'fusion': 'weighted_rrf',
        'weights': weights,
        'candidate_pool': candidate_pool,
        'results': results,
    }
    return payload
