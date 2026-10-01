"""A–G: original candidate, acceptance and integrity, all with fake processes."""
import asyncio
from pathlib import Path
from uuid import UUID
import json
import pytest
from fastapi.testclient import TestClient
from backend.agent.config import AgentSettings
from backend.agent.context import WeldingAgentContext,workspace_summary
from backend.main import create_app
from backend.model_clients.contracts import ModelFault
from backend.model_clients.guided_vla import GuidedVLAError
from backend.model_clients.native import read_json,sha256
from tests.agent_fakes import FakeRunner,FakeSimulator,invoke
from tests.native_stack_fakes import candidate_workflow
from tests.test_agent import events
from tests.test_guided_vla import save


@pytest.fixture
def factory(tmp_path,monkeypatch):
    for module in ('native','native_rough3d','guided_vla','config'):
        monkeypatch.setattr('backend.model_clients.'+module+'.ROOT',tmp_path)
    import openai
    def forbidden(*args,**kwargs):raise AssertionError('Real API/process forbidden')
    monkeypatch.setattr(openai,'OpenAI',forbidden)
    monkeypatch.setattr(openai,'AsyncOpenAI',forbidden)
    monkeypatch.setattr('subprocess.Popen',forbidden)
    return lambda **kw:candidate_workflow(tmp_path,**kw)


def ready(workflow):
    job=workflow.load_sample('SAMPLE_1');job=workflow.set_mask(job.id)
    job=workflow.approve_mask(job.id,job.mask.id,'F')
    return workflow.parse_instruction(job.id,'왼쪽에서 오른쪽으로 용접해')


def change_guidance(directory, change):
    data=read_json(directory/'iteration_001/plan.json')
    change(data)
    save(directory/'iteration_001/plan.json',data)
    save(directory/'query_image_guidance_2d.json',data['image_guidance_2d'])


def far_mask(directory):
    def change(data):
        segment=data['image_guidance_2d']['segments'][0]
        segment['points_pixel']=[[float(10+i*10),70.25] for i in range(9)]
        segment['points_normalized']=[[x/100,y/100] for x,y in segment['points_pixel']]
    change_guidance(directory,change)


def partial(directory):
    (directory/'iteration_001/plan.json').unlink()
    save(directory/'iteration_001/clarification.json',{'status':'needs_clarification','questions':['PRIVATE QUESTION']})


def assert_blocked(workflow,transport,job):
    with pytest.raises(ModelFault):workflow.run_guided_vla(job.id)
    with pytest.raises(GuidedVLAError):workflow.guided_vla.prepare_workflow(workflow.storage,job)
    with pytest.raises(GuidedVLAError):workflow.guided_vla.run(workflow.storage,job)
    assert not transport.calls and transport.health_calls==0
    assert not workflow.guided_vla.settings.attempts.exists()


def test_a_valid_native_output_preserves_normal_state_and_offline_guided_package(factory):
    workflow,transport,calls=factory();job=workflow.plan(ready(workflow).id)
    output=job.native_output
    assert output.status=='NATIVE_OUTPUT_VALIDATED' and output.validation.status=='PASS'
    assert output.candidate.frame=='image_pixel:F' and job.state.value=='ROUGH_PATH_READY'
    assert job.rough3d and job.rough_trajectory and not output.user_override
    workflow.verify_native_output(job)
    attempt=workflow.guided_vla.prepare_workflow(workflow.storage,job)
    manifest,_=workflow.guided_vla.verify(attempt)
    assert not manifest['live_called'] and not (attempt/'submission.json').exists()
    assert len(calls['rough3d'])==1 and not transport.calls and not transport.health_calls


