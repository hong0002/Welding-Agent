"""Read-only Segment2 YOLO display adapter. Never invokes a native process/model."""
from math import isfinite
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.model_clients.config import ROOT
from backend.model_clients.native import CAMERAS, read_json, sha256


class DisplaySchema(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class YoloBox(DisplaySchema):
    x_min: float
    y_min: float
    x_max: float
    y_max: float


class YoloDetection(DisplaySchema):
    detection_id: str  # Display ID: camera + original box index, never a native ID.
    class_id: int | None = None
    confidence: float | None = None
    bbox: YoloBox


class YoloView(DisplaySchema):
    image_width: int
    image_height: int
    detections: list[YoloDetection]


class YoloOverlay(DisplaySchema):
    source: Literal['segment2_native_yolo'] = 'segment2_native_yolo'
    display_only: Literal[True] = True
    coordinate_space: Literal['image_pixel'] = 'image_pixel'
    frame: Literal['image_top_left_x_right_y_down'] = 'image_top_left_x_right_y_down'
    job_id: UUID
    scene_id: UUID | None = None
    sample_id: str | None = None
    artifact_id: UUID | None = None
    available: bool = False
    views: dict[str, YoloView] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    trajectory3_reuse_verified: bool = False


class OverlayInvalid(Exception):
    def __init__(self, code):
        self.code = code


def require(value, code):
    if not value:
        raise OverlayInvalid(code)


def _reuse_verified(storage, job, records, yolo_hash):
    """Only claim reuse with a sealed current output AND native YOLO REUSE diagnostic."""
    if not job.native_output or not job.native_output.native_artifact_id:
        return False
    try:
        from backend.model_clients.native_candidate import verify_snapshot
        directory, proof = verify_snapshot(storage, job)
        capture = read_json(records / f'{job.native_output.native_artifact_id}.capture.json')
        require(capture['sample_id'] == job.scene.sample_id and
                Path(capture['directory']).resolve() == directory, 'YOLO_OUTPUT_STALE')
        require(proof['files']['yolo/detections.json'] == yolo_hash, 'YOLO_OUTPUT_STALE')
        reuse = read_json(directory / 'yolo/provenance.json')
        require(reuse['mode'] == 'explicit_previous_stage', 'YOLO_OUTPUT_STALE')
        diagnostic_id = UUID(capture['diagnostic_id'])
        log = records / 'diagnostics' / f'{diagnostic_id}.jsonl'
        require(log.stat().st_size <= 8_000_000, 'YOLO_ARTIFACT_MALFORMED')
        import json
        return any(line.get('event') == 'yolo_milestone' and line.get('mode') == 'YOLO REUSE'
                   for line in (json.loads(s) for s in log.read_text(encoding='utf-8').splitlines()))
    except Exception:
        # Missing optional reuse evidence never hides valid Segment2 boxes.
        return False


def read_yolo_overlay(storage, job_id, *, records=None, running=False):
    """Resolve only the CURRENT F-mask's original Segment2 lineage, no sample search."""
    records = Path(records or ROOT / '.cache/native-models').resolve()
    with storage.lock:
        job = storage.get_job(job_id)  # No workflow recovery/mutation on this GET.
        scene = job.scene
        result = YoloOverlay(job_id=job.id, scene_id=scene.id if scene else None,
                             sample_id=scene.sample_id if scene else None)
        try:
            require(not running, 'YOLO_OUTPUT_STALE')
            mask = job.mask
            require(scene and scene.views and mask and mask.artifact and
                    mask.artifact.provenance.native_source_artifact_id, 'YOLO_OUTPUT_NOT_AVAILABLE')
            meta = mask.artifact.provenance
            result.artifact_id = meta.native_source_artifact_id
            require(scene.primary_view == 'F' and scene.views['F'].mask and
                    scene.views['F'].mask.id == mask.id and mask.scene_id == scene.id and
                    meta.source_scene_id == scene.id, 'YOLO_OUTPUT_STALE')
            record = read_json(records / f'{meta.native_source_artifact_id}.json')
            require(record.get('stage') == 'segment' and record.get('native_stack') == 'native_v2' and
                    record.get('artifact_id') == str(meta.native_source_artifact_id), 'YOLO_OUTPUT_STALE')
            require(record.get('sample_id') == scene.sample_id, 'YOLO_SAMPLE_MISMATCH')
            directory = Path(record['directory']).resolve()
            require(directory.is_relative_to((ROOT / '.cache').resolve()) and
                    directory.name == meta.native_session_id, 'YOLO_OUTPUT_STALE')
            name = 'yolo/detections.json'
            require(name in record['files'] and (directory / name).is_file(), 'YOLO_OUTPUT_NOT_AVAILABLE')
            require((directory / name).resolve().is_relative_to(directory) and
                    sha256(directory / name) == record['files'][name], 'YOLO_OUTPUT_STALE')
            native_result = directory / 'iteration_001/result.json'
            require(sha256(native_result) == record['files']['iteration_001/result.json'], 'YOLO_OUTPUT_STALE')
            require(read_json(native_result).get('sample_id') == scene.sample_id, 'YOLO_SAMPLE_MISMATCH')
            data = read_json(directory / name)
            require(data.get('sample_id') == scene.sample_id, 'YOLO_SAMPLE_MISMATCH')
            require(data.get('schema_version') == 1 and data.get('bbox_source') == 'server_yolo',
                    'YOLO_ARTIFACT_MALFORMED')
            require(data.get('coordinate_frame') == 'original_image_pixels_xyxy', 'YOLO_COORDINATE_INVALID')
            require(isinstance(data.get('request_id'), str) and data['request_id'], 'YOLO_ARTIFACT_MALFORMED')
            cameras = data.get('cameras')
            require(isinstance(cameras, dict), 'YOLO_ARTIFACT_MALFORMED')
            # Scene proof seals the normalized images against which boxes are rendered.
            proof = read_json(storage.artifact_path('native_context', job.id, '.scene.json'))
            require(proof.get('sample_id') == scene.sample_id, 'YOLO_SAMPLE_MISMATCH')
            for view, item in cameras.items():
                try:
                    require(view in CAMERAS and view in scene.views and scene.views[view].view_id == view,
                            'YOLO_VIEW_MISMATCH')
                    image = scene.views[view]
                    require(proof['hashes'][view] == image.image_sha256 and
                            sha256(storage.artifact_path('scenes', image.image_id)) == proof['normalized_hashes'][view],
                            'YOLO_OUTPUT_STALE')
                    require(isinstance(item, dict) and type(item.get('width')) is int and
                            type(item.get('height')) is int and
                            (item['width'], item['height']) == (image.width, image.height), 'YOLO_COORDINATE_INVALID')
                    original = storage.read_image('scenes', image.image_id)
                    require(original.size == (image.width, image.height), 'YOLO_COORDINATE_INVALID')
                    # Native upload uses fixed camera filenames under its request UUID.
                    path = PurePosixPath(item.get('full_image_path', ''))
                    require(path.name == f'{view}.png' and path.parent.name == data['request_id'], 'YOLO_VIEW_MISMATCH')
                    boxes = item.get('boxes')
                    require(isinstance(boxes, list) and len(boxes) <= 1000, 'YOLO_ARTIFACT_MALFORMED')
                    detections = []
                    for index, box in enumerate(boxes):
                        try:
                            require(isinstance(box, dict), 'YOLO_ARTIFACT_MALFORMED')
                            xyxy = box.get('xyxy')
                            require(isinstance(xyxy, list) and len(xyxy) == 4 and
                                    all(type(n) in (int, float) and isfinite(n) for n in xyxy), 'YOLO_COORDINATE_INVALID')
                            x0, y0, x1, y1 = xyxy
                            require(0 <= x0 <= x1 <= image.width and 0 <= y0 <= y1 <= image.height,
                                    'YOLO_COORDINATE_INVALID')
                            class_id = box.get('class_id')
                            confidence = box.get('confidence')
                            require(class_id is None or type(class_id) is int and class_id >= 0, 'YOLO_ARTIFACT_MALFORMED')
                            require(confidence is None or type(confidence) in (int, float) and
                                    isfinite(confidence) and 0 <= confidence <= 1, 'YOLO_ARTIFACT_MALFORMED')
                            detections.append(YoloDetection(detection_id=f'{view}:{index}', class_id=class_id,
                                confidence=confidence, bbox=YoloBox(x_min=x0, y_min=y0, x_max=x1, y_max=y1)))
                        except OverlayInvalid as exc:
                            result.warnings.append(exc.code)
                    result.views[view] = YoloView(image_width=image.width, image_height=image.height, detections=detections)
                except OverlayInvalid as exc:
                    result.warnings.append(exc.code)
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    result.warnings.append('YOLO_ARTIFACT_MALFORMED')
            result.available = bool(result.views)
            result.trajectory3_reuse_verified = _reuse_verified(storage, job, records, record['files'][name])
        except OverlayInvalid as exc:
            result.views = {}
            result.warnings.append(exc.code)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            result.views = {}
            result.warnings.append('YOLO_ARTIFACT_MALFORMED')
        result.warnings = sorted(set(result.warnings))
        return result
