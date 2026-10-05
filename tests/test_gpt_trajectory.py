"""Native predictor fake boundary only. Network, paid SDK and process launches forbidden."""
from dataclasses import replace
import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
import h5py
import httpx
import numpy as np
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend.model_clients.gpt_trajectory import GPTTrajectoryPredictor,GPTTrajectorySettings
from backend.model_clients.guided_vla import GuidedVLAError
from backend.model_clients.native import read_json,sha256
from backend.model_clients.final_trajectory import configured_final_predictor
from backend.model_clients.gpt_trajectory_entry import build_content
from backend.services.final_prediction_proof import FRAME
from backend.main import create_app
from tests.module_fakes import module_workflow
from tests.test_module_workflow import rough_job
from tests.agent_fakes import FakeRunner,FakeSimulator,invoke
from backend.agent.context import WeldingAgentContext
from backend.agent.config import AgentSettings
from backend.agent.decision import parse_request,DecisionIntent


def save(path,value):path.write_text(json.dumps(value,allow_nan=True),encoding='utf-8')


def response(sample,split,artifact,h5):
    with h5py.File(h5) as f:gt=f['trajectory'][:,:3]
    gt=np.column_stack([np.interp(np.linspace(0,len(gt)-1,33),np.arange(len(gt)),gt[:,i]) for i in range(3)])
    pred=gt+np.array([.3,-.2,.1]);error=np.linalg.norm(pred-gt,axis=1)
    return dict(artifact_id=artifact,sample_id=sample,split=split,source='vlm_final_gpt',provider='gpt',model='gpt-6-luna',
        point_count=33,predicted_path_xyz_mm=pred.tolist(),ground_truth_path_xyz_mm=gt.tolist(),coordinate_frame=FRAME,units='mm',
        connections=['within_segment']*32,ade_mm=float(error.mean()),fde_mm=float(error[-1]),
        is_robot_executable=False,physical_robot_executable=False,simulation_only=True)


class FakeNative:
    def __init__(self,change=None,exit=0):self.calls=[];self.change=change;self.exit=exit
    def __call__(self,command,**kwargs):
        self.calls.append((command,kwargs));options=read_json(command[-1]);a=Path(options['attempt'])
        r=response(options['sample_id'],options['split'],options['artifact_id'],options['h5'])
        save(a/'corners.json',dict(model=r['model'],proposal=dict(path_description='private explanation never sent to chat',
            points=[dict(zip(('x','y','z'),p)) for p in r['predicted_path_xyz_mm']],connections=r['connections'])))
        if self.change=='partial':return self.exit,[]
        if self.change=='nan':r['predicted_path_xyz_mm'][16][0]=float('nan')
        if self.change=='inf':r['predicted_path_xyz_mm'][16][0]=float('inf')
        if self.change=='frame':r['coordinate_frame']='camera_unknown'
        if self.change=='units':r['units']='m'
        if self.change=='sample':r['sample_id']='FOREIGN_SAMPLE'
        if self.change=='count':r['predicted_path_xyz_mm'].pop()
        if self.change=='gap':r['connections'][16]='between_segments'
        if self.change=='malformed':r={'sample_id':r['sample_id'],'model':r['model']}
        save(a/'response.json',r)
        if 'predicted_path_xyz_mm' in r:
            np.savez_compressed(a/'trajectory.npz',predicted_path_m=np.asarray(r['predicted_path_xyz_mm'])*.001,
                                ground_truth_path_m=np.asarray(r['ground_truth_path_xyz_mm'])*.001)
        save(a/'metadata.json',dict(artifact_id=options['artifact_id'],attempt_id=a.name,episode_id=options['sample_id'],
            split=options['split'],source='vlm_final_gpt',provider='gpt',coordinate_frame=FRAME,source_units='mm',scale_to_meters=.001,
            is_robot_executable=False,vla_orientation=False))
        return self.exit,[]


