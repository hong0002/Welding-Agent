"""New version/Agent/Guided contracts with fake native outputs only."""
import asyncio
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
import re
from uuid import UUID
import pytest
from fastapi.testclient import TestClient
from PIL import ImageDraw
from backend.agent.config import AgentSettings
from backend.agent.context import WeldingAgentContext
from backend.agent.mask_intent import MaskIntent
from backend.main import create_app
from backend.model_clients.contracts import ModelFault
from backend.model_clients.native import CAMERAS, read_json, read_native_result, sha256
from backend.model_clients.native_profiles import native_profile
from backend.model_clients.guided_vla import serialize_guidance, GuidedVLAError
from backend.model_clients.native_rough3d import NativeRough3DClient
from backend.orchestrator.state_machine import WorkflowError
from tests.agent_fakes import FakeSimulator, FakeRunner, invoke
from tests.test_agent import events
from tests.native_stack_fakes import candidate_workflow


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    for module in ('native','native_rough3d','guided_vla','config'):
        monkeypatch.setattr('backend.model_clients.'+module+'.ROOT',tmp_path)
    import openai
    def forbidden(*args,**kwargs):raise AssertionError('No real API or SSH in migration tests')
    monkeypatch.setattr(openai,'OpenAI',forbidden)
    monkeypatch.setattr(openai,'AsyncOpenAI',forbidden)
    return candidate_workflow(tmp_path)


@pytest.mark.parametrize('message',['마스크 씌워줘','마스크 만들어줘','용접 영역 찾아줘','용접선 찾아줘',
    '용접할 부분 표시해줘','자동으로 검출해줘','VLM으로 영역 찾아줘','용접 위치 찾아줘'])
def test_scene_ready_mask_intent_runs_only_segment_no_approval(candidate,message):
    workflow,transport,calls=candidate
    job=workflow.load_sample('SAMPLE_1')
    runner=FakeRunner();sim=FakeSimulator()
    with TestClient(create_app(workflow=workflow,simulator=sim,agent_runner=runner,
            agent_settings=AgentSettings(api_key='offline'))) as api:
        sid=api.post('/api/agent/sessions').json()['session_id']
        stream=events(api.post('/api/agent/chat/stream',json={'session_id':sid,'job_id':str(job.id),'message':message}))
        assert stream[-1][1]['ok'] is True,stream
        names=[data['tool'] for event,data in stream if event=='tool_started']
        assert names==['get_workspace_state','detect_weld_mask']
        assert any(event=='workspace_updated' for event,_ in stream)
        assert runner.calls==0 and not sim.calls
        assert not any(secret in json.dumps(stream) for secret in ('points_pixel','polylines','LOCAL_PATH','cot_ko.md'))
    current=workflow.get_job(job.id)
    assert list(current.scene.views)==list(CAMERAS)
    assert [v for v,s in current.scene.views.items() if s.mask]==['F','R','S4']
    assert all(not current.scene.views[v].mask.approved for v in ('F','R','S4'))
    assert len(calls['segment'])==1 and not calls['rough3d'] and not transport.calls
    with pytest.raises(WorkflowError):workflow.parse_instruction(job.id,'왼쪽에서 오른쪽으로 용접해')


def planned(workflow):
    job=workflow.load_sample('SAMPLE_1');job=workflow.set_mask(job.id)
    job=workflow.approve_mask(job.id,job.mask.id,'F')
    workflow.parse_instruction(job.id,'왼쪽에서 오른쪽으로 용접해')
    return workflow.plan(job.id)


