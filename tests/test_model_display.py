"""Display availability never bypasses native acceptance. No live transport."""
import hashlib
import io
import json
from uuid import uuid4

from PIL import Image
import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.model_clients.contracts import ModelFault
from backend.model_clients.native import read_json, sha256
from backend.model_clients.model_display import read_path, read_masks, verified
from backend.orchestrator.state_machine import WorkflowError
from tests.agent_fakes import FakeSimulator
from tests.test_guided_vla import save
from tests.test_native_output_preview import factory, ready, change_guidance, assert_blocked


def plan_or_report(workflow,job):
    try:return workflow.plan(job.id)
    except ModelFault:return workflow.get_job(job.id)


@pytest.mark.parametrize('kind',['instruction','mask_id','region','direction','proximity','count','normalized','connected','reference','malformed_plan'])
def test_native_points_display_despite_acceptance_failure(factory,kind):
    before={}
    def change(directory):
        def mutate(data):
            g=data['image_guidance_2d'];s=g['segments'][0]
            if kind=='instruction':data['raw_instruction_ko']='different instruction'
            elif kind=='mask_id':s['source_mask_id']='F:unknown'
            elif kind=='region':data['plan']['segment_decisions']=[]
            elif kind=='direction':data['plan']['segment_decisions'][0]['direction']='reverse'
            elif kind=='proximity':
                s['points_pixel']=[[10.+i*10,70.] for i in range(9)]
                s['points_normalized']=[[x/100,y/100] for x,y in s['points_pixel']]
            elif kind=='count':g['actual_point_count']=99
            elif kind=='normalized':s['points_normalized'][0]=[.9,.9]
            elif kind=='connected':s['connected_to_next']=True
            elif kind=='reference':data['rough_trajectory_3d']['segments'][0]['points_xyz_mm'][0][0]+=1
        change_guidance(directory,mutate)
        if kind=='malformed_plan':(directory/'iteration_001/plan.json').write_text('{')
        before.update({p.relative_to(directory).as_posix():sha256(p) for p in directory.rglob('*') if p.is_file()})
    w,transport,calls=factory(rough_output_transform=change)
    job=plan_or_report(w,ready(w));d=job.native_output.model_output
    assert d.displayable and d.overlay_allowed and d.point_count==9
    assert d.status=='OUTPUT_RAW_DISPLAYABLE' and not d.guided_vla_allowed
    assert job.native_output.validation.status=='FAIL' and not job.rough3d
    assert_blocked(w,transport,job)
    from pathlib import Path
    directory=Path(w.rough3d.runtime.last_display_capture['directory'])
    assert all(sha256(directory/name)==digest for name,digest in before.items())
    assert len(calls['rough3d'])==1


def test_valid_display_keeps_existing_accepted_gate(factory):
    w,transport,_=factory();job=w.plan(ready(w).id);d=job.native_output.model_output
    assert d.status=='OUTPUT_VALIDATED' and d.point_count==9 and d.guided_vla_allowed
    assert not d.simulator_allowed and not job.vla_prediction
    w.verify_native_output(w.get_job(job.id))
    assert not transport.calls and transport.health_calls==0


def test_partial_finite_points_break_lines_without_reordering(factory):
    expected={}
    def change(directory):
        def mutate(data):
            points=data['image_guidance_2d']['segments'][0]['points_pixel']
            expected['original']=points.copy()
            points[2]=[float('nan'),20.];points[5]=[float('inf'),20.]
        change_guidance(directory,mutate)
    w,t,_=factory(rough_output_transform=change);job=plan_or_report(w,ready(w));d=job.native_output.model_output
    assert d.point_count==7 and d.omitted_point_count==2 and d.partial
    runs=d.segments[0].runs
    assert [len(r) for r in runs]==[2,2,3]
    assert [p for run in runs for p in run]==[tuple(p) for i,p in enumerate(expected['original']) if i not in (2,5)]
    assert_blocked(w,t,job)


@pytest.mark.parametrize('kind',['nan','frame','no_geometry'])
def test_hard_display_failure_only_minimal_renderability(factory,kind):
    def change(directory):
        def mutate(data):
            g=data['image_guidance_2d']
            if kind=='nan':g['segments'][0]['points_pixel']=[[float('nan'),20.]]*9
            elif kind=='frame':g['coordinate_frame_pixel']='robot_mm'
            else:g['segments']=[]
        change_guidance(directory,mutate)
    w,t,_=factory(rough_output_transform=change);job=plan_or_report(w,ready(w))
    assert job.native_output.model_output.available and not job.native_output.model_output.displayable
    assert_blocked(w,t,job)


