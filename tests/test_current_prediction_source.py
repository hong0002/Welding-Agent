"""Current artifact -> exact XYZ -> native playback, entirely fake/offline."""
import numpy as np
import pytest
from backend.services.prediction_path_evidence import verify_selection,verify_rendered,verify_demo_source,xyz_hash
from backend.services.robot_demo import RobotPreview
from backend.services.current_preview_config import CurrentPreviewError
from backend.services.current_preview_gate import verify_preview,read
from backend.orchestrator.workflow import Workflow
from tests.test_gpt_simulator_handoff import gpt_fixture
from tests.test_simulator_stp_client import fixture


def source_row(client,job,attempt):
    with np.load(attempt/'trajectory.npz') as arrays:points=arrays['predicted_path_m'].copy()
    return dict(id=str(job.vla_prediction.artifact_id),stage='gpt_stage',stage_index=2,label='GPT Derived',
        sample_id=job.scene.sample_id,stale=False,units='m',coordinate_frame='source_robot_frame_unaligned_with_isaac',runs=[points.tolist()]),points


def test_selected_gpt_stage_and_hash_reach_immutable_descriptor(tmp_path,monkeypatch):
    client,job,attempt=gpt_fixture(tmp_path);row,points=source_row(client,job,attempt)
    monkeypatch.setattr('backend.services.output_catalog.xyz_output',lambda *a,**k:row)
    preview=RobotPreview(Workflow(client.storage),client.runtime,client,project=client.settings.project)
    assert preview.run(job.id,row['id'],2,'gpt_stage')['mode']=='STRICT'
    d,p,file=verify_preview(client.runtime.calls[-1],project=client.settings.project)
    assert d['prediction_selection']['stage_index']==2 and d['prediction_selection']['output_kind']=='gpt_stage'
    assert d['prediction_selection']['source_xyz_sha256']==xyz_hash(points)
    assert p['playback']['source_artifact_id']==row['id'] and file.read_bytes()==(attempt/'trajectory.npz').read_bytes()


@pytest.mark.parametrize('change',['different_stage','gt_substitution','broken_runs'])
def test_selected_xyz_mismatch_never_launches_or_substitutes(tmp_path,change):
    client,job,attempt=gpt_fixture(tmp_path);row,points=source_row(client,job,attempt)
    if change=='different_stage':row['runs'][0][1][0]+=1
    elif change=='gt_substitution':
        with np.load(attempt/'trajectory.npz') as a:row['runs']=[(a['ground_truth_path_m']+1).tolist()]
    else:row['runs']=[points[:3].tolist(),points[3:].tolist()]
    with pytest.raises(CurrentPreviewError) as error:client.run(job_id=job.id,artifact_id=row['id'],selected_source=row)
    assert error.value.code=='CURRENT_PREVIEW_SELECTED_SOURCE_MISMATCH'
    assert not client.runtime.calls and not client.builder.calls


@pytest.mark.parametrize('change',['stale','playback','other_sample'])
def test_saved_playback_or_previous_source_cannot_be_current_robot(tmp_path,monkeypatch,change):
    client,job,attempt=fixture(tmp_path);row,_=source_row(client,job,attempt)
    if change=='stale':row['stale']=True
    elif change=='playback':row['stage']='playback'
    else:row['sample_id']='B_PR_03_0009'
    monkeypatch.setattr('backend.services.output_catalog.xyz_output',lambda *a,**k:row)
    with pytest.raises(CurrentPreviewError) as e:RobotPreview(Workflow(client.storage),client.runtime,client).run(job.id)
    assert e.value.code=='CURRENT_PREDICTION_REQUIRED' and not client.runtime.calls and not client.builder.calls


def test_actual_red_curve_inverse_and_playback_hash_reject_gt():
    points=np.array([[.1,.2,.3],[.11,.21,.31],[.13,.2,.32]])
    t=np.eye(4);t[:3,:3]=[[0,-1,0],[1,0,0],[0,0,1]];t[:3,3]=[.4,.3,.2]
    world=points@t[:3,:3].T+t[:3,3]
    proof=verify_rendered(points,t,world.astype('float32'),points.copy())
    assert proof['renderer_source_point_count']==3 and proof['path_source_is_current_prediction']
    assert proof['source_xyz_sha256']==proof['package_source_xyz_sha256']==proof['playback_parent_xyz_sha256']
    assert proof['renderer_inverse_error_m_max']<2e-7 and not proof['gt_is_target']
    with pytest.raises(ValueError):verify_rendered(points,t,world+1,points)
    with pytest.raises(ValueError):verify_rendered(points,t,world,points+1)
    scaled=t.copy();scaled[:3,:3]*=2
    with pytest.raises(ValueError,match='rigid'):verify_rendered(points,scaled,points@scaled[:3,:3].T+scaled[:3,3],points)


