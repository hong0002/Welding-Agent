"""Current source routing only; native preparation and all transports are injected."""
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import sys
import numpy as np
import pytest

from backend.services.current_preview_gate import read,sha,verify_preview
from backend.services.robot_demo import RobotPreview,CODE,successful_anchor
from backend.services.geometry_preview import CODE as GEOMETRY_CODE
from tests.test_simulator_final_client import fixture


def test_relative_final_client_preserves_exact_current_stage_without_approval(tmp_path,monkeypatch):
    client,job,attempt=fixture(tmp_path)
    original=(attempt/'trajectory.npz').read_bytes()
    job.mask.approved=False;job.mask.approved_at=None;job.vla_prediction=None
    client.storage.save_job(job)
    points=[[float(i),float(i*.5),0.] for i in range(9)]
    row=dict(id=str(uuid4()),stage='gpt_stage',stage_index=1,label='GPT Corners',stale=False,
        sample_id=job.scene.sample_id,units='mm',coordinate_frame='gpt_start_relative_visualization_mm',runs=[points])
    monkeypatch.setattr('backend.services.output_catalog.xyz_output',lambda *a,**k:row)
    project=client.settings.project
    source=Path(__file__).resolve().parents[1]
    for name in set(CODE)|set(GEOMETRY_CODE):
        target=project/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((source/name).read_bytes())
    runtime=client.runtime;runtime.backend='dataset_final';runtime.config=SimpleNamespace(root=client.root)
    checks=[];runtime.check_configuration=lambda **kw:checks.append(kw)
    calls=[]
    def prepare(folder,root):
        calls.append((folder,root));mapped=np.asarray(points)*.001+[.4,0,.2]
        np.savez(folder/'demo_playback.npz',demo_playback_points=mapped,source_indices=np.arange(9),
            joint_position_rad=np.arange(54).reshape(9,6)*.001,run_bounds=np.asarray([[0,9]]))
        return dict(anchor_tcp_m=[.4,0,.2],uniform_scale=.001,playback_point_count=9,
            orientation_source='simulator_fixture_policy')
    workflow=SimpleNamespace(storage=client.storage,final_predictor=None,get_display_job=lambda _:job)
    preview=RobotPreview(workflow,runtime,client,project=project,prepare=prepare)
    result=preview.run(job.id,row['id'],1,'gpt_stage')
    assert result['mode']=='DEMO' and result['source_preserved'] and not result['physical_execution']
    assert checks==[{'kind':'robot'}] and len(calls)==1 and len(runtime.calls)==1
    d,geometry,_=verify_preview(runtime.calls[0],project=project)
    assert geometry['runs']==[points] and d['backend']=='dataset_final'
    assert d['prediction_selection']['stage_index']==1 and d['prediction_selection']['output_kind']=='gpt_stage'
    assert d['prediction_selection']['source_point_count']==9 and d['artifact_id']==row['id']
    assert d['job_id']==str(job.id) and d['sample_id']==job.scene.sample_id and not d['validated_simulation']
    assert not d['vla_orientation'] and d['robot_demo_only']
    assert (attempt/'trajectory.npz').read_bytes()==original and not client.storage.get_job(job.id).mask.approved
    assert not client.builder.calls  # No native strict preparation or alternate target.


def test_final_strict_current_absolute_selection_stays_native(tmp_path,monkeypatch):
    client,job,attempt=fixture(tmp_path)
    with np.load(attempt/'trajectory.npz') as data:points=data['predicted_path_m'].copy()
    row=dict(id=str(job.vla_prediction.artifact_id),stage='prediction',label='Guided VLA',stale=False,
        sample_id=job.scene.sample_id,units='m',coordinate_frame='source_robot_frame_unaligned_with_isaac',runs=[points.tolist()])
    monkeypatch.setattr('backend.services.output_catalog.xyz_output',lambda *a,**k:row)
    workflow=SimpleNamespace(storage=client.storage,final_predictor=None,get_display_job=lambda _:job)
    def no_demo(*args):raise AssertionError('Strict must not fallback')
    preview=RobotPreview(workflow,client.runtime,client,project=client.settings.project,prepare=no_demo)
    assert preview.run(job.id,row['id'],output_kind='prediction')['mode']=='STRICT'
    d,_,copy=verify_preview(client.runtime.calls[0],project=client.settings.project)
    assert d['backend']=='dataset_final' and not d.get('robot_demo_only')
    assert copy.read_bytes()==(attempt/'trajectory.npz').read_bytes() and len(client.builder.calls)==1


