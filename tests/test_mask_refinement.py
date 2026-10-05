"""Actual adapter/Workflow, SDK-shaped fakes. Never launch native or call OpenAI."""
import base64
from io import BytesIO
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from backend.model_clients.contracts import ModelFault
from backend.model_clients.native import read_json,sha256
from backend.model_clients.guided_workflow import conditioning_hash
from backend.orchestrator.state_machine import WorkflowError
from tests.test_semantic_workflow import native,turn


@pytest.fixture(autouse=True)
def no_live(monkeypatch):
    import openai,subprocess
    def forbidden(*args,**kwargs):raise AssertionError('Live transport/process forbidden')
    monkeypatch.setattr(openai,'OpenAI',forbidden);monkeypatch.setattr(openai,'AsyncOpenAI',forbidden)
    monkeypatch.setattr(subprocess,'Popen',forbidden)


def manual(w,job):
    current=w.storage.read_image('masks',job.mask.id)
    current.paste(0,(0,0,50,100))
    stream=BytesIO();current.save(stream,format='PNG')
    return w.set_mask(job.id,stream.getvalue(),view_id='F',edited_from_mask_id=job.mask.id,require_review=True)


def test_current_edited_input_minimal_payload_lineage_and_unapproved_draft(native):
    w,transport,calls,job=native
    job=manual(w,job);parent=job.mask
    before=w.storage.read_image('masks',parent.id)
    parent_path=w.storage.artifact_path('masks',parent.id);parent_hash=sha256(parent_path)
    rgb=w._scene_image(job,'F')
    instruction='현재 수정한 마스크 기준으로 매끈하게 보정해줘'
    refined=w.refine_mask(job.id,instruction=instruction)
    assert refined.id==job.id and refined.scene.id==job.scene.id and refined.scene.sample_id=='SAMPLE_1'
    assert refined.scene.split==job.scene.split
    assert refined.mask.mask_source=='ai_refined' and refined.mask.id!=parent.id
    assert refined.mask.edited_from_mask_id==parent.id
    assert not refined.mask.approved and refined.mask.approved_at is None
    assert refined.mask.artifact.provenance.source_scene_id==job.scene.id
    assert refined.mask.artifact.provenance.source_mask_id==parent.id
    assert sha256(parent_path)==parent_hash
    process=w.segmentation.refinement_fixture
    assert len(process.payloads)==len(calls['refine'])==1
    payload=process.payloads[0]
    assert payload['model']=='offline' and payload['store'] is False
    content=payload['input'][1]['content']
    images=[c for c in content if c['type']=='input_image']
    assert len(images)==2 and instruction in content[0]['text']
    for spec,expected in zip(images,[rgb.convert('RGB'),before]):
        actual=Image.open(BytesIO(base64.b64decode(spec['image_url'].split(',')[1])))
        assert actual.size==expected.size and actual.tobytes()==expected.tobytes()
        assert not actual.info
    text=json.dumps(payload['input'])
    assert 'SAMPLE_1' not in text and str(w.storage.root) not in text
    assert not any(x in text for x in ('.h5','.obj','retrieval','yolo/detections','DO NOT STORE THIS NOTE'))
    result=w.segmentation.last_result
    manifest=read_json(result.directory/'input_manifest.json')
    assert manifest['operation']=='MASK_REFINE' and manifest['job_id']==str(job.id)
    assert manifest['scene_id']==str(job.scene.id) and manifest['source_mask_id']==str(parent.id)
    assert manifest['source_mask_pixels_sha256']==__import__('hashlib').sha256(before.tobytes()).hexdigest()
    assert manifest['reference_in_request'] is False
    assert not (result.directory/'retrieval.json').exists()
    record=read_json(w.segmentation.runtime.records/f'{result.artifact_id}.json')
    assert record['exit_code']==0
    assert record['files']['iteration_001/F_prediction.png']==sha256(result.directory/'iteration_001/F_prediction.png')
    assert 'note' not in read_json(result.directory/'iteration_001/result.json')['predictions']['F']
    assert refined.raw_segment_output.validation.status=='PASS'
    assert refined.raw_segment_output.model_output.mask_urls.keys()=={'F'}
    assert len(calls['segment'])==1 and not calls['rough3d'] and not transport.calls
    with pytest.raises(WorkflowError):w.parse_instruction(job.id,'위에서 아래로 용접해')


