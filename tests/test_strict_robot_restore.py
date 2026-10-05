"""Reuse native strict playback with fake IK/transport, no models or Isaac."""
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.model_clients.guided_workflow import conditioning_hash
from backend.model_clients.gpt_trajectory import GPTTrajectoryPredictor
from backend.orchestrator.workflow import Workflow
from backend.schemas import WorkflowState
from backend.services.robot_demo import RobotPreview
from backend.services.current_preview_config import CurrentPreviewError
from backend.services.current_preview_gate import read,sha,verify_preview
from tests.test_simulator_stp_client import fixture
from tests.test_gpt_simulator_handoff import gpt_fixture
from tests.test_gpt_trajectory import save


@pytest.mark.parametrize('provider',['guided','gpt'])
def test_absolute_strict_without_cached_readiness_or_demo(tmp_path,provider,monkeypatch):
    client,job,attempt=(gpt_fixture if provider=='gpt' else fixture)(tmp_path)
    count=33 if provider=='gpt' else 9
    artifact=str(job.vla_prediction.artifact_id)
    with np.load(attempt/'trajectory.npz') as a:points=a['predicted_path_m'].tolist()
    row=dict(id=artifact,stage='prediction',label=provider,runs=[points],units='m',coordinate_frame='source_robot_frame_unaligned_with_isaac',sample_id=job.scene.sample_id,stale=False)
    monkeypatch.setattr('backend.services.output_catalog.xyz_output',lambda *a,**kw:row)
    before=sha(attempt/'trajectory.npz')
    assert not client.capabilities(job_id=job.id)['robot_preview_ready']
    preview=RobotPreview(Workflow(client.storage),client.runtime,client,project=client.settings.project,
        prepare=lambda *_:pytest.fail('Absolute trajectory must not enter Demo preparation'))
    result=preview.run(job.id,artifact)
    assert result['mode']=='STRICT' and len(client.builder.calls)==len(client.runtime.calls)==1
    d,p,file=verify_preview(client.runtime.calls[0],project=client.settings.project)
    assert d['point_count']==count and d['backend']=='dataset_stp' and d['kind']=='robot'
    assert file.read_bytes()==(attempt/'trajectory.npz').read_bytes() and sha(attempt/'trajectory.npz')==before
    assert not d.get('robot_demo_only') and d['physical_robot_executable'] is False
    assert Path(p['h5']).stem==Path(p['obj']).stem==job.scene.sample_id
    assert d['orientation_source']=='simulator_stp_policy' and d['native_layout']=='stp'


def raw_gpt(tmp_path):
    client,job,old=gpt_fixture(tmp_path)
    artifact=job.vla_prediction.artifact_id
    attempt=client.settings.project/'.cache/native-models/gpt-trajectory'/old.name
    attempt.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(old),str(attempt))
    job.vla_prediction=None;job.state=WorkflowState.ROUGH_PATH_READY
    job.mask.approved=False;job.mask.approved_at=None
    save(attempt/'source_job.json',job.model_dump(mode='json'))
    manifest=read(attempt/'request_manifest.json')
    manifest.update(source_job=str(attempt/'source_job.json'),source_job_sha256=sha(attempt/'source_job.json'),
                    workflow_conditioning_sha256=conditioning_hash(job),approved_at=None,mask_views=['F','R','S4'],visualization_only=True)
    save(attempt/'request_manifest.json',manifest)
    (attempt/'completion.json').unlink() # Existing display-only lifecycle has no approval completion.
    job.raw_final_prediction=GPTTrajectoryPredictor.capture_display(attempt,artifact,job)
    client.storage.save_job(job)
    return client,job,attempt


def test_unapproved_multiview_absolute_gpt_uses_same_strict_package(tmp_path):
    client,job,attempt=raw_gpt(tmp_path)
    before={p:sha(p) for p in attempt.glob('*') if p.is_file()}
    claim=client.prepare(job_id=job.id,artifact_id=job.raw_final_prediction.artifact_id,kind='robot')
    d,p,file=verify_preview(claim,project=client.settings.project)
    assert d['visualization_source'] and d['source_point_count']==33 and d['playback_point_count']==65
    assert not d.get('robot_demo_only') and p['orientation_source']=='simulator_stp_policy'
    assert file.read_bytes()==(attempt/'trajectory.npz').read_bytes()
    assert all(sha(f)==h for f,h in before.items()) and not (attempt/'completion.json').exists()
    current=client.storage.get_job(job.id)
    assert not current.mask.approved and current.vla_prediction is None
    assert current.raw_final_prediction.validation_status=='FAIL' # No promotion disguised as simulation.
    with np.load(file) as arrays:
        np.testing.assert_array_equal(arrays['predicted_path_m'],np.asarray(read(attempt/'response.json')['predicted_path_xyz_mm'])*.001)


def test_strict_native_failure_does_not_scale_or_retry_demo(tmp_path,monkeypatch):
    client,job,attempt=fixture(tmp_path)
    row=dict(id=str(job.vla_prediction.artifact_id),runs=[[[1,2,3],[2,3,4]]],coordinate_frame='source_robot_frame_unaligned_with_isaac',sample_id=job.scene.sample_id,stale=False)
    monkeypatch.setattr('backend.services.output_catalog.xyz_output',lambda *a,**kw:row)
    def fail(**_):raise CurrentPreviewError('SIMULATOR_STP_IK_FAIL','Native IK failed.',409)
    monkeypatch.setattr(client,'run',fail)
    robot=RobotPreview(Workflow(client.storage),client.runtime,client,prepare=lambda *_:pytest.fail('No Demo retry'))
    with pytest.raises(CurrentPreviewError,match='Native IK failed'):robot.run(job.id)
    assert not client.builder.calls and not client.runtime.calls
