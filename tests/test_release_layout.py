"""Source-only release contract tests: no model/network/Isaac execution."""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
import yaml
from backend.services.project_paths import PROJECT,native_parent
from backend.model_clients.gpt2_trajectory import GPT2TrajectorySettings,GPT2TrajectoryPredictor
from backend.services.simulator2_client import backend_selection

def test_packaged_root_and_original_sibling_fallback(tmp_path):
    assert native_parent(PROJECT)==PROJECT/'modules'
    assert native_parent(tmp_path)==tmp_path.parent
    (tmp_path/'modules').mkdir()
    assert native_parent(tmp_path)==tmp_path/'modules'

def test_final_defaults_and_sources_are_packaged():
    settings=GPT2TrajectorySettings()
    assert settings.repository==PROJECT/'modules/vlm_final_gpt2'
    assert settings.shared_root==PROJECT/'modules'
    assert settings.config.is_file()
    for module in ('vlm_segment2','vlm_trajectory3','vlm_project','vlm_project2','vlm_project4','vlm_embedding_server','simulator_final'):
        assert (native_parent()/module).is_dir()
    config=GPT2TrajectoryPredictor(settings,execute=lambda *a,**k:None).config()
    assert (config['model'],config['reasoning_effort'],config['output_points'])==('gpt-6-luna','medium',33)

def test_final_backend_root_without_external_assets(monkeypatch,tmp_path):
    for name in ('WELD_SIM_FINAL_ROOT','WELD_SIM_BACKEND'):monkeypatch.delenv(name,raising=False)
    env=tmp_path/'empty.env';env.write_text('WELD_SIM_BACKEND=dataset_final\n',encoding='utf-8')
    assert backend_selection(env)==('dataset_final',PROJECT/'modules/simulator_final')

def load_setup_module():
    spec=importlib.util.spec_from_file_location('release_setup',PROJECT/'scripts/configure_release.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def test_config_generation_retains_policy_and_exact_binding(tmp_path,monkeypatch):
    module=load_setup_module()
    values={'WELD_DATASET_ROOT':str(tmp_path),'WELD_NATIVE_SSH_ALIAS':'operator-alias',
        'WELD_NATIVE_REMOTE_ROOT':'/external/source','WELD_NATIVE_REMOTE_PYTHON':'/external/python',
        'WELD_NATIVE_YOLO_PYTHON':'/external/yolo-python'}
    scene=SimpleNamespace(sample_id='synthetic_sample',images={'F':tmp_path/'synthetic_F.png'})
    files=module.generate(values,scene)
    segment=yaml.safe_load(files['segment2.windows.yaml']);rough=yaml.safe_load(files['trajectory3.windows.yaml'])
    assert segment['mask']['model']=='gpt-6-luna'
    assert segment['mask']['reasoning_effort']=='low'
    assert rough['models']['planner']=='gpt-6-luna'
    assert rough['models']['reasoning_effort']=='low'
    assert rough['retrieval']['top_k']==3
    import json
    assert json.loads(files['binding.json'])['image']==str(scene.images['F'])
    assert 'OPENAI_API_KEY' not in ''.join(files.values())
    monkeypatch.setattr(module,'PROJECT',tmp_path)
    directory=tmp_path/'.cache/configs';module.save(files,directory)
    module.save(files,directory)
    prior=(directory/'binding.json').read_bytes()
    with pytest.raises(ValueError,match='CONFIG_EXISTS_AND_DIFFERS'):
        module.save({**files,'binding.json':'different'},directory)
    assert (directory/'binding.json').read_bytes()==prior
    with pytest.raises(ValueError,match='NOT_OWNED'):module.save(files,tmp_path/'foreign')

def test_native_prediction_math_unchanged():
    # Moving configuration roots must not edit native prompt/interpolation/scene math.
    import hashlib,json
    hashes=json.loads((PROJECT/'docs/source-inventory.json').read_text(encoding='utf-8'))['native_original_python_sha256']
    for name,expected in hashes.items():
        if name.endswith('/predict.py') or name.endswith('/interpolate.py') or name.startswith('modules/simulator_final/'):
            assert hashlib.sha256((PROJECT/name).read_bytes()).hexdigest()==expected,name

def test_no_dataset_prediction_or_index_in_module_tree():
    forbidden={'.h5','.hdf5','.obj','.npz','.npy','.faiss','.sqlite','.db','.pt','.pth','.safetensors','.usd','.usda','.usdc','.stp','.stl','.dae'}
    assert not [p for p in (PROJECT/'modules').rglob('*') if p.is_file() and p.suffix.lower() in forbidden]


@pytest.mark.parametrize('entry',('gpt2_trajectory_entry.py','native_trajectory3_entry.py'))
def test_fixed_script_bootstrap_without_backend_on_initial_path(entry,monkeypatch):
    # Executing as a file from native cwd must discover backend before its imports.
    import sys,runpy
    path=PROJECT/'backend/model_clients'/entry
    monkeypatch.setattr(sys,'path',[p for p in sys.path if Path(p or '.').resolve()!=PROJECT])
    namespace=runpy.run_path(str(path),run_name='release_import_probe')
    assert callable(namespace['main'])
    assert sys.path[0]==str(PROJECT)


def test_root_env_key_only_for_allowlisted_owned_native_cwd(tmp_path):
    from backend.model_clients.native_process import configure_packaged_key
    root=tmp_path/'release';(root/'modules/vlm_segment2').mkdir(parents=True)
    (root/'modules/vlm_trajectory3').mkdir()
    (root/'.env').write_text('OPENAI_API_KEY=offline-fixture-key\n',encoding='utf-8')
    for name in ('vlm_segment2','vlm_trajectory3'):
        env={};assert configure_packaged_key(env,root/'modules'/name,root)=='root_dotenv'
        assert env['OPENAI_API_KEY']=='offline-fixture-key'
    env={};assert configure_packaged_key(env,tmp_path/'foreign',root)=='native_contract'
    assert not env
    (root/'.env').unlink()
    env={};assert configure_packaged_key(env,root/'modules/vlm_segment2',root)=='native_contract'
    assert not env


def test_local_assets_can_be_external_but_helper_stays_in_verified_source_tree(tmp_path):
    from backend.model_clients.gpt2_local_retrieval import LocalFinalRetrieval
    # Avoid runtime/encoder initialization entirely; inspect helper selection only.
    local=object.__new__(LocalFinalRetrieval)
    local.root=tmp_path/'external-assets';local.shared_root=tmp_path/'verified-source'
    helper=local.shared_root/'vlm_project2/fewshot_examples.py';helper.parent.mkdir(parents=True)
    helper.write_text('def prepare_examples(*a,**k):return "offline-helper"\n',encoding='utf-8')
    local.retrieve_actions=lambda *a,**k:(_ for _ in ()).throw(AssertionError('No retrieval allowed'))
    import sys
    previous=sys.modules.get('vlm_project2.fewshot_examples')
    try:assert local.reference_helper()()=='offline-helper'
    finally:
        if previous is None:sys.modules.pop('vlm_project2.fewshot_examples',None)
        else:sys.modules['vlm_project2.fewshot_examples']=previous
