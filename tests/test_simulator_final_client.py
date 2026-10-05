"""Injected native outputs only. No model/Isaac/external process calls."""
import json
from pathlib import Path
from uuid import uuid4
import numpy as np
import pytest

from backend.services.current_preview_config import CurrentPreviewError
from backend.services.current_preview_gate import read,verify_preview
from backend.services.simulator_prediction_package import sha
from backend.services.simulator_final_client import SimulatorFinalClient,SimulatorFinalRuntime
from backend.services.simulator_final_contract import NATIVE_FILES
from backend.services.simulator_final_result import validate,observed_completion
from tests.test_current_vla_preview import prepared
from tests.test_simulator_stp_client import StpBuilder
from tests.test_viewport_capture_compat import png


class FinalBuilder(StpBuilder):
    def build(self,**options):
        result=super().build(**options)
        result['orientation_source']='simulator_final_policy'
        result['validation']['frame']='simulator_final_scene'
        return result


def fixture(tmp_path):
    old,job,_,attempt=prepared(tmp_path,'B_PP_03_0001')
    root=tmp_path/'simulator_final';root.mkdir()
    for name in NATIVE_FILES:
        file=root/name;file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text('# fake native output only')
    (root/'run_rb10_trajectory_with_ATU01035.py').write_text('# import_urdf_isaac61 capture_native_frame')
    (root/'rbpodo_description/robots/rb10_1300e_u.urdf').write_text('<robot name="fake"/>')
    client=SimulatorFinalClient(old.storage,old.runtime,root=root,builder=FinalBuilder(),settings=old.settings)
    return client,job,attempt


def test_native_final_exact_current_source_and_approval(tmp_path):
    client,job,attempt=fixture(tmp_path)
    protected={file:sha(file) for file in (attempt/'trajectory.npz',client.storage.artifact_path('jobs',job.id,'.json'),client.storage.artifact_path('masks',job.mask.id))}
    claim=client.prepare(job_id=job.id)
    descriptor,package,prediction=verify_preview(claim,project=client.settings.project)
    assert descriptor['backend']=='dataset_final'
    assert descriptor['simulator_root']==str(client.root)
    assert package['playback']['coordinate_frame']=='simulator_final_scene'
    assert descriptor['source_point_count']==9 and descriptor['playback_point_count']==17
    assert prediction.read_bytes()==(attempt/'trajectory.npz').read_bytes()
    assert all(sha(file)==digest for file,digest in protected.items())
    caps=client.capabilities(job_id=job.id)
    assert caps['robot_preview_ready'] and not caps['path_preview_ready']
    assert not caps['physical_robot_executable'] and not caps['vla_orientation']
    client.run(job_id=job.id,kind='robot')
    assert len(client.runtime.calls)==1
    verify_preview(client.runtime.calls[0],project=client.settings.project)


@pytest.mark.parametrize('mutation',['job','mask','native','prediction'])
def test_mutation_rejects_before_native_launch(tmp_path,mutation):
    client,job,attempt=fixture(tmp_path);claim=client.prepare(job_id=job.id)
    if mutation=='job':
        job.scene.split='val' if job.scene.split!='val' else 'train';client.storage.save_job(job)
    else:
        file=(client.storage.artifact_path('masks',job.mask.id) if mutation=='mask' else client.root/'contact_registration_determinism.py' if mutation=='native' else attempt/'trajectory.npz')
        file.write_bytes(b'changed')
    with pytest.raises(ValueError):verify_preview(claim,project=client.settings.project)
    assert not client.runtime.calls


def test_native_failure_no_retry_or_alternate_renderer(tmp_path):
    client,job,_=fixture(tmp_path)
    client.builder.failure='SIMULATOR_FINAL_IK_FAIL'
    with pytest.raises(CurrentPreviewError) as error:client.run(job_id=job.id)
    assert error.value.code=='SIMULATOR_FINAL_IK_FAIL'
    assert len(client.builder.calls)==1 and not client.runtime.calls
    with pytest.raises(CurrentPreviewError) as error:client.prepare(job_id=job.id,kind='path')
    assert error.value.code=='SIMULATOR_FINAL_ROBOT_PREVIEW_REQUIRED'
    assert len(client.builder.calls)==1


def test_native_completion_requires_captures_measured_motion_and_prediction(tmp_path):
    client,job,_=fixture(tmp_path);claim=client.prepare(job_id=job.id)
    d,p,_=verify_preview(claim,project=client.settings.project)
    out=tmp_path/'output';out.mkdir()
    for name in ('start','middle','end'):(out/(name+'.png')).write_bytes(png())
    (out/'scene.usda').write_text('#usda 1.0\n')
    native=np.load(Path(d['package']).parent/'native/trajectory_solution.npz')
    np.savez(out/'scene.actual_weld.npz',actual_tip_path_world_m=native['tcp_pose_xyz_mm_rpy_deg'][:,:3]*.001)
    data={k:d[k] for k in ('job_id','artifact_id','package_id','sample_id','point_count','playback_point_count')}
    data.update(request_id=str(uuid4()),session_id=str(uuid4()),state='done',backend='dataset_final',
        physical_robot_executable=False,vla_orientation=False,gt_is_target=False,exact_xyz_preserved=True,
        physics_stepping=True,robot_motion=True,playback_finished=True)
    validate(data,out,data,d)
    (out/'middle.png').unlink()
    with pytest.raises(OSError):validate(data,out,data,d)


