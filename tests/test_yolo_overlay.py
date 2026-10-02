"""Stored native output/fake processes only; HTTP, SDK and native launches forbidden."""
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import ImageDraw

from backend.agent.config import AgentSettings
from backend.main import create_app
from backend.model_clients.native import read_json, sha256
from backend.services.yolo_overlay import read_yolo_overlay
from tests.agent_fakes import FakeRunner, FakeSimulator
from tests.native_stack_fakes import candidate_workflow
from tests.test_guided_vla import save


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    for module in ('native', 'native_rough3d', 'guided_vla', 'config'):
        monkeypatch.setattr('backend.model_clients.' + module + '.ROOT', tmp_path)
    monkeypatch.setattr('backend.services.yolo_overlay.ROOT', tmp_path)
    def forbidden(*a, **kw):
        raise AssertionError('No model, SDK, HTTP or process in YOLO display tests')
    import openai
    import httpx
    monkeypatch.setattr(openai, 'OpenAI', forbidden)
    monkeypatch.setattr(openai, 'AsyncOpenAI', forbidden)
    monkeypatch.setattr('subprocess.Popen', forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', forbidden)
    workflow, transport, calls = candidate_workflow(tmp_path)
    job = workflow.load_sample('SAMPLE_1')
    return workflow, job, transport, calls


def segmented(fixture):
    workflow, job, transport, calls = fixture
    job = workflow.set_mask(job.id)  # Fake native process only.
    return workflow, job, transport, calls


def overlay(workflow, job, **kw):
    return read_yolo_overlay(workflow.storage, job.id, records=workflow.segmentation.runtime.records, **kw)


def change(workflow, job, transform, *, reseal=True):
    records = workflow.segmentation.runtime.records
    record_path = records / f'{job.mask.artifact.provenance.native_source_artifact_id}.json'
    record = read_json(record_path)
    from pathlib import Path
    path = Path(record['directory']) / 'yolo/detections.json'
    data = read_json(path)
    transform(data)
    save(path, data)
    if reseal:
        record['files']['yolo/detections.json'] = sha256(path)
        save(record_path, record)
    return path, record_path


def test_native_display_contract_exact_identity_dimensions_and_sanitization(fixture):
    w, job, t, calls = segmented(fixture)
    result = overlay(w, job)
    assert result.available and result.sample_id == 'SAMPLE_1'
    assert result.artifact_id == job.mask.artifact.provenance.native_source_artifact_id
    assert list(result.views) == ['B','F','L','R','S1','S2','S3','S4','T']
    assert result.views['F'].image_width == result.views['F'].image_height == 100
    assert result.views['F'].detections[0].bbox.model_dump() == dict(x_min=12., y_min=15., x_max=40., y_max=45.)
    assert result.views['F'].detections[0].confidence == .93
    assert result.coordinate_space == 'image_pixel' and result.display_only
    assert len(result.views['R'].detections) == 2 and not result.views['S1'].detections
    assert result.views['R'].detections[1].confidence is None
    assert not result.trajectory3_reuse_verified
    text = result.model_dump_json()
    assert all(s not in text for s in ('/server','manifest_path','weights','prompt','ssh','full_image_path','points_pixel'))
    assert len(calls['segment']) == 1 and not calls['rough3d'] and not t.calls


@pytest.mark.parametrize('target', ['native', 'record', 'scene_proof'])
def test_wrong_sample_binding(fixture, target):
    w, job, _, _ = segmented(fixture)
    if target == 'native':
        change(w, job, lambda d: d.update(sample_id='OTHER'))
    elif target == 'record':
        records = w.segmentation.runtime.records
        p = records / f'{job.mask.artifact.provenance.native_source_artifact_id}.json'
        r = read_json(p); r['sample_id'] = 'OTHER'; save(p, r)
    else:
        p = w.storage.artifact_path('native_context', job.id, '.scene.json')
        r = read_json(p); r['sample_id'] = 'OTHER'; save(p, r)
    result = overlay(w, job)
    assert not result.available and not result.views and result.warnings == ['YOLO_SAMPLE_MISMATCH']


@pytest.mark.parametrize('mode', ['invalid_view', 'image_identity', 'dimensions'])
def test_wrong_view_rejects_only_affected_view(fixture, mode):
    w, job, _, _ = segmented(fixture)
    def transform(d):
        if mode == 'invalid_view':d['cameras']['WRONG'] = d['cameras'].pop('F')
        elif mode == 'image_identity':d['cameras']['F']['full_image_path'] = d['cameras']['R']['full_image_path']
        else:d['cameras']['F']['width'] = 101
    change(w, job, transform)
    r = overlay(w, job)
    assert r.available and 'F' not in r.views and 'WRONG' not in r.views and 'R' in r.views
    assert r.warnings == ['YOLO_COORDINATE_INVALID' if mode == 'dimensions' else 'YOLO_VIEW_MISMATCH']


@pytest.mark.parametrize('xyxy', [[40,0,12,10], [0,40,10,12], [-1,0,10,10], [0,0,101,10],
                                 [0,0,10,101], [0,float('nan'),10,10], [0,0,float('inf'),10], ['0',0,10,10], [0,0,10]])
def test_bad_box_nonfinite_and_bounds_warning_preserves_other_detections(fixture, xyxy):
    w, job, _, _ = segmented(fixture)
    change(w, job, lambda d: d['cameras']['F']['boxes'].append(dict(xyxy=xyxy)))
    r = overlay(w, job)
    assert r.available and len(r.views['F'].detections) == 1
    assert r.warnings == ['YOLO_COORDINATE_INVALID']


@pytest.mark.parametrize('confidence', [-1, 1.1, float('nan'), float('inf'), '0.9', True])
def test_bad_confidence_only_drops_box(fixture, confidence):
    w, job, _, _ = segmented(fixture)
    change(w, job, lambda d: d['cameras']['F']['boxes'][0].update(confidence=confidence))
    r = overlay(w, job)
    assert r.available and not r.views['F'].detections and r.warnings == ['YOLO_ARTIFACT_MALFORMED']


def test_display_ids_are_unique_indices_and_no_invented_class_or_score(fixture):
    w, job, _, _ = segmented(fixture)
    change(w, job, lambda d: d['cameras']['F']['boxes'].extend([dict(xyxy=[1,2,3,4]), dict(xyxy=[1,2,3,4])]))
    r = overlay(w, job)
    assert [d.detection_id for d in r.views['F'].detections] == ['F:0','F:1','F:2']
    assert r.views['F'].detections[1].model_dump(exclude_none=True) == dict(
        detection_id='F:1', bbox=dict(x_min=1., y_min=2., x_max=3., y_max=4.))


def test_no_artifact_stale_hash_redetection_and_running(fixture):
    w, job, _, _ = fixture
    assert overlay(w, job).warnings == ['YOLO_OUTPUT_NOT_AVAILABLE']
    job = w.set_mask(job.id)
    original = overlay(w, job).artifact_id
    assert overlay(w, job, running=True).warnings == ['YOLO_OUTPUT_STALE']
    change(w, job, lambda d: d.update(sample_id='OTHER'), reseal=False)
    assert not overlay(w, job).available and overlay(w, job).warnings == ['YOLO_OUTPUT_STALE']
    job = w.set_mask(job.id)
    assert overlay(w, job).available and overlay(w, job).artifact_id != original
    # A stale session name cannot fall back to another successful sample run.
    job.mask.artifact.provenance.native_session_id = 'old'
    w.storage.save_job(job)
    assert overlay(w, job).warnings == ['YOLO_OUTPUT_STALE']


def test_missing_file_invalid_frame_and_malformed_json_nonfatal(fixture):
    w, job, _, _ = segmented(fixture)
    path, _ = change(w, job, lambda d: d.update(coordinate_frame='letterbox_normalized'))
    assert overlay(w, job).warnings == ['YOLO_COORDINATE_INVALID']
    path.unlink()
    assert overlay(w, job).warnings == ['YOLO_OUTPUT_NOT_AVAILABLE']
    assert w.approve_mask(job.id, job.mask.id, 'F').mask.approved


def test_sealed_malformed_json_is_a_display_warning(fixture):
    w, job, _, _ = segmented(fixture)
    path, record_path = change(w, job, lambda _:None)
    path.write_text('{malformed', encoding='utf-8')
    record = read_json(record_path)
    record['files']['yolo/detections.json'] = sha256(path)
    save(record_path, record)
    result = overlay(w, job)
    assert not result.available and result.warnings == ['YOLO_ARTIFACT_MALFORMED']
    assert w.approve_mask(job.id, job.mask.id, 'F').mask.approved


def test_manual_edit_preserves_yolo_lineage_and_original_file(fixture):
    w, job, t, calls = segmented(fixture)
    original = overlay(w, job).model_dump()
    mask = w.storage.read_image('masks', job.mask.id)
    ImageDraw.Draw(mask).rectangle((10,18,15,18), fill=0)
    stream = BytesIO(); mask.save(stream, format='PNG')
    job = w.set_mask(job.id, stream.getvalue(), edited_from_mask_id=job.mask.id, view_id='F')
    assert job.mask.mask_source == 'manual_edited'
    assert overlay(w, job).model_dump() == original
    assert len(calls['segment']) == 1 and not calls['rough3d'] and not t.calls


def test_api_read_only_method_no_browser_paths_no_agent_bbox(fixture):
    w, job, _, calls = segmented(fixture)
    from backend.agent.context import workspace_summary
    summary = workspace_summary(job)
    assert 'bbox' not in str(summary) and 'yolo' not in str(summary).lower()
    # In-process ASGI, never a network transport.
    with TestClient(create_app(workflow=w, simulator=FakeSimulator(), agent_runner=FakeRunner(),
                              agent_settings=AgentSettings(api_key='offline'))) as client:
        response = client.get(f'/api/weld/{job.id}/yolo')
        assert response.status_code == 200 and response.json()['available']
        assert client.post(f'/api/weld/{job.id}/yolo', json={'path':'C:/elsewhere'}).status_code == 405
        assert client.get(f'/api/weld/{job.id}/yolo?path=C:/elsewhere').status_code == 400
        assert client.get(f'/api/weld/{uuid4()}/yolo').status_code == 404
    assert len(calls['segment']) == 1 and not calls['rough3d']