@pytest.mark.parametrize('mode,code,raw_png',[
    ('restore','MASK_REFINEMENT_CONSTRAINT_VIOLATION',True),
    ('malformed','MASK_REFINEMENT_OUTPUT_INVALID',False),
    ('empty','MASK_REFINEMENT_EMPTY_MASK',True),
    ('partial','MASK_REFINEMENT_OUTPUT_PARTIAL',True),
    ('foreign_camera','MASK_REFINEMENT_OUTPUT_INVALID',False),
    ('process_fail','MASK_REFINEMENT_PROCESS_FAILED',False),
    ('timeout','MODEL_TIMEOUT',False),
    ('tampered_input','NATIVE_INPUT_MISMATCH',True),
])
def test_failures_preserve_input_raw_output_no_detection_retry(native,mode,code,raw_png):
    w,transport,calls,job=native
    job=manual(w,job);parent_id=job.mask.id
    before=sha256(w.storage.artifact_path('masks',parent_id))
    w.segmentation.refinement_fixture.mode=mode
    trace=turn(w,job,'현재 편집 마스크 기준으로 보정해줘','MASK_REFINE','refine_weld_mask')
    assert trace[-1][1]['ok']==raw_png,trace
    assert any(e==('warning' if raw_png else 'error') and d['code']==code for e,d in trace),trace
    current=w.get_job(job.id)
    assert current.mask.id==parent_id and sha256(w.storage.artifact_path('masks',parent_id))==before
    assert not current.mask.approved and current.state==job.state
    result=w.segmentation.last_result
    assert result is not None
    assert (result.directory/'iteration_001/F_prediction.png').is_file()==raw_png
    assert current.raw_segment_output.validation.status=='FAIL'
    assert current.raw_segment_output.model_output.displayable==raw_png
    if mode=='restore':
        raw=np.asarray(Image.open(result.directory/'iteration_001/F_prediction.png'))
        assert raw[:,:50].any() and not np.asarray(w.storage.read_image('masks',parent_id))[:,:50].any()
    assert len(calls['refine'])==1 and len(calls['segment'])==1 and not calls['rough3d'] and not transport.calls
    if mode not in ('process_fail','timeout'):
        assert 'DO NOT STORE THIS NOTE' not in (result.directory/'iteration_001/result.json').read_text(encoding='utf-8')


def test_missing_region_partial_mask_is_not_applied(native):
    w,_,calls,job=native
    w.segmentation.refinement_fixture.mode='missing_region'
    with pytest.raises(ModelFault) as exc:w.refine_mask(job.id,instruction='보정해줘')
    assert exc.value.code=='MASK_REFINEMENT_OUTPUT_PARTIAL'
    assert w.get_job(job.id).mask.id==job.mask.id
    assert w.get_job(job.id).raw_segment_output.model_output.displayable
    assert len(calls['refine'])==1


def test_success_invalidates_downstream_and_retains_immutable_originals(native):
    w,_,calls,job=native
    job=w.edit_mask(job.id,operation='REMOVE',relation='LEFT')
    job=w.approve_mask(job.id,job.mask.id,'F')
    w.parse_instruction(job.id,'왼쪽에서 오른쪽으로 용접해');job=w.plan(job.id)
    job=w.run_guided_vla(job.id)  # injected offline transport only
    old_conditioning=conditioning_hash(job);old_vla=job.vla_prediction
    attempt=w.guided_vla.settings.attempts/str(old_vla.attempt_id)
    files={str(p):sha256(p) for p in attempt.rglob('*') if p.is_file()}
    refined=w.refine_mask(job.id,instruction='현재 마스크를 보정해줘')
    for field in ('instruction','rough_trajectory','final_trajectory','rough3d','vla_prediction','raw_final_prediction','validation','native_output'):
        assert getattr(refined,field) is None
    assert conditioning_hash(refined)!=old_conditioning  # current-preview package gate becomes stale
    assert not refined.mask.approved and refined.mask.approved_at is None
    assert all(sha256(Path(name))==digest for name,digest in files.items())
    assert len(calls['refine'])==1 and len(calls['rough3d'])==1


def test_explicit_approval_uses_refined_native_vectors_and_carried_yolo(native):
    w,_,calls,job=native
    job=manual(w,job);job=w.refine_mask(job.id,instruction='현재 마스크를 보정해줘')
    artifact_id=job.mask.artifact.provenance.native_source_artifact_id
    raw=read_json(w.segmentation.last_result.directory/'iteration_001/result.json')['predictions']['F']
    job=w.approve_mask(job.id,job.mask.id,'F')
    w.parse_instruction(job.id,'왼쪽에서 오른쪽으로 용접해');job=w.plan(job.id)
    assert job.state.value=='ROUGH_PATH_READY'
    approved=Path(calls['rough3d'][-1][-1])
    actual=read_json(approved/'iteration_001/result.json')['predictions']['F']
    assert actual['polylines']==raw['polylines']
    proof=read_json(approved.parent/f'{approved.name}.json')
    assert proof['source_native_artifact_id']==str(artifact_id)
    assert (approved/'yolo/detections.json').is_file()
    assert len(calls['refine'])==1 and len(calls['segment'])==1


def test_wrong_view_or_lineage_rejected_before_dispatch(native):
    w,_,calls,job=native
    with pytest.raises(WorkflowError):w.refine_mask(job.id,view='R',instruction='보정')
    image=w._scene_image(job,'F');image.info['refinement_context']={'job_id':job.id,'scene_id':job.scene.id,'mask_id':'wrong'}
    with pytest.raises(ModelFault) as exc:
        w.segmentation.refine(image,w.storage.read_image('masks',job.mask.id),job.mask,instruction='보정')
    assert exc.value.code=='NATIVE_INPUT_MISMATCH' and not calls['refine']


