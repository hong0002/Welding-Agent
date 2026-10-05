"""Focused endpoint and viewport tests: fake model/Kit, no network or Isaac."""
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import numpy as np
import pytest
import yaml
from fastapi.testclient import TestClient
from PIL import Image
from backend.schemas import UserEndpointRequest, VLAResultSummary, WorkflowState
from backend.services.user_endpoint import verify_endpoint, binding
from backend.services.simulator_final_live import NativeLiveCapture
from backend.model_clients.gpt2_endpoint_native import install_endpoint
from backend.model_clients.guided_workflow import conditioning_hash
from tests.test_gpt2_ricl_boundary import actual_native, query, NATIVE
from tests.test_preview_live import frames, packet
from tests.test_preview_capture import runtime_fixture
from tests.agent_fakes import FakeSimulator
from backend.agent.config import AgentSettings
from backend.main import create_app


def test_endpoint_binding_invalidation_keeps_mask_and_rough(query):
    wf,job,*_=query
    job.scene.sample_id='B_PR_03_0001'
    # The generic fake fixture is SAMPLE_1; isolate endpoint transitions from its
    # intentionally different native-sample evidence. Proof checks tested below.
    wf.get_job=wf.storage.get_job
    wf.guided_vla=SimpleNamespace(status=lambda:dict(source='vlm_final_gpt2'))
    wf.storage.save_job(job)
    before=conditioning_hash(job);mask=job.mask.model_dump();rough=job.rough3d.model_dump()
    after=wf.set_user_endpoint(job.id,[12.,13.,14.])
    assert after.user_endpoint.source=='user_selected_3d' and after.user_endpoint.units=='mm'
    assert verify_endpoint(after.model_dump(mode='json'))['end_xyz_mm']==[12.,13.,14.]
    assert before!=conditioning_hash(after) and after.mask.model_dump()==mask and after.rough3d.model_dump()==rough
    after.vla_prediction=VLAResultSummary(artifact_id=uuid4(),attempt_id=uuid4(),sample_id='B_PR_03_0001',split=job.scene.split,
        point_count=33,coordinate_frame='source_robot_frame_unaligned_with_isaac',source='vlm_final_gpt2',provider='gpt',mask_views=[])
    after.state=WorkflowState.VLA_READY;wf.storage.save_job(after)
    updated=wf.set_user_endpoint(job.id,[15.,16.,17.],'dataset_gt_endpoint')
    assert updated.vla_prediction is None and updated.raw_final_prediction is None and updated.user_endpoint.revision==2
    assert updated.mask.model_dump()==mask and updated.rough3d.model_dump()==rough
    assert updated.state==WorkflowState.ROUGH_PATH_READY and updated.previous_outputs[-1]['stage']=='prediction'
    corrupted=updated.model_dump(mode='json');corrupted['instruction']['text']='changed'
    with pytest.raises(ValueError,match='BINDING_CHANGED'):verify_endpoint(corrupted)


