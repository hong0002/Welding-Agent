from dataclasses import replace
from io import BytesIO
import json
from uuid import UUID
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from backend.main import create_app
from backend.model_clients.guided_vla import GuidedVLAError
from backend.model_clients.native import CAMERAS, read_json
from backend.orchestrator.state_machine import WorkflowError
from tests.module_fakes import module_workflow


@pytest.fixture
def modules(tmp_path, monkeypatch):
    for module in ('guided_vla', 'native_rough3d', 'native', 'config'):
        monkeypatch.setattr(f'backend.model_clients.{module}.ROOT', tmp_path)
    workflow, transport = module_workflow(tmp_path)
    with TestClient(create_app(workflow=workflow)) as client:
        yield workflow, transport, client


def rough_job(workflow):
    job = workflow.load_sample('SAMPLE_1')
    job = workflow.set_mask(job.id)
    job = workflow.approve_mask(job.id, job.mask.id, 'F')
    job = workflow.parse_instruction(job.id, '왼쪽에서 오른쪽으로 용접해')
    return workflow.plan(job.id)


def test_api_nine_views_segment_approval_guided_ready_independent(modules):
    workflow, transport, client = modules
    loaded = client.post('/api/scenes/sample', json={'sample_id': 'SAMPLE_1'})
    assert loaded.status_code == 201
    job = loaded.json(); jid = job['id']
    assert list(job['scene']['views']) == list(CAMERAS)
    assert job['rough_mode'] == 'native_3d' and job['scene']['primary_view'] == 'F'
    for view in job['scene']['views'].values():
        assert view['mask'] is None
        assert client.get(view['image_url']).status_code == 200
    assert client.post(f'/api/weld/{jid}/guided-vla', json={}).status_code == 409
    job = client.post('/api/masks/automatic', json={'job_id':jid}).json()
    assert [v for v in CAMERAS if job['scene']['views'][v]['mask']] == ['F','R','S4']
    assert all(job['scene']['views'][v]['mask']['approved'] is False for v in ('F','R','S4'))
    assert client.post('/api/instructions/parse', json={'job_id':jid,'instruction':'왼쪽에서 오른쪽으로'}).status_code == 409
    job = client.post('/api/masks/approve', json={'job_id':jid,'mask_id':job['mask']['id'],'view_id':'F'}).json()
    assert job['mask']['approved'] and not job['scene']['views']['R']['mask']['approved']
    assert client.post('/api/instructions/parse', json={'job_id':jid,'instruction':'왼쪽에서 오른쪽으로 용접해'}).status_code == 200
    job = client.post('/api/weld/plan', json={'job_id':jid}).json()
    assert job['state'] == 'ROUGH_PATH_READY'
    assert job['rough3d']['reference_in_request'] is False
    assert client.get(job['rough3d']['reference_preview_url']).status_code == 200
    assert len(job['rough_trajectory']['segments']) == 1 and job['final_trajectory'] is None
    assert transport.calls == []
    assert transport.health_calls == 0
    assert client.post(f'/api/weld/{jid}/guided-vla', json={'server':'untrusted'}).status_code == 422
    result = client.post(f'/api/weld/{jid}/guided-vla', json={})
    assert result.status_code == 200, result.text
    job = result.json()
    assert job['state'] == 'VLA_READY' and job['vla_prediction']['point_count'] == 9
    assert job['vla_prediction']['simulator_ready'] is False
    assert job['vla_prediction']['physical_robot_executable'] is False
    assert 'predicted_path_xyz_mm' not in result.text and 'test-secret' not in result.text
    assert job['final_trajectory'] is None and job['validation'] is None
    assert len(transport.calls) == 1
    assert transport.health_calls == 1
    files = transport.calls[0]['files']
    assert [spec[0] for _, spec in files] == ['guidance.md','F_mask.png']
    assert b'registered_to_query' not in files[0][1][1].getvalue()
    assert client.post(f'/api/weld/{jid}/guided-vla', json={}).status_code == 409
    assert len(transport.calls) == 1
    assert client.get('/api/simulator/status').json()['state'] == 'STOPPED'
    attempt = workflow.guided_vla.settings.attempts / job['vla_prediction']['attempt_id']
    manifest = read_json(attempt/'request_manifest.json')
    assert manifest['mask_views'] == ['F'] and manifest['reference_in_request'] is False
    assert read_json(attempt/'submission.json')['live_called'] is False
    assert read_json(attempt/'completion.json')['response_validated'] is True
    assert workflow.guided_vla.verify(attempt)[0] == manifest  # survives the VLA_READY snapshot update


