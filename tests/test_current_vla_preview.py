"""Synthetic packages and fake launchers only. No Isaac or model calls."""
from datetime import datetime
import json
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.main import create_app
from backend.model_clients.guided_workflow import conditioning_hash
from backend.orchestrator.state_machine import WorkflowError
from backend.schemas import WeldJob, Scene, SceneView, Mask, VLAResultSummary, WorkflowState
from backend.services.current_vla_preview import CurrentVLAPreviewService
from backend.services.current_preview_gate import verify_preview, resolve_command
from backend.services.storage import LocalStorage
from backend.services.simulator_prediction_package import query_assets
from tests.agent_fakes import FakeSimulator
from tests.test_simulator_prediction_package import fixture, read, sha, write


class FakePreview:
    def __init__(self):
        self.calls = []; self.entries = []
    def submit(self, claim):
        self.calls.append(claim)
        return self.status()
    def status(self):
        return dict(state='STOPPED', can_stop=False, latest=None, error=None, pid=None)
    def stop(self): pass
    def close(self): pass


def prepared(tmp_path):
    adapter, result, attempt, h5 = fixture(tmp_path)
    project = adapter.settings.project
    storage = LocalStorage(project/'storage')
    scene = Scene(id=uuid4(),sample_id=result.sample_id, split='train', primary_view='F', width=100, height=100, image_url='/scene')
    view = SceneView(view_id='F', image_id=uuid4(), width=100, height=100, image_url='/F', image_sha256='a'*64)
    scene.views = {'F':view}
    storage.save_image('scenes',view.image_id,Image.new('RGB',(100,100)))
    metadata = read(attempt/'request_manifest.json')
    mask = Mask(id=UUID(metadata['source_mask_id']),scene_id=scene.id,width=100,height=100,mask_source='manual',
        approved=True,approved_at=datetime.fromisoformat(metadata['approved_at']),selected_pixels=10000,image_url='/mask',overlay_url='/overlay',
        regions=[],min_component_area=16)
    storage.save_image('masks',mask.id,Image.new('L',(100,100),255))
    vla = VLAResultSummary(artifact_id=result.artifact_id,attempt_id=UUID(attempt.name),sample_id=result.sample_id,
        split='train',coordinate_frame=result.coordinate_frame,ade_mm=result.ade_mm,fde_mm=result.fde_mm,mask_views=['F'])
    job = WeldJob(id=uuid4(),scene=scene,mask=mask,state=WorkflowState.VLA_READY,vla_prediction=vla)
    storage.save_job(job)
    # Fake completed native Workflow attempt; no transport/execution is invoked.
    write(attempt/'source_job.json',job.model_dump(mode='json'))
    metadata.update(workflow_job_id=str(job.id),workflow_conditioning_sha256=conditioning_hash(job),mask_views=['F'],
        source_job=str(attempt/'source_job.json'),source_job_sha256=sha(attempt/'source_job.json'),
        source_mask=str(storage.artifact_path('masks',mask.id)),source_mask_sha256=sha(storage.artifact_path('masks',mask.id)),
        scene_source_sha256={'F':sha(storage.artifact_path('scenes',view.image_id))},
        scene_normalized_sha256={'F':sha(storage.artifact_path('scenes',view.image_id))},rough_session=str(attempt),rough_source_files={})
    (attempt/'request_manifest.json').write_text(json.dumps(metadata))
    storage._write_json(storage.artifact_path('native_context',job.id,'.scene.json'),json.dumps({'images':{'F':str(storage.artifact_path('scenes',view.image_id))}}))
    storage._write_json(storage.artifact_path('native_context',result.artifact_id,'.vla.json'),json.dumps(dict(job_id=str(job.id),
        attempt_id=attempt.name,directory=str(attempt),files={name:sha(attempt/name) for name in ('request_manifest.json','source_job.json','response.json','trajectory.npz','metadata.json','completion.json')})))
    geometry = project/'.cache/geometry.json'; clearance = project/'.cache/clearance.json'
    write(geometry,dict(sample_id=result.sample_id,h5_sha256=sha(h5),obj_sha256=sha(query_assets(adapter.settings.dataset_root,result.sample_id)[1]),
        object_placement_candidate_only={'object_translation_m':[0,0,0]},candidates=[dict(outward_sign=-1,
        source_to_scene=np.eye(4).tolist(),fixed_tool_diagnostic={'initial_flange_rotation':np.eye(3).tolist()})]))
    write(clearance,dict(sample_id=result.sample_id,verdict='B_PR_TOOL_CLEARANCE_FAIL',registry_connected=False))
    runtime = FakePreview()
    service = CurrentVLAPreviewService(storage,runtime,settings=adapter.settings,geometry=geometry,clearance=clearance,fixtures=adapter.fixtures)
    return service, job, result, attempt


