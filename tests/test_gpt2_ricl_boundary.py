from backend.services.project_paths import native_parent
"""Real native import/input boundary; fake transport, no RICL or fake query NPZ."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import h5py
import httpx
import numpy as np
from PIL import Image
import pytest
import yaml

from backend.model_clients.gpt2_query_snapshot import snapshot_current_query
from backend.model_clients.native import CAMERAS, read_json, sha256
from tests.module_fakes import module_workflow
from tests.test_module_workflow import rough_job

PROJECT = Path(__file__).resolve().parents[1]
NATIVE = native_parent(PROJECT)/'vlm_final_gpt2'


@pytest.fixture
def actual_native(monkeypatch):
    if not (native_parent(PROJECT)/'vlm_project2/fewshot_examples.py').is_file():
        pytest.skip('Original shared native module not available')
    def deny(*a,**k): raise AssertionError('Live API/SSH prohibited')
    import openai
    monkeypatch.setattr(openai,'OpenAI',deny)
    monkeypatch.setattr(openai,'AsyncOpenAI',deny)
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',deny)
    monkeypatch.setattr(subprocess,'run',deny)
    monkeypatch.setattr(sys,'dont_write_bytecode',True)
    monkeypatch.setattr(sys,'path',[str(PROJECT/'backend/simulator_compat'),str(NATIVE),str(native_parent(PROJECT)),*sys.path])
    spec=importlib.util.spec_from_file_location('gpt2_real_import_test',NATIVE/'predict.py')
    native=importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules,spec.name,native)
    spec.loader.exec_module(native)
    return native


@pytest.fixture
def query(tmp_path,monkeypatch):
    for module in ('native','native_rough3d','guided_vla','config'):
        monkeypatch.setattr('backend.model_clients.'+module+'.ROOT',tmp_path)
    wf,transport=module_workflow(tmp_path);job=rough_job(wf)
    source=read_json(wf.storage.artifact_path('native_context',job.id,'.scene.json'))
    label=tmp_path/'current-label.json'
    label.write_text(json.dumps(dict(info={'gid':job.scene.sample_id},categories={'fixture':'unit-test'},
        annotation_image=[dict(image_filename=job.scene.sample_id+'_F_Color.png',
            image_label=[dict(type='polyline',label='full_welding',points=[[1,1],[4,4]])])])),encoding='utf-8')
    h5=tmp_path/'current.h5'
    # Only the first XYZ is an allowed query input; invalid interior is irrelevant.
    with h5py.File(h5,'w') as f:f['trajectory']=np.array([[10.,20.,30.],[np.nan,987654321.,np.nan]])
    monkeypatch.setattr('backend.model_clients.gpt2_query_snapshot.exact_assets',lambda *_:(h5,tmp_path/'unused.obj'))
    resolved=SimpleNamespace(sample_id=job.scene.sample_id,split=job.scene.split,label=label,
        images={v:Path(source['images'][v]) for v in CAMERAS})
    dataset=SimpleNamespace(resolve=lambda _:resolved)
    def stage():return snapshot_current_query(wf.storage,job,tmp_path/'.cache/query-inputs',dataset=dataset,project=tmp_path)
    return wf,job,transport,stage,h5,dataset


def test_genuine_current_query_snapshot_has_no_gt_or_prediction_npz(query):
    wf,job,transport,stage,h5,_=query
    mask=job.mask.model_dump(mode='json');before=sha256(wf.storage.artifact_path('jobs',job.id,'.json'))
    root,source,receipt=stage()
    metadata=read_json(source/'metadata.json')
    assert metadata['start_xyz']==[10.,20.,30.] and metadata['instruction']==job.instruction.text
    assert set(metadata)=={'episode_id','split','instruction','start_xyz','source_units','coordinate_frame'}
    assert set(p.name for p in source.iterdir())=={'metadata.json','source_label.json','raw_rgb'}
    assert len(list((source/'raw_rgb').iterdir()))==9 and not list(root.rglob('*.npz'))
    assert receipt['query_gt_trajectory_included'] is False and receipt['baseline_prediction_included'] is False
    assert receipt['native_invocations']==0 and receipt['native_cli_ready'] is True
    assert wf.storage.get_job(job.id).mask.model_dump(mode='json')==mask
    assert sha256(wf.storage.artifact_path('jobs',job.id,'.json'))==before and not transport.calls


def test_two_native_requests_are_buildable_without_query_gt_or_baseline(actual_native,query,monkeypatch):
    native=actual_native;_,_,_,stage,_,_=query;root,source,_=stage()
    dest=root/'observed-native-input';dest.mkdir()
    def no_array_load(*a,**k):raise AssertionError('Query arrays must not be loaded for model input')
    monkeypatch.setattr(native.np,'load',no_array_load)
    config=yaml.safe_load((NATIVE/'config.yaml').read_text(encoding='utf-8'))
    metadata=read_json(source/'metadata.json')
    content,start,views,polylines,sizes=native.input_content(source,dest,metadata,config)
    context=json.loads(content[0]['text'])
    assert set(context)=={'instruction','known_start_xyz_mm','coordinate_frame','camera_order','workpiece_metadata'}
    assert context['known_start_xyz_mm']==[10.,20.,30.] and views==['F']
    calls=[]
    def parse(**request):
        calls.append(request)
        assert request['store'] is False
        proposal=native.Proposal(path_description='safe fixture',points=[{'x':0,'y':0,'z':0},{'x':1,'y':2,'z':3}],
                                connections=['within_segment'],uncertainties=[])
        return SimpleNamespace(output_parsed=proposal,model=config['model'],id='offline-'+str(len(calls)),usage=None)
    client=SimpleNamespace(responses=SimpleNamespace(parse=parse))
    rough=native.call_stage(client,config,content,'rough')
    corners=native.call_stage(client,config,content,'corners',rough)
    assert len(calls)==2 and corners['previous_response_id']==rough['response_id']
    for request in calls:
        payload=json.dumps(request['input'])
        assert '987654321' not in payload
        for key in ('ground_truth_path','baseline_prediction','known_end_xyz_mm','known_end_offset_mm'):
            assert key not in payload
    assert not (source/'trajectory.npz').exists()


def test_unmodified_cli_still_requires_npz_before_inference(actual_native,query,monkeypatch):
    native=actual_native;_,job,_,stage,_,_=query;root,source,_=stage()
    config=yaml.safe_load((NATIVE/'config.yaml').read_text(encoding='utf-8'))
    config.update(baseline_root=str(source.parent),output_root=str(root/'native'))
    path=root/'config.yaml';path.write_text(yaml.safe_dump(config),encoding='utf-8')
    monkeypatch.setattr(sys,'argv',['predict.py','--config',str(path),'--sample-id',job.scene.sample_id,'--cached-only'])
    with pytest.raises(ValueError,match='no baseline samples found'):native.main()
    assert not (root/'native').exists()


def test_native_export_loads_evaluation_before_saving_final(actual_native,query):
    native=actual_native;_,_,_,stage,_,_=query;root,source,_=stage();dest=root/'native-output';dest.mkdir()
    points,indices,modes=native.interpolate_corners([[0,0,0],[1,2,3]],['within_segment'],33)
    with pytest.raises(FileNotFoundError):
        native.export(source,dest,read_json(source/'metadata.json'),np.array([10.,20.,30.]),
                      points,modes,indices,['F'],{},c={})
    assert not list(dest.iterdir()) and not (source/'trajectory.npz').exists()


def test_original_fewshot_depends_on_train_examples_not_query_npz(actual_native,query,tmp_path,monkeypatch):
    import vlm_project2.fewshot_examples as shared
    native=actual_native;_,job,_,stage,_,_=query;root,source,_=stage();dest=root/'fewshot-test';dest.mkdir()
    config=yaml.safe_load((NATIVE/'config.yaml').read_text(encoding='utf-8'))
    _,_,_,polylines,sizes=native.input_content(source,dest,read_json(source/'metadata.json'),config)
    sid='L_PR_03_0001';training=tmp_path/'train-data/2.데이터(NIA)/Training'
    labels=training/'02.라벨링데이터';images=training/'01.원천데이터';labels.mkdir(parents=True);images.mkdir()
    filename=sid+'_F_Color.png';Image.new('RGB',(8,8)).save(images/filename)
    (labels/(sid+'.json')).write_text(json.dumps(dict(annotation_image=[dict(image_filename=filename,
        image_label=[dict(type='polyline',label='full_welding',points=[[1,1],[6,6]])])])),encoding='utf-8')
    calls=[]
    def retrieve(config,payload):
        calls.append(payload)
        return dict(index_split='train',results=[dict(sample_id=sid,texts={},metadata={},
                    rough_action={'source':'TRAIN','points_xyz_mm':[[1,2,3],[4,5,6]]})])
    monkeypatch.setattr(shared,'retrieve_actions',retrieve)
    shared.training_files.cache_clear()
    try:
        content,provenance=shared.prepare_examples(config,tmp_path/'train-data',job.scene.sample_id,
            job.instruction.text,polylines,sizes,dest)
    finally:shared.training_files.cache_clear()
    assert len(calls)==1 and calls[0]['sample_id']==job.scene.sample_id
    assert not any('trajectory' in k or 'start_xyz' in k for k in calls[0])
    assert provenance['sample_ids']==[sid] and provenance['query_sample_excluded'] is True
    assert any(x['type']=='input_image' for x in content) and not (source/'trajectory.npz').exists()


def test_invalid_known_start_never_stages_or_repairs_query(query):
    _,_,_,stage,h5,_=query
    with h5py.File(h5,'r+') as f:f['trajectory'][0,0]=np.nan
    from backend.model_clients.guided_vla import GuidedVLAError
    with pytest.raises(GuidedVLAError,match='GPT2_KNOWN_START_INVALID'):stage()


def test_stale_current_query_never_stages(query):
    wf,job,_,stage,_,_=query
    stored=wf.storage.get_job(job.id);stored.instruction.text+=' changed';wf.storage.save_job(stored)
    from backend.model_clients.guided_vla import GuidedVLAError
    with pytest.raises(GuidedVLAError,match='GPT2_INPUT_INVALID'):stage()
