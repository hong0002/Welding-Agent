"""Result access is independent of execution authority; fake transports only."""
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import numpy as np
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from tests.agent_fakes import FakeRunner,FakeSimulator
from backend.agent.config import AgentSettings
from backend.services.output_catalog import catalog,xyz_output
from backend.services.visibility_artifacts import prediction_rows,simulator_rows,recovered_gpt_rows
from backend.services.visibility_path_preview import ResultPathPreview
from backend.services.geometry_preview import GeometryPreviewService,verify,CODE
from backend.services.current_preview_config import CurrentPreviewError
from backend.orchestrator.state_machine import StateMachine
from backend.model_clients.gpt_trajectory_entry import derive_rough_visualization
from tests.test_gpt_trajectory import setup,save


def code_fixture(project):
    for name in CODE:
        file=project/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('offline fixture')


class Runtime:
    backend='dataset_stp'
    def __init__(self,project,blocked=False):
        self.config=SimpleNamespace(root=project/'readonly-simulator');self.calls=[];self.blocked=blocked
    def check_configuration(self,**kwargs):
        if self.blocked:raise CurrentPreviewError('CURRENT_PREVIEW_LAUNCHER_NOT_CONFIGURED','missing',503)
    def submit(self,claim):self.calls.append(claim)


@pytest.mark.parametrize('change',['partial','nan','frame','units','sample','count','gap'])
def test_unaccepted_geometry_and_all_stage_rows_visible(setup,tmp_path,change):
    wf,job,client,fake,_=setup;fake.change=change;job=wf.run_final_trajectory_prediction(job.id)
    rows=catalog(wf.storage,job,client,project=tmp_path)['outputs']
    assert any(r['stage']=='gpt_stage' and r['states']['OUTPUT_RENDERABLE'] for r in rows)
    assert xyz_output(wf.storage,job,client,project=tmp_path)['runs']
    assert not job.vla_prediction and not any(r['states']['PHYSICAL_EXECUTION_READY'] for r in rows)
    assert 'private explanation' not in json.dumps(rows)


def test_corners_only_and_rough_derived_independent(setup,tmp_path):
    wf,job,client,_,_=setup;a=client.settings.attempts/str(uuid4());a.mkdir(parents=True)
    save(a/'rough.json',dict(proposal=dict(points=[[0,0,0],[1,2,3]],connections=['within_segment'])))
    save(a/'derived_visualization.json',dict(predicted_path_xyz_mm=[[0,0,0],[.5,1,1.5],[1,2,3]],units='mm'))
    job.raw_final_prediction=client.capture_display(a,uuid4(),job)
    stages=[r for r in catalog(wf.storage,job,client,project=tmp_path)['outputs'] if r['stage']=='gpt_stage']
    assert len(stages)==2 and all(r['states']['OUTPUT_RENDERABLE'] for r in stages)
    assert 'Derived' in stages[1]['label']


def test_previous_remains_when_provider_generates_no_geometry(setup,tmp_path):
    wf,job,client,fake,_=setup;job=wf.run_final_trajectory_prediction(job.id,mask_conditioning_views=['F'])
    artifact=job.raw_final_prediction.artifact_id
    job=wf.parse_instruction(job.id,'오른쪽에서 왼쪽으로 용접해')
    assert any(v['stage']=='prediction' for v in job.previous_outputs)
    # Display retrieval does not need the currently selected provider.
    value=xyz_output(wf.storage,job,None,artifact,project=tmp_path)
    assert value['stale'] and value['runs'] and not value['current_overlay_allowed']
    assert len(fake.calls)==1


@pytest.mark.parametrize('blocked',[False,True])
def test_ik_or_configuration_cannot_remove_relative_path(setup,tmp_path,blocked):
    wf,job,client,fake,_=setup;fake.change='partial';job=wf.run_final_trajectory_prediction(job.id)
    code_fixture(tmp_path);runtime=Runtime(tmp_path,blocked)
    scene=SimpleNamespace(capabilities=lambda **_:{'path_preview_ready':False,'robot_reason_code':'IK_FAIL'},run=lambda **_:pytest.fail('Scene gate bypass'))
    result=ResultPathPreview(wf,runtime,scene,project=tmp_path).run(job.id)
    assert result['viewer_mode']==('WEB_SOURCE_FRAME' if blocked else 'RELATIVE_FRAME')
    assert result['display']['runs'] and not result['robot_ready']
    assert len(fake.calls)==1 and len(runtime.calls)==(0 if blocked else 1)


