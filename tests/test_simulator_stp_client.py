"""Fake native transport/output only: exact OBJ and STP layout admission."""
import json
import sys
import numpy as np
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.agent.config import AgentSettings
from backend.main import create_app
from backend.orchestrator.workflow import Workflow
from backend.services.current_preview_config import CurrentPreviewError
from backend.services.simulator2_client import backend_selection
from backend.services.simulator2_contract import exact_assets
from backend.services.simulator_stp_client import (
    AUDIT_FILES, DatasetSimulatorStpClient, DatasetStpPreviewRuntime, inspect_native_contract,
)
from backend.services.simulator_client import SimulatorConfig
from backend.services.simulator_prediction_package import sha
from tests.agent_fakes import FakeSimulator
from tests.test_current_vla_preview import prepared
from tests.test_simulator2_client import FakeBuilder
from backend.services.current_preview_gate import verify_preview, read
from backend.services.simulator_prediction_package import write


class StpBuilder(FakeBuilder):
    def build(self, **options):
        result=super().build(**options)
        file=options['output']/'trajectory_solution.npz'
        with np.load(file) as saved: arrays={k:saved[k].copy() for k in saved.files}
        arrays.update(environment_layout=np.asarray('stp'),fixture_table_top_m=np.asarray(-.010),
            environment_floor_z_m=np.asarray(-.670),environment_table_center_xy_m=np.array([.860,0.]),
            environment_table_size_xy_m=np.array([.500,.800]),position_error_mm=np.zeros(17),orientation_error_deg=np.zeros(17))
        np.savez(file,**arrays)
        result.update(native_layout='stp',native_flags=['--layout','stp'],cad_source='sample_obj',
            orientation_source='simulator_stp_policy',environment={'layout':'stp'},
            fk_residual_mm_max=0.,orientation_residual_deg_max=0.)
        result['validation']['frame']='simulator_stp_scene'
        (options['output']/'report.json').write_text(json.dumps(result),encoding='utf-8')
        return result


def fixture(tmp_path):
    old, job, result, attempt = prepared(tmp_path, 'B_PP_03_0001')
    root = tmp_path/'simulator_stp'
    native = root/'simulator'
    native.mkdir(parents=True)
    for name in AUDIT_FILES:
        file=native/name;file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text('# fake native source', encoding='utf-8')
    (native/'run_welding_sample.py').write_text("parser.add_argument('--layout', choices=('legacy', 'stp'))", encoding='utf-8')
    (native/'rbpodo_description/robots/rb10_1300e_u.urdf').write_text('<robot name="offline"/>')
    return DatasetSimulatorStpClient(old.storage, old.runtime, root=root, builder=StpBuilder(),settings=old.settings), job, attempt


def test_selection_default_stp_and_rollback(tmp_path, monkeypatch):
    env = tmp_path/'settings.env'
    env.write_text('WELD_SIM_BACKEND=dataset_stp\nWELD_SIM_STP_ROOT=../simulator_stp\n', encoding='utf-8')
    monkeypatch.delenv('WELD_SIM_BACKEND', raising=False)
    assert backend_selection(env) == ('dataset_stp', Path('../simulator_stp').resolve())
    monkeypatch.setenv('WELD_SIM_BACKEND', 'dataset_v2')
    assert backend_selection(env)[0] == 'dataset_v2'
    monkeypatch.setenv('WELD_SIM_BACKEND', 'legacy')
    assert backend_selection(env)[0] == 'legacy'


def test_source_contract_actual_layout_not_invented_mode(tmp_path):
    client, _, _ = fixture(tmp_path)
    evidence = inspect_native_contract(client.repository_root)
    assert evidence['native_layout_flag'] == '--layout stp'
    assert evidence['source_complete'] and evidence['contract_pass'] and evidence['code'] is None
    assert evidence['cad_source']=='sample_obj' and evidence['environment_source']=='stp_reference_layout'