def test_missing_size_can_use_bound_current_scene_dimensions_for_display_only(factory):
    def change(directory):change_guidance(directory,lambda d:d['image_guidance_2d'].pop('image_size'))
    w,t,_=factory(rough_output_transform=change);job=plan_or_report(w,ready(w));d=job.native_output.model_output
    assert d.displayable and d.width==100 and d.height==100
    assert 'DISPLAY_DIMENSIONS_FROM_SCENE' in d.warnings
    assert_blocked(w,t,job)


def test_foreign_sample_is_only_diagnostic_and_new_job_has_no_layers(factory):
    def change(directory):change_guidance(directory,lambda data:data.update(sample_id='OTHER_SAMPLE'))
    w,t,_=factory(rough_output_transform=change);job=plan_or_report(w,ready(w));d=job.native_output.model_output
    assert d.displayable and not d.overlay_allowed and d.sample_id=='OTHER_SAMPLE'
    assert 'FOREIGN_OR_STALE_MODEL_OUTPUT' in d.warnings
    fresh=w.load_sample('SAMPLE_1')
    assert not fresh.native_output and not fresh.raw_segment_output
    assert w.get_job(job.id).native_output.model_output.displayable
    assert_blocked(w,t,job)


def test_clarification_without_geometry_has_no_fabricated_path(factory):
    from tests.test_trajectory_clarification import clarification_output
    def clarification_only(directory):
        clarification_output(directory)
        (directory/'query_image_guidance_2d.json').unlink(missing_ok=True)
    w,t,_=factory(rough_output_transform=clarification_only);job=plan_or_report(w,ready(w))
    assert job.trajectory_clarification
    assert not job.native_output.model_output.displayable
    assert job.native_output.model_output.point_count==0
    assert_blocked(w,t,job)


@pytest.mark.parametrize('kind',['valid','instruction','nonbinary','empty','foreign','malformed','polygon'])
def test_segment_display_and_accepted_slot_are_separate(factory,kind):
    phase={'mutate':False}
    def change(directory):
        if not phase['mutate']:return
        data=read_json(directory/'iteration_001/result.json')
        if kind=='instruction':data['instruction']='mismatch'
        elif kind=='foreign':data['sample_id']='FOREIGN'
        elif kind=='nonbinary':Image.new('L',(100,100),128).save(directory/'iteration_001/F_prediction.png')
        elif kind=='empty':Image.new('L',(100,100),0).save(directory/'iteration_001/F_prediction.png')
        elif kind in ('malformed','polygon'):
            for view in ('F','R','S4'):
                data['predictions'][view]={}
                if kind=='malformed':(directory/f'iteration_001/{view}_prediction.png').write_bytes(b'broken')
                else:
                    (directory/f'iteration_001/{view}_prediction.png').unlink()
                    data['predictions'][view]={'polygons':[{'points':[[10,10],[30,10],[30,30]]}]}
        save(directory/'iteration_001/result.json',data)
    w,t,calls=factory(segment_output_transform=change)
    old=ready(w);old_id=old.mask.id;old_at=old.mask.approved_at
    phase['mutate']=True
    if kind=='valid':job=w.set_mask(old.id)
    else:
        with pytest.raises(ModelFault):w.set_mask(old.id)
        job=w.get_job(old.id)
        assert job.mask.id==old_id and job.mask.approved_at==old_at
    output=job.raw_segment_output;d=output.model_output
    assert d.available
    assert d.displayable == (kind!='malformed')
    assert d.overlay_allowed == (kind!='foreign')
    assert output.validation.status==('PASS' if kind=='valid' else 'FAIL')
    assert not d.guided_vla_allowed and not d.simulator_allowed
    if kind=='valid':
        assert not job.mask.approved and job.mask.id!=old_id
        job=w.approve_mask(job.id,job.mask.id,'F')
        assert job.mask.approved
    if d.displayable:
        with TestClient(create_app(workflow=w,simulator=FakeSimulator())) as api:
            response=api.get(d.mask_urls['F']);assert response.status_code==200
            assert Image.open(io.BytesIO(response.content)).size==(100,100)
            assert api.get(f'/api/weld/{job.id}/model-output/segment/../../image').status_code==404
    assert not t.calls and not t.health_calls and len(calls['segment'])==2