@pytest.fixture
def setup(tmp_path,monkeypatch):
    import openai
    def deny(*a,**k):raise AssertionError('Real network/model/process prohibited')
    monkeypatch.setattr(openai,'OpenAI',deny);monkeypatch.setattr(openai,'AsyncOpenAI',deny)
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',deny)
    for module in ('native','native_rough3d','guided_vla','config','gpt_trajectory'):
        monkeypatch.setattr('backend.model_clients.'+module+'.ROOT',tmp_path)
    wf,transport=module_workflow(tmp_path);job=rough_job(wf)
    h5=tmp_path/'sample.h5';obj=tmp_path/'sample.obj';obj.write_text('v 0 0 0\n')
    with h5py.File(h5,'w') as f:f.create_dataset('trajectory',data=np.column_stack([np.arange(9),np.zeros(9),np.ones(9)]))
    monkeypatch.setattr('backend.model_clients.gpt_trajectory.exact_assets',lambda *_:(h5,obj))
    repo=tmp_path/'vlm_final_gpt';repo.mkdir()
    for name in ('predict.py','interpolate.py'):(repo/name).write_text('# offline native fixture')
    config=repo/'config.yaml';config.write_text('fixture: true')
    fake=FakeNative();settings=GPTTrajectorySettings(repo,Path(__file__),config,tmp_path/'.cache/native-models/gpt-trajectory')
    client=GPTTrajectoryPredictor(settings,execute=fake)
    monkeypatch.setattr(client,'configuration',lambda:{'model':'gpt-6-luna'})
    wf.guided_vla=client
    return wf,job,client,fake,transport


def test_selection_explicit_and_no_fallback(tmp_path,monkeypatch):
    path=tmp_path/'selection.env';path.write_text('WELD_FINAL_TRAJECTORY_BACKEND=gpt\n')
    monkeypatch.delenv('WELD_FINAL_TRAJECTORY_BACKEND',raising=False)
    assert isinstance(configured_final_predictor(path),GPTTrajectoryPredictor)
    monkeypatch.setenv('WELD_FINAL_TRAJECTORY_BACKEND','guided_vla')
    assert configured_final_predictor(path).status()['backend']=='guided'
    monkeypatch.setenv('WELD_FINAL_TRAJECTORY_BACKEND','typo')
    with pytest.raises(GuidedVLAError,match='BACKEND_INVALID'):configured_final_predictor(path)


def test_missing_selector_defaults_to_guided(tmp_path,monkeypatch):
    monkeypatch.delenv('WELD_FINAL_TRAJECTORY_BACKEND',raising=False)
    path=tmp_path/'selection.env';path.write_text('# no selector\n',encoding='utf-8')
    assert configured_final_predictor(path).status()['backend']=='guided'


def test_native_import_bridge_without_execution(tmp_path,monkeypatch):
    """Fixture source checks import-only behavior; it does not replace native retrieval."""
    import sys
    from backend.model_clients.gpt_trajectory_entry import load_native
    repo=tmp_path/'native';repo.mkdir()
    (repo/'predict.py').write_text('''
def call_stage(*a, **k): raise AssertionError('Paid call prohibited')
def check_proposal(*a, **k): pass
def interpolate_corners(*a, **k): pass
def prepare_examples(*a, **k): raise AssertionError('Retrieval prohibited')
''',encoding='utf-8')
    monkeypatch.setattr(sys,'path',sys.path.copy())
    monkeypatch.setitem(sys.modules,'welding_native_final_predictor',None)
    native=load_native(repo)
    assert all(callable(getattr(native,n)) for n in ('call_stage','check_proposal','interpolate_corners','prepare_examples'))