def test_absolute_registered_scene_and_no_second_launch_on_failure(setup,tmp_path):
    wf,job,client,fake,_=setup;job=wf.run_final_trajectory_prediction(job.id,mask_conditioning_views=['F'])
    code_fixture(tmp_path);runtime=Runtime(tmp_path);calls=[]
    def scene_run(**kwargs):calls.append(kwargs)
    scene=SimpleNamespace(capabilities=lambda **_:{'path_preview_ready':True},run=scene_run)
    service=ResultPathPreview(wf,runtime,scene,project=tmp_path)
    assert service.run(job.id)['viewer_mode']=='REGISTERED_SCENE'
    def fail(**kwargs):calls.append(kwargs);raise CurrentPreviewError('PREVIEW_STARTUP_FAILED','failure',503)
    scene.run=fail
    assert service.run(job.id)['viewer_mode']=='WEB_SOURCE_FRAME'
    assert len(calls)==2 and not runtime.calls and len(fake.calls)==1


def test_stale_foreign_unknown_units_isolated_immutable_package(setup,tmp_path):
    wf,job,client,_,_=setup;a=client.settings.attempts/str(uuid4());a.mkdir(parents=True)
    save(a/'response.json',dict(sample_id='FOREIGN_SAMPLE',predicted_path_xyz_mm=[[0,0,0],[1,2,3]],units='unknown',coordinate_frame='unknown'))
    job.raw_final_prediction=client.capture_display(a,uuid4(),job);wf.storage.save_job(job)
    artifact=job.raw_final_prediction.artifact_id;StateMachine.clear_trajectories(job);wf.storage.save_job(job)
    code_fixture(tmp_path);service=GeometryPreviewService(wf,Runtime(tmp_path),project=tmp_path)
    claim=service.prepare_display(job.id,artifact);path=Path(claim['path']);d=json.loads(path.read_text())
    assert d['sample_id']=='FOREIGN_SAMPLE' and d['isolated_only'] and not d['robot_ready']
    _,geometry,_=verify(d,path,tmp_path);assert geometry['units']=='unknown' and geometry['runs']==[[[0,0,0],[1,2,3]]]
    job.mask.approved=False;wf.storage.save_job(job)
    assert verify(d,path,tmp_path)[1]==geometry


def test_old_guided_npz_still_visible_with_corrupt_response_and_provenance(setup,tmp_path):
    wf,job,_,_,_=setup;artifact=uuid4();a=tmp_path/'.cache/native-models/guided-vla'/str(uuid4());a.mkdir(parents=True)
    (a/'response.json').write_text('{broken')
    np.savez(a/'trajectory.npz',predicted_path_m=np.array([[0,0,0],[1,2,3]],dtype=float))
    save(wf.storage.artifact_path('native_context',artifact,'.vla.json'),dict(job_id=str(job.id),directory=str(a),files={'missing':'hash'}))
    row=prediction_rows(wf.storage,job,project=tmp_path)[0]
    assert row['states']['OUTPUT_RENDERABLE'] and row['stale'] and row['warnings']==['UNVERIFIED_SOURCE_EVIDENCE']
    assert not row['states']['ROBOT_PLAYBACK_READY'] and row['units']=='m'


def test_simulator_source_and_derived_playback_are_separate(setup,tmp_path):
    wf,job,_,_,_=setup;session=tmp_path/'.cache/simulator/current-previews/sessions'/str(uuid4());session.mkdir(parents=True)
    request=uuid4();artifact=uuid4();package=tmp_path/'.cache/simulator/current-previews/packages'/str(uuid4());package.mkdir(parents=True)
    save(package/'preview.json',dict(job_id=str(job.id),sample_id=job.scene.sample_id,coordinate_frame='source_robot_frame_unaligned_with_isaac'))
    save(session/'catalog.json',{str(artifact):dict(path=str(package/'preview.json'))})
    (session/'queue').mkdir();save(session/'queue'/(str(request)+'.json'),dict(artifact_id=str(artifact)))
    output=session/'outputs'/str(request);output.mkdir(parents=True)
    np.savez(output/'waypoints.npz',predicted_path_m=np.array([[0,0,0],[1,1,1]]),playback_target_world_m=np.array([[2,2,2],[3,3,3],[4,4,4]]))
    rows=simulator_rows(job,project=tmp_path)
    assert [r['stage'] for r in rows]==['simulator_source','playback']
    assert [sum(map(len,r['runs'])) for r in rows]==[2,3]
    assert all(r['stale'] and not r['current_overlay_allowed'] for r in rows)
    assert xyz_output(wf.storage,job,None,request,project=tmp_path,output_kind='playback')['runs']==rows[1]['runs']
    (output/'waypoints.npz').write_bytes(b'corrupt archive')
    unreadable=simulator_rows(job,project=tmp_path)
    assert len(unreadable)==2 and all(r['states']['OUTPUT_EXISTS'] and not r['states']['OUTPUT_RENDERABLE'] for r in unreadable)
    assert all('NO_READABLE_FINITE_GEOMETRY' in r['warnings'] for r in unreadable)