@pytest.mark.parametrize('kind',['path','robot'])
def test_exact_sample_obj_source_n9_native_stp_and_separate_playback(tmp_path,kind):
    client,job,attempt=fixture(tmp_path)
    protected={p:sha(p) for p in (attempt/'trajectory.npz',client.storage.artifact_path('jobs',job.id,'.json'),client.storage.artifact_path('masks',job.mask.id))}
    caps=client.capabilities(job_id=job.id)
    assert caps['path_preview_ready'] and caps['robot_preflight_available'] and not caps['robot_preview_ready']
    assert not client.builder.calls
    claim=client.prepare(job_id=job.id,kind=kind)
    d,p,npz=verify_preview(claim,project=client.settings.project)
    assert d['sample_id']==job.scene.sample_id==Path(p['h5']).stem==Path(p['obj']).stem
    assert d['backend']=='dataset_stp' and d['native_layout']=='stp' and d['cad_source']=='sample_obj'
    assert d['source_point_count']==9 and d['playback_point_count']==17 and p['playback']['derived'] is True
    assert p['playback']['coordinate_frame']=='simulator_stp_scene'
    assert npz.read_bytes()==(attempt/'trajectory.npz').read_bytes()
    assert all(sha(file)==digest for file,digest in protected.items())
    assert d['orientation_source']=='simulator_stp_policy' and d['vla_orientation'] is False
    assert d['simulation_only'] and all(d[k] is False for k in ('fixture_ready','validated_simulation','physical_robot_executable'))
    assert p['ade_mm']==job.vla_prediction.ade_mm and p['fde_mm']==job.vla_prediction.fde_mm
    caps=client.capabilities(job_id=job.id)
    assert caps['cad_source']=='OBJ' and caps['native_layout']=='stp_reference_layout'
    assert caps['robot_preview_ready']==(kind=='robot') and str(tmp_path) not in str(caps)
    assert not client.runtime.calls


@pytest.mark.parametrize('change,code', [
    ('artifact','CURRENT_PREVIEW_ARTIFACT_INVALID'),('scene','CURRENT_PREVIEW_ARTIFACT_INVALID'),
    ('mask','CURRENT_PREVIEW_ARTIFACT_INVALID'),('frame','SIMULATOR_STP_FRAME_MISMATCH'),
    ('h5','SIMULATOR_STP_H5_MISSING'),('obj','SIMULATOR_STP_OBJ_MISSING')])
def test_current_identity_and_provenance_fail_before_cad(tmp_path, change, code):
    client, job, attempt = fixture(tmp_path)
    artifact = None
    if change == 'artifact': artifact = uuid4()
    elif change == 'scene': job.scene.sample_id='B_PP_03_0002'; client.storage.save_job(job)
    elif change == 'mask': client.storage.artifact_path('masks',job.mask.id).write_bytes(b'changed')
    elif change == 'frame': job.vla_prediction.coordinate_frame='camera_relative'; client.storage.save_job(job)
    else:
        h5,obj = exact_assets(client.settings.dataset_root,job.scene.sample_id)
        path = h5 if change == 'h5' else obj
        path.rename(path.with_name('B_PP_03_0002'+path.suffix))
    with pytest.raises(CurrentPreviewError) as error:
        client.prepare(job_id=job.id, artifact_id=artifact, kind='path')
    assert error.value.code == code and not client.runtime.calls


def test_uuid_only_stp_preflight_5174_and_cached_launch(tmp_path):
    client,job,_=fixture(tmp_path);simulator=FakeSimulator()
    with TestClient(create_app(workflow=Workflow(client.storage),simulator=simulator,
            current_vla_preview=client,agent_settings=AgentSettings(enabled=False))) as api:
        for endpoint in ('/preview-current-vla/path','/preview-current-vla','/current-vla/preview-preflight'):
            for name in ('layout','obj_path','h5_path','matrix','xyz','family','command'):
                assert api.post('/api/simulator'+endpoint,json={'job_id':str(job.id),name:'browser'}).status_code==422
        response=api.post('/api/simulator/current-vla/preview-preflight',json={'job_id':str(job.id)},headers={'Origin':'http://127.0.0.1:5174'})
        assert response.status_code==200,response.text
        assert response.json()['robot_preview_ready']
        assert len(client.builder.calls)==1 and not client.runtime.calls
        response=api.post('/api/simulator/preview-current-vla',json={'job_id':str(job.id)},headers={'Origin':'http://127.0.0.1:5174'})
        assert response.status_code==202,response.text
        assert len(client.runtime.calls)==1 and len(client.builder.calls)==1 and not simulator.calls


@pytest.mark.parametrize('origin', ['http://localhost:5173','http://127.0.0.1:5173','http://localhost:5174','http://127.0.0.1:5174'])
def test_fixed_dev_origins_keep_existing_replay_allowed(tmp_path, origin, monkeypatch):
    monkeypatch.delenv('WELD_CORS_ORIGINS', raising=False)
    client, _, _ = fixture(tmp_path)
    simulator = FakeSimulator()
    with TestClient(create_app(workflow=Workflow(client.storage),simulator=simulator,
            current_vla_preview=client,agent_settings=AgentSettings(enabled=False))) as api:
        assert api.post('/api/simulator/start',json={},headers={'Origin':origin}).status_code == 202
        assert simulator.calls == ['start']


