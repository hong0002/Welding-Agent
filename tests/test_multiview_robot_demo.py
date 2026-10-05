"""Focused offline checks; real model, SSH, Isaac and hardware transports prohibited."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from PIL import Image
from backend.model_clients.gpt_mask_conditioning import inputs,selected_views
from backend.model_clients.gpt_trajectory_entry import build_content
from backend.model_clients.guided_vla import GuidedVLAError
from backend.model_clients.native import read_json,CAMERAS
from backend.demo_robot_prepare import map_runs
from tests.test_gpt_trajectory import setup
from tests.agent_fakes import invoke,FakeSimulator
from backend.agent.context import WeldingAgentContext

@pytest.mark.parametrize('text,expected',[
    ('R 마스크로 최종 3D 예측해줘',['R']),('F 마스크 기준으로 예측해줘',['F']),
    ('S4 마스크로 만들어줘',['S4']),('F랑 R 마스크 같이 참고해줘',['F','R']),
    ('검출된 마스크 전부 참고해서 최종 3D 예측해줘',None),('최종 3D 궤적 예측해줘',None)])
def test_camera_semantics(text,expected):assert selected_views(text)==expected

def test_default_and_unapproved_manual_inputs(setup):
    wf,job,client,fake,transport=setup
    job.mask.approved=False;job.mask.approved_at=None;job.mask.mask_source='manual_edited'
    source,split,masks=inputs(wf.storage,job)
    assert list(masks)==['F','R','S4']
    assert masks['F']['provenance']==['UNAPPROVED','MANUAL']
    assert list(inputs(wf.storage,job,['R'])[2])==['R']
    job.scene.views['R'].mask=None;job.scene.views['S4'].mask=None
    assert list(inputs(wf.storage,job)[2])==['F']
    with pytest.raises(GuidedVLAError,match='GPT_MASK_VIEW_UNAVAILABLE'):inputs(wf.storage,job,['R'])
    assert not fake.calls and not transport.calls

def test_camera_overlay_order_provenance_and_no_fake_masks(tmp_path):
    import base64,io
    native=SimpleNamespace(CAMERAS=CAMERAS,write_json=lambda p,v:p.write_text(json.dumps(v)))
    images={}
    for view in CAMERAS:
        p=tmp_path/f'{view}.png';Image.new('RGB',(20,20),(100,100,100)).save(p);images[view]=str(p)
    Image.new('L',(20,20),255).save(tmp_path/'R_mask.png')
    label=tmp_path/'label.json';label.write_text('{}')
    content,sizes=build_content(native,dict(attempt=str(tmp_path),label=str(label),instruction='R 마스크',images=images,
        mask_views=['R'],mask_provenance={'R':['UNAPPROVED','MANUAL']}),{'image_max_side':100},np.zeros(3))
    annotations=[v['text'] for v in content[1:] if v['type']=='input_text']
    assert [v.split(';')[0] for v in annotations]==['Camera '+v for v in CAMERAS]
    pictures=[Image.open(io.BytesIO(base64.b64decode(v['image_url'].split(',')[1]))) for v in content if v['type']=='input_image']
    assert pictures[3].getpixel((10,10))[0]>pictures[1].getpixel((10,10))[0]
    manifest=read_json(tmp_path/'input_manifest.json')
    assert manifest['mask_views']==['R'] and manifest['query_mask_png']=={'R':'R_mask.png'}
    assert set(manifest['image_sizes'])==set(CAMERAS) and not (tmp_path/'F_mask.png').exists()

def test_native_fake_multiview_dispatch_preserves_originals_and_no_approval(setup):
    wf,job,client,fake,transport=setup
    job.mask.approved=False;job.mask.approved_at=None;wf.storage.save_job(job)
    before={v:wf.storage.artifact_path('masks',m.id).read_bytes() for v,m in [('F',job.mask),('R',job.scene.views['R'].mask),('S4',job.scene.views['S4'].mask)]}
    updated=wf.run_final_trajectory_prediction(job.id,mask_conditioning_views=['R'],instruction='R 마스크로 최종 3D 예측해줘')
    assert len(fake.calls)==1 and not transport.calls and not transport.health_calls
    assert not updated.mask.approved and updated.vla_prediction is None
    assert updated.raw_final_prediction.mask_views==['R'] and updated.raw_final_prediction.displayable
    options=read_json(fake.calls[0][0][-1]);folder=Path(options['attempt']);manifest=read_json(folder/'request_manifest.json')
    assert options['mask_views']==['R'] and manifest['mask_inputs']['R']['id']==str(job.scene.views['R'].mask.id)
    assert (folder/'R_mask.png').read_bytes()==before['R'] and not (folder/'F_mask.png').exists()
    assert read_json(folder/'submission.json')['claimed']

def test_agent_r_selection_only_final_tool_no_upstream(setup):
    wf,job,client,fake,transport=setup
    job.mask.approved=False;job.mask.approved_at=None;wf.storage.save_job(job)
    events=[];ctx=WeldingAgentContext(job.id,'offline','R 마스크로 최종 3D 예측해줘',wf,FakeSimulator(),lambda *v:events.append(v))
    asyncio.run(invoke(ctx,'get_workspace_state'))
    result=asyncio.run(invoke(ctx,'run_final_trajectory_prediction'))
    assert result['mask_conditioning_views']==['R'] and len(fake.calls)==1 and not transport.calls
    assert ctx.mask_conditioning_views==['R'] and not wf.get_job(job.id).mask.approved
    assert read_json(fake.calls[0][0][-1])['mask_views']==['R']

def test_approved_f_strict_proof_kept_separate(setup):
    wf,job,client,fake,transport=setup
    result=wf.run_final_trajectory_prediction(job.id,mask_conditioning_views=['F'])
    assert result.vla_prediction and result.vla_prediction.mask_views==['F']
    assert result.state.value=='VLA_READY' and result.raw_final_prediction.validation_status=='PASS'
    assert len(fake.calls)==1 and not transport.calls

def test_agent_unspecified_defaults_all_despite_tool_f_suggestion(setup):
    wf,job,client,fake,transport=setup
    ctx=WeldingAgentContext(job.id,'offline','최종 3D 궤적 예측해줘',wf,FakeSimulator(),lambda *_:None)
    asyncio.run(invoke(ctx,'get_workspace_state'))
    result=asyncio.run(invoke(ctx,'run_final_trajectory_prediction',mask_conditioning_views=['F']))
    assert result['mask_conditioning_views']==['F','R','S4']
    assert read_json(fake.calls[0][0][-1])['mask_views']==['F','R','S4'] and not transport.calls

def test_demo_uniform_mapping_preserves_shape_order_and_runs():
    runs=[[[1,2,3],[2,2,3]],[[4,2,3],[4,4,3]]];original=json.dumps(runs)
    mapped,scale,bounds=map_runs(runs,[.8,0,.2])
    source=np.asarray([p for r in runs for p in r]);np.testing.assert_allclose(np.diff(mapped,axis=0),np.diff(source,axis=0)*scale)
    np.testing.assert_array_equal(mapped[0],[.8,0,.2]);assert bounds==[[0,2],[2,4]]
    assert np.max(np.linalg.norm(mapped-mapped[0],axis=1))==pytest.approx(.060)
    assert json.dumps(runs)==original

@pytest.mark.parametrize('points',[[[[1,2,3]]],[[[0,0,0],[float('nan'),1,2]]],[[[0,0,0],[0,0,0]]]])
def test_demo_malformed_or_no_motion_rejected(points):
    with pytest.raises(ValueError):map_runs(points,[.8,0,.2])

def test_demo_gate_rejects_source_tamper_and_hardware_flags(tmp_path):
    from backend.services.robot_demo import verify,CODE
    from backend.services.current_preview_gate import sha
    from uuid import uuid4
    folder=tmp_path/str(uuid4());folder.mkdir();job_id=str(uuid4());artifact=str(uuid4())
    job_file=tmp_path/(job_id+'.json');job_file.write_text(json.dumps({'id':job_id}))
    geometry={'runs':[[[0,0,0],[1,1,1]]],'units':'mm','coordinate_frame':'relative'}
    for name,v in [('geometry.json',geometry),('source-display.json',dict(job_id=job_id,artifact_id=artifact,sample_id='B_PP_03_0001',geometry=geometry)),('demo_mapping.json',{})]:
        (folder/name).write_text(json.dumps(v))
    (folder/'demo_playback.npz').write_bytes(b'offline fake')
    for n in CODE:
        (tmp_path/n).parent.mkdir(parents=True,exist_ok=True);(tmp_path/n).write_text('# fake')
    d=dict(preview_id=folder.name,kind='robot',robot_demo_only=True,demo_transformed=True,source_preserved=True,
        physical_robot_executable=False,physical_execution=False,vla_orientation=False,validated_simulation=False,
        job_id=job_id,artifact_id=artifact,sample_id='B_PP_03_0001',point_count=2,playback_point_count=2,
        job_file=str(job_file),simulator_root=str(tmp_path/'sim'),package=str(folder/'geometry.json'),native_files={},
        owned_code={n:sha(tmp_path/n) for n in CODE})
    for n,k in [('geometry.json','package_sha256'),('source-display.json','source_sha256'),('demo_mapping.json','mapping_sha256'),('demo_playback.npz','playback_sha256')]:d[k]=sha(folder/n)
    verify(d,folder/'preview.json',tmp_path)
    d['physical_execution']=True
    with pytest.raises(ValueError):verify(d,folder/'preview.json',tmp_path)
    d['physical_execution']=False;(folder/'geometry.json').write_text('{}')
    with pytest.raises(ValueError):verify(d,folder/'preview.json',tmp_path)


@pytest.mark.parametrize('tamper',[False,True])
@pytest.mark.parametrize('backend',['dataset_stp','dataset_final'])
def test_demo_runtime_small_source_evidence_and_joint_motion(tmp_path,monkeypatch,tamper,backend):
    from backend.services.current_preview_runtime import CurrentPreviewRuntime
    session=tmp_path/'session';output=session/'outputs'/'request';output.mkdir(parents=True)
    (session/'results').mkdir();package=tmp_path/'package';package.mkdir()
    value={'runs':[[[0,0,0],[1,2,3]]],'units':'mm','coordinate_frame':'relative'}
    for p in (package/'geometry.json',output/'geometry.json'):p.write_text(json.dumps(value))
    if tamper:(output/'geometry.json').write_text('{}')
    q=np.array([[0,0,0,0,0,0],[.01,.02,.03,.04,.05,.06]]);points=np.array([[.8,0,.2],[.81,0,.2]])
    for p in (package/'demo_playback.npz',output/'waypoints.npz'):
        np.savez_compressed(p,joint_position_rad=q,demo_playback_points=points)
    (output/'scene.usda').write_text('# fake stage')
    report=dict(state='done',artifact_id='artifact',package_id='package',point_count=2,exact_xyz_preserved=True,
        fixture_ready=False,physical_robot_executable=False,robot_motion=True,rb10_joints_moved=True,
        robot_demo_only=True,physical_execution=False,physics_stepping=False,capture_status='FAILED')
    for p in (output/'report.json',session/'results'/'request.json'):p.write_text(json.dumps(report))
    if backend=='dataset_final':
        from backend.services.simulator_final_client import SimulatorFinalRuntime
        runtime=SimulatorFinalRuntime(SimpleNamespace(),monitor=False)
    else:runtime=CurrentPreviewRuntime(SimpleNamespace(),monitor=False,backend=backend)
    runtime.process=SimpleNamespace(poll=lambda:None,stop=lambda:None);runtime.session=session
    runtime.state='RUNNING_PREVIEW';runtime.claim={}
    runtime.latest=dict(request_id='request',artifact_id='artifact',package_id='package',point_count=2,
        source_point_count=2,playback_point_count=2,sample_family='B_PP',geometry_only=False,robot_demo_only=True,status='QUEUED')
    monkeypatch.setattr('backend.services.current_preview_runtime.verify_preview',lambda _:({'package':str(package/'geometry.json'),'playback_point_count':2},None,None))
    runtime.tick()
    assert runtime.state==('FAILED' if tamper else 'READY')
    if not tamper:
        assert runtime.latest['rb10_joints_moved'] and runtime.latest['exact_xyz_preserved']
        assert runtime.latest['capture_status']=='FAILED' # Capture failure never lies about successful motion.