def completion_fixture(tmp_path,monkeypatch):
    from backend.services.simulator_client import SimulatorConfig
    client,job,_=fixture(tmp_path);claim=client.prepare(job_id=job.id)
    descriptor,_,_=verify_preview(claim,project=client.settings.project)
    runtime=SimulatorFinalRuntime(SimulatorConfig(root=client.root,python=None,sample_id=None,
        data_root=None,prediction_root=None,runtime_dir=tmp_path/'runtime'),monitor=False)
    runtime.session=runtime.config.runtime_dir/'current-previews/sessions'/str(uuid4());runtime.latest={key:descriptor[key] for key in
        ('job_id','artifact_id','package_id','sample_id','point_count','playback_point_count')}
    runtime.latest.update(request_id=str(uuid4()),session_id=runtime.session.name,status='QUEUED',backend='dataset_final',kind='robot')
    output=runtime.session/'outputs'/runtime.latest['request_id'];output.mkdir(parents=True)
    (runtime.session/'results').mkdir()
    for name in ('start','middle','end'):(output/(name+'.png')).write_bytes(png())
    (output/'scene.usda').write_text('#usda 1.0\n')
    with np.load(Path(descriptor['package']).parent/'native/trajectory_solution.npz') as native:
        np.savez(output/'scene.actual_weld.npz',actual_tip_path_world_m=native['tcp_pose_xyz_mm_rpy_deg'][:,:3]*.001)
    class Process:
        pid=123
        def poll(self):return None
        def stop(self):self.stopped=True
    runtime.process=Process();runtime.claim=claim;runtime.state='RUNNING_PREVIEW'
    runtime.playback_finished_seen=runtime.scene_saved_seen=runtime.native_traceback_seen=False
    runtime.submitted=runtime.clock()
    monkeypatch.setattr('backend.services.current_preview_gate.verify_preview',lambda value:verify_preview(value,project=client.settings.project))
    monkeypatch.setattr('backend.services.current_preview_runtime.verify_preview',lambda value:verify_preview(value,project=client.settings.project))
    return runtime,descriptor,output


def test_owned_pipe_completion_requires_exact_save_and_playback_markers(tmp_path,monkeypatch):
    runtime,descriptor,output=completion_fixture(tmp_path,monkeypatch)
    runtime.observe_native_line('[PLAYBACK] finished')
    runtime.observe_native_line('[SAVE] '+str(tmp_path/'another-scene.usda'))
    runtime.tick();assert runtime.state=='RUNNING_PREVIEW'
    assert not (output/'report.json').exists()
    runtime.observe_native_line('[SAVE] '+str(output/'scene.usda'))
    runtime.tick();assert runtime.state=='READY'
    assert runtime.latest['status']=='SUCCEEDED'
    data=read(runtime.session/'results'/(runtime.latest['request_id']+'.json'))
    assert data['completion_source']=='owned_native_stdout_and_saved_artifacts'
    assert data['observed_artifacts_sha256']['end.png']==sha(output/'end.png')
    validate(data,output,runtime.latest,descriptor)


@pytest.mark.parametrize('failure',['capture','traceback','approval'])
def test_saved_marker_does_not_bypass_native_evidence_or_lineage(tmp_path,monkeypatch,failure):
    runtime,descriptor,output=completion_fixture(tmp_path,monkeypatch)
    runtime.observe_native_line('[PLAYBACK] finished')
    runtime.observe_native_line('[SAVE] '+str(output/'scene.usda'))
    if failure=='capture':(output/'end.png').unlink()
    elif failure=='traceback':runtime.observe_native_line('Traceback (most recent call last):')
    else:Path(descriptor['package']).write_text('{}')
    runtime.tick()
    assert runtime.state=='FAILED' and runtime.process is None
    assert runtime.latest['reason_code']=='SIMULATOR_FINAL_OUTPUT_INVALID'
    assert not (output/'report.json').exists()


def test_observed_completion_never_claims_missing_native_markers(tmp_path,monkeypatch):
    runtime,descriptor,output=completion_fixture(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='markers missing'):
        observed_completion(descriptor,runtime.latest,output,playback_finished=True,scene_saved=False)


def test_final_frame_http_contract_and_stop_staleness(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import create_app
    from backend.agent.config import AgentSettings
    from backend.orchestrator.workflow import Workflow
    from backend.services.storage import LocalStorage
    from tests.agent_fakes import FakeSimulator
    runtime,descriptor,output=completion_fixture(tmp_path,monkeypatch)
    app=create_app(workflow=Workflow(LocalStorage(tmp_path/'api-storage')),simulator=FakeSimulator(),
        preview_runtime=runtime,agent_settings=AgentSettings(enabled=False))
    params={key:runtime.latest[key] for key in ('job_id','artifact_id')}
    with TestClient(app) as api:
        gallery=api.get('/api/simulator/current-preview/frames',params=params).json()
        assert [frame['name'] for frame in gallery['frames']]==['start','middle','end']
        for frame in gallery['frames']:
            response=api.get(frame['url'])
            assert response.status_code==200 and response.content==png()
            assert response.headers['cache-control']=='no-store'
        assert api.get(gallery['frames'][0]['url'].replace('/start/','/P0/')).status_code==404
        runtime.stop()
        assert api.get(gallery['frames'][0]['url']).status_code==409