@pytest.mark.parametrize('origin', ['https://external.example','http://127.0.0.1:5180','null'])
def test_unlisted_origin_rejected(tmp_path, origin, monkeypatch):
    monkeypatch.delenv('WELD_CORS_ORIGINS', raising=False)
    client, job, _ = fixture(tmp_path)
    with TestClient(create_app(workflow=Workflow(client.storage),simulator=FakeSimulator(),
            current_vla_preview=client,agent_settings=AgentSettings(enabled=False))) as api:
        assert api.post('/api/simulator/preview-current-vla/path',json={'job_id':str(job.id)},headers={'Origin':origin}).status_code == 403
        assert not client.runtime.calls


def test_explicit_origins_are_authoritative(tmp_path, monkeypatch):
    client, _, _ = fixture(tmp_path)
    monkeypatch.setenv('WELD_CORS_ORIGINS','http://localhost:5173')
    simulator = FakeSimulator()
    with TestClient(create_app(workflow=Workflow(client.storage),simulator=simulator,
            current_vla_preview=client,agent_settings=AgentSettings(enabled=False))) as api:
        assert api.post('/api/simulator/start',json={},headers={'Origin':'http://localhost:5174'}).status_code == 403
        assert not simulator.calls


def test_runtime_missing_launcher_and_factory_selects_stp(tmp_path,monkeypatch):
    client,_,_=fixture(tmp_path)
    config=SimulatorConfig(client.root,None,'',tmp_path,tmp_path,tmp_path/'runtime')
    runtime=DatasetStpPreviewRuntime(config,root=client.repository_root)
    assert not runtime.status()['configured'] and runtime.status()['backend']=='dataset_stp'
    assert 'CURRENT_PREVIEW_LAUNCHER_NOT_CONFIGURED' in runtime.status()['configuration_codes']
    runtime.close()
    monkeypatch.setenv('WELD_SIM_BACKEND','dataset_stp')
    monkeypatch.setenv('WELD_SIM_STP_ROOT',str(client.repository_root))
    monkeypatch.setenv('WELD_SIM_STP_MODE','stp')
    with TestClient(create_app(workflow=Workflow(client.storage),simulator=FakeSimulator(),agent_settings=AgentSettings(enabled=False))) as api:
        assert api.app.state.current_vla_preview.backend=='dataset_stp'
        assert api.app.state.current_vla_preview.root==client.root
        assert api.get('/api/simulator/status').json()['backend']=='dataset_stp'


def test_invalid_layout_or_native_source_fails_closed(tmp_path):
    client, job, _ = fixture(tmp_path)
    client.mode='legacy'
    with pytest.raises(CurrentPreviewError) as error: client.prepare(job_id=job.id)
    assert error.value.code == 'SIMULATOR_STP_MODE_INVALID'
    client.mode='stp'
    (client.root/'welding_environment.py').unlink()
    with pytest.raises(CurrentPreviewError) as error: client.prepare(job_id=job.id)
    assert error.value.code == 'SIMULATOR_STP_SOURCE_INVALID'


@pytest.mark.parametrize('change,code',[('matrix','SIMULATOR_STP_FRAME_MISMATCH'),('environment','SIMULATOR_STP_SCENE_BUILD_FAIL'),('residual','SIMULATOR_STP_IK_FAIL'),('source','SIMULATOR_STP_PLAYBACK_FAIL')])
def test_invalid_native_output_rejected_no_launch_or_retry(tmp_path,change,code):
    client,job,_=fixture(tmp_path);build=client.builder.build
    def invalid(**options):
        r=build(**options);file=options['output']/'trajectory_solution.npz'
        with np.load(file) as saved:a={k:saved[k].copy() for k in saved.files}
        if change=='matrix':r['source_to_scene'][0][3]=float('nan')
        elif change=='environment':a['environment_floor_z_m']=np.asarray(float('nan'))
        elif change=='residual':a['position_error_mm'][0]=2.
        elif change=='source':a['predicted_source_xyz_m'][0,0]+=1
        np.savez(file,**a)
        return r
    client.builder.build=invalid
    with pytest.raises(CurrentPreviewError) as error:client.prepare(job_id=job.id,kind='robot')
    assert error.value.code==code and len(client.builder.calls)==1 and not client.runtime.calls


