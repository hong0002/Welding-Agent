"""Owned preview startup diagnostics, without importing Isaac or exception payloads."""
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import tempfile
import traceback
from uuid import UUID

from backend.services.current_preview_gate import read, resolve_command


MESSAGES = {
    'OWNED_CODE_FINGERPRINT_MISSING': 'Preview admission failed: descriptor fingerprint is outdated. Refresh the preview descriptor and retry.',
    'PREVIEW_ADMISSION_FAILED': 'Preview admission failed: artifact or approval evidence differs. Check the current artifact before retrying.',
    'PREVIEW_STARTUP_FAILED': 'Preview startup failed. Check the sanitized native log before retrying.',
}


def safe_failure(exc, stage):
    # Never echo str(exc): SDK/Kit exceptions can include paths, keys or payloads.
    code = ('OWNED_CODE_FINGERPRINT_MISSING' if stage == 'preview_admission'
            and isinstance(exc, ValueError) and str(exc) == 'Native/owned code fingerprint missing'
            else 'PREVIEW_ADMISSION_FAILED' if stage == 'preview_admission' else 'PREVIEW_STARTUP_FAILED')
    name = type(exc).__name__
    name = name if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', name) else 'Error'
    frames = []
    for frame in traceback.extract_tb(exc.__traceback__)[-8:]:
        # Only repo-relative file names and line numbers, never source lines/locals.
        path = Path(frame.filename).resolve()
        root = Path(__file__).resolve().parents[2]
        if path.is_relative_to(root):
            frames.append(dict(file=path.relative_to(root).as_posix(), line=frame.lineno))
    return dict(state='failed', stage=stage, phase=stage, reason_code=code,
                message=MESSAGES[code], exception_class=name, frames=frames,
                at=datetime.now(timezone.utc).isoformat())


def public_failure(data, request_id, session_id):
    """Accept only bound runner diagnostics; arbitrary native text stays private."""
    code = data.get('reason_code')
    if (data.get('state') != 'failed' or code not in MESSAGES
            or data.get('stage') not in {'preview_admission', 'preview_startup'}
            or data.get('request_id') != request_id or data.get('session_id') != session_id):
        return None
    return dict(reason_code=code, stage=data['stage'], error=MESSAGES[code])


def run_preview(options, *, project=None, renderer=None):
    """Recheck the ordinary gate before importing SimulationApp; no migration here."""
    project = (project or Path(__file__).resolve().parents[2]).resolve()
    session = Path(options['session']).resolve()
    request = str(UUID(options['first_request']))
    if (session.parent != project / '.cache/simulator/current-previews/sessions'
            or str(UUID(session.name)) != session.name or not session.is_dir()):
        raise ValueError('Preview session is not backend-owned')
    stage = 'preview_admission'
    try:
        descriptor,_,_=resolve_command(read(session/'queue'/(request+'.json')), read(session/'catalog.json'), project=project)
        stage = 'preview_startup'
        if renderer is None:
            if descriptor.get('robot_demo_only'):
                from backend.demo_robot_isaac_preview import main
            elif descriptor.get('backend')=='dataset_final':
                from backend.simulator_final_preview import main
            elif descriptor.get('geometry_only'):
                from backend.geometry_isaac_preview import main
            else:
                from backend.current_vla_isaac_preview import main
            renderer = main
        renderer(options)
    except Exception as exc:
        failure = safe_failure(exc, stage)
        failure.update(session_id=session.name, request_id=request, exit_code=1)
        # Isaac's Python must not need the backend's PIL/Pydantic dependencies.
        result = session/'results'/(request+'.json')
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=result.parent,
                                         suffix='.tmp', delete=False) as stream:
            json.dump(failure, stream, allow_nan=False)
            temporary = stream.name
        os.replace(temporary, result)
        # This persists even if the parent pipe has already closed. The parent
        # separately records the fixed stdout event in native.log.
        with (session/'startup.native.log').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(failure)+'\n')
        try:
            print('[CURRENT_PREVIEW] '+json.dumps(failure), flush=True)
        except OSError:
            pass  # Owned result/developer log remain when the pipe is closed.
        raise SystemExit(1) from None
