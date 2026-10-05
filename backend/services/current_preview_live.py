"""Bound current-preview MJPEG reads. Playback state is never mutated here."""
from datetime import datetime
import hashlib
import io
import json
import time

from PIL import Image
from backend.services.current_preview_config import CurrentPreviewError
from backend.services.current_preview_frames import _context

MAX_BYTES = 2 * 1024 * 1024
FRESH_SECONDS = 2


def _read(context):
    session, request, output, latest = context
    directory = output / 'live'
    if directory.resolve() != directory.absolute():
        return None
    identity = dict(job_id=latest['job_id'], artifact_id=latest['artifact_id'],
                    session_id=session.name, request_id=request)
    try:
        file = directory / 'status.json'
        if file.resolve() != file.absolute() or file.stat().st_size > 4096:
            return None
        meta = json.loads(file.read_text(encoding='utf-8'))
        if not isinstance(meta, dict):
            return None
        if any(meta.get(k) != v for k, v in identity.items()):
            return None
        return meta
    except (OSError, ValueError, TypeError):
        return None


def info(context):
    empty = dict(available=False, state='OFFLINE', fps=0, target_fps=8, url=None, warning=None)
    if not context:
        return empty
    session, request, _, latest = context
    if latest['kind'] != 'robot' or latest.get('backend') not in {'dataset_v2', 'dataset_stp', 'dataset_final'}:
        return empty
    final = latest.get('backend') == 'dataset_final'
    empty.update(target_fps=4 if final else 8, delivery='polling' if final else 'mjpeg', image_url=None, sequence=0, captured_at=None)
    url = (f'/api/simulator/current-preview/live/{session.name}/{request}'
           f'?job_id={latest["job_id"]}&artifact_id={latest["artifact_id"]}')
    if final: empty['image_url'] = url.replace('/live/','/live-frame/')
    meta = _read(context)
    if not meta:
        return dict(empty, state='CONNECTING' if latest['status']=='QUEUED' else 'OFFLINE', url=url)
    try:
        age = time.time() - datetime.fromisoformat(meta['captured_at']).timestamp()
        fresh = -1 <= age <= FRESH_SECONDS and meta.get('sequence', 0) > 0
    except (KeyError, ValueError, TypeError):
        fresh = False
    active = meta.get('active') is True and latest['status']=='QUEUED'
    fps = meta.get('fps', 0)
    if not isinstance(fps, (int, float)) or not 0 <= fps <= 8:
        fps = 0
    warning = meta.get('warning')
    if warning not in {'LIVE_CAPTURE_FRAME_SKIPPED', 'LIVE_CAPTURE_API_UNAVAILABLE', 'LIVE_CAPTURE_PENDING'}:
        warning = None
    generated = isinstance(meta.get('sequence'), int) and meta['sequence'] > 0
    available = active and (generated or not warning)
    state = ('LIVE' if fresh else 'PAUSED' if generated else 'CONNECTING') if available else 'PAUSED' if generated else 'OFFLINE'
    return dict(empty, available=available, state=state,
                fps=fps, url=url, warning=warning,sequence=meta.get('sequence',0),captured_at=meta.get('captured_at'))


def read_packet(runtime, job_id, artifact_id, session_id, request_id, verify):
    context = _context(runtime, job_id, artifact_id, verify)
    if not context:
        raise CurrentPreviewError('CURRENT_PREVIEW_STREAM_STALE', '현재 활성 Robot Preview가 아닙니다.', 409)
    session, request, output, latest = context
    if (session.name != str(session_id) or request != str(request_id) or latest['kind'] != 'robot'
            or latest.get('backend') not in {'dataset_v2', 'dataset_stp', 'dataset_final'}):
        raise CurrentPreviewError('CURRENT_PREVIEW_STREAM_STALE', '현재 Robot Preview의 stream이 아닙니다.', 409)
    meta = _read(context)
    if latest['status'] != 'QUEUED' or meta and meta.get('active') is not True:
        return False, None
    if meta is None:
        return True, None  # Metadata may become visible between atomic writes.
    if info(context)['state'] != 'LIVE':
        return True, None
    try:
        file = output / 'live/latest.jpg'
        if file.resolve() != file.absolute() or file.stat().st_size > MAX_BYTES:
            return True, None
        data = file.read_bytes()
        if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != meta.get('sha256'):
            return True, None  # Atomic pair between writes; skip, never fail playback.
        with Image.open(io.BytesIO(data)) as picture:
            if picture.format != 'JPEG' or not (0 < picture.width <= 1280 and 0 < picture.height <= 720):
                return True, None
            picture.verify()
        sequence = meta.get('sequence')
        if not isinstance(sequence, int) or sequence <= 0:
            return True, None
        return True, (sequence, data)
    except (OSError, ValueError, Image.DecompressionBombError):
        return True, None
