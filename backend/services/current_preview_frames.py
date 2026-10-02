"""Latest capture reads from the current owned preview only. No launch or stream."""
from datetime import datetime, timezone
import hashlib
import io
from pathlib import Path
from uuid import UUID

from PIL import Image

from backend.services.current_preview_config import CurrentPreviewError
from backend.services.preview_capture import CAPTURE_NAMES

MAX_FRAME_BYTES = 8 * 1024 * 1024


def _stale():
    return CurrentPreviewError('CURRENT_PREVIEW_FRAME_STALE', '현재 작업의 활성 미리보기 화면이 아닙니다.', 409)


def _context(runtime, job_id, artifact_id, verify):
    latest = runtime.latest
    if latest and (latest['job_id'] != str(job_id) or latest['artifact_id'] != str(artifact_id)):
        raise _stale()
    if (runtime.state not in {'RUNNING_PREVIEW', 'READY'} or runtime.process is None
            or runtime.session is None or not latest or latest['status'] not in {'QUEUED', 'SUCCEEDED'}):
        return None
    session = Path(runtime.session).resolve()
    if (session.parent != runtime.config.runtime_dir.resolve()/'current-previews/sessions'
            or str(UUID(session.name)) != session.name):
        raise _stale()
    try:
        descriptor, _, _ = verify(runtime.claim)
    except (OSError, ValueError, KeyError, TypeError):
        raise CurrentPreviewError('CURRENT_PREVIEW_ARTIFACT_INVALID', '승인 또는 현재 VLA 증거가 변경되어 화면을 숨겼습니다.', 409) from None
    if any(descriptor[key] != latest[key] for key in ('job_id','artifact_id','package_id','sample_id','kind')):
        raise _stale()
    request = str(UUID(latest['request_id']))
    output = session/'outputs'/request
    if output.resolve() != output.absolute() or not output.resolve().is_relative_to(session):
        raise _stale()
    return session, request, output, latest


def _read_png(output, name):
    if name not in CAPTURE_NAMES:
        raise ValueError('Unknown capture name')
    file = output/(name+'.png')
    if file.resolve() != file.absolute() or not file.is_file() or file.stat().st_size > MAX_FRAME_BYTES:
        return None
    data = file.read_bytes()
    if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data) > MAX_FRAME_BYTES:
        return None
    try:
        with Image.open(io.BytesIO(data)) as picture:
            width, height = picture.size
            if picture.format != 'PNG' or not (0 < width <= 4096 and 0 < height <= 4096) or width*height > 16_000_000:
                return None
            picture.verify()
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    return data, hashlib.sha256(data).hexdigest(), width, height, datetime.fromtimestamp(file.stat().st_mtime, timezone.utc).isoformat()


def list_frames(runtime, job_id, artifact_id, verify):
    context = _context(runtime, job_id, artifact_id, verify)
    empty = dict(available=False, delivery='latest_capture', frames=[], session_id=None, request_id=None,
                 job_id=str(job_id), artifact_id=str(artifact_id), kind=None)
    if context is None:
        return dict(**empty, reason_code='CURRENT_PREVIEW_NOT_ACTIVE')
    session, request, output, latest = context
    frames = []
    for name in CAPTURE_NAMES:
        try:
            captured = _read_png(output, name)
        except OSError:
            captured = None  # Capture/write still in progress; motion remains independent.
        if captured:
            _, digest, width, height, captured_at = captured
            url = (f'/api/simulator/current-preview/frames/{session.name}/{request}/{name}/{digest}.png'
                   f'?job_id={job_id}&artifact_id={artifact_id}')
            frames.append(dict(name=name, url=url, sha256=digest, width=width, height=height, captured_at=captured_at))
    return dict(available=bool(frames), delivery='latest_capture', frames=frames,
        session_id=session.name, request_id=request, job_id=str(job_id), artifact_id=str(artifact_id),
        kind=latest['kind'], reason_code=None if frames else
        'CURRENT_PREVIEW_FRAME_UNAVAILABLE' if latest['status']=='SUCCEEDED' else 'CURRENT_PREVIEW_FRAME_PENDING')


def frame_bytes(runtime, job_id, artifact_id, session_id, request_id, name, digest, verify):
    context = _context(runtime, job_id, artifact_id, verify)
    if context is None:
        raise _stale()
    session, request, output, _ = context
    if session.name != str(session_id) or request != str(request_id):
        raise _stale()
    try:
        captured = _read_png(output, name)
    except OSError:
        captured = None
    if captured is None or captured[1] != digest:
        raise CurrentPreviewError('CURRENT_PREVIEW_FRAME_UNAVAILABLE', '최신 캡처 이미지를 아직 읽을 수 없습니다.', 404)
    return captured[0]
