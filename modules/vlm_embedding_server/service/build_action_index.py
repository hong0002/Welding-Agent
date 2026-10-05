#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / 'incoming/action_source/welding_actions_v1/actions.jsonl'
DEFAULT_EMBEDDINGS = ROOT / 'embeddings/welding_actions_v1/multilingual_e5_base_v1'
DEFAULT_INDEX = ROOT / 'index/welding_actions_v1/multilingual_e5_base_v1'


def parse_args():
    parser = argparse.ArgumentParser(description='Build multilingual task/action and mask FAISS indices')
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--embedding-output', type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument('--index-output', type=Path, default=DEFAULT_INDEX)
    parser.add_argument('--model', default='intfloat/multilingual-e5-base')
    parser.add_argument('--encoder-id', default='multilingual_e5_base_v1')
    parser.add_argument('--batch-size', type=int, default=128)
    parser.add_argument('--device', default='cuda:0')
    parser.add_argument('--faiss-device', type=int, default=0)
    parser.add_argument('--split', default='train')
    return parser.parse_args()


def mean_pool(last_hidden_state, attention_mask, torch):
    mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    total = (last_hidden_state * mask).sum(1)
    return total / mask.sum(1).clamp(min=1e-9)


def encode_texts(texts, tokenizer, model, torch, device, batch_size, prefix):
    vectors = []
    for start in range(0, len(texts), batch_size):
        batch = [prefix + text for text in texts[start:start + batch_size]]
        inputs = tokenizer(batch, padding=True, truncation=True, max_length=256, return_tensors='pt')
        inputs = {key: value.to(device, non_blocking=True) for key, value in inputs.items()}
        with torch.inference_mode():
            output = model(**inputs)
            pooled = mean_pool(output.last_hidden_state, inputs['attention_mask'], torch)
            pooled = torch.nn.functional.normalize(pooled.float(), p=2, dim=1)
        vectors.append(pooled.cpu().numpy().astype('float32'))
        print(f'[EMBED] {min(start + batch_size, len(texts))}/{len(texts)}', flush=True)
    return np.concatenate(vectors, axis=0)


def normalize_rows(array):
    array = np.asarray(array, dtype='float32')
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    return array / np.maximum(norms, 1e-12)


def save_gpu_flat_ip(vectors, path, faiss, resources, device_id):
    cpu = faiss.IndexFlatIP(vectors.shape[1])
    gpu = faiss.index_cpu_to_gpu(resources, device_id, cpu)
    gpu.add(vectors)
    faiss.write_index(faiss.index_gpu_to_cpu(gpu), str(path))


def main():
    args = parse_args()
    import faiss
    import torch
    from transformers import AutoModel, AutoTokenizer

    if not torch.cuda.is_available():
        raise SystemExit('PyTorch CUDA is unavailable')
    if not hasattr(faiss, 'StandardGpuResources'):
        raise SystemExit('FAISS GPU build is unavailable')
    records = []
    with args.source.open(encoding='utf-8') as stream:
        for line in stream:
            record = json.loads(line)
            if record['split'] == args.split:
                records.append(record)
    records.sort(key=lambda item: item['sample_id'])
    if not records:
        raise SystemExit(f'no records for split={args.split}')

    args.embedding_output.mkdir(parents=True, exist_ok=True)
    args.index_output.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModel.from_pretrained(args.model).to(args.device).eval()
    task_texts = [item['texts']['task_text_ko'] + ' ' + item['texts']['task_text_en'] for item in records]
    action_texts = [item['texts']['action_text_ko'] + ' ' + item['texts']['action_text_en'] for item in records]
    task_vectors = encode_texts(task_texts, tokenizer, model, torch, args.device, args.batch_size, 'passage: ')
    action_vectors = encode_texts(action_texts, tokenizer, model, torch, args.device, args.batch_size, 'passage: ')
    mask_vectors = normalize_rows([item['mask']['descriptor'] for item in records])

    np.save(args.embedding_output / 'task.npy', task_vectors)
    np.save(args.embedding_output / 'action.npy', action_vectors)
    np.save(args.embedding_output / 'mask.npy', mask_vectors)
    sample_ids = [item['sample_id'] for item in records]
    (args.index_output / 'sample_ids.json').write_text(json.dumps(sample_ids), encoding='utf-8')
    resources = faiss.StandardGpuResources()
    save_gpu_flat_ip(task_vectors, args.index_output / 'task.faiss', faiss, resources, args.faiss_device)
    save_gpu_flat_ip(action_vectors, args.index_output / 'action.faiss', faiss, resources, args.faiss_device)
    save_gpu_flat_ip(mask_vectors, args.index_output / 'mask.faiss', faiss, resources, args.faiss_device)
    manifest = {
        'schema_version': 'welding-action-index-v1',
        'encoder_name': args.model,
        'encoder_id': args.encoder_id,
        'split': args.split,
        'record_count': len(records),
        'text_embedding_dim': int(task_vectors.shape[1]),
        'mask_embedding_dim': int(mask_vectors.shape[1]),
        'metric': 'cosine_via_l2_normalized_inner_product',
        'faiss_index': 'IndexFlatIP',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'source': str(args.source.resolve()),
    }
    (args.index_output / 'index_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'[SAVE] action_index={args.index_output}')
    print(f'[SUMMARY] split={args.split} records={len(records)}')


if __name__ == '__main__':
    main()
