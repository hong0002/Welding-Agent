"""Owned, immutable display evidence. Never a source for downstream prediction.

Only PNG pixels and finite native 2D coordinates are published. Native JSON,
prompts, Markdown and files remain unchanged/private. Acceptance uses the
existing strict readers/proofs independently from this deliberately small gate.
"""
import hashlib
import json
import math
import re
from pathlib import Path
from uuid import UUID

from PIL import Image, ImageDraw

from backend.schemas import ModelOutputDisplay, DisplayPathSegment

MAX_BYTES = 16 * 1024 * 1024
MAX_PIXELS = 12_000_000
MAX_POINTS = 36_864


def _json(path):
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        return None
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, UnicodeError):
        return None


def _point(value):
    if isinstance(value, dict):
        value = [value.get('x'), value.get('y')]
    try:
        if (isinstance(value, (list, tuple)) and len(value) == 2
                and all(type(v) in (int, float) and math.isfinite(v) for v in value)):
            return tuple(value)
    except (OverflowError,ValueError):pass
    return None


def _sample(data, fallback):
    value = data.get('sample_id',data.get('query_sample_id')) if data else None
    if value is None:return fallback
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_]{1,128}', value) else None


def _size(size):
    if not isinstance(size, dict):
        return None
    w, h = size.get('width'), size.get('height')
    return (w, h) if (type(w) is int and type(h) is int and w > 0 and h > 0
                      and w * h <= MAX_PIXELS) else None


def read_path(directory, scene):
    plan_path = directory / 'iteration_001/plan.json'
    guidance_path = directory / 'query_image_guidance_2d.json'
    plan = _json(plan_path)
    data = plan.get('image_guidance_2d') if plan else None
    if not isinstance(data, dict):
        data = _json(guidance_path)
    result = ModelOutputDisplay(available=plan_path.is_file() or guidance_path.is_file(),
        status='OUTPUT_MALFORMED' if plan_path.is_file() or guidance_path.is_file() else 'OUTPUT_MISSING')
    if not data:
        return result
    result.sample_id = _sample(plan or data, scene.sample_id)
    guidance_sample = _sample(data,result.sample_id)
    sample_conflict = guidance_sample != result.sample_id
    if sample_conflict:
        result.warnings.append('DISPLAY_SAMPLE_IDENTITY_CONFLICT')
        if result.sample_id==scene.sample_id:result.sample_id=guidance_sample
    camera = data.get('primary_camera')
    if not isinstance(camera, str):
        camera = None
    size = _size(data.get('image_size'))
    frame = data.get('coordinate_frame_pixel')
    if size is None and camera in scene.views and result.sample_id==scene.sample_id:
        size=(scene.views[camera].width,scene.views[camera].height)
        result.warnings.append('DISPLAY_DIMENSIONS_FROM_SCENE')
    # Unknown/contradictory units cannot become image pixels by guessing.
    frame_valid=isinstance(camera,str) and camera in scene.views and frame==f'image_pixel:{camera}'
    if not frame_valid:result.warnings.append('DISPLAY_FRAME_UNRESOLVED')
    result.primary_camera = camera if isinstance(camera,str) and camera in scene.views else None
    if size:result.width, result.height = size
    result.overlay_allowed = (frame_valid and bool(size) and not sample_conflict and result.sample_id == scene.sample_id
        and size == (scene.views[camera].width, scene.views[camera].height))
    if not result.overlay_allowed:
        result.warnings.append('FOREIGN_OR_STALE_MODEL_OUTPUT')
    segments = data.get('segments')
    if not isinstance(segments, list):
        segments = [{'points_pixel': data.get('points_pixel')}]
    total = 0
    for index, segment in enumerate(segments[:4096]):
        points = segment.get('points_pixel') if isinstance(segment, dict) else None
        if not isinstance(points, list):
            continue
        runs, run = [], []
        for value in points:
            total += 1
            if total > MAX_POINTS:
                result.warnings.append('DISPLAY_LIMIT_EXCEEDED')
                break
            point = _point(value)
            if point is None:
                result.omitted_point_count += 1
                if run:
                    runs.append(run); run = []
            else:
                result.point_count += 1
                run.append(point)
        if run:
            runs.append(run)
        if runs:
            result.segments.append(DisplayPathSegment(segment_index=index, runs=runs))
        if total > MAX_POINTS:
            break
    result.displayable = bool(result.point_count)
    plan_status = plan.get('plan') if plan else None
    result.partial = bool(result.omitted_point_count or not isinstance(plan_status, dict) or
        plan_status.get('status') != 'ready' or 'DISPLAY_LIMIT_EXCEEDED' in result.warnings)
    if result.omitted_point_count:
        result.warnings.append('NONFINITE_OR_INVALID_POINTS_OMITTED')
    if result.displayable:
        result.status = 'OUTPUT_RAW_DISPLAYABLE'
    else:
        result.warnings.append('NO_FINITE_GEOMETRY')
    return result