def test_b_f_soft_fail_exposes_exact_native_points_but_never_guided(factory):
    before={}
    def transform(directory):
        far_mask(directory)
        before.update({p.relative_to(directory).as_posix():sha256(p) for p in directory.rglob('*') if p.is_file()})
    workflow,transport,calls=factory(rough_output_transform=transform)
    job=workflow.plan(ready(workflow).id);output=job.native_output
    assert output.status=='NATIVE_OUTPUT_READY_UNVALIDATED' and output.native_output_generated
    assert output.validation.status=='FAIL' and [i.code for i in output.validation.issues]==['mask_proximity']
    assert job.state.value=='INSTRUCTION_READY' and job.rough3d is job.rough_trajectory is None
    directory,proof=workflow.verify_native_output(job)
    native=read_json(directory/'query_image_guidance_2d.json')['segments']
    assert output.candidate.model_dump(mode='json')['segments'][0]['points_pixel']==native[0]['points_pixel']
    assert proof['files']==before # no native point, JSON, image or MD rewrite
    assert all(sha256(directory/name)==digest for name,digest in before.items())
    assert_blocked(workflow,transport,job)
    with TestClient(create_app(workflow=workflow,simulator=FakeSimulator())) as client:
        shown=client.get(f'/api/weld/{job.id}').json()
        assert shown['native_output']['candidate']['segments'][0]['points_pixel']==native[0]['points_pixel']
        assert client.get(output.preview_urls['guidance']).status_code==200
        assert client.get(f'/api/weld/{job.id}/native-output/image/arbitrary').status_code==404
    assert len(calls['rough3d'])==1


@pytest.mark.parametrize('mutation',['sample','frame','nan','count','mask_id','normalized','connected','malformed','mask_branch','refiner','reference','previous_session'])
def test_c_hard_native_contract_blocks_candidate_and_vla(factory,mutation):
    def transform(directory):
        def change(data):
            guidance=data['image_guidance_2d'];segment=guidance['segments'][0]
            if mutation=='sample':data['sample_id']='OTHER'
            elif mutation=='frame':guidance['coordinate_frame_pixel']='robot_mm'
            elif mutation=='nan':segment['points_pixel'][0][0]=float('nan')
            elif mutation=='count':segment['points_pixel']=segment['points_pixel'][:1];segment['points_normalized']=segment['points_normalized'][:1];guidance['actual_point_count']=1
            elif mutation=='mask_id':segment['source_mask_id']='F:unknown'
            elif mutation=='normalized':segment['points_normalized'][0]=[.7,.7]
            elif mutation=='connected':segment['connected_to_next']=True
            elif mutation=='mask_branch':data['mask_available']=False
            elif mutation=='refiner':data['refined_task']['direction']='tampered'
            elif mutation=='reference':data['rough_trajectory_3d']['segments'][0]['points_xyz_mm'][0][0]+=1
            elif mutation=='previous_session':data['previous_mask_session']='OTHER'
        if mutation=='malformed':(directory/'iteration_001/plan.json').write_text('{')
        else:change_guidance(directory,change)
    workflow,transport,_=factory(rough_output_transform=transform);job=ready(workflow)
    with pytest.raises(ModelFault) as fault:workflow.plan(job.id)
    assert fault.value.code=='NATIVE_OUTPUT_HARD_INVALID'
    job=workflow.get_job(job.id);output=job.native_output
    assert output.candidate is None and not output.preview_urls
    assert any(i.classification=='HARD_INVALID' for i in output.validation.issues)
    assert not job.rough3d and not job.rough_trajectory
    assert_blocked(workflow,transport,job)


