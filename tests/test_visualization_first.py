"""Visualization policy regressions. All models, SDK and process transport fake."""
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import numpy as np
import pytest
from backend.model_clients.geometry_display import finite_runs,output_geometry,presentation
from backend.model_clients.gpt_trajectory import GPTTrajectoryPredictor
from backend.model_clients.gpt_trajectory_entry import capture_stage,visualization_start
from backend.model_clients.gpt_trajectory_retrieval import prepare_visualization_examples
from backend.orchestrator.state_machine import StateMachine
from backend.services.geometry_preview import GeometryPreviewService,verify,CODE
from backend.services.output_catalog import catalog
from tests.test_gpt_trajectory import setup,save


def stage(points,connections=None):return dict(proposal=dict(points=points,connections=connections or ['within_segment']))


@pytest.mark.parametrize('dimensions',[2,3])
def test_nonfinite_breaks_never_bridge(dimensions):
    points=[[i]*dimensions for i in range(5)];points[2][0]=float('nan')
    runs,omitted=finite_runs(points,dimensions)
    assert [len(r) for r in runs]==[2,2] and omitted==1


def test_unknown_or_between_segment_edges_never_connect():
    runs,_=finite_runs([[0,0,0],[1,1,1],[2,2,2]],connections=['between_segments','unknown'])
    assert list(map(len,runs))==[1,1,1]


@pytest.mark.parametrize('text',[
    '{"points":[[0,1,2],[3,4,5]],"extra":"ignored"}',
    '{"proposal":{"points":[{"x":0,"y":1,"z":2},{"x":3,"y":4,"z":5}]}}',
    '{"points":[[0,1,2],[3,4,5]',
])
def test_malformed_schema_keeps_only_explicit_xyz(text):
    assert finite_runs(output_geometry(text))[0]==[[[0,1,2],[3,4,5]]]
    assert not output_geometry('secret prompt xyz 0 1 2')


def test_sdk_parse_failure_capture_does_not_read_hidden_reasoning(tmp_path):
    visible=SimpleNamespace(type='message',content=[SimpleNamespace(type='output_text',text='{"points":[[0,0,0],[1,2,3]]}')])
    response=SimpleNamespace(output=[SimpleNamespace(type='reasoning',summary='SECRET'),visible])
    def post(*a,**kw):return kw['options']['post_parser'](response)
    resource=SimpleNamespace(_post=post);client=SimpleNamespace(responses=resource)
    def parse(*a):
        def fail(r):raise ValueError('secret SDK exception')
        resource._post('/responses',options={'post_parser':fail})
    native=SimpleNamespace(call_stage=parse,write_json=save)
    with pytest.raises(ValueError):capture_stage(client,native,{},[],'rough',None,{},tmp_path)
    text=(tmp_path/'raw_partial_rough.json').read_text()
    assert 'SECRET' not in text and 'secret' not in text and 'points' in text
    assert resource._post is post


@pytest.mark.parametrize('fails', [[],['segment2_adapter'],['segment2_adapter','local']])
def test_retrieval_fallback_chain_once_per_mode(tmp_path,fails):
    calls=[]
    def prepare(*a,mode,**kw):
        calls.append(mode)
        if mode in fails:raise ValueError('private SSH detail')
        return [],dict(mode=mode)
    _,proof=prepare_visualization_examples({},tmp_path,'S','i',{}, {},tmp_path,query=None,
        mode='segment2_adapter',segment_config=None,prepare=prepare)
    assert calls==['segment2_adapter','local','none'][:len(fails)+1]
    assert proof['visualization_only']==bool(fails)
    assert 'private' not in json.dumps(proof)


def test_rough_survives_bad_corners_and_stages_are_separate(setup,tmp_path):
    wf,job,client,_,_=setup;a=client.settings.attempts/str(uuid4());a.mkdir(parents=True)
    save(a/'rough.json',stage([[0,0,0],[1,2,3]]))
    save(a/'corners.json',stage([[float('nan')]*3]))
    d=client.capture_display(a,uuid4(),job)
    assert d.displayable and d.point_count==2 and d.stages==['GPT Rough','GPT Corners']
    job.raw_final_prediction=d
    v=client.read_display(wf.storage,job,d.artifact_id)
    assert v['runs']==[[[0,0,0],[1,2,3]]]


def test_catalog_reports_invalid_display_copy_without_generic_failure(setup):
    from backend.model_clients.guided_vla import GuidedVLAError
    wf,job,client,_,_=setup
    job=wf.run_final_trajectory_prediction(job.id)
    def invalid(*args):raise GuidedVLAError('FINAL_TRAJECTORY_DISPLAY_STALE')
    rows=catalog(wf.storage,job,SimpleNamespace(read_display=invalid))['outputs']
    row=next(r for r in rows if r['stage']=='final')
    assert row['states']['OUTPUT_EXISTS'] and not row['states']['OUTPUT_RENDERABLE']
    assert row['warnings']==['DISPLAY_EVIDENCE_INVALID']


def test_upstream_edit_archives_result_and_viewer_cannot_overlay(setup):
    wf,job,client,fake,_=setup;job=wf.run_final_trajectory_prediction(job.id)
    artifact=job.raw_final_prediction.artifact_id
    changed=wf.parse_instruction(job.id,'오른쪽에서 왼쪽으로 용접해')
    assert not changed.raw_final_prediction and not changed.vla_prediction
    value=client.read_display(wf.storage,changed,artifact)
    assert value['stale'] and not value['current_overlay_allowed'] and value['runs']
    rows=catalog(wf.storage,changed,client)['outputs']
    assert any(r['id']==str(artifact) and r['states']['OUTPUT_RENDERABLE'] and r['stale'] for r in rows)
    assert len(fake.calls)==1


def test_relative_geometry_package_no_robot_or_workpiece_alignment(setup,tmp_path,monkeypatch):
    wf,job,client,fake,_=setup;fake.change='partial';job=wf.run_final_trajectory_prediction(job.id)
    assert job.raw_final_prediction.coordinate_mode=='relative_visualization' and not job.vla_prediction
    for name in CODE:
        file=tmp_path/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('offline renderer fixture')
    runtime=SimpleNamespace(config=SimpleNamespace(root=tmp_path/'readonly-simulator'),backend='dataset_stp')
    service=GeometryPreviewService(wf,runtime,project=tmp_path)
    claim=service.prepare(job.id);path=Path(claim['path']);descriptor=json.loads(path.read_text())
    d,value,_=verify(descriptor,path,tmp_path)
    assert d['geometry_only'] and not d['robot_ready'] and not d['physical_robot_executable']
    assert value['runs'] and 'source_to_scene' not in d and 'h5' not in d
    StateMachine.replace_instruction(job);wf.storage.save_job(job)
    with pytest.raises(ValueError,match='stale'):verify(descriptor,path,tmp_path)


@pytest.mark.parametrize('warning',['IK_FAIL','WORKSPACE_WARNING','VALIDATION_FAIL','APPROVAL_MISSING'])
def test_common_state_does_not_hide_geometry(warning):
    states=presentation(exists=True,renderable=True,simulation=True)
    assert states['OUTPUT_RENDERABLE'] and states['SIMULATION_DISPLAYABLE']
    assert not states['OUTPUT_VALIDATED'] and not states['OUTPUT_APPROVED'] and not states['ROBOT_PLAYBACK_READY']
    assert not states['physical_robot_executable']