def _mask_image(path):
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        return None
    try:
        with Image.open(path) as source:
            if source.format != 'PNG' or source.width * source.height > MAX_PIXELS:
                return None
            source.load()
            # Preserve grayscale intensities, including nonbinary model output.
            return source.convert('L')
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def read_masks(directory, scene):
    path = directory / 'iteration_001/result.json'
    data = _json(path)
    result = ModelOutputDisplay(sample_id=_sample(data, scene.sample_id))
    predictions = data.get('predictions', {}) if data else {}
    if not isinstance(predictions, dict):
        predictions = {}
    images = {}
    result.available = path.is_file()
    result.overlay_allowed = result.sample_id == scene.sample_id
    for view, metadata in scene.views.items():
        png = directory / 'iteration_001' / f'{view}_prediction.png'
        prediction = predictions.get(view, {})
        result.available |= png.is_file() or bool(prediction)
        if isinstance(prediction,dict) and prediction.get('camera_id',view)!=view:
            result.overlay_allowed=False
            result.warnings.append('DISPLAY_FRAME_UNRESOLVED')
            continue  # Retain private geometry; never relabel a foreign camera as F.
        image = _mask_image(png)
        if png.is_file() and image is None:
            result.warnings.append('MASK_PNG_MALFORMED')
        if image is None and isinstance(prediction, dict):
            # Native polygon/polyline coordinates, rendered verbatim. No skeleton,
            # interpolation or region reassignment; this is only raster display.
            image = Image.new('L', (metadata.width, metadata.height))
            draw = ImageDraw.Draw(image); count = 0
            for kind in ('polygons', 'polylines'):
                values = prediction.get(kind, [])
                if not isinstance(values, list):
                    continue
                for item in values[:4096]:
                    vertices = item.get('points', []) if isinstance(item, dict) else item
                    if not isinstance(vertices, list) or len(vertices) > 4096:
                        continue
                    points = [_point(p) for p in vertices]
                    if len(points) < 1:continue
                    if any(p is None for p in points):
                        from backend.model_clients.geometry_display import finite_runs
                        runs,omitted=finite_runs(vertices,2)
                        result.omitted_point_count+=omitted
                        result.partial=True
                        for run in runs:
                            if len(run)>1:draw.line([tuple(p) for p in run],fill=255,width=1)
                            else:draw.point(tuple(run[0]),fill=255)
                            count+=len(run)
                    elif kind == 'polygons' and len(points) >= 3:
                        draw.polygon(points, fill=255)
                        count += len(points)
                    elif len(points)>1:
                        draw.line(points, fill=255, width=1)
                        count += len(points)
                    else:draw.point(points[0],fill=255);count+=1
            if not count:
                image = None
        if image is not None:
            if image.size != (metadata.width, metadata.height):
                result.overlay_allowed = False
                result.warnings.append('DISPLAY_DIMENSIONS_MISMATCH')
            images[view] = image
    result.displayable = bool(images)
    result.status = ('OUTPUT_RAW_DISPLAYABLE' if images else
        'OUTPUT_MALFORMED' if result.available else 'OUTPUT_MISSING')
    if result.sample_id != scene.sample_id:
        result.warnings.append('FOREIGN_OR_STALE_MODEL_OUTPUT')
    result.warnings = list(dict.fromkeys(result.warnings))
    return result, images