def test_native_missing_shared_module_blocks_before_inference(tmp_path):
    repo=tmp_path/'vlm_final_gpt';repo.mkdir()
    for n in ('predict.py','interpolate.py','config.yaml'):(repo/n).write_text('# fixture')
    client=GPTTrajectoryPredictor(GPTTrajectorySettings(repo,Path(__file__),repo/'config.yaml',tmp_path/'.cache/gpt'),execute=FakeNative())
    # Use existing Python file with no extension so config can check shared dependency.
    python=tmp_path/'python';python.write_text('fixture')
    client.settings=replace(client.settings,python=python,attempts=Path(__file__).resolve().parents[1]/'.cache/gpt')
    assert client.status()['code']=='GPT_TRAJECTORY_RETRIEVAL_DEPENDENCY_MISSING'
    assert not client.execute.calls


def test_success_current_approval_and_idempotent_generic_api(setup):
    wf,job,client,fake,transport=setup
    mask=job.mask.model_dump();instruction=job.instruction.model_dump()
    with TestClient(create_app(workflow=wf,simulator=FakeSimulator(),agent_settings=AgentSettings(enabled=False))) as api:
        r=api.post(f'/api/weld/{job.id}/final-trajectory',json={});assert r.status_code==200,r.text
        result=r.json();assert result['state']=='VLA_READY'
        assert result['vla_prediction']['source']=='vlm_final_gpt' and result['vla_prediction']['point_count']==33
        assert 'private explanation' not in r.text and 'predicted_path_xyz_mm' not in r.text
        assert api.post(f'/api/weld/{job.id}/final-trajectory',json={}).status_code==200
        assert api.post(f'/api/weld/{job.id}/final-trajectory',json={'python':'evil'}).status_code==422
        raw=result['raw_final_prediction'];data=api.get(raw['display_url']).json()
        assert len(data['runs'][0])==33 and raw['simulator_eligible']
    assert len(fake.calls)==1 and not transport.calls and not transport.health_calls
    fresh=wf.get_job(job.id);assert fresh.mask.model_dump()==mask and fresh.instruction.model_dump()==instruction
    assert client.verify_current(wf.storage,fresh)==fresh.vla_prediction
    command,options=fake.calls[0];assert options['cwd']==client.settings.repository and command[0]==str(client.settings.python)
    assert options['preserve_openai_api_key'] is True
    assert options['watchdog_policy'].setup==options['timeout']==900
    assert options['watchdog_policy'].retrieval==options['watchdog_policy'].model_stage==900
    inputs=read_json(command[-1]);manifest=read_json(Path(inputs['attempt'])/'request_manifest.json')
    assert inputs['instruction']==job.instruction.text and set(inputs['images'])==set(job.scene.views)
    assert (Path(inputs['attempt'])/'F_mask.png').read_bytes()==wf.storage.artifact_path('masks',job.mask.id).read_bytes()
    assert manifest['reference_in_request'] is False and manifest['trajectory3_guidance_in_request'] is False


@pytest.mark.parametrize('change',['partial','malformed','count','nan','inf','frame','units','sample','gap'])
def test_invalid_raw_visible_without_promotion(setup,change):
    wf,job,client,fake,_=setup;fake.change=change
    with pytest.raises(GuidedVLAError):wf.run_final_trajectory_prediction(job.id)
    fresh=wf.get_job(job.id);assert fresh.state.value=='ROUGH_PATH_READY' and fresh.vla_prediction is None
    d=fresh.raw_final_prediction;assert d and not d.simulator_eligible and d.validation_status=='FAIL'
    assert (client.settings.attempts/str(d.attempt_id)/'corners.json').is_file()
    if change=='sample':assert not d.displayable
    elif change=='malformed':assert not d.displayable
    else:
        assert d.displayable
        value=client.read_display(wf.storage,fresh,d.artifact_id)
        if change=='units':assert d.units==value['units']=='m'  # Never silently claim mm.
        if change=='frame':assert d.coordinate_frame==value['coordinate_frame']=='unknown'
        if change in ('nan','inf'):assert len(value['runs'])==2 and d.omitted_point_count==1
        if change=='gap':assert len(value['runs'])==2
    assert len(fake.calls)==1