@pytest.mark.parametrize('mutation',['source','mask','approval','scene','snapshot','approved_session','approved_proof'])
def test_c_tampering_after_creation_blocks_public_display_and_every_vla_entry(factory,mutation):
    workflow,transport,_=factory();job=workflow.plan(ready(workflow).id)
    directory,proof=workflow.verify_native_output(job)
    if mutation=='source':(directory/'iteration_001/plan.json').write_text('{}')
    elif mutation=='mask':workflow.storage.artifact_path('masks',job.mask.id).write_bytes(b'changed')
    elif mutation=='scene':workflow.dataset.resolve('SAMPLE_1').images['S4'].write_bytes(b'changed')
    elif mutation=='approved_session':(Path(proof['approved_session']['directory'])/'status.json').write_text('{}')
    elif mutation=='approved_proof':
        session=Path(proof['approved_session']['directory']);(session.parent/f'{session.name}.json').write_text('{}')
    else:
        if mutation=='approval':job.mask.approved_at=job.mask.approved_at.replace(year=2020)
        else:job.native_output.candidate.segments[0].points_pixel[0]=(1.,1.)
        workflow.storage.save_job(job)
    with pytest.raises(ModelFault) as fault:workflow.get_job(job.id)
    assert fault.value.code=='NATIVE_OUTPUT_HARD_INVALID'
    with pytest.raises(ModelFault) as fault:workflow.native_output_image(job.id,'review')
    assert fault.value.code=='NATIVE_OUTPUT_HARD_INVALID'
    assert_blocked(workflow,transport,workflow.storage.get_job(job.id))


def test_d_missing_path_correct_error_no_candidate(factory):
    workflow,transport,calls=factory(rough_missing=True);job=ready(workflow)
    with pytest.raises(ModelFault) as fault:workflow.plan(job.id)
    assert fault.value.code=='NATIVE_OUTPUT_MISSING'
    assert '완전한 경로 결과를 생성하지 못했습니다' in fault.value.message
    job=workflow.get_job(job.id)
    assert job.native_output.status=='NATIVE_OUTPUT_MISSING' and not job.native_output.native_output_generated
    assert not job.native_output.candidate and not job.native_output.preview_urls
    assert_blocked(workflow,transport,job)
    assert len(calls['rough3d'])==1


def test_e_partial_clarification_artifacts_are_not_a_completed_path(factory):
    workflow,transport,calls=factory(rough_output_transform=partial);job=ready(workflow)
    with pytest.raises(ModelFault) as fault:workflow.plan(job.id)
    assert fault.value.code=='NATIVE_OUTPUT_MISSING'
    job=workflow.get_job(job.id);output=job.native_output
    assert output.status=='PARTIAL_NATIVE_OUTPUT' and not output.native_output_generated and output.candidate is None
    assert output.validation.issues[0].code=='native_clarification'
    assert output.artifacts['query_image_guidance_2d.json'] and output.artifacts['iteration_001/clarification.json']
    assert 'PRIVATE QUESTION' not in json.dumps(workspace_summary(job))
    assert 'plan.json' not in output.artifacts
    workflow.verify_native_output(job)
    assert_blocked(workflow,transport,job)
    assert len(calls['rough3d'])==1


def test_generated_points_survive_missing_native_report_without_acceptance(factory):
    def transform(directory):(directory/'iteration_001/cot_ko.md').unlink()
    workflow,transport,_=factory(rough_output_transform=transform);job=workflow.plan(ready(workflow).id)
    assert job.native_output.candidate and job.native_output.status=='NATIVE_OUTPUT_READY_UNVALIDATED'
    assert any(i.code=='auxiliary_artifacts' for i in job.native_output.validation.issues)
    assert_blocked(workflow,transport,job)


def test_f_reverse_direction_does_not_reorder_native_candidate(factory):
    def transform(directory):
        change_guidance(directory,lambda d:d['plan']['segment_decisions'][0].update(direction='reverse'))
    workflow,transport,_=factory(rough_output_transform=transform);job=workflow.plan(ready(workflow).id)
    assert job.native_output.candidate.segments[0].direction=='reverse'
    assert job.native_output.candidate.segments[0].points_pixel[0][0]==10
    assert any(i.code=='direction_consistency' for i in job.native_output.validation.issues)
    assert_blocked(workflow,transport,job)


