"""Native boundary parity with deterministic proposals; zero network or Isaac."""
import ast
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
import pytest
import yaml
from tests.test_gpt2_ricl_boundary import actual_native, query, NATIVE, PROJECT
from backend.model_clients.native import read_json
from backend.services.gpt2_prediction_proof import PREDICTION_KEYS


def cache(directory):
    directory.mkdir(parents=True)
    proposal=dict(path_description='deterministic offline',points=[dict(x=0,y=0,z=0),dict(x=1,y=2,z=3),dict(x=4,y=2,z=3)],
                  connections=['within_segment']*2,uncertainties=[])
    for stage in ('rough','corners'):
        data=dict(stage=stage,proposal=proposal,response_id='offline-'+stage,
                  previous_response_id='offline-rough' if stage=='corners' else None,end_conditioned=False,
                  fewshot={'applied':True,'sample_ids':['TRAIN_FIXTURE']})
        (directory/(stage+'.json')).write_text(json.dumps(data),encoding='utf-8')


def replay(native,root,source,sample,monkeypatch,prediction_only):
    config=yaml.safe_load((NATIVE/'config.yaml').read_text(encoding='utf-8'))
    config.update(baseline_root=str(source.parent),output_root=str(root/'outputs'),max_retries=0)
    file=root/'config.yaml';file.write_text(yaml.safe_dump(config),encoding='utf-8')
    dest=root/('outputs__prediction-only' if prediction_only else 'outputs')/source.name
    cache(dest)
    monkeypatch.setattr(sys,'argv',['predict.py','--config',str(file),'--sample-id',sample,'--cached-only',
                                  *(['--prediction-only'] if prediction_only else [])])
    assert (native.main() or 0)==0
    assert read_json(dest/'status.json')['status']=='complete'
    return dest


def test_native_cli_no_query_npz_and_no_evaluation_reads(actual_native,query,monkeypatch):
    native=actual_native;_,job,_,stage,_,_=query;root,source,_=stage()
    def deny(*a,**k): raise AssertionError('Prediction-only must not read evaluation arrays or compute metrics')
    monkeypatch.setattr(native.np,'load',deny)
    monkeypatch.setattr(native,'metrics',deny)
    dest=replay(native,root,source,job.scene.sample_id,monkeypatch,True)
    # restore np.load only for examining the committed result.
    monkeypatch.undo()
    with np.load(dest/'trajectory.npz',allow_pickle=False) as z:
        assert set(z.files)==PREDICTION_KEYS and z['predicted_path_xyz'].shape==(33,3)
        assert np.isfinite(z['predicted_path_xyz']).all()
        assert np.array_equal(z['predicted_path_xyz'][0],[10.,20.,30.])
        assert np.array_equal(z['predicted_path_m'],z['predicted_path_xyz']*.001)
    meta=read_json(dest/'metadata.json');summary=read_json(dest.parent/'summary.json')
    assert meta['known_start_application_count']==1 and meta['evaluation_performed'] is False
    assert summary['evaluation_performed'] is False and not any('mean_' in k for k in summary)
    assert not (source/'trajectory.npz').exists()
    assert not any('ground_truth' in p.name for p in dest.iterdir())


def test_default_evaluation_and_prediction_only_exact_prediction_parity(actual_native,query,monkeypatch):
    native=actual_native;_,job,_,stage,_,_=query;root,source,_=stage()
    gt=np.array([[10.,20.,30.],[11.,21.,32.],[14.,22.,33.]])*.001
    np.savez_compressed(source/'trajectory.npz',ground_truth_path_m=gt,predicted_path_m=gt+.001)
    default=replay(native,root,source,job.scene.sample_id,monkeypatch,False)
    prod=replay(native,root,source,job.scene.sample_id,monkeypatch,True)
    with np.load(default/'trajectory.npz') as a,np.load(prod/'trajectory.npz') as b:
        assert all(np.array_equal(a[k],b[k]) for k in PREDICTION_KEYS)
        assert np.max(np.abs(a['predicted_path_xyz']-b['predicted_path_xyz']))==0
        assert 'ground_truth_path_m' in a and 'ground_truth_path_m' not in b
    assert 'metrics' in read_json(default/'metadata.json')
    assert 'baseline_metrics_on_same_gt' in read_json(default/'metadata.json')
    assert 'mean_ade_source_units' in read_json(default.parent/'summary.json')
    assert all((default/(name+'.csv')).exists() for name in ('predicted_path_source','predicted_path_m','ground_truth_path_source','ground_truth_path_m'))
    # Original pre-change exporter must still produce every identical numeric array.
    original=PROJECT/'tests/fixtures/gpt2_evaluation_export_v1.py'
    tree=ast.parse(original.read_text(encoding='utf-8'))
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='export')
    scope=dict(native.__dict__)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(original),'exec'),scope)
    before=root/'before'/source.name;before.mkdir(parents=True)
    meta=read_json(source/'metadata.json')
    p,i,m=native.interpolate_corners([[0,0,0],[1,2,3],[4,2,3]],['within_segment']*2,33)
    cfg=yaml.safe_load((root/'config.yaml').read_text(encoding='utf-8'))
    scope['export'](source,before,meta,np.asarray(meta['start_xyz']),p,m,i,['F'],read_json(default/'metadata.json')['stages'],c=cfg)
    with np.load(default/'trajectory.npz') as a,np.load(before/'trajectory.npz') as b:
        assert set(a.files)==set(b.files) and all(np.array_equal(a[k],b[k]) for k in a.files)
    assert read_json(default/'metadata.json')==read_json(before/'metadata.json')
    for p in before.glob('*.csv'): assert p.read_bytes()==(default/p.name).read_bytes()


