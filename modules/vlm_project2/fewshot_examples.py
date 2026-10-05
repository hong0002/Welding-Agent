"""Shared TRAIN action retrieval for dataset builders 3 and 4 (no GPT calls)."""
from __future__ import annotations

import base64
import hashlib
import io
import json
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

from .retrieval_client import RetrievalConfig, retrieve_actions
from .trajectory import CAMERAS, mask_descriptor


@lru_cache(maxsize=2)
def training_files(root):
    training = Path(root) / '2.데이터(NIA)' / 'Training'
    labels = {p.stem: p for p in (training / '02.라벨링데이터').rglob('*.json')}
    images = {p.name: p for p in (training / '01.원천데이터').rglob('*_Color.png')}
    return labels, images


def prepare_examples(config, data_root, sample_id, instruction, polylines, sizes, directory, frozen_cache=None):
    """Use query images already in server DB; never send query H5/trajectory.

    Reference images are read locally by returned TRAIN sample IDs. Search and
    GPT provenance are separate: callers attach returned provenance only to new calls.
    """
    settings = config['retrieval']
    payload = dict(sample_id=sample_id, refined_search_text_ko=instruction,
                   top_k=settings['top_k'], candidate_pool=settings['candidate_pool'],
                   weights=settings['weights'], rrf_constant=settings.get('rrf_constant', 60),
                   mask_available=any(polylines.values()),
                   mask_descriptor=mask_descriptor(polylines, sizes), accepted_masks=polylines)
    # Transport/lifetime settings do not change search semantics or invalidate caches.
    identity = {key: config['server'][key] for key in ('ssh_alias','remote_root','remote_python')}
    fingerprint = hashlib.sha256(json.dumps([identity, payload], sort_keys=True).encode()).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    cache = directory / 'retrieval.json'
    cached = json.loads(cache.read_text()) if cache.exists() else {}
    if frozen_cache is not None:
        frozen_cache = Path(frozen_cache)
        fixed = json.loads(frozen_cache.read_text())
        if fixed.get('request', {}).get('sample_id') != sample_id:
            raise RuntimeError('Frozen retrieval cache belongs to another query sample')
        result = fixed['response']
        fingerprint = fixed['request_fingerprint']
        temporary = cache.with_suffix('.tmp')
        temporary.write_text(json.dumps(fixed, ensure_ascii=False, indent=2))
        temporary.replace(cache)
        print(f'[RETRIEVE FROZEN] {sample_id}: {frozen_cache}', flush=True)
    elif cached.get('request_fingerprint') == fingerprint:
        result = cached['response']
        print(f'[RETRIEVE CACHE] {sample_id}', flush=True)
    else:
        result = retrieve_actions(RetrievalConfig(**config['server']), payload)
        if result.get('resident'):
            worker = result['resident']
            print(f"[RETRIEVE RESIDENT] {sample_id}: pid={worker['pid']}; server_search={worker['search_seconds']:.2f}s", flush=True)
        temporary = cache.with_suffix('.tmp')
        temporary.write_text(json.dumps({'request_fingerprint': fingerprint, 'request': payload,
                                         'response': result}, ensure_ascii=False, indent=2))
        temporary.replace(cache)
    if result.get('index_split', 'train').lower() not in ('train', 'training'):
        raise RuntimeError('Few-shot search must use the TRAIN index')
    labels, images = training_files(str(data_root))
    content = []
    ids = []
    for item in result.get('results', []):
        sid = item['sample_id']
        if sid == sample_id:
            raise RuntimeError('Query sample returned as its own few-shot example')
        if sid not in labels:
            raise RuntimeError(f'Local TRAIN reference label not found: {sid}')
        label = json.loads(labels[sid].read_text(encoding='utf-8-sig'))
        views = {}
        for annotation in label.get('annotation_image', []):
            filename = annotation.get('image_filename', '')
            camera = next((c for c in CAMERAS if filename.endswith(f'_{c}_Color.png')), None)
            paths = [v['points'] for v in annotation.get('image_label', [])
                     if v.get('type') == 'polyline' and v.get('label') == 'full_welding' and len(v.get('points', [])) >= 2]
            if camera and paths:
                views[camera] = (filename, paths)
        if not views:
            continue
        ids.append(sid)
        content.append({'type': 'input_text', 'text': json.dumps({
            'reference_sample_id': sid, 'role': 'TRAIN example; reference coordinates are not query targets',
            'texts': item.get('texts', {}), 'metadata': item.get('metadata', {}),
            'rough_action': item['rough_action'],
        }, ensure_ascii=False)})
        priority = settings.get('camera_priority', ['F', 'R', 'S4', 'L', 'S1', 'T', 'B', 'S2', 'S3'])
        for camera in [c for c in priority if c in views][:settings.get('max_views_per_example', 3)]:
            filename, paths = views[camera]
            with Image.open(images[filename]) as src:
                image = src.convert('RGB')
            draw = ImageDraw.Draw(image)
            for path in paths:
                draw.line([tuple(p) for p in path], fill=(30, 255, 80), width=12)
            image.thumbnail((settings.get('image_max_side', 768),) * 2, Image.Resampling.LANCZOS)
            buffer = io.BytesIO(); image.save(buffer, format='JPEG', quality=90)
            dest = directory / 'fewshots' / sid
            dest.mkdir(parents=True, exist_ok=True)
            (dest / f'{camera}.jpg').write_bytes(buffer.getvalue())
            content += [{'type': 'input_text', 'text': f'Reference {sid}, camera {camera}: green = GT seam mask'},
                        {'type': 'input_image', 'image_url': 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode(), 'detail': 'high'}]
    if not ids:
        raise RuntimeError('Search returned no TRAIN examples with masks; retry retrieval before a paid GPT call')
    provenance = {'applied': True, 'sample_ids': ids, 'index_split': 'train',
                  'request_fingerprint': fingerprint, 'query_sample_excluded': True}
    if frozen_cache is not None:
        provenance.update(frozen_from=str(frozen_cache.resolve()),
                          retrieval_condition='Full query masks retained in cached retrieval; query GPT masks may be ablated')
    return content, provenance