def test_demo_explicit_transformed_copy_parent_preserves_raw_relative():
    geometry=dict(runs=[[[0,0,0],[2,3,0],[4,2,1]]])
    mapping=dict(uniform_scale=.01,anchor_tcp_m=[.4,0,.2]);source=np.array(geometry['runs'][0])
    arrays=dict(source_indices=np.array([0,1,2]),demo_playback_points=source*.01+[.4,0,.2])
    proof=verify_demo_source(geometry,arrays,mapping)
    assert proof['playback_parent_is_current_prediction'] and not proof['path_source_is_current_prediction']
    assert proof['source_xyz_sha256']==xyz_hash(source) and proof['path_transformed_from_current_prediction']
    arrays['demo_playback_points'][1,0]+=1
    with pytest.raises(ValueError):verify_demo_source(geometry,arrays,mapping)


def test_implicit_selection_prefers_current_gpt_over_other_prediction(monkeypatch):
    import backend.services.output_catalog as module
    base=dict(dimensions=3,states={'OUTPUT_RENDERABLE':True},runs=[[[0,0,0],[1,0,0]]],stale=False)
    rows=[dict(base,id='gpt',stage='final'),dict(base,id='guided',stage='prediction'),dict(base,id='old',stage='playback',stale=True)]
    monkeypatch.setattr(module,'catalog',lambda *a,**k:{'outputs':rows})
    assert module.xyz_output(None,None,None)['id']=='gpt'
    assert module.xyz_output(None,None,None,'guided',output_kind='prediction')['id']=='guided'


def test_guided_selected_view_uses_exact_immutable_npz_not_reconverted_json(tmp_path):
    import json
    from backend.services.output_catalog import xyz_output
    client,job,attempt=fixture(tmp_path)
    with np.load(attempt/'trajectory.npz') as a:points=a['predicted_path_m'].copy()
    response=json.loads((attempt/'response.json').read_text())
    response['predicted_path_xyz_mm']=(points.astype('float32')*np.float32(1000)).tolist()
    (attempt/'response.json').write_text(json.dumps(response))
    row=xyz_output(client.storage,job,None,job.vla_prediction.artifact_id,project=client.settings.project,output_kind='prediction')
    assert row['units']=='m' and np.array_equal(np.asarray(row['runs'][0]),points)
    assert verify_selection(row,points)['source_xyz_sha256']==xyz_hash(points)


def test_completion_requires_red_curve_proof_for_selected_artifact(tmp_path,monkeypatch):
    from tests.test_preview_capture import runtime_fixture,completion
    from backend.services.preview_capture_result import validate_result
    runtime,client,claim,attempt,builder,launcher=runtime_fixture(tmp_path,monkeypatch)
    try:
        output,result,data=completion(runtime,claim,())
        d=read(claim['path']);package=__import__('pathlib').Path(d['package']).parent
        with np.load(package/'predictions'/d['sample_id']/'trajectory.npz') as a:points=a['predicted_path_m'].copy()
        row=dict(id=d['artifact_id'],stage='prediction',label='Guided VLA',coordinate_frame=d['coordinate_frame'],units='m',runs=[points.tolist()])
        d['prediction_selection']=verify_selection(row,points)
        with pytest.raises(ValueError,match='actual rendered'):validate_result(data,output,runtime.latest,d)
        with np.load(output/'waypoints.npz') as a:recorded={k:a[k].copy() for k in a.files}
        t=np.asarray(d['source_to_scene']);rendered=(points.astype(float)@t[:3,:3].T+t[:3,3]).astype('float32')
        recorded['rendered_path_world_m']=rendered
        with np.load(package/'native/trajectory_solution.npz') as a:parent=a['predicted_source_xyz_m'].copy()
        proof=verify_rendered(points,t,rendered,parent)
        data.update(**proof,prediction_selection=d['prediction_selection'])
        import json
        np.savez(output/'waypoints.npz',**recorded);(output/'report.json').write_text(json.dumps(data))
        assert validate_result(data,output,runtime.latest,d)['path_source_is_current_prediction']
        recorded['rendered_path_world_m'][1,0]+=.01;np.savez(output/'waypoints.npz',**recorded)
        with pytest.raises(ValueError,match='BasisCurves'):validate_result(data,output,runtime.latest,d)
    finally:runtime.stop()