def test_unmatched_decision_is_soft_but_still_checks_proximity(factory):
    def transform(directory):
        far_mask(directory)
        change_guidance(directory,lambda d:d['plan'].update(segment_decisions=[]))
    workflow,transport,_=factory(rough_output_transform=transform);job=workflow.plan(ready(workflow).id)
    assert job.native_output.candidate and job.native_output.candidate.segments[0].direction is None
    assert {i.code for i in job.native_output.validation.issues}=={'guided_contract','region_mapping','mask_proximity'}
    assert_blocked(workflow,transport,job)


def test_preflight_failure_does_not_reuse_previous_capture(factory,monkeypatch):
    workflow,_,_=factory(rough_output_transform=far_mask);job=workflow.plan(ready(workflow).id)
    assert workflow.rough3d.runtime.last_capture
    def fail(*args,**kwargs):raise ModelFault('MODEL_NOT_CONFIGURED')
    monkeypatch.setattr(workflow.rough3d,'prepare_session',fail)
    with pytest.raises(ModelFault):workflow.plan(job.id)
    current=workflow.get_job(job.id)
    assert current.native_output.status=='NATIVE_OUTPUT_MISSING' and current.native_output.native_artifact_id is None
    assert not current.native_output.candidate and not current.native_output.artifacts


def test_failed_evidence_capture_never_falls_back_to_unproven_native_output(factory,monkeypatch):
    workflow,transport,_=factory();job=ready(workflow)
    original=workflow.rough3d.predict
    def predict(*args,**kwargs):
        result=original(*args,**kwargs);workflow.rough3d.runtime.last_capture=None
        return result
    monkeypatch.setattr(workflow.rough3d,'predict',predict)
    with pytest.raises(ModelFault) as fault:workflow.plan(job.id)
    assert fault.value.code=='NATIVE_OUTPUT_HARD_INVALID'
    assert not workflow.get_job(job.id).native_output and not transport.calls


def test_g_agent_explains_generated_but_unvalidated_without_raw_data(factory):
    workflow,transport,calls=factory(rough_output_transform=far_mask);job=ready(workflow);sim=FakeSimulator()
    context=WeldingAgentContext(job.id,'offline','왼쪽에서 오른쪽으로 용접해',workflow,sim,lambda *_:None)
    async def tools():
        await invoke(context,'get_workspace_state')
        result=await invoke(context,'create_current_weld_plan')
        assert result['native_output_generated'] and result['validation_status']=='FAIL'
        assert result['status']=='NATIVE_OUTPUT_READY_UNVALIDATED' and result['warning_count']==1
        assert result['segment_count']==1 and result['point_count']==9
        assert all(key not in json.dumps(result) for key in ('points_pixel','points_normalized','source_session','cot_ko.md',str(workflow.storage.root)))
    asyncio.run(tools())
    with TestClient(create_app(workflow=workflow,simulator=sim,agent_runner=FakeRunner(),agent_settings=AgentSettings(api_key='offline'))) as api:
        sid=api.post('/api/agent/sessions').json()['session_id']
        stream=events(api.post('/api/agent/chat/stream',json={'session_id':sid,'job_id':str(job.id),'message':'왼쪽에서 오른쪽으로 용접해'}))
        assert stream[-1][1]['ok'],stream
        text=''.join(d['text'] for e,d in stream if e=='assistant_delta')
        assert '모델은 경로를 생성했습니다' in text and '검증되지 않은 경로' in text and '생성 실패' not in text
    assert not sim.calls and not transport.calls and not transport.health_calls


def test_upstream_edit_clears_candidate_and_disabled_override_rejected(factory):
    workflow,_,_=factory(rough_output_transform=far_mask);job=workflow.plan(ready(workflow).id)
    with TestClient(create_app(workflow=workflow,simulator=FakeSimulator())) as api:
        assert api.post(f'/api/weld/{job.id}/guided-vla',json={'user_override':True}).status_code==422
    job=workflow.parse_instruction(job.id,'오른쪽에서 왼쪽으로 용접해')
    assert job.native_output is None and job.rough3d is None