def test_versioned_prod_export_explicitly_skipped_by_evaluator(actual_native,query,monkeypatch):
    native=actual_native;_,job,_,stage,_,_=query;root,source,_=stage()
    dest=replay(native,root,source,job.scene.sample_id,monkeypatch,True)
    spec=importlib.util.spec_from_file_location('offline_eval',NATIVE/'evaluate.py')
    evaluator=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluator)
    def deny(*a,**k):raise AssertionError('Evaluator must explicitly skip no-GT export')
    monkeypatch.setattr(evaluator.np,'load',deny)
    rows,issues=evaluator.load_export(dest.parent,[],[],set())
    assert rows==[] and any('prediction-only export; evaluation skipped' in i for i in issues)


@pytest.mark.parametrize('flag',['--end','--no-mask','--no-rough','--no-retrieval','--all-ablations'])
def test_prediction_only_rejects_protocol_changing_flags(actual_native,monkeypatch,flag):
    monkeypatch.setattr(sys,'argv',['predict.py','--prediction-only',flag])
    with pytest.raises(SystemExit) as exc:actual_native.main()
    assert exc.value.code==2


def test_protected_native_algorithms_and_protocol_unchanged():
    current=(NATIVE/'predict.py').read_text(encoding='utf-8')
    import hashlib
    receipt=read_json(PROJECT/'tests/fixtures/gpt2_protocol_fingerprints.json')
    tree=ast.parse(current)
    nodes={n.name:hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest() for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    for name,digest in receipt['functions'].items(): assert nodes[name]==digest
    constants={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('PROMPT','PROMPT_VERSION')}
    assert constants==receipt['constants']
    for name,digest in receipt['files'].items():
        assert hashlib.sha256((NATIVE/name).read_bytes()).hexdigest()==digest


@pytest.mark.parametrize('mutation',['prediction','diagnostic_gt'])
def test_simulator_companion_rejects_changed_array_even_after_rehash(tmp_path,mutation):
    import h5py
    from backend.services.gpt2_simulator_companion import write_companion,verify_companion
    from backend.services.simulator_prediction_package import sha
    source=tmp_path/'native.npz';episode=tmp_path/'episode';episode.mkdir();h5=tmp_path/'sample.h5'
    with h5py.File(h5,'w') as f:f['trajectory']=[[10.,20.,30.],[11.,22.,33.]]
    xyz=np.array([[10.,20.,30.],[12.,22.,32.]])
    np.savez_compressed(source,predicted_path_xyz=xyz,predicted_path_m=xyz*.001,start_xyz=xyz[0],
                        predicted_delta_xyz=np.diff(xyz,axis=0),corner_indices=np.array([0,1]),connections=np.array(['within_segment']))
    native_bytes=source.read_bytes();receipt=write_companion(episode,native_bytes,h5)
    verify_companion(episode,source,h5,receipt)
    with np.load(episode/'trajectory.npz') as z:arrays={k:z[k] for k in z.files}
    arrays['predicted_path_m' if mutation=='prediction' else 'ground_truth_path_m'][0,0]+=.1
    np.savez_compressed(episode/'trajectory.npz',**arrays)
    receipt['simulator_input_sha256']=sha(episode/'trajectory.npz')
    with pytest.raises(ValueError):verify_companion(episode,source,h5,receipt)
    assert source.read_bytes()==native_bytes and (episode/'native_prediction.npz').read_bytes()==native_bytes