def test_derived_interpolation_uses_only_native_rough_points(tmp_path):
    points=np.array([[0,0,0],[1,2,3]],dtype=float);seen=[]
    def interpolate(p,m,n):seen.append((p.tolist(),m,n));return p,None,np.array(['within_segment'])
    native=SimpleNamespace(check_proposal=lambda r:(SimpleNamespace(connections=['within_segment']),points),interpolate_corners=interpolate,write_json=save)
    derive_rough_visualization(native,{},tmp_path,False)
    data=json.loads((tmp_path/'derived_visualization.json').read_text())
    assert data['predicted_path_xyz_mm']==points.tolist() and seen==[(points.tolist(),['within_segment'],33)]
    assert data['coordinate_frame']=='gpt_start_relative_visualization_mm' and not data['robot_ready']


def test_2d_upstream_invalidation_preserves_independent_segments(setup,tmp_path):
    wf,job,client,_,_=setup
    before=job.rough_trajectory.model_dump(mode='json')
    StateMachine.clear_trajectories(job)
    rows=catalog(wf.storage,job,client,project=tmp_path)['outputs']
    row=next(r for r in rows if r['stage']=='rough_preview')
    assert row['stale'] and row['states']['OUTPUT_RENDERABLE']
    assert len(row['segments'])==len(before['segments'])
    assert [s['region_id'] for s in row['segments']]==[s['region_id'] for s in before['segments']]


def test_read_api_stale_output_no_acceptance_and_browser_paths_rejected(setup):
    wf,job,client,fake,_=setup;fake.change='partial';job=wf.run_final_trajectory_prediction(job.id)
    artifact=job.raw_final_prediction.artifact_id
    job=wf.parse_instruction(job.id,'오른쪽에서 왼쪽으로 용접해')
    app=create_app(workflow=wf,agent_runner=FakeRunner(),simulator=FakeSimulator(),agent_settings=AgentSettings(enabled=False))
    with TestClient(app) as http:
        response=http.get(f'/api/weld/{job.id}/outputs/{artifact}/display')
        assert response.status_code==200 and response.json()['runs'] and response.json()['stale']
        response=http.post('/api/simulator/path-preview',json={'job_id':str(job.id),'launcher':'arbitrary/path'})
        assert response.status_code==422 and len(fake.calls)==1


def test_acceptance_receipt_corruption_does_not_hide_bound_source(setup,tmp_path):
    wf,job,client,fake,_=setup;job=wf.run_final_trajectory_prediction(job.id,mask_conditioning_views=['F'])
    receipt=wf.storage.artifact_path('native_context',job.vla_prediction.artifact_id,'.vla.json')
    receipt.write_text('{corrupt')
    row=prediction_rows(wf.storage,job,project=tmp_path)[0]
    assert row['states']['OUTPUT_RENDERABLE'] and row['warnings']==['UNVERIFIED_SOURCE_EVIDENCE']
    assert sum(map(len,row['runs']))==33 and not row['states']['OUTPUT_VALIDATED']
    assert len(fake.calls)==1


def test_corrupt_owned_gpt_stage_has_safe_metadata_card(setup,tmp_path):
    wf,job,client,_,_=setup;a=client.settings.attempts/str(uuid4());a.mkdir(parents=True)
    artifact=uuid4();save(a/'request_manifest.json',dict(workflow_job_id=str(job.id),artifact_id=str(artifact),sample_id=job.scene.sample_id))
    (a/'rough.json').write_text('{corrupt')
    rows=recovered_gpt_rows(job,set(),project=tmp_path)
    assert len(rows)==1 and rows[0]['states']['OUTPUT_EXISTS'] and not rows[0]['states']['OUTPUT_RENDERABLE']
    assert rows[0]['warnings']==['DISPLAY_DATA_UNREADABLE'] and rows[0]['stage']=='gpt_stage'