@pytest.mark.parametrize('mutation',['mask','approval','instruction','scene','raw'])
def test_stale_lineage_never_reuses_or_dispatches(setup,mutation):
    wf,job,client,fake,_=setup;done=wf.run_final_trajectory_prediction(job.id)
    if mutation=='mask':wf.storage.save_image('masks',job.mask.id,Image.new('L',(100,100),255))
    if mutation=='approval':done.mask.approved_at=done.mask.approved_at.replace(year=2025)
    if mutation=='instruction':done.instruction.text='다른 지시'
    if mutation=='scene':done.scene.sample_id='WRONG'
    if mutation=='raw':(client.settings.attempts/str(done.vla_prediction.attempt_id)/'corners.json').write_text('{}')
    wf.storage.save_job(done)
    with pytest.raises(GuidedVLAError):client.verify_current(wf.storage,done)
    assert len(fake.calls)==1


def test_stale_approved_mask_before_dispatch(setup):
    wf,job,client,fake,_=setup;job.mask.approved_at=job.mask.approved_at.replace(year=2025);wf.storage.save_job(job)
    from backend.model_clients.contracts import ModelFault
    with pytest.raises((GuidedVLAError,ModelFault)):wf.run_final_trajectory_prediction(job.id)
    assert fake.calls==[]


@pytest.mark.parametrize('text',['최종 궤적 생성해줘','GPT로 궤적 생성해줘','최종 3D 궤적 만들어줘','실제 XYZ 경로 만들어줘'])
def test_semantic_final_execution(setup,text):
    wf,job,_,fake,_=setup;assert parse_request(text).intent==DecisionIntent.VLA
    ctx=WeldingAgentContext(job.id,'fake',text,wf,FakeSimulator(),lambda *_:None)
    asyncio.run(invoke(ctx,'get_workspace_state'))
    value=asyncio.run(invoke(ctx,'run_final_trajectory_prediction'))
    assert value['source']=='vlm_final_gpt' and len(fake.calls)==1
    asyncio.run(invoke(ctx,'run_final_trajectory_prediction'));assert len(fake.calls)==1
    assert not ctx.simulator.calls


@pytest.mark.parametrize('text',['최종 궤적 생성해줘','GPT로 궤적 생성해줘','최종 3D 궤적 만들어줘','실제 XYZ 경로 만들어줘'])
def test_agent_service_uses_generic_gpt_only_and_reuses_result(setup,text):
    from tests.test_agent import events
    wf,job,_,fake,transport=setup;runner=FakeRunner();sim=FakeSimulator()
    mask=job.mask.model_dump();guidance=job.rough3d.model_dump()
    with TestClient(create_app(workflow=wf,simulator=sim,agent_runner=runner,
                              agent_settings=AgentSettings(api_key='offline-placeholder'))) as api:
        sid=api.post('/api/agent/sessions').json()['session_id']
        body={'session_id':sid,'job_id':str(job.id),'message':text}
        log=events(api.post('/api/agent/chat/stream',json=body))
        assert log[-1][1]['ok'] is True,log
        started=[d for e,d in log if e=='tool_started']
        assert [d['tool'] for d in started]==['get_workspace_state','run_final_trajectory_prediction']
        assert started[-1]['label']=='GPT 최종 3D 궤적 예측'
        assert all(d['final_predictor']=='gpt' for e,d in log if e=='decision_summary')
        assert next(d for e,d in reversed(log) if e=='decision_summary')['point_count']==33
        serialized=json.dumps(log,ensure_ascii=False)
        assert 'vlm_final_gpt' in serialized and 'private explanation' not in serialized
        assert 'predicted_path_xyz_mm' not in serialized
        again=events(api.post('/api/agent/chat/stream',json=body));assert again[-1][1]['ok']
    assert len(fake.calls)==1 and not transport.calls and not transport.health_calls
    assert runner.calls==0 and not sim.calls
    fresh=wf.get_job(job.id)
    assert fresh.mask.model_dump()==mask and fresh.rough3d.model_dump()==guidance