def test_v3_approved_session_json_guidance_exact_guided_package_and_no_request(candidate):
    workflow,transport,calls=candidate
    job=planned(workflow)
    assert len(calls['segment'])==len(calls['rough3d'])==1
    assert job.rough_trajectory.generator=='vlm_trajectory3:native'
    assert job.rough3d.is_robot_executable is False and job.rough3d.reference_in_request is False
    proof=read_json(workflow.storage.artifact_path('native_context',job.rough3d.artifact_id,'.rough3d.json'))
    saved=NativeRough3DClient.load_saved(proof['directory'],'SAMPLE_1')
    assert saved.native_stack=='vlm_trajectory3'
    assert saved.reference_trajectory_3d.unit=='mm' and not saved.reference_trajectory_3d.is_robot_executable
    assert saved.reference_trajectory_3d.registered_to_query is False
    approved=Path(calls['rough3d'][0][-1]);sealed=workflow.rough3d.approvals.verify(
        approved,workflow.storage.read_image('masks',job.mask.id),job.mask)
    assert 'yolo/detections.json' in sealed['files']
    attempt=workflow.guided_vla.prepare_workflow(workflow.storage,job)
    manifest,files=workflow.guided_vla.verify(attempt)
    assert manifest['split']=='train' and manifest['mask_views']==['F'] and manifest['reference_in_request'] is False
    assert manifest['live_called'] is False and not (attempt/'submission.json').exists()
    assert files['masks/F_mask.png']==workflow.storage.artifact_path('masks',job.mask.id).read_bytes()
    text=files['guidance.md'].decode()
    points=[[float(x),float(y)] for x,y in re.findall(r'P\d+ = \(([^,]+), ([^)]+)\)',text)]
    assert points==saved.image_guidance_2d['segments'][0]['points_normalized']
    assert 'points_xyz_mm' not in text and 'retrieved_teaching' not in text
    assert not transport.calls and transport.health_calls==0
    (approved/'yolo/detections.json').write_text('{}')
    with pytest.raises(ModelFault):workflow.rough3d.approvals.verify(approved,workflow.storage.read_image('masks',job.mask.id),job.mask)


def test_redetection_preserves_previous_masks_invalidates_and_requires_new_approval(candidate):
    workflow,transport,calls=candidate
    job=planned(workflow)
    # Offline transport only verifies unchanged VLA_READY regression behavior.
    job=workflow.run_guided_vla(job.id)
    previous=job.mask;path=workflow.storage.artifact_path('masks',previous.id);digest=sha256(path)
    context=WeldingAgentContext(job.id,'offline','마스크 다시 찾아줘',workflow,FakeSimulator(),lambda *_:None)
    async def run():
        await invoke(context,'get_workspace_state')
        result=await invoke(context,'detect_weld_mask')
        assert result['approval_required'] and result['views']==['F','R','S4']
        assert (await invoke(context,'detect_weld_mask'))['code']=='segmentation_already_attempted'
    asyncio.run(run())
    current=workflow.get_job(job.id)
    assert current.mask.id!=previous.id and not current.mask.approved
    assert current.mask.artifact.provenance.source_mask_id==previous.id
    assert sha256(path)==digest and workflow.storage.artifact_path('masks',previous.id,'.json').is_file()
    assert current.instruction is current.rough_trajectory is current.rough3d is current.vla_prediction is None
    assert len(calls['segment'])==2 and len(calls['rough3d'])==1 and len(transport.calls)==1


def test_existing_approved_mask_requires_explicit_redetection(candidate):
    workflow,_,calls=candidate;job=planned(workflow)
    context=WeldingAgentContext(job.id,'offline','마스크 씌워줘',workflow,FakeSimulator(),lambda *_:None)
    async def run():
        await invoke(context,'get_workspace_state')
        result=await invoke(context,'detect_weld_mask')
        assert result['reused_existing_mask']
    asyncio.run(run())
    assert workflow.get_job(job.id).mask.id==job.mask.id and len(calls['segment'])==1


def test_manual_edited_eraser_contract_and_baseline_remain(candidate):
    workflow,_,_=candidate
    job=workflow.load_sample('SAMPLE_1');job=workflow.set_mask(job.id);original=job.mask
    mask=workflow.storage.read_image('masks',original.id)
    ImageDraw.Draw(mask).rectangle((10,18,15,18),fill=0) # border removal retains original native centerline
    stream=BytesIO();mask.save(stream,format='PNG')
    job=workflow.set_mask(job.id,stream.getvalue(),edited_from_mask_id=original.id,view_id='F')
    assert job.mask.mask_source=='manual_edited' and job.mask.approved
    image,mask,components=workflow._conditioning(job)
    session,_,proof=workflow.rough3d.prepare_session(image,mask,components)
    assert proof['mask_source']=='manual_edited' and proof['mask_id']==str(job.mask.id)
    workflow.rough3d.approvals.verify(session,mask,job.mask)
    workflow.select_rough_mode(job.id,'baseline_2d')
    workflow.parse_instruction(job.id,'왼쪽에서 오른쪽으로 용접해')
    assert workflow.plan(job.id).state.value=='VALIDATED'


