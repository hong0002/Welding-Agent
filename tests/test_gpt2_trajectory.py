"""Offline native cached replay + fake process. Paid/SSH/Isaac calls forbidden."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import types
from uuid import UUID
import h5py
import httpx
import numpy as np
import pytest
import yaml
from backend.model_clients.gpt2_trajectory import GPT2TrajectoryPredictor, GPT2TrajectorySettings
from backend.model_clients.guided_vla import GuidedVLAError
from backend.model_clients.native import CAMERAS, read_json, sha256
from backend.model_clients.final_trajectory import configured_final_predictor
from backend.services.gpt2_prediction_proof import FRAME, PREDICTION_KEYS, verify_completed_gpt2
from backend.services.current_vla_preview import WorkflowPredictionAdapter
from backend.services.simulator_prediction_package import PackageSettings
from backend.services.output_catalog import catalog, xyz_output
from tests.module_fakes import module_workflow
from tests.test_module_workflow import rough_job

PROJECT = Path(__file__).resolve().parents[1]
NATIVE = PROJECT.parent/'vlm_final_gpt2'


def write(p,v): p.write_text(json.dumps(v,allow_nan=False),encoding='utf-8')


@pytest.fixture
def native(monkeypatch):
    """Only an offline import harness. Never installed in the production launcher."""
    if not (NATIVE/'predict.py').is_file(): pytest.skip('Native read-only source unavailable')
    def deny(*a,**k): raise AssertionError('Real API/retrieval prohibited')
    import openai
    monkeypatch.setattr(openai,'OpenAI',deny)
    monkeypatch.setattr(openai,'AsyncOpenAI',deny)
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',deny)
    monkeypatch.setattr(sys,'path',[str(PROJECT/'backend/simulator_compat'),str(NATIVE),*sys.path])
    package=types.ModuleType('vlm_project2');package.__path__=[]
    shared=types.ModuleType('vlm_project2.fewshot_examples');shared.prepare_examples=deny
    monkeypatch.setitem(sys.modules,'vlm_project2',package)
    monkeypatch.setitem(sys.modules,'vlm_project2.fewshot_examples',shared)
    interpolation=types.ModuleType('interpolate');interpolation.__file__=str(NATIVE/'interpolate.py')
    monkeypatch.setitem(sys.modules,'interpolate',interpolation)
    exec(compile((NATIVE/'interpolate.py').read_bytes(),str(NATIVE/'interpolate.py'),'exec'),interpolation.__dict__)
    module=types.ModuleType('offline_gpt2_native');module.__file__=str(NATIVE/'predict.py')
    monkeypatch.setitem(sys.modules,module.__name__,module)
    exec(compile((NATIVE/'predict.py').read_bytes(),str(NATIVE/'predict.py'),'exec'),module.__dict__)
    monkeypatch.setattr(module,'make_client',deny)
    monkeypatch.setattr(module,'call_stage',deny)
    return module


class CachedNative:
    """Runs the actual native CLI with saved synthetic proposals, never inference."""
    def __init__(self,native,monkeypatch,kind=None): self.native=native;self.monkeypatch=monkeypatch;self.kind=kind;self.calls=[]
    def __call__(self,command,**kwargs):
        self.calls.append((command,kwargs))
        attempt=Path(command[-1]);launch=read_json(attempt/'launch.json');manifest=read_json(attempt/'request_manifest.json')
        directory=attempt/manifest['native_directory'];directory.mkdir(parents=True)
        if self.kind=='retrieval_failed':
            write(attempt/'invocation_counts.json',dict(model_stage_calls=0,ssh_calls=1,completed_stages=[]))
            return 1,[]
        # Explicitly synthetic proposals; fixture coordinates never become production artifacts.
        proposal=dict(path_description='offline fixture',points=[{'x':0,'y':0,'z':0},{'x':2,'y':1,'z':.5},{'x':4,'y':1,'z':1}],
                      connections=['within_segment','within_segment'],uncertainties=[])
        for name in ('rough','corners'):
            write(directory/(name+'.json'),dict(stage=name,proposal=proposal,response_id='fixture-'+name,
                previous_response_id='fixture-rough' if name=='corners' else None,model='gpt-6-luna',
                end_conditioned=False,ablation=dict(no_mask=False,no_rough=False,no_retrieval=False),
                fewshot={'applied':True,'sample_ids':['TRAIN_FIXTURE']}))
        if self.kind=='partial': return 1,[]
        self.monkeypatch.setattr(sys,'argv',['predict.py','--config',str(attempt/'native_config.yaml'),
            '--sample-id',launch['sample_id'],'--cached-only','--prediction-only'])
        code=self.native.main() or 0  # sys.exit(None) is native success exit=0.
        if self.kind=='bad_status': write(directory/'status.json',{'status':'failed','error_type':'FixtureError'})
        if self.kind=='wrong_units':
            meta=read_json(directory/'metadata.json');meta['source_units']='m';write(directory/'metadata.json',meta)
        if self.kind=='double_start':
            with np.load(directory/'trajectory.npz',allow_pickle=False) as z: a={k:z[k] for k in z.files}
            a['predicted_path_xyz']+=a['start_xyz'];a['predicted_path_m']=a['predicted_path_xyz']*.001
            a['predicted_delta_xyz']=np.diff(a['predicted_path_xyz'],axis=0)
            np.savez_compressed(directory/'trajectory.npz',**a)
        return code,[]


@pytest.fixture
def setup(tmp_path,monkeypatch,native):
    monkeypatch.setattr('backend.model_clients.gpt2_trajectory.ROOT',tmp_path)
    for module in ('native','native_rough3d','guided_vla','config'):
        monkeypatch.setattr('backend.model_clients.'+module+'.ROOT',tmp_path)
    wf,transport=module_workflow(tmp_path);job=rough_job(wf)
    h5=tmp_path/'query.h5';obj=tmp_path/'query.obj';obj.write_text('v 0 0 0\n')
    gt=np.array([[10.,20.,30.],[11.,21.,30.],[14.,21.,31.]])
    with h5py.File(h5,'w') as f: f['trajectory']=gt
    monkeypatch.setattr('backend.model_clients.gpt2_trajectory.exact_assets',lambda *_:(h5,obj))
    baseline=tmp_path/'baseline';folder=baseline/'0000_query';(folder/'raw_rgb').mkdir(parents=True)
    source=read_json(wf.storage.artifact_path('native_context',job.id,'.scene.json'))
    for view in CAMERAS: (folder/'raw_rgb'/f'{view}_Color.png').write_bytes(Path(source['images'][view]).read_bytes())
    label=dict(info={'gid':job.scene.sample_id},categories={'fixture':'test'},annotation_image=[dict(image_filename=f"{job.scene.sample_id}_F_Color.png",
        image_label=[dict(type='polyline',label='full_welding',points=[[1,1],[4,4]])])])
    write(folder/'source_label.json',label)
    write(folder/'metadata.json',dict(episode_id=job.scene.sample_id,split=job.scene.split,source_units='mm',
        coordinate_frame=FRAME,start_xyz=gt[0].tolist(),instruction='native fixture instruction'))
    np.savez_compressed(folder/'trajectory.npz',ground_truth_path_m=gt*.001,predicted_path_m=(gt+1)*.001)
    from types import SimpleNamespace
    def resolve(_):
        current=wf.storage.get_job(job.id)
        images=read_json(wf.storage.artifact_path('native_context',job.id,'.scene.json'))['images']
        return SimpleNamespace(sample_id=current.scene.sample_id,split=current.scene.split,
            label=folder/'source_label.json',images={v:Path(images[v]) for v in CAMERAS})
    monkeypatch.setattr('backend.model_clients.gpt2_query_snapshot.DatasetScenes',lambda *_:SimpleNamespace(resolve=resolve))
    monkeypatch.setattr('backend.model_clients.gpt2_query_snapshot.exact_assets',lambda *_:(h5,obj))
    shared=tmp_path/'shared';(shared/'vlm_project2').mkdir(parents=True)
    (shared/'vlm_project2/fewshot_examples.py').write_text('# fake offline dependency; never invoked\n')
    fake=CachedNative(native,monkeypatch)
    client=GPT2TrajectoryPredictor(GPT2TrajectorySettings(repository=NATIVE,python=Path(sys.executable),
        config=NATIVE/'config.yaml',attempts=tmp_path/'.cache/native-models/gpt2-trajectory',
        shared_root=shared,baseline_root=baseline),execute=fake)
    wf.guided_vla=client
    return wf,job,client,fake,transport


def test_selector_is_explicit_and_rollback_retained(tmp_path,monkeypatch):
    monkeypatch.delenv('WELD_FINAL_TRAJECTORY_BACKEND',raising=False)
    env=tmp_path/'selection.env';env.write_text('WELD_FINAL_TRAJECTORY_BACKEND=gpt2\n',encoding='utf-8')
    assert isinstance(configured_final_predictor(env),GPT2TrajectoryPredictor)
    env.write_text('WELD_FINAL_TRAJECTORY_BACKEND=gpt\n',encoding='utf-8')
    assert configured_final_predictor(env).status()['source']=='vlm_final_gpt'


def test_missing_native_retrieval_never_falls_back(setup,tmp_path):
    wf,job,client,fake,transport=setup
    client.settings=replace(client.settings,shared_root=tmp_path/'absent')
    with pytest.raises(GuidedVLAError,match='GPT2_NATIVE_RETRIEVAL_MISSING'): client.run(wf.storage,job)
    assert fake.calls==[] and transport.calls==[] and not client.settings.attempts.exists()


def test_backend_owned_ssh_override_preserves_native_protocol(setup):
    wf,job,client,fake,transport=setup
    client.settings=replace(client.settings,retrieval_ssh_alias='verified-native-host')
    original=client.config()
    client.run(wf.storage,job)
    attempt=client.settings.attempts/str(client.last_attempt_id)
    resolved=yaml.safe_load((attempt/'native_config.yaml').read_text(encoding='utf-8'))
    assert resolved['server']==dict(original['server'],ssh_alias='verified-native-host')
    assert resolved['retrieval']==original['retrieval']
    for key in ('model','reasoning_effort','rough_points','output_points','mask_width_px','image_max_side'):
        assert resolved[key]==original[key]
    assert client.config()==original and len(fake.calls)==1 and not transport.calls


def test_ssh_override_is_backend_env_only(tmp_path,monkeypatch):
    monkeypatch.delenv('WELD_GPT2_RETRIEVAL_SSH_ALIAS',raising=False)
    env=tmp_path/'native.env';env.write_text('WELD_GPT2_RETRIEVAL_SSH_ALIAS=verified-native-host\n',encoding='utf-8')
    assert GPT2TrajectorySettings.from_env(env).retrieval_ssh_alias=='verified-native-host'


def test_missing_evaluation_baseline_does_not_block_prediction(setup,tmp_path):
    wf,job,client,fake,transport=setup
    client.settings=replace(client.settings,baseline_root=tmp_path/'absent')
    result=client.run(wf.storage,job)
    assert result.source=='vlm_final_gpt2' and len(fake.calls)==1 and transport.calls==[]
    attempt=client.settings.attempts/str(client.last_attempt_id)
    assert not list((attempt/'inputs').rglob('*.npz'))


def test_native_cached_cli_export_normalization_and_strict_source(setup,tmp_path):
    wf,job,client,fake,transport=setup
    original_mask=job.mask.model_dump(mode='json');original_instruction=job.instruction.model_dump(mode='json')
    result=wf.run_final_trajectory_prediction(job.id)
    assert result.vla_prediction.source=='vlm_final_gpt2' and result.state.value=='VLA_READY'
    assert result.mask.model_dump(mode='json')==original_mask and result.instruction.model_dump(mode='json')==original_instruction
    attempt=client.settings.attempts/str(client.last_attempt_id);manifest=read_json(attempt/'request_manifest.json')
    native_dir=attempt/manifest['native_directory']
    assert sha256(native_dir/'trajectory.npz')==sha256(attempt/'trajectory.npz')
    with np.load(attempt/'trajectory.npz',allow_pickle=False) as a:
        assert set(a.files)==PREDICTION_KEYS and a['predicted_path_m'].dtype==np.float64
        assert a['predicted_path_m'].shape==(33,3)
        r=read_json(attempt/'response.json')
        assert np.array_equal(a['predicted_path_xyz'],r['predicted_path_xyz_mm'])
        assert np.array_equal(a['predicted_path_m'],np.asarray(r['predicted_path_xyz_mm'])*.001)
        assert np.array_equal(a['predicted_path_xyz'][0],manifest['known_start_xyz_mm'])
    assert manifest['web_masks_used_as_input'] is False and manifest['trajectory3_used_as_input'] is False
    assert manifest['reference_in_request'] is True and manifest['references_supplied_by_adapter'] is False
    assert manifest['start_applications']==1 and manifest['rough_source_files']=={}
    assert r['prediction_only'] and r['ground_truth_path_xyz_mm'] is None and r['ade_mm'] is None and r['fde_mm'] is None
    assert not list((attempt/'inputs').rglob('*.npz'))
    resolved=yaml.safe_load((attempt/'native_config.yaml').read_text(encoding='utf-8'))
    original=yaml.safe_load((NATIVE/'config.yaml').read_text(encoding='utf-8'))
    for key in original:
        if key not in ('baseline_root','output_root','end_output_root','data_root','api_keys_path','max_retries'): assert resolved[key]==original[key]
    assert resolved['max_retries']==0
    assert len(fake.calls)==1 and fake.calls[0][1]['cwd']==NATIVE and not transport.calls and not transport.health_calls
    data=client.read_display(wf.storage,result,result.raw_final_prediction.artifact_id)
    assert len(data['runs'][0])==33 and data['stages'][-1]['stage']=='GPT · Final'
    rows=catalog(wf.storage,result,client,project=tmp_path)['outputs']
    final=next(r for r in rows if r['stage']=='final')
    assert final['source']=='vlm_final_gpt2' and final['states']['OUTPUT_VALIDATED'] and final['states']['CURRENT_RESULT']
    assert xyz_output(wf.storage,result,client,project=tmp_path)['stage']=='final'
    settings=PackageSettings(client.settings.attempts,tmp_path,tmp_path,tmp_path/'.cache/packages',project=tmp_path)
    adapter=WorkflowPredictionAdapter(settings,wf.storage,result)
    source=adapter._source(result.vla_prediction.artifact_id)
    assert source[1].source=='vlm_final_gpt2' and source[4]==(native_dir/'trajectory.npz').read_bytes()
    normalized=read_json(attempt/'owned/normalized.json')
    assert normalized['mask_binding'] is None and normalized['orientation_source']=='simulator_final_policy'
    assert normalized['vla_orientation'] is False and not (native_dir/'response.json').exists()


@pytest.mark.parametrize('kind',['bad_status','wrong_units','double_start','partial'])
def test_partial_or_invalid_is_not_promoted_and_no_retry(setup,kind):
    wf,job,client,fake,transport=setup;fake.kind=kind
    result=wf.run_final_trajectory_prediction(job.id)
    assert result.vla_prediction is None and result.state.value!='VLA_READY'
    assert result.raw_final_prediction.source=='vlm_final_gpt2' and result.raw_final_prediction.validation_status!='PASS'
    assert result.latest_final_attempt['status']=='PARTIAL'
    assert len(fake.calls)==1 and not transport.calls
    attempt=client.settings.attempts/str(client.last_attempt_id)
    assert not (attempt/'completion.json').exists()


def test_invalid_supplied_start_is_rejected_before_native_dispatch(setup):
    wf,job,client,fake,transport=setup
    with h5py.File(client.settings.attempts.parents[2]/'query.h5','r+') as f: f['trajectory'][0,0]=np.nan
    with pytest.raises(GuidedVLAError,match='GPT2_KNOWN_START_INVALID'): client.run(wf.storage,job)
    assert not fake.calls and not transport.calls


@pytest.mark.parametrize('mutation',['native_bytes','normalized_xyz','instruction','source_code'])
def test_immutable_native_or_binding_tamper_blocks_strict(setup,mutation):
    wf,job,client,fake,transport=setup;result=wf.run_final_trajectory_prediction(job.id)
    attempt=client.settings.attempts/str(client.last_attempt_id);manifest=read_json(attempt/'request_manifest.json')
    if mutation=='native_bytes':
        file=attempt/manifest['native_directory']/'corners.json';file.write_bytes(file.read_bytes()+b' ')
    elif mutation=='normalized_xyz':
        file=attempt/'response.json';r=read_json(file);r['predicted_path_xyz_mm'][0][0]+=1;write(file,r)
    elif mutation=='source_code':
        file=client.settings.shared_root/'vlm_project2/fewshot_examples.py';file.write_text('# changed offline fixture')
    else: result.instruction.text+=' changed'
    with pytest.raises(ValueError): verify_completed_gpt2(attempt,manifest,result.model_dump(mode='json'),simulation_preview=True)


def test_no_model_import_or_inference_during_status(setup):
    wf,job,client,fake,transport=setup
    status=client.status()
    assert status['source']=='vlm_final_gpt2' and status['backend']=='gpt' and status['selector']=='gpt2'
    assert status['model']=='gpt-6-luna' and status['reasoning_effort']=='medium'
    assert not fake.calls and not transport.calls


def test_native_retrieval_failure_has_safe_phase_code_no_retry(setup):
    wf,job,client,fake,transport=setup;fake.kind='retrieval_failed'
    with pytest.raises(GuidedVLAError,match='GPT2_NATIVE_RETRIEVAL_FAILED'):client.run(wf.storage,job)
    assert len(fake.calls)==1 and not transport.calls
    assert client.last_display is None


def test_nondefault_native_count_is_preserved_not_forced_to_33(setup,tmp_path):
    wf,job,client,fake,_=setup
    config=yaml.safe_load(client.settings.config.read_text(encoding='utf-8'))
    config.update(rough_points=4,output_points=9)
    path=tmp_path/'native-mode.yaml';path.write_text(yaml.safe_dump(config),encoding='utf-8')
    client.settings=replace(client.settings,config=path)
    result=wf.run_final_trajectory_prediction(job.id)
    assert result.vla_prediction.point_count==9
    attempt=client.settings.attempts/str(client.last_attempt_id)
    with np.load(attempt/'trajectory.npz',allow_pickle=False) as a: assert a['predicted_path_xyz'].shape==(9,3)


def test_gpt2_admission_failure_preserves_existing_output(setup,tmp_path):
    wf,job,client,fake,_=setup;before=wf.run_final_trajectory_prediction(job.id)
    existing=before.vla_prediction.model_dump(mode='json')
    client.settings=replace(client.settings,shared_root=tmp_path/'missing-shared')
    with pytest.raises(GuidedVLAError): wf.run_final_trajectory_prediction(job.id)
    assert wf.get_job(job.id).vla_prediction.model_dump(mode='json')==existing and len(fake.calls)==1


def test_actual_gpt2_npz_to_dataset_final_strict_fake_playback(setup,tmp_path,monkeypatch):
    from backend.services.dataset_sample import exact_assets
    from backend.services.simulator_final_client import SimulatorFinalClient
    from backend.services.current_preview_gate import verify_preview
    from backend.services.robot_demo import RobotPreview
    from tests.test_simulator_final_client import fixture
    from types import SimpleNamespace
    wf,job,client,fake,transport=setup
    dataset=tmp_path/'dataset';sample='B_PP_03_0001'
    h5,obj=exact_assets(dataset,sample)
    h5.parent.mkdir(parents=True);obj.parent.mkdir(parents=True)
    h5.write_bytes((tmp_path/'query.h5').read_bytes());obj.write_bytes((tmp_path/'query.obj').read_bytes())
    job.scene.sample_id=sample;job.native_output=None;job.rough3d=None;job.raw_segment_output=None;wf.storage.save_job(job)
    source_file=wf.storage.artifact_path('native_context',job.id,'.scene.json')
    source=read_json(source_file);source['sample_id']=sample;source['dataset_root']=str(dataset);write(source_file,source)
    folder=client.settings.baseline_root/'0000_query'
    meta=read_json(folder/'metadata.json');meta['episode_id']=sample;write(folder/'metadata.json',meta)
    label=read_json(folder/'source_label.json');label['annotation_image'][0]['image_filename']=sample+'_F_Color.png';write(folder/'source_label.json',label)
    label['info']['gid']=sample;write(folder/'source_label.json',label)
    monkeypatch.setattr('backend.model_clients.gpt2_trajectory.exact_assets',lambda *_:(h5,obj))
    monkeypatch.setattr('backend.model_clients.gpt2_query_snapshot.exact_assets',lambda *_:(h5,obj))
    result=wf.run_final_trajectory_prediction(job.id)
    original=client.settings.attempts/str(client.last_attempt_id)/'trajectory.npz';original_hash=sha256(original)
    template,_,_=fixture(tmp_path/'sim-fixture')
    settings=PackageSettings(client.settings.attempts,dataset,template.root,tmp_path/'.cache/packages',project=tmp_path)
    simulator=SimulatorFinalClient(wf.storage,template.runtime,root=template.root,builder=template.builder,settings=settings)
    row=xyz_output(wf.storage,result,client,project=tmp_path)
    monkeypatch.setattr('backend.services.output_catalog.xyz_output',lambda *a,**k:row)
    def no_demo(*a,**k): raise AssertionError('Absolute GPT2 must not enter DEMO')
    preview=RobotPreview(SimpleNamespace(storage=wf.storage,final_predictor=client,get_display_job=lambda _:result),
        simulator.runtime,simulator,project=tmp_path,prepare=no_demo)
    assert preview.run(result.id,row['id'],output_kind=row['stage'])['mode']=='STRICT'
    d,p,npz=verify_preview(simulator.runtime.calls[0],project=tmp_path)
    assert d['backend']=='dataset_final' and d['prediction_source']=='vlm_final_gpt2'
    assert d['source_point_count']==33 and d['playback_point_count']==65
    assert (npz.parent/'native_prediction.npz').read_bytes()==original.read_bytes() and sha256(original)==original_hash
    with np.load(npz,allow_pickle=False) as z,np.load(original,allow_pickle=False) as native:
        assert np.array_equal(z['predicted_path_m'],native['predicted_path_m'])
        assert 'ground_truth_path_m' in z and 'ground_truth_path_m' not in native
    assert d['orientation_source']=='simulator_final_policy' and d['vla_orientation'] is False
    assert not d.get('robot_demo_only') and not d['physical_robot_executable']
    assert len(simulator.builder.calls)==1 and len(fake.calls)==1 and not transport.calls


def test_agent_dispatches_native_gpt2_once_and_reuses_current_final(setup):
    import asyncio
    from backend.agent.context import WeldingAgentContext
    from tests.agent_fakes import FakeSimulator, invoke
    wf,job,client,fake,transport=setup
    ctx=WeldingAgentContext(job.id,'offline','GPT 최종 궤적 생성해줘',wf,FakeSimulator(),lambda *_:None)
    asyncio.run(invoke(ctx,'get_workspace_state'))
    result=asyncio.run(invoke(ctx,'run_final_trajectory_prediction'))
    assert result['source']=='vlm_final_gpt2' and result['point_count']==33
    assert ctx.mask_conditioning_views==[] and len(fake.calls)==1 and not transport.calls
    again=WeldingAgentContext(job.id,'offline','GPT 최종 궤적 생성해줘',wf,FakeSimulator(),lambda *_:None)
    asyncio.run(invoke(again,'get_workspace_state'))
    reused=asyncio.run(invoke(again,'run_final_trajectory_prediction'))
    assert reused['already_ready'] is True and len(fake.calls)==1 and not transport.calls