def test_unready_gpt_reports_dependency_without_guided_fallback(setup,monkeypatch):
    wf,job,client,fake,transport=setup;log=[]
    def missing():raise GuidedVLAError('GPT_TRAJECTORY_RETRIEVAL_DEPENDENCY_MISSING')
    monkeypatch.setattr(client,'configuration',missing)
    ctx=WeldingAgentContext(job.id,'fake','최종 궤적 생성해줘',wf,FakeSimulator(),lambda e,d:log.append((e,d)))
    asyncio.run(invoke(ctx,'get_workspace_state'))
    result=asyncio.run(invoke(ctx,'run_final_trajectory_prediction'))
    assert result['code']=='GPT_TRAJECTORY_RETRIEVAL_DEPENDENCY_MISSING'
    assert not fake.calls and not transport.calls and not transport.health_calls
    assert any(d['final_predictor']=='gpt' and not next(p['ready'] for p in d['prerequisites'] if p['key']=='vla_backend')
               for e,d in log if e=='decision_summary')
    assert wf.get_job(job.id).state.value=='ROUGH_PATH_READY'


def test_legacy_guided_tool_rejects_gpt_mode(setup):
    wf,job,_,fake,transport=setup
    ctx=WeldingAgentContext(job.id,'fake','최종 궤적 생성해줘',wf,FakeSimulator(),lambda *_:None)
    asyncio.run(invoke(ctx,'get_workspace_state'))
    assert asyncio.run(invoke(ctx,'run_guided_vla'))['code']=='FINAL_TRAJECTORY_BACKEND_MISMATCH'
    assert not fake.calls and not transport.calls and not transport.health_calls


@pytest.mark.parametrize('text',['GPT가 궤적을 어떻게 생성해?','현재 궤적 상태 알려줘','Guided VLA 상태 알려줘','GPT 궤적 모델이 뭐야?'])
def test_read_only_no_native_dispatch(setup,text):
    wf,job,_,fake,_=setup
    ctx=WeldingAgentContext(job.id,'fake',text,wf,FakeSimulator(),lambda *_:None)
    asyncio.run(invoke(ctx,'get_workspace_state'));asyncio.run(invoke(ctx,'run_final_trajectory_prediction'))
    assert fake.calls==[]


@pytest.mark.parametrize('text',['Guided VLA 상태 알려줘','GPT 궤적 모델이 뭐야?'])
def test_status_question_reports_selected_gpt_without_dispatch(setup,text):
    from tests.test_agent import events
    wf,job,_,fake,transport=setup;runner=FakeRunner()
    with TestClient(create_app(workflow=wf,simulator=FakeSimulator(),agent_runner=runner,
                              agent_settings=AgentSettings(api_key='offline-placeholder'))) as api:
        sid=api.post('/api/agent/sessions').json()['session_id']
        log=events(api.post('/api/agent/chat/stream',json={'session_id':sid,'job_id':str(job.id),'message':text}))
    assert log[-1][1]['ok']
    output=''.join(d['text'] for e,d in log if e=='assistant_delta')
    assert 'vlm_final_gpt' in output and 'gpt-6-luna' in output
    assert not fake.calls and not transport.calls and not transport.health_calls and runner.calls==0


def test_binary_mask_input_no_gt_mask_or_reference_xyz(setup):
    wf,job,client,fake,_=setup;wf.run_final_trajectory_prediction(job.id)
    options=read_json(fake.calls[0][0][-1]);native=SimpleNamespace(CAMERAS=tuple(job.scene.views),write_json=save)
    content,sizes=build_content(native,options,{'image_max_side':1024},np.array([0.,0.,0.]))
    assert len([c for c in content if c['type']=='input_image'])==9
    manifest=read_json(Path(options['attempt'])/'input_manifest.json')
    assert manifest['gt_masks_used'] is False and manifest['query_mask_png']=='F_mask.png'
    assert not manifest['trajectory3_guidance_in_model_input']
    assert 'points_xyz_mm' not in json.dumps(content) and 'human_approved_web_F' in content[0]['text']