def test_no_endpoint_hash_unchanged_and_nonfinite_rejected(query):
    import hashlib
    _,job,*_=query
    data=job.model_dump(mode='json')
    legacy={k:data[k] for k in ('scene','mask','instruction','rough_mode','rough3d','rough_trajectory')}
    if job.native_output:legacy['native_output']=data['native_output']
    assert conditioning_hash(job)==hashlib.sha256(json.dumps(legacy,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    assert verify_endpoint(data) is None
    with pytest.raises(ValueError):UserEndpointRequest(end_xyz_mm=[1,float('nan'),2])


@pytest.mark.parametrize('source',['user_selected_3d','dataset_gt_endpoint'])
def test_native_both_requests_supplied_endpoint_no_gt_reads_or_snap(actual_native,query,monkeypatch,source):
    native=actual_native;_,_,_,stage,_,_=query;root,query_path,_=stage();dest=root/'endpoint';dest.mkdir()
    metadata=json.loads((query_path/'metadata.json').read_text());metadata['episode_id']='B_PR_03_0001'
    endpoint=dict(sample_id='B_PR_03_0001',end_xyz_mm=[20.,25.,28.],source=source,
        coordinate_frame='source_robot_frame_unaligned_with_isaac',binding_hash='fixture')
    def deny(*a,**kw):raise AssertionError('GT loader forbidden')
    monkeypatch.setattr(native,'endpoint_context',deny);monkeypatch.setattr(native.np,'load',deny)
    install_endpoint(native,endpoint)
    config=yaml.safe_load((NATIVE/'config.yaml').read_text(encoding='utf-8'));config['prediction_only']=True
    content,start,*_=native.input_content(query_path,dest,metadata,config)
    calls=[]
    def parse(**request):
        calls.append(request)
        return SimpleNamespace(output_parsed=native.Proposal(path_description='fixture',
            points=[dict(x=0,y=0,z=0),dict(x=4,y=2,z=3)],connections=['within_segment'],uncertainties=[]),
            model=config['model'],id='offline-'+str(len(calls)),usage=None)
    client=SimpleNamespace(responses=SimpleNamespace(parse=parse))
    rough=native.call_stage(client,config,content,'rough');corners=native.call_stage(client,config,content,'corners',rough)
    for call in calls:
        context=json.loads(call['input'][1]['content'][0]['text'])
        assert context['known_end_xyz_mm']==endpoint['end_xyz_mm'] and context['known_end_offset_mm']==[10.,5.,-2.]
        assert context['endpoint_source']==source and '987654321' not in json.dumps(call['input'])
    points,indices,modes=native.interpolate_corners([[0,0,0],[4,2,3]],['within_segment'],33)
    native.export(query_path,dest,metadata,start,points,modes,indices,['F'],{'rough':rough,'corners':corners},c=config)
    monkeypatch.undo()
    with np.load(dest/'trajectory.npz') as data:
        assert len(data['predicted_path_xyz'])==33
        assert np.array_equal(data['predicted_path_xyz'][-1],[14.,22.,33.])
        assert not np.array_equal(data['predicted_path_xyz'][-1],endpoint['end_xyz_mm'])
    meta=json.loads((dest/'metadata.json').read_text())
    assert meta['known_start_application_count']==1 and meta['xyz_posthoc_snapped'] is False
    assert meta['gt_endpoint_used_as_model_input']==(source=='dataset_gt_endpoint') and meta['gt_interior_path_used_as_model_input'] is False
    assert meta['end_error_mm']==pytest.approx(np.linalg.norm(np.array([14,22,33])-endpoint['end_xyz_mm']))


def test_native_live_observer_preserves_update_and_evidence(tmp_path):
    calls=[];callbacks=[]
    app=SimpleNamespace(update=lambda: calls.append('native'))
    original=app.update
    live=NativeLiveCapture(tmp_path,{},tmp_path/'stop.json',request_capture=callbacks.append)
    live.start(app);app.update();app.update()
    assert calls==['native','native'] and len(callbacks)==1 and live.producer.fps==4
    rgba=Image.new('RGBA',(80,60),'red').tobytes();callbacks[0](rgba,len(rgba),80,60,None)
    assert {p.name for p in (tmp_path/'live').iterdir()}=={'latest.jpg','status.json'}
    live.close();assert app.update is original
    app.update();assert calls[-1]=='native' and not live.producer.active


def test_final_polling_image_bound_no_frame_stop_and_stale(tmp_path,monkeypatch):
    runtime,client,_,_,_,_=runtime_fixture(tmp_path,monkeypatch)
    runtime.latest['backend']='dataset_final'
    from backend.orchestrator.workflow import Workflow
    url=f'/api/simulator/current-preview/live-frame/{runtime.session.name}/{runtime.latest["request_id"]}?job_id={runtime.latest["job_id"]}&artifact_id={runtime.latest["artifact_id"]}'
    with TestClient(create_app(workflow=Workflow(client.storage),simulator=FakeSimulator(),
        current_vla_preview=client,preview_runtime=runtime,agent_settings=AgentSettings(enabled=False))) as api:
        assert api.get(url).status_code==204
        p=frames(runtime)
        info=runtime.preview_frames(runtime.latest['job_id'],runtime.latest['artifact_id'])['live']
        assert info['delivery']=='polling' and info['image_url']==url and info['target_fps']==4
        response=api.get(url+'&version=123')
        assert response.status_code==200 and response.headers['content-type']=='image/jpeg'
        assert response.headers['x-frame-sequence']=='1' and response.headers['cache-control']=='no-store'
        assert api.get(url.replace(runtime.latest['artifact_id'],str(uuid4()))).status_code==409
        assert api.get(url,headers={'Origin':'https://foreign.invalid'}).status_code==403
        p.close();assert api.get(url).status_code==204
        runtime.stop();assert api.get(url).status_code==409