def seal(storage, job, report, directory, stage):
    """Capture only an attempt already located by the owned runtime/wrapper."""
    if not report.native_artifact_id:
        return
    folder = storage.root / 'native_display' / str(job.id) / str(report.native_artifact_id)
    proof_path = folder / 'display.json'
    if proof_path.exists():
        try:report.model_output=verified(storage,job,report,stage)[0]
        except (OSError,ValueError,KeyError,TypeError):
            report.model_output=ModelOutputDisplay(available=True,status='OUTPUT_MALFORMED',warnings=['DISPLAY_EVIDENCE_INVALID'])
        return  # Never overwrite prior evidence.
    folder.mkdir(parents=True, exist_ok=True)
    files = {}
    if stage == 'segment':
        try:display, images = read_masks(directory, job.scene)
        except (OSError,ValueError,TypeError,KeyError,OverflowError):
            display=ModelOutputDisplay(available=True,status='OUTPUT_MALFORMED',warnings=['DISPLAY_PARSE_FAILED']);images={}
        for view, image in images.items():
            target = folder / f'{view}.png'
            with target.open('xb') as stream:
                image.save(stream, format='PNG')
            files[target.name] = hashlib.sha256(target.read_bytes()).hexdigest()
            display.mask_urls[view] = f'/api/weld/{job.id}/model-output/segment/{view}/image'
    else:
        try:display = read_path(directory, job.scene)
        except (OSError,ValueError,TypeError,KeyError,OverflowError):
            display=ModelOutputDisplay(available=True,status='OUTPUT_MALFORMED',warnings=['DISPLAY_PARSE_FAILED'])
    validated = report.status == 'NATIVE_OUTPUT_VALIDATED' and report.validation.status == 'PASS'
    if validated and display.displayable:
        display.status = 'OUTPUT_VALIDATED'
        display.guided_vla_allowed = stage == 'trajectory'
    report.model_output = display
    payload = dict(job_id=str(job.id), scene_id=str(job.scene.id), sample_id=job.scene.sample_id,
        stage=stage, artifact_id=str(report.native_artifact_id), files=files, model_output=display.model_dump(mode='json'))
    with proof_path.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
    binding = storage.artifact_path('native_context',report.native_artifact_id,f'.{job.id}.display-proof.json')
    with binding.open('x',encoding='utf-8') as stream:
        json.dump({'sha256':hashlib.sha256(proof_path.read_bytes()).hexdigest()},stream)


def verified(storage, job, report, stage):
    """Display copy integrity/scene binding is independent of acceptance lineage."""
    artifact_id = str(UUID(str(report.native_artifact_id)))
    folder = storage.root / 'native_display' / str(job.id) / artifact_id
    data = _json(folder / 'display.json')
    binding = _json(storage.artifact_path('native_context',report.native_artifact_id,f'.{job.id}.display-proof.json'))
    if not binding or binding.get('sha256')!=hashlib.sha256((folder/'display.json').read_bytes()).hexdigest():
        raise ValueError('DISPLAY_EVIDENCE_INVALID')
    if not data or any(data.get(k) != v for k, v in dict(job_id=str(job.id), scene_id=str(job.scene.id),
        sample_id=job.scene.sample_id, stage=stage, artifact_id=artifact_id).items()):
        raise ValueError('DISPLAY_EVIDENCE_INVALID')
    display = ModelOutputDisplay.model_validate(data['model_output'])
    for name, digest in data['files'].items():
        if not re.fullmatch(r'(B|F|L|R|S[1-4]|T)\.png', name):
            raise ValueError('DISPLAY_EVIDENCE_INVALID')
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
            raise ValueError('DISPLAY_EVIDENCE_INVALID')
    return display, folder