def test_raw_edit_requires_current_output_identity_and_binary_human_save(factory):
    def change(directory):
        data=read_json(directory/'iteration_001/result.json');data['instruction']='mismatch';save(directory/'iteration_001/result.json',data)
    w,t,_=factory(segment_output_transform=change);job=w.load_sample('SAMPLE_1')
    with pytest.raises(ModelFault):w.set_mask(job.id)
    job=w.get_job(job.id);raw_id=job.raw_segment_output.native_artifact_id
    mask=Image.new('L',(100,100));mask.putpixel((20,20),255)
    buffer=io.BytesIO();mask.save(buffer,format='PNG')
    with pytest.raises(WorkflowError):w.set_mask(job.id,buffer.getvalue(),view_id='F',edited_from_raw_output_id=uuid4())
    # A sufficient region is created through an explicit human save only.
    from PIL import ImageDraw
    ImageDraw.Draw(mask).rectangle((10,10,30,30),fill=255);buffer=io.BytesIO();mask.save(buffer,format='PNG')
    edited=w.set_mask(job.id,buffer.getvalue(),view_id='F',edited_from_raw_output_id=raw_id)
    assert edited.mask.approved and edited.mask.mask_source=='manual_edited'
    assert edited.mask.artifact.provenance.native_source_artifact_id==raw_id
    assert not edited.rough3d and not edited.vla_prediction and not t.calls


def test_display_snapshot_tampering_is_safe_and_never_admits(factory):
    w,t,_=factory();job=w.plan(ready(w).id)
    _,folder=verified(w.storage,job,job.native_output,'trajectory')
    (folder/'display.json').write_text('{}')
    shown=w.get_job(job.id)
    assert not shown.native_output.model_output.displayable
    assert shown.native_output.model_output.warnings==['DISPLAY_EVIDENCE_INVALID']
    with pytest.raises(ModelFault):w.run_guided_vla(job.id)
    assert not t.calls and not t.health_calls


def test_segment_display_snapshot_hash_and_job_binding(factory):
    w,t,_=factory();job=w.set_mask(w.load_sample('SAMPLE_1').id)
    d,folder=verified(w.storage,job,job.raw_segment_output,'segment')
    before=sha256(folder/'F.png')
    foreign=w.load_sample('SAMPLE_1');foreign.raw_segment_output=job.raw_segment_output
    w.storage.save_job(foreign)
    assert not w.get_job(foreign.id).raw_segment_output.model_output.displayable
    (folder/'F.png').write_bytes(b'changed')
    shown=w.get_job(job.id)
    assert shown.raw_segment_output.validation.status=='FAIL'
    assert not shown.raw_segment_output.model_output.displayable
    assert shown.mask.id==job.mask.id and not t.calls


def test_old_native_proof_is_display_compatible_without_weakening_acceptance(factory):
    w,t,_=factory();job=w.plan(ready(w).id)
    proof_path=w.storage.artifact_path('native_context',job.native_output.native_artifact_id,'.native-output.json')
    proof=read_json(proof_path)
    proof['output_sha256']=hashlib.sha256(job.native_output.model_dump_json(exclude={'model_output'}).encode()).hexdigest()
    save(proof_path,proof)
    job.native_output.model_output=None;job.raw_segment_output=None
    w.storage.save_job(job)
    current=w.get_job(job.id)
    assert current.native_output.model_output.displayable
    assert current.native_output.status=='NATIVE_OUTPUT_VALIDATED'
    w.verify_native_output(current)
    assert current.raw_segment_output.model_output.displayable
    assert not t.calls


def test_agent_hard_output_summary_never_contains_raw_geometry(factory):
    import asyncio
    from backend.agent.context import WeldingAgentContext
    from tests.agent_fakes import invoke
    def change(directory):change_guidance(directory,lambda d:d.update(raw_instruction_ko='different'))
    w,t,_=factory(rough_output_transform=change);job=ready(w)
    context=WeldingAgentContext(job.id,'offline','용접 경로 생성해줘',w,FakeSimulator(),lambda *_:None)
    async def run():
        await invoke(context,'get_workspace_state')
        result=await invoke(context,'create_current_weld_plan')
        assert result['native_output_generated'] and result['displayable'] and result['point_count']==9
        assert result['validation_status']=='FAIL' and not result['guided_vla_allowed']
        assert all(k not in json.dumps(result) for k in ('points_pixel','runs','segments','source_session','HIDDEN_PRIVATE','D:\\'))
    asyncio.run(run())
    assert not t.calls and not t.health_calls


def test_invalid_question_lineage_does_not_hide_partial_geometry_on_public_read(factory):
    from tests.test_trajectory_clarification import clarification_output
    w,t,_=factory(rough_output_transform=clarification_output);job=plan_or_report(w,ready(w))
    job.trajectory_clarification.question='HIDDEN_PRIVATE_TEXT';w.storage.save_job(job)
    with pytest.raises(WorkflowError):w.get_job(job.id)
    with TestClient(create_app(workflow=w,simulator=FakeSimulator())) as api:
        response=api.get(f'/api/weld/{job.id}')
    assert response.status_code==200
    result=response.json()
    assert result['native_output']['model_output']['displayable']
    assert not result['trajectory_clarification']
    assert 'HIDDEN_PRIVATE_TEXT' not in response.text
    assert not result['native_output']['model_output']['guided_vla_allowed']
    assert not t.calls and not t.health_calls