def test_current_job_exact_prediction_package_not_old_sample_or_gt(tmp_path):
    service, job, original, attempt = prepared(tmp_path)
    claim = service.prepare(job_id=job.id)
    d,p,npz = verify_preview(claim,project=service.settings.project)
    assert d['job_id']==str(job.id) and d['artifact_id']==str(original.artifact_id)==p['artifact_id']
    assert p['sample_id']==job.scene.sample_id=='B_PR_03_0001'
    with np.load(npz,allow_pickle=False) as copy, np.load(attempt/'trajectory.npz') as source:
        np.testing.assert_array_equal(copy['predicted_path_m'],source['predicted_path_m'])
        assert copy['predicted_path_m'].shape==(9,3)
        assert not np.array_equal(copy['predicted_path_m'],copy['ground_truth_path_m'])
    assert npz.read_bytes()==(attempt/'trajectory.npz').read_bytes()
    assert d['fixture_ready'] is False and d['physical_robot_executable'] is False
    assert d['validated_simulation'] is False and d['registry_validated'] is False
    assert d['orientation_source']=='simulator_fixture_policy' and d['vla_orientation'] is False
    assert d['clearance_warning']=='B_PR_TOOL_CLEARANCE_FAIL'
    assert p['preflight']['fixture_ready'] is False  # Original admission never promoted.
    assert p['ade_mm']==original.ade_mm and p['fde_mm']==original.fde_mm
    command=dict(type='preview_current_vla',artifact_id=d['artifact_id'],mode='unvalidated',kind='robot')
    assert resolve_command(command,{d['artifact_id']:claim},project=service.settings.project)[0]==d
    command['path']='untrusted.npz'
    with pytest.raises(ValueError):resolve_command(command,{d['artifact_id']:claim},project=service.settings.project)


@pytest.mark.parametrize('edit',['job','mask','source','package','descriptor','geometry'])
def test_changed_input_rejected_in_owned_child_gate(tmp_path,edit):
    service,job,_,attempt=prepared(tmp_path);claim=service.prepare(job_id=job.id)
    descriptor=read(claim['path']); package=read(descriptor['package'])
    if edit=='job':
        job.scene.views['F'].image_sha256='b'*64;service.storage.save_job(job)
    else:
        target={'mask':service.storage.artifact_path('masks',job.mask.id),'source':attempt/'trajectory.npz',
                'package':Path(package['prediction_root'])/package['sample_id']/'trajectory.npz',
                'descriptor':Path(claim['path']),'geometry':service.geometry}[edit]
        target.write_bytes(b'changed')
    with pytest.raises(ValueError):verify_preview(claim,project=service.settings.project)


def test_api_ids_origin_no_paths_and_old_replay_unchanged(tmp_path):
    service,job,_,_=prepared(tmp_path);old=FakeSimulator()
    from backend.orchestrator.workflow import Workflow
    workflow=Workflow(service.storage)
    with TestClient(create_app(workflow=workflow,simulator=old,current_vla_preview=service,preview_runtime=service.runtime)) as api:
        for body in ({'job_id':str(job.id),'path':'x'},{'trajectory':[[0,0,0]]},{},
                     {'job_id':str(job.id),'artifact_id':str(uuid4())}):
            assert api.post('/api/simulator/preview-current-vla',json=body).status_code==422
        assert api.post('/api/simulator/preview-current-vla?sample=old',json={'job_id':str(job.id)}).status_code==400
        assert api.post('/api/simulator/preview-current-vla',json={'job_id':str(job.id)},headers={'Origin':'https://untrusted.invalid'}).status_code==403
        assert not service.runtime.calls and not old.calls
        result=api.post('/api/simulator/preview-current-vla',json={'job_id':str(job.id)})
        assert result.status_code==202,result.text
        assert len(service.runtime.calls)==1 and old.calls==[]
        assert api.post('/api/simulator/preview-current-vla/path',json={'job_id':str(job.id)}).status_code==202
        assert read(service.runtime.calls[-1]['path'])['kind']=='path'
        assert api.post('/api/simulator/start',json={}).status_code==202
        old.status()
        assert api.post('/api/simulator/run-sample',json={}).status_code==202
        assert old.calls==['start','run']