def test_final_demo_uses_original_native_contact_scene_policy(monkeypatch):
    from backend.services.sample_scene import build_sample_scene
    calls=[];poses=np.arange(12).reshape(2,6)
    def native_scene(obj,sample,source):
        assert source is poses;calls.append(('native_scene',obj,sample));return source,{'original':True},{'native':True}
    def environment(source,arrays,report,*,layout):
        assert source is poses and arrays=={'original':True};calls.append(('environment',layout));return source,arrays,report
    # simulator_final.run_welding_sample.prepare calls this public native entrypoint;
    # it owns the family-specific build_contact_scene dispatch internally.
    monkeypatch.setitem(sys.modules,'welding_scene_layout',SimpleNamespace(build_scene=native_scene))
    monkeypatch.setitem(sys.modules,'welding_environment',SimpleNamespace(apply_environment=environment))
    result=build_sample_scene('sample.obj','B_PR_03_0001',poses,backend='dataset_final')
    assert result[0] is poses and calls==[('native_scene',Path('sample.obj'),'B_PR_03_0001'),('environment','stp')]


def test_final_demo_renderer_is_explicit_not_native_strict_renderer(tmp_path,monkeypatch):
    from backend.services.preview_startup import run_preview
    session=tmp_path/'.cache/simulator/current-previews/sessions'/str(uuid4())
    (session/'queue').mkdir(parents=True);request=str(uuid4())
    (session/'queue'/(request+'.json')).write_text('{}');(session/'catalog.json').write_text('{}')
    monkeypatch.setattr('backend.services.preview_startup.resolve_command',lambda *a,**k:({'backend':'dataset_final','robot_demo_only':True},None,None))
    calls=[]
    monkeypatch.setitem(sys.modules,'backend.demo_robot_isaac_preview',SimpleNamespace(main=lambda options:calls.append(options)))
    monkeypatch.setitem(sys.modules,'backend.simulator_final_preview',SimpleNamespace(main=lambda _:pytest.fail('Strict renderer for Demo')))
    options=dict(session=str(session),first_request=request)
    run_preview(options,project=tmp_path)
    assert calls==[options] and 'isaacsim' not in sys.modules


def test_final_success_evidence_can_seed_demo_pose_without_reusing_old_prediction(tmp_path):
    project=tmp_path/'project';root=tmp_path/'native';root.mkdir();package_id=str(uuid4());artifact=str(uuid4())
    package=project/'.cache/simulator/prediction-packages'/package_id;solution=package/'native/trajectory_solution.npz'
    solution.parent.mkdir(parents=True);solution.write_bytes(b'pose seed only')
    (package/'package.json').write_text('{}')
    descriptor=project/'.cache/simulator/current-previews/packages'/str(uuid4())/'preview.json'
    descriptor.parent.mkdir(parents=True)
    descriptor.write_text(json.dumps(dict(simulator_root=str(root),package_id=package_id,native_files={'trajectory_solution.npz':sha(solution)})))
    session=project/'.cache/simulator/current-previews/sessions'/str(uuid4())
    report=session/'outputs'/str(uuid4())/'report.json';report.parent.mkdir(parents=True)
    report.write_text(json.dumps(dict(state='done',robot_motion=True,backend='dataset_final',package_id=package_id,artifact_id=artifact)))
    (session/'catalog.json').write_text(json.dumps({artifact:dict(path=str(descriptor),sha256=sha(descriptor))}))
    assert successful_anchor(project,root)==(solution,report)


@pytest.mark.parametrize('demo',[False,True])
def test_final_capture_names_follow_selected_strict_or_demo_contract(tmp_path,demo):
    from backend.services.current_preview_frames import list_frames,frame_bytes,FINAL_CAPTURE_NAMES
    from backend.services.preview_capture import CAPTURE_NAMES
    from PIL import Image
    from backend.services.current_preview_config import CurrentPreviewError
    runtime_dir=tmp_path/'runtime';session=runtime_dir/'current-previews/sessions'/str(uuid4())
    request=str(uuid4());output=session/'outputs'/request;output.mkdir(parents=True)
    for name in (*CAPTURE_NAMES,*FINAL_CAPTURE_NAMES):Image.new('RGB',(20,10),'red').save(output/(name+'.png'))
    latest=dict(job_id=str(uuid4()),artifact_id=str(uuid4()),package_id=str(uuid4()),sample_id='B_PP_03_0001',
        kind='robot',backend='dataset_final',robot_demo_only=demo,status='SUCCEEDED',request_id=request)
    runtime=SimpleNamespace(latest=latest,state='READY',process=object(),session=session,
        config=SimpleNamespace(runtime_dir=runtime_dir),claim={})
    verify=lambda _:(latest,None,None)
    gallery=list_frames(runtime,latest['job_id'],latest['artifact_id'],verify)
    names=CAPTURE_NAMES if demo else FINAL_CAPTURE_NAMES
    assert [frame['name'] for frame in gallery['frames']]==list(names)
    first=gallery['frames'][0]
    assert frame_bytes(runtime,latest['job_id'],latest['artifact_id'],session.name,request,
        first['name'],first['sha256'],verify).startswith(b'\x89PNG')
    wrong=FINAL_CAPTURE_NAMES[0] if demo else CAPTURE_NAMES[0]
    with pytest.raises(CurrentPreviewError):
        frame_bytes(runtime,latest['job_id'],latest['artifact_id'],session.name,request,wrong,first['sha256'],verify)