def test_upload_exact_hash_canonical_views_missing_and_ambiguous(modules):
    workflow, _, client = modules
    scene = workflow.dataset.resolve('SAMPLE_1')
    source = scene.images['R']
    job = client.post('/api/scenes/upload', files={'file':(source.name,source.read_bytes(),'image/png')}).json()
    assert list(job['scene']['views']) == list(CAMERAS) and job['scene']['sample_id'] == 'SAMPLE_1'
    assert client.post('/api/scenes/upload', files={'file':(source.name,b'wrong','image/png')}).status_code == 409
    assert client.post('/api/scenes/sample', json={'sample_id':'../outside'}).status_code == 422
    scene.images['T'].unlink()
    with pytest.raises(WorkflowError, match='9-view'): workflow.load_sample('SAMPLE_1')


def test_per_view_manual_edited_invalidation_and_dimensions(modules):
    workflow, transport, _ = modules
    job = rough_job(workflow)
    assert not job.scene.views['R'].mask.approved
    old = job.scene.views['R'].mask
    mask = workflow.storage.read_image('masks', old.id)
    mask.putpixel((10,18),0)
    stream = BytesIO();mask.save(stream,format='PNG')
    changed = workflow.set_mask(job.id,stream.getvalue(),view_id='R',edited_from_mask_id=old.id)
    assert changed.scene.views['R'].mask.mask_source == 'manual_edited'
    assert changed.scene.views['R'].mask.approved and changed.mask.approved
    assert changed.rough3d is None and changed.rough_trajectory is None and changed.instruction is None
    assert transport.calls == []
    stored = workflow.storage.read_image('masks',changed.scene.views['R'].mask.id)
    assert stored.size == (100,100) and set(np.unique(stored)) == {0,255}
    with pytest.raises(WorkflowError):workflow.approve_mask(job.id,old.id,'R')


@pytest.mark.parametrize('mutation',['mask','guidance','scene','instruction','manifest','reference'])
def test_stale_input_rejected_before_any_prediction(modules, mutation):
    workflow, transport, _ = modules
    job = rough_job(workflow)
    attempt = workflow.guided_vla.prepare_workflow(workflow.storage,job)
    if mutation == 'mask':
        image = workflow.storage.read_image('masks',job.mask.id);image.putpixel((10,20),0)
        workflow.storage.save_image('masks',job.mask.id,image)
    elif mutation == 'guidance':(attempt/'guidance.md').write_text('changed')
    elif mutation == 'reference':(attempt/'reference_trajectory_3d.json').write_text('{}')
    elif mutation == 'scene':workflow.dataset.resolve('SAMPLE_1').images['S4'].write_bytes(b'changed')
    elif mutation == 'instruction':workflow.parse_instruction(job.id,'오른쪽에서 왼쪽으로 용접해')
    else:(attempt/'request_manifest.json').write_text('{}')
    with pytest.raises(GuidedVLAError, match='CHANGED'):workflow.guided_vla.execute(attempt)
    assert transport.calls == [] and not (attempt/'submission.json').exists()