def test_artifact_only_current_binding_cannot_replay_stale_job(tmp_path):
    service,job,result,_=prepared(tmp_path)
    claim=service.prepare(artifact_id=result.artifact_id)
    assert read(claim['path'])['job_id']==str(job.id)
    job.state=WorkflowState.MASK_READY;job.vla_prediction=None;service.storage.save_job(job)
    with pytest.raises(WorkflowError):service.prepare(artifact_id=result.artifact_id)


@pytest.mark.parametrize('result_valid',[True,False])
def test_owned_preview_queue_completion_and_cleanup(tmp_path,monkeypatch,result_valid):
    import sys
    from backend.services.current_preview_runtime import CurrentPreviewRuntime
    from backend.services.simulator_client import SimulatorConfig
    from tests.test_simulator import FakeProcess
    service,job,_,_=prepared(tmp_path);claim=service.prepare(job_id=job.id)
    monkeypatch.setattr('backend.services.current_preview_runtime.verify_preview',
        lambda c:verify_preview(c,project=service.settings.project))
    class Launcher:
        calls=[]
        def preview(self,python,root,manifest):
            self.calls.append(manifest);self.child=FakeProcess(123);return self.child
        def launch(self,*args,**kwargs):raise AssertionError('Existing sample script forbidden')
    launcher=Launcher()
    config=SimulatorConfig(root=service.settings.simulator_root,python=Path(sys.executable),sample_id='OLD_SAMPLE',
        data_root=tmp_path,prediction_root=tmp_path,runtime_dir=tmp_path/'runtime')
    runtime=CurrentPreviewRuntime(config,launcher=launcher,monitor=False)
    try:
        runtime.submit(claim)
        command=read(runtime.session/'queue'/(runtime.latest['request_id']+'.json'))
        assert command==dict(type='preview_current_vla',artifact_id=str(job.vla_prediction.artifact_id),mode='unvalidated',kind='robot')
        assert 'path' not in command and 'OLD_SAMPLE' not in json.dumps(command)
        with pytest.raises(WorkflowError):runtime.submit(claim)
        assert len(launcher.calls)==1
        runtime.ready_seen=True;runtime.tick()
        assert runtime.state=='RUNNING_PREVIEW'
        output=runtime.session/'outputs'/runtime.latest['request_id'];output.mkdir(parents=True)
        for name in ('scene.usda','P0.png','P8.png'):(output/name).write_bytes(b'x'*1200)
        result=dict(state='done',artifact_id=runtime.latest['artifact_id'],package_id=runtime.latest['package_id'],
            point_count=9,fixture_ready=False,physical_robot_executable=False,exact_xyz_preserved=result_valid,robot_motion=True)
        write(runtime.session/'results'/(runtime.latest['request_id']+'.json'),result)
        runtime.tick()
        assert runtime.state==('READY' if result_valid else 'FAILED')
        assert runtime.latest['status']==('SUCCEEDED' if result_valid else 'FAILED')
        if not result_valid:assert launcher.child.stopped
        assert len(launcher.calls)==1
    finally:
        runtime.close()
    assert launcher.child.stopped and runtime.lease is None


def test_preview_timeout_cancels_owned_tree_no_retry(tmp_path,monkeypatch):
    import sys
    from backend.services.current_preview_runtime import CurrentPreviewRuntime
    from backend.services.simulator_client import SimulatorConfig
    from tests.test_simulator import FakeProcess
    service,job,_,_=prepared(tmp_path);claim=service.prepare(job_id=job.id)
    monkeypatch.setattr('backend.services.current_preview_runtime.verify_preview',
        lambda c:verify_preview(c,project=service.settings.project))
    class Launcher:
        calls=0
        def preview(self,*args):self.calls+=1;self.child=FakeProcess(123);return self.child
    launcher=Launcher();clock=[0.]
    config=SimulatorConfig(root=service.settings.simulator_root,python=Path(sys.executable),sample_id='OLD_SAMPLE',
        data_root=tmp_path,prediction_root=tmp_path,runtime_dir=tmp_path/'runtime',startup_timeout=1)
    runtime=CurrentPreviewRuntime(config,launcher=launcher,clock=lambda:clock[0],monitor=False)
    try:
        runtime.submit(claim);clock[0]=2.;runtime.tick()
        assert runtime.state=='FAILED' and launcher.child.stopped and runtime.lease is None
        assert launcher.calls==1
    finally:runtime.close()
