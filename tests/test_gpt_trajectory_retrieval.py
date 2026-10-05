"""Fake selection transport + real readonly native TRAIN action/image utilities."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json
import subprocess
import h5py
import numpy as np
import pytest
from PIL import Image
from backend.model_clients.gpt_trajectory_retrieval import (Query,RetrievalError,prepare_examples,
    select_segment2,select_local,load_reference,owned_preparer,verify_provenance)
from backend.model_clients.gpt_trajectory_entry import load_native,build_content
from backend.model_clients.native import CAMERAS
from backend.services.simulator2_contract import identity
from backend.services.scene_dataset import DatasetScenes


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')


def sample(root,sid,split='Training',*,rgb=100,xyz=20):
    joint={'B':'Butt','C':'Corner'}[sid[0]];category=f'{"TS" if split=="Training" else "VS"}_{joint}_PP(Plate-Plate)'
    source=root/'2.데이터(NIA)'/split/'01.원천데이터'/category/'03(3mm)'/sid
    images={v:source/f'{sid}_{v}_Color.png' for v in CAMERAS};source.mkdir(parents=True)
    for p in images.values():Image.new('RGB',(32,32),(rgb,rgb,rgb)).save(p)
    label=source.parents[2].parent/'02.라벨링데이터'/category.replace('TS_','TL_').replace('VS_','VL_')/'03(3mm)'/sid/(sid+'.json')
    write(label,dict(info={'gid':sid},categories=dict(metal_position=joint,parent_metal='plate-plate',object_size='S',metal_thickness='3'),
        rgb_images=[dict(filename=p.name,rgb_width=32,rgb_height=32) for p in images.values()],
        annotation_image=[dict(image_filename=images['F'].name,image_label=[dict(type='polyline',label='full_welding',points=[[5,16],[25,16]])])]))
    _,relative=identity(sid);h5=root/'1.데이터/Other/Other/로봇티칭데이터'/relative/(sid+'.h5')
    h5.parent.mkdir(parents=True,exist_ok=True)
    with h5py.File(h5,'w') as f:
        f['trajectory']=np.column_stack([np.linspace(xyz,xyz+20,40),np.ones(40)*3,np.ones(40)*4])
        f['interpolation_type']=np.bytes_('linear')
    obj=root/'1.데이터/Other/Other/모델링 데이터'/relative/(sid+'.obj');obj.parent.mkdir(parents=True,exist_ok=True);obj.write_text('v 0 0 0')
    return DatasetScenes(root).resolve(sid)


@pytest.fixture
def inputs(tmp_path,monkeypatch):
    import openai,httpx
    def deny(*a,**k):raise AssertionError('No live model/network/process')
    monkeypatch.setattr(openai,'OpenAI',deny);monkeypatch.setattr(openai,'AsyncOpenAI',deny)
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',deny);monkeypatch.setattr(subprocess,'Popen',deny)
    root=tmp_path/'dataset';root.mkdir()
    query=sample(root,'B_PP_03_0001','Validation',xyz=987654321)
    sample(root,'B_PP_03_0002');sample(root,'B_PP_03_0003',rgb=110,xyz=30)
    sample(root,'B_PP_03_0004','Validation',xyz=765432100)
    mask=tmp_path/'F_mask.png';image=Image.new('L',(32,32));image.paste(255,(5,14,26,19));image.save(mask)
    q=Query(query.sample_id,'평판 맞대기 접합부를 왼쪽부터 용접해',query.images,json.loads(query.label.read_text(encoding='utf-8'))['categories'],
        {'F':[[[5,16],[25,16]]]},dict.fromkeys(CAMERAS,(32,32)),mask)
    cfg=dict(rough_points=9,mask_width_px=3,retrieval=dict(top_k=2,candidate_pool=4,image_max_side=64))
    destination=tmp_path/'attempt';destination.mkdir()
    segment=tmp_path/'segment.yaml';segment.write_text('''
server: {ssh_alias: test-only, remote_root: /fixed, remote_python: /unused}
retrieval: {remote_python: /fixed/python, bbox_source: server_yolo}
yolo: {remote_python: /fixed/yolo, weights: service/weights/fixed.pt}
''')
    return root,q,cfg,destination,segment


def selected(q,c):
    return [dict(sample_id='B_PP_03_0002',native_rank=1,image_score=.9),
            dict(sample_id='B_PP_03_0003',native_rank=2,image_score=.8)]


def prepare(values,mode='segment2_adapter',**kwargs):
    root,q,c,d,s=values
    return prepare_examples(c,root,q.sample_id,q.instruction,q.polylines,q.sizes,d,
                            query=q,mode=mode,segment_config=s,**kwargs)


def test_segment2_selection_reuses_real_contract_and_only_rgb(inputs):
    root,q,c,d,s=inputs;calls=[]
    class Native:
        RetrievalConfig=lambda **k:SimpleNamespace(**k)
        @staticmethod
        def retrieve_sample(cfg,sample,**kw):
            calls.append((cfg,sample,kw))
            return dict(index_split='train',bbox_source='server_yolo',query_sample_id=sample,self_sample_excluded=True,
                results=[dict(sample_id='B_PP_03_0002',score=.9),dict(sample_id='B_PP_03_0003',score=.8)])
    items=select_segment2(q,c,s,d,native=Native)
    assert [i['sample_id'] for i in items]==['B_PP_03_0002','B_PP_03_0003']
    cfg,sid,args=calls[0]
    assert cfg.bbox_source=='server_yolo' and cfg.top_k==4 and sid==q.sample_id
    assert set(args)=={'images','output_dir'} and set(args['images'])==set(CAMERAS)
    assert all(p.suffix=='.png' for p in args['images'].values())  # No H5/label to remote selection.


@pytest.mark.parametrize('field,value',[('index_split','val'),('bbox_source','database'),
    ('query_sample_id','OTHER'),('self_sample_excluded',False)])
def test_remote_proof_required_no_fallback(inputs,field,value):
    _,q,c,d,s=inputs
    class Native:
        RetrievalConfig=lambda **k:SimpleNamespace(**k)
        @staticmethod
        def retrieve_sample(*a,**k):
            r=dict(index_split='train',bbox_source='server_yolo',query_sample_id=q.sample_id,self_sample_excluded=True,
                   results=[dict(sample_id='B_PP_03_0002',score=.9)])
            r[field]=value;return r
    with pytest.raises(RetrievalError):select_segment2(q,c,s,d,native=Native)


def test_train_h5_answers_content_provenance_and_no_query_gt(inputs,monkeypatch):
    root,q,c,d,s=inputs
    original=h5py.File;opened=[]
    def guarded(path,*a,**k):
        assert Path(path).stem!=q.sample_id,'query GT was read by retrieval'
        assert Path(path).stem!='B_PP_03_0004','validation GT was read by retrieval'
        opened.append(Path(path));return original(path,*a,**k)
    monkeypatch.setattr(h5py,'File',guarded)
    content,p=prepare(inputs,selector=selected)
    assert len([v for v in content if v['type']=='input_image'])==18
    texts=[v['text'] for v in content if v['type']=='input_text']
    assert not any('987654321' in v or '765432100' in v or str(root) in v for v in texts)
    examples=[json.loads(t) for t in texts if t.startswith('{')]
    for value in examples:
        assert value['split']=='train' and value['registered_to_query'] is False
        assert value['instruction_source']=='native_train_categories_and_h5_teaching_description'
        points=value['correct_teaching_answer']['points']
        assert all(point['y']==0 and point['z']==0 for point in points)  # H5-relative XYZ, not F pixel y=16.
        assert points[-1]['x']==20 and points[0]['x']==0
    assert p['retrieved_sample_ids']==['B_PP_03_0002','B_PP_03_0003']
    assert p['top_k']==2 and p['query_gt_in_retrieval'] is p['query_gt_in_examples'] is False
    assert len(opened)==2 and all(r['split']=='train' and r['h5_sha256'] and len(r['images_sha256'])==9 for r in p['references'])
    assert len(p['source_files'])==22 and (d/'retrieval_provenance.json').is_file()
    verify_provenance(p,q.sample_id,root,'segment2_adapter')
    first=next(iter(p['source_files']));Path(first).write_bytes(b'changed')
    with pytest.raises(RetrievalError):verify_provenance(p,q.sample_id,root,'segment2_adapter')


@pytest.mark.parametrize('sid',['B_PP_03_0001','B_PP_03_0004'])
def test_self_or_validation_reference_rejected_before_gpt(inputs,sid):
    with pytest.raises(RetrievalError):prepare(inputs,selector=lambda *_:[dict(sample_id=sid,native_rank=1,image_score=.9)])


def test_local_explicit_bounded_training_selection(inputs):
    root,q,c,d,s=inputs
    items=select_local(q,root,c)
    assert {i['sample_id'] for i in items}=={'B_PP_03_0002','B_PP_03_0003'}
    content,p=prepare(inputs,mode='local')
    assert len(p['references'])==2 and 'bounded_local' in p['implementation'] and content


def test_none_explicit_no_selection_no_teaching_read(inputs):
    def deny(*a,**k):raise AssertionError('None cannot retrieve or load teaching')
    content,p=prepare(inputs,mode='none',selector=deny,reference_loader=deny)
    assert content==[] and p['retrieved_sample_ids']==[] and p['source_files']=={}
    assert p['mode']=='none' and p['warning']=='NO_RETRIEVAL_ACCURACY_UNVERIFIED'


def test_selection_failure_does_not_switch_mode(inputs):
    def failed(*a):raise RetrievalError('fake remote failure')
    with pytest.raises(RetrievalError):prepare(inputs,selector=failed)
    assert not (inputs[3]/'retrieval_provenance.json').exists()


def test_owned_native_import_bridge_is_not_external_restoration(tmp_path,monkeypatch):
    import sys
    repo=tmp_path/'native';repo.mkdir()
    (repo/'predict.py').write_text('from vlm_project2.fewshot_examples import prepare_examples\ndef call_stage(): pass\n')
    monkeypatch.setattr(sys,'path',sys.path.copy())
    n=load_native(repo)
    assert n.prepare_examples is prepare_examples
    assert not (tmp_path/'vlm_project2').exists() and 'vlm_project2.fewshot_examples' not in sys.modules


def test_none_uses_native_no_retrieval_prompt_and_h5_only_as_known_start(inputs):
    root,q,c,d,s=inputs
    native=load_native(Path(__file__).resolve().parents[2]/'vlm_final_gpt')
    native_config={'no_retrieval':True}
    assert 'No retrieved examples' in native.prompt_for_mode(False,native_config)
    assert native.PROMPT_VERSION=='gpt-luna-path-corners-v2'
    assert callable(native.call_stage) and callable(native.check_proposal) and callable(native.interpolate_corners)


def test_real_native_two_stages_with_fake_sdk_train_examples_and_33_output(inputs):
    root,q,c,d,s=inputs
    content,provenance=prepare(inputs,selector=selected)
    native=load_native(Path(__file__).resolve().parents[2]/'vlm_final_gpt')
    calls=[]
    def parse(**request):
        calls.append(request)
        proposal=native.Proposal(path_description='Safe structured path',
            points=[dict(x=i,y=i/2,z=0) for i in (0,5,10)],
            connections=['within_segment']*2,uncertainties=[])
        return SimpleNamespace(output_parsed=proposal,model='gpt-6-luna',id=f'fake-{len(calls)}',usage=None)
    client=SimpleNamespace(responses=SimpleNamespace(parse=parse))
    c.update(model='gpt-6-luna',reasoning_effort='medium',max_output_tokens=5000)
    options=dict(attempt=str(d),label=str(DatasetScenes(root).resolve(q.sample_id).label),
        images={v:str(p) for v,p in q.images.items()},instruction=q.instruction)
    __import__('shutil').copyfile(q.mask,d/'F_mask.png');c['image_max_side']=64
    query,sizes=build_content(native,options,c,np.array([10.,20.,30.]))
    previous=None
    for stage in ('rough','corners'):
        response=native.call_stage(client,c,content+query,stage,previous,provenance)
        native.write_json(d/(stage+'.json'),response)
        plan,points=native.check_proposal(response);previous=response
    xyz,indices,modes=native.interpolate_corners(points,plan.connections,33)
    assert xyz.shape==(33,3) and np.isfinite(xyz).all() and len(modes)==32
    assert len(calls)==2 and (d/'rough.json').is_file() and (d/'corners.json').is_file()
    for request in calls:
        assert request['model']=='gpt-6-luna' and request['reasoning']=={'effort':'medium'}
        assert request['store'] is False and request['input'][0]['content']==native.PROMPT
        encoded=json.dumps(request['input'])
        assert str(root) not in encoded and '987654321' not in encoded and '765432100' not in encoded
        assert len([v for v in request['input'][1]['content'] if v['type']=='input_image'])==27
    assert sizes['F']==(32,32) and 'initial approximate path' in calls[1]['input'][1]['content'][-1]['text']