def test_root_utf8_env_is_only_key_source(tmp_path,monkeypatch,capsys):
    from backend.model_clients.native_mask_refine_entry import root_api_key
    monkeypatch.setenv('OPENAI_API_KEY','fake-inherited-key')
    (tmp_path/'.env').write_text('\ufeffOPENAI_API_KEY=fake-root-only-key\n# 한국어\n',encoding='utf-8')
    assert root_api_key(tmp_path)=='fake-root-only-key'
    (tmp_path/'.env').write_text('OTHER=value\n',encoding='utf-8')
    assert root_api_key(tmp_path)==''
    assert 'fake-root-only-key' not in capsys.readouterr().out


def test_image_metadata_never_enters_external_payload(native):
    w,_,_,job=native
    original=w._scene_image
    def with_metadata(*args,**kwargs):
        image=original(*args,**kwargs);image.info['exif']=b'Exif\x00\x00private-path-marker';return image
    w._scene_image=with_metadata
    job=manual(w,job)
    w.refine_mask(job.id,instruction='보정')
    for item in w.segmentation.refinement_fixture.payloads[0]['input'][1]['content']:
        if item['type']=='input_image':
            raw=base64.b64decode(item['image_url'].split(',')[1])
            assert b'private-path-marker' not in raw
            with Image.open(BytesIO(raw)) as image:assert not image.info


def test_sdk_exception_payload_is_never_logged_or_saved(native,capsys,caplog):
    w,_,calls,job=native
    w.segmentation.refinement_fixture.mode='sdk_fail'
    with pytest.raises(ModelFault):w.refine_mask(job.id,instruction='보정')
    captured=capsys.readouterr()
    assert 'fake-private-secret-and-raw-payload' not in captured.out+captured.err+caplog.text
    directory=w.segmentation.last_result.directory
    assert all(b'fake-private-secret-and-raw-payload' not in p.read_bytes() for p in directory.rglob('*') if p.is_file())
    assert read_json(directory/'iteration_001/result.json')['sdk_status']=='failed'
    assert len(calls['refine'])==1 and len(calls['segment'])==1


def test_exact_native_inference_function_with_fake_responses_only(tmp_path):
    """Read the sibling definitions; no native main/import/retrieval is executed."""
    import ast
    from types import SimpleNamespace
    from xml.sax.saxutils import escape
    from pydantic import BaseModel,Field
    from tests.mask_refinement_fakes import image_url
    from backend.model_clients.native_mask_refine_entry import infer,paths
    source=Path(__file__).resolve().parents[2]/'vlm_segment2/mask.py'
    raster_source=source.with_name('mask_data.py')
    if not source.is_file():pytest.skip('Sibling read-only source unavailable')
    ns={'OpenAI':object,'Path':Path,'Image':Image,'BaseModel':BaseModel,'Field':Field,'escape':escape,
        'image_data_url':image_url,'ImageDraw':__import__('PIL.ImageDraw',fromlist=['ImageDraw'])}
    names={'Point','Polyline','CameraMaskPrediction','predict_camera'}
    definitions=[]
    for node in ast.parse(source.read_text(encoding='utf-8')).body:
        if isinstance(node,(ast.ClassDef,ast.FunctionDef)) and node.name in names:definitions.append(node)
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DEVELOPER_PROMPT' for t in node.targets):definitions.append(node)
    for node in ast.parse(raster_source.read_text(encoding='utf-8')).body:
        if isinstance(node,ast.FunctionDef) and node.name=='rasterize':definitions.append(node)
    exec(compile(ast.Module(body=definitions,type_ignores=[]),str(source),'exec'),ns)
    native=SimpleNamespace(**{k:v for k,v in ns.items() if not k.startswith('__')})
    Image.new('RGB',(100,100),(10,20,30)).save(tmp_path/'F_rgb.png')
    Image.new('L',(100,100),255).save(tmp_path/'F_current_mask.png')
    prediction=native.CameraMaskPrediction(camera_id='F',polylines=[{'points':[{'x':10,'y':20},{'x':30,'y':20}]}],note='private visibility note')
    payloads=[]
    def parse(**kwargs):
        payloads.append(kwargs)
        return SimpleNamespace(output_parsed=prediction,id='fake-only',status='completed')
    data=infer(native,tmp_path,dict(model='offline',reasoning_effort='low',sample_id='SAMPLE_1',instruction='마스크 보정',line_width_px=5),
        SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    assert len(payloads)==1 and payloads[0]['text_format'] is native.CameraMaskPrediction
    assert len([x for x in payloads[0]['input'][1]['content'] if x['type']=='input_image'])==2
    assert 'SAMPLE_1' not in json.dumps(payloads[0]['input'])
    assert 'note' not in data['predictions']['F']
    expected=native.rasterize((100,100),paths(data['predictions']['F'],(100,100)),5)
    with Image.open(tmp_path/'iteration_001/F_prediction.png') as image:assert image.tobytes()==expected.tobytes()
