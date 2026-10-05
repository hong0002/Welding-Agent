"""Existing fake completed artifact -> immutable GPT33 -> fake native STP only."""
import json
import pytest
import numpy as np
from backend.schemas import VLAResultSummary
from backend.model_clients.guided_workflow import conditioning_hash
from backend.services.current_preview_gate import verify_preview
from backend.services.simulator_prediction_package import read,sha
from backend.services.current_preview_config import CurrentPreviewError
from tests.test_simulator_stp_client import fixture
from tests.test_gpt_trajectory import response,save


def gpt_fixture(tmp_path):
    client,job,attempt=fixture(tmp_path)
    old=read(attempt/'request_manifest.json')
    h5,obj=client.settings.dataset_root/'unused',client.settings.dataset_root/'unused'
    from backend.services.simulator2_contract import exact_assets
    h5,obj=exact_assets(client.settings.dataset_root,job.scene.sample_id)
    r=response(job.scene.sample_id,job.scene.split,str(job.vla_prediction.artifact_id),h5)
    save(attempt/'response.json',r)
    np.savez_compressed(attempt/'trajectory.npz',predicted_path_m=np.asarray(r['predicted_path_xyz_mm'])*.001,
                        ground_truth_path_m=np.asarray(r['ground_truth_path_xyz_mm'])*.001)
    job.vla_prediction=VLAResultSummary(artifact_id=job.vla_prediction.artifact_id,attempt_id=job.vla_prediction.attempt_id,
        sample_id=job.scene.sample_id,split=job.scene.split,model='gpt-6-luna',point_count=33,source='vlm_final_gpt',provider='gpt',
        coordinate_frame=r['coordinate_frame'],ade_mm=r['ade_mm'],fde_mm=r['fde_mm'],mask_views=['F'])
    client.storage.save_job(job);save(attempt/'source_job.json',job.model_dump(mode='json'))
    old.update(backend='gpt',source='vlm_final_gpt',provider='gpt',artifact_id=str(job.vla_prediction.artifact_id),
        sample_id=job.scene.sample_id,split=job.scene.split,workflow_conditioning_sha256=conditioning_hash(job),
        source_job_sha256=sha(attempt/'source_job.json'),h5=str(h5),h5_sha256=sha(h5),obj=str(obj),obj_sha256=sha(obj))
    save(attempt/'request_manifest.json',old)
    save(attempt/'metadata.json',dict(artifact_id=str(job.vla_prediction.artifact_id),attempt_id=attempt.name,
        episode_id=job.scene.sample_id,split=job.scene.split,source='vlm_final_gpt',provider='gpt',coordinate_frame=r['coordinate_frame'],
        source_units='mm',scale_to_meters=.001,is_robot_executable=False,vla_orientation=False))
    save(attempt/'process_exit.json',{'exit_code':0})
    save(attempt/'completion.json',dict(attempt_id=attempt.name,response_validated=True,
        files={name:sha(attempt/name) for name in ('response.json','trajectory.npz','metadata.json')}))
    client.storage._write_json(client.storage.artifact_path('native_context',job.vla_prediction.artifact_id,'.vla.json'),json.dumps(dict(
        job_id=str(job.id),attempt_id=attempt.name,directory=str(attempt),
        files={name:sha(attempt/name) for name in ('request_manifest.json','source_job.json','response.json','trajectory.npz','metadata.json','completion.json','process_exit.json')})))
    return client,job,attempt


@pytest.mark.parametrize('kind',['path','robot'])
def test_gpt_source_33_preserved_through_stp_native_playback(tmp_path,kind):
    client,job,attempt=gpt_fixture(tmp_path)
    before=sha(attempt/'trajectory.npz')
    assert client.capabilities(job_id=job.id)['source_point_count']==33 and not client.builder.calls
    claim=client.prepare(job_id=job.id,kind=kind)
    d,p,file=verify_preview(claim,project=client.settings.project)
    assert d['source_point_count']==p['point_count']==33 and d['playback_point_count']==65
    assert p['prediction_source']==d['prediction_source']=='vlm_final_gpt'
    assert file.read_bytes()==(attempt/'trajectory.npz').read_bytes() and sha(attempt/'trajectory.npz')==before
    assert d['vla_orientation'] is False and d['orientation_source']=='simulator_stp_policy'
    assert d['physical_robot_executable'] is False and d['simulation_only']
    assert not client.runtime.calls and len(client.builder.calls)==1


@pytest.mark.parametrize('change',['failed','sample','mask','gt','npz'])
def test_gpt_invalid_artifact_blocks_before_native_or_isaac(tmp_path,change):
    client,job,attempt=gpt_fixture(tmp_path)
    if change=='failed':save(attempt/'completion.json',{'response_validated':False})
    if change=='sample':job.scene.sample_id='B_PP_03_0002';client.storage.save_job(job)
    if change=='mask':job.mask.approved_at=job.mask.approved_at.replace(year=2025);client.storage.save_job(job)
    if change=='gt':save(attempt/'response.json',{'sample_id':job.scene.sample_id})
    if change=='npz':(attempt/'trajectory.npz').write_bytes(b'broken')
    with pytest.raises(CurrentPreviewError):client.prepare(job_id=job.id,kind='path')
    assert not client.builder.calls and not client.runtime.calls


@pytest.mark.parametrize('source,count,dtype',[('guided_vla',9,np.float32),('vlm_final_gpt',33,np.float64)])
def test_renderer_numeric_gate_preserves_source_and_no_isaac_import(source,count,dtype):
    import sys
    from backend.current_vla_isaac_preview import validate_prediction_array
    before=set(sys.modules);points=np.zeros((count,3),dtype=dtype)
    assert validate_prediction_array(points,{'point_count':count,'prediction_source':source,'backend':'dataset_stp'})==count
    assert not any(n.startswith(('isaacsim','omni')) for n in set(sys.modules)-before)
    with pytest.raises(ValueError):validate_prediction_array(points,{'point_count':count+1,'prediction_source':source,'backend':'dataset_stp'})