def test_vla_ready_edit_invalidates_and_baseline_remains(modules):
    workflow, transport, _ = modules
    job = rough_job(workflow)
    ready = workflow.run_guided_vla(job.id)
    assert ready.state.value == 'VLA_READY'
    changed = workflow.parse_instruction(job.id,'오른쪽에서 왼쪽으로 용접해')
    assert changed.vla_prediction is None and changed.rough3d is None
    workflow.select_rough_mode(job.id,'baseline_2d')
    baseline = workflow.plan(job.id)
    assert baseline.state.value == 'VALIDATED' and baseline.final_trajectory
    assert baseline.vla_prediction is None and len(transport.calls) == 1


@pytest.mark.parametrize('message',[
    '왼쪽에서 오른쪽으로 경로를 만들어줘', 'VLA 실행하지 마',
    "Don't run Guided VLA", 'Explain how to run VLA', '기존 VLA 샘플 실행해',
    '현재 VLA를 Isaac에서 실행해',
])
def test_agent_guided_intent_gate_no_calls(modules, message):
    import asyncio
    from backend.agent.context import WeldingAgentContext
    from tests.agent_fakes import FakeSimulator, invoke
    workflow, transport, _ = modules
    job = rough_job(workflow)
    context = WeldingAgentContext(job.id,'test-session',message,workflow,FakeSimulator(),lambda *_:None)
    context.remember(job)
    result = asyncio.run(invoke(context,'run_guided_vla'))
    assert result['code'] == 'guided_vla_intent_required'
    assert transport.calls == [] and transport.health_calls == 0


def test_agent_guided_explicit_intent_summary_and_single_attempt(modules):
    import asyncio
    from backend.agent.context import WeldingAgentContext, workspace_summary
    from tests.agent_fakes import FakeSimulator, invoke
    workflow, transport, _ = modules
    job = rough_job(workflow)
    context = WeldingAgentContext(job.id,'test-session','Guided VLA 예측 실행해',workflow,FakeSimulator(),lambda *_:None)
    context.remember(job)
    async def run():
        result = await invoke(context,'run_guided_vla')
        repeated = await invoke(context,'run_guided_vla')
        return result,repeated
    result,repeated = asyncio.run(run())
    assert result['point_count'] == 9 and result['simulator_ready'] is False
    assert repeated['code'] == 'guided_vla_already_attempted' and len(transport.calls) == 1
    summary = json.dumps(workspace_summary(workflow.get_job(job.id)))
    assert all(s not in summary for s in ('points_pixel','points_xyz','predicted_path','native_context',str(workflow.storage.root)))


def test_health_probe_failure_and_incomplete_multi_region_rough_fail_closed(modules):
    workflow, transport, _ = modules
    job = rough_job(workflow)
    transport.health = lambda:{'status':'loading','waypoints':9,'dimensions':3}
    with pytest.raises(GuidedVLAError,match='SERVER_UNAVAILABLE'):workflow.run_guided_vla(job.id)
    assert not workflow.guided_vla.settings.attempts.exists() and not transport.calls
    mask = workflow.storage.read_image('masks',job.mask.id)
    for y in range(60,65):
        for x in range(10,50):mask.putpixel((x,y),255)
    stream = BytesIO();mask.save(stream,format='PNG')
    workflow.set_mask(job.id,stream.getvalue(),view_id='F',edited_from_mask_id=job.mask.id)
    workflow.parse_instruction(job.id,'왼쪽에서 오른쪽으로 용접해')
    before = len(workflow.rough3d.received_masks)
    current=workflow.generate_rough(job.id)
    # The fake model emits just one segment for two requested regions. Rough
    # now dispatches, but incomplete correspondence cannot become accepted.
    assert len(workflow.rough3d.received_masks) == before+1
    assert current.rough3d is None and current.rough_trajectory is None
    assert current.native_output.status=='NATIVE_OUTPUT_READY_UNVALIDATED'
    assert 'region_mapping' in {i.code for i in current.native_output.validation.issues}
    assert not transport.calls