def test_v3_no_mask_and_malformed_guidance_fail_closed(candidate):
    workflow,_,_=candidate;job=planned(workflow)
    proof=read_json(workflow.storage.artifact_path('native_context',job.rough3d.artifact_id,'.rough3d.json'))
    directory=Path(proof['directory']);data=read_json(directory/'iteration_001/plan.json')
    guidance=dict(data['image_guidance_2d'],mask_available=False)
    with pytest.raises(GuidedVLAError):serialize_guidance('SAMPLE_1',guidance,data['plan'])
    data['mask_available']=False
    (directory/'iteration_001/plan.json').write_text(json.dumps(data))
    with pytest.raises(ModelFault):read_native_result('rough3d',directory,'SAMPLE_1',data['raw_instruction_ko'],version='native_3d_v3')


def test_versioned_session_names_and_no_version_fallback(tmp_path):
    for name in ('20261001_000001_SAMPLE','20261001_000001_123456_SAMPLE'):(tmp_path/name).mkdir()
    assert len(native_profile('segment','native_v1').sessions(tmp_path,'SAMPLE'))==1
    assert len(native_profile('segment','native_v2').sessions(tmp_path,'SAMPLE'))==1
    with pytest.raises(ValueError):native_profile('rough3d','native_v2')


def test_chat_sample_load_binds_new_job_then_mask_without_models(candidate):
    workflow,transport,calls=candidate;runner=FakeRunner()
    with TestClient(create_app(workflow=workflow,simulator=FakeSimulator(),agent_runner=runner,
            agent_settings=AgentSettings(api_key='offline'))) as api:
        sid=api.post('/api/agent/sessions').json()['session_id']
        stream=events(api.post('/api/agent/chat/stream',json={'session_id':sid,'message':'SAMPLE_1 불러와'}))
        done=stream[-1][1];assert done['ok'] and done['job_id']
        assert [data['tool'] for event,data in stream if event=='tool_started']==['load_welding_scene']
        assert list(workflow.get_job(UUID(done['job_id'])).scene.views)==list(CAMERAS)
        assert not calls['segment'] and not calls['rough3d'] and not transport.calls
        stream=events(api.post('/api/agent/chat/stream',json={'session_id':sid,'job_id':done['job_id'],'message':'용접할 부분 찾아줘'}))
        assert stream[-1][1]['ok'] and len(calls['segment'])==1
        assert not api.app.state.agent._jobs and not api.app.state.agent._sessions and runner.calls==0


def test_one_shot_smoke_runs_configured_clients_once_and_never_guided_http(candidate,tmp_path,monkeypatch):
    from backend import native_stack_migration_smoke as smoke
    workflow,transport,calls=candidate
    monkeypatch.setattr(smoke,'SAMPLE','SAMPLE_1')
    monkeypatch.setattr(smoke,'preserved_sources',lambda:{'fixture':'unchanged'})
    monkeypatch.setattr(smoke,'settings',lambda stage:
        (workflow.segmentation if stage=='segment' else workflow.rough3d).runtime.settings)
    directory=tmp_path/'.cache/smoke';directory.mkdir()
    report=asyncio.run(smoke.run(directory,workflow))
    assert report['verdict']=='LIVE_NATIVE_STACK_PASS',report
    assert len(calls['segment'])==len(calls['rough3d'])==1
    assert not transport.calls and not transport.health_calls
    assert all(report['gates'].values()) and report['external_sources_unchanged']
    assert (directory/'smoke-approval.json').is_file()
    assert (directory/'report.json').is_file()


def test_fixed_detector_bridge_loads_native_module_without_calling_it(tmp_path,monkeypatch):
    import sys
    from backend.model_clients.native_trajectory3_entry import install_detector
    monkeypatch.delitem(sys.modules,'welding_shared_yolo_client',raising=False)
    monkeypatch.setattr(sys,'path',sys.path.copy())
    module=tmp_path/'retrieval_client.py'
    module.write_text('class RetrievalConfig: pass\ndef detect_images(*args): raise AssertionError("No detection")\n')
    try:
        loaded=install_detector(tmp_path)
        assert loaded is sys.modules['welding_shared_yolo_client']
        assert Path(loaded.__file__)==module
        with pytest.raises(ValueError):install_detector(tmp_path)
    finally:
        sys.modules.pop('welding_shared_yolo_client',None)