def test_fixed_launcher_translates_config_to_native_layout_not_browser(tmp_path,monkeypatch):
    from backend.services.simulator_stp_client import NativeStpBuilder
    import backend.services.simulator2_client as module
    calls=[]
    def run(argv,**kwargs):
        calls.append((argv,kwargs))
        return type('P',(),dict(returncode=0,stdout=json.dumps({'ok':True})))()
    monkeypatch.setattr(module.subprocess,'run',run)
    NativeStpBuilder().build(root=tmp_path,h5=tmp_path/'sample.h5',obj=tmp_path/'sample.obj',sample_id='sample',output=tmp_path/'output')
    argv,options=calls[0];manifest=json.loads(options['input'])
    assert options['shell'] is False and len(calls)==1
    assert manifest['layout']=='stp' and manifest['backend']=='dataset_stp' and 'mode' not in manifest
    assert argv[-1].endswith('simulator_stp_prepare.py')


def test_gt_substitution_is_rejected_before_launcher(tmp_path):
    client,job,_=fixture(tmp_path)
    client.builder.substitute=True
    with pytest.raises(CurrentPreviewError) as error:client.prepare(job_id=job.id,kind='path')
    assert error.value.code=='SIMULATOR_STP_PLAYBACK_FAIL'
    assert len(client.builder.calls)==1 and not client.runtime.calls


def test_saved_stp_package_and_layout_cannot_change_after_admission(tmp_path):
    client,job,_=fixture(tmp_path)
    claim=client.prepare(job_id=job.id,kind='path')
    descriptor=read(claim['path'])
    file=Path(descriptor['package']).parent/'native/trajectory_solution.npz'
    with np.load(file) as saved:arrays={k:saved[k].copy() for k in saved.files}
    arrays['environment_layout']=np.asarray('legacy')
    np.savez(file,**arrays)
    with pytest.raises(ValueError):verify_preview(claim,project=client.settings.project)
    with pytest.raises(CurrentPreviewError) as error:client.run(job_id=job.id,kind='path')
    assert error.value.code=='CURRENT_PREVIEW_ARTIFACT_INVALID'
    assert len(client.builder.calls)==1 and not client.runtime.calls


def test_native_environment_renderer_consumes_saved_dimensions():
    from backend.services.preview_environment import stp_primitives
    saved=dict(environment_layout=np.asarray('stp'),environment_floor_z_m=np.asarray(-.670),
        fixture_table_top_m=np.asarray(-.010),environment_table_center_xy_m=np.array([.860,0]),environment_table_size_xy_m=np.array([.500,.800]))
    before={k:v.copy() for k,v in saved.items()}
    cubes=stp_primitives(saved)
    assert cubes[1]==('RobotPedestal',[0,0,-.335],[.600,.800,.670])
    assert cubes[2]==('ReferenceTable',[.860,0,-.030],[.500,.800,.04])
    assert len(cubes)==7 and all(np.array_equal(v,before[k]) for k,v in saved.items())


def test_stp_capture_failure_is_nonfatal_with_fake_owned_process(tmp_path,monkeypatch):
    from tests.test_simulator import FakeProcess
    from tests.test_preview_capture import completion
    from backend.services.preview_capture import CAPTURE_NAMES
    client,job,_=fixture(tmp_path);claim=client.prepare(job_id=job.id)
    monkeypatch.setattr('backend.services.current_preview_runtime.verify_preview',lambda c:verify_preview(c,project=client.settings.project))
    class Launcher:
        def preview(self,*args):self.child=FakeProcess(123);return self.child
    launcher=Launcher();config=SimulatorConfig(client.root,Path(sys.executable),'',tmp_path,tmp_path,tmp_path/'runtime')
    runtime=DatasetStpPreviewRuntime(config,root=client.repository_root,launcher=launcher,monitor=False)
    monkeypatch.setattr(runtime,'check_configuration',lambda **kwargs:None)
    try:
        runtime.submit(claim);runtime.ready_seen=True;runtime.tick()
        _,result,data=completion(runtime,claim,CAPTURE_NAMES)
        data['backend']='dataset_stp'
        output=runtime.session/'outputs'/runtime.latest['request_id']
        (output/'report.json').write_text(json.dumps(data),encoding='utf-8');result.write_text(json.dumps(data),encoding='utf-8');runtime.tick()
        assert runtime.state=='READY' and runtime.latest['playback_status']=='SUCCEEDED'
        assert runtime.latest['capture_status']=='FAILED' and runtime.latest['reason_code']=='SIMULATOR_STP_CAPTURE_WARNING'
        assert not launcher.child.stopped and len(client.builder.calls)==1
    finally:runtime.close()
    assert launcher.child.stopped and runtime.lease is None
