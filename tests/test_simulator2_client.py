"""Offline injected native outputs; no external process, model, or Isaac in pytest."""
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.orchestrator.workflow import Workflow
from backend.services.current_preview_config import CurrentPreviewError
from backend.services.current_preview_gate import verify_preview
from backend.services.simulator2_client import DatasetSimulatorV2Client, backend_selection
from backend.services.simulator2_contract import identity, exact_assets, NATIVE_FILES, Simulator2ContractError
from backend.simulator2_prepare import validate_playback
from tests.agent_fakes import FakeSimulator
from tests.test_current_vla_preview import prepared
from backend.services.simulator_prediction_package import read,sha,write


class FakeBuilder:
    def __init__(self, failure=None, substitute=False): self.calls=[];self.failure=failure;self.substitute=substitute
    def build(self, **options):
        self.calls.append(options)
        if self.failure: raise CurrentPreviewError(self.failure,'Offline native preflight failed.',409)
        output=options['output'];output.mkdir()
        with np.load(options['prediction']/'trajectory.npz') as data:
            pred=data['predicted_path_m'].copy();gt=data['ground_truth_path_m'].copy()
        raw=np.column_stack(((gt if self.substitute else pred).astype(float)*1000,np.zeros((9,3))))
        # Known fixture: every source corner and one midpoint on each native segment.
        points=np.empty((17,6));points[::2]=raw;points[1::2]=(raw[:-1]+raw[1:])/2
        parameter=np.arange(17)*.5
        arrays=dict(raw_tcp_pose_xyz_mm_rpy_deg=raw,tcp_pose_xyz_mm_rpy_deg=points,
            playback_waypoint_parameter=parameter,source_to_scene=np.eye(4),predicted_source_xyz_m=pred,
            ground_truth_source_xyz_m=gt,workpiece_vertices_world_m=np.array([[0,0,0],[1,0,0],[0,1,0]]),
            workpiece_face_counts=np.array([3]),workpiece_face_indices=np.array([0,1,2]),
            joint_position_rad=np.zeros((17,6)),tracking_point=np.asarray('mounted_fixture_v2'),
            cad_to_robot_tcp=np.eye(4),urdf_tcp_to_weld_tcp=np.eye(4))
        np.savez(output/'trajectory_solution.npz',**arrays)
        write(output/'report.json',dict(sample_id=options['sample_id']))
        return dict(ok=True,sample_id=options['sample_id'],kind=options['kind'],prediction_input=True,
            robot_ready=options['kind']=='robot',vla_orientation=False,orientation_source='simulator2_policy',
            validation=validate_playback(raw,points,parameter),source_to_scene=np.eye(4).tolist())


def client_fixture(tmp_path, **kwargs):
    legacy,job,result,attempt=prepared(tmp_path,'B_PP_03_0001')
    root=tmp_path/'simulator2'
    for name in NATIVE_FILES:
        file=root/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('# offline native fixture')
    (root/'rbpodo_description/robots/rb10_1300e_u.urdf').write_text('<robot name="offline"/>')
    builder=FakeBuilder(**kwargs)
    client=DatasetSimulatorV2Client(legacy.storage,legacy.runtime,root=root,builder=builder,settings=legacy.settings)
    return client,job,result,attempt,builder,legacy


@pytest.mark.parametrize('kind',['path','robot'])
def test_current_exact_sample_original_nine_and_derived_playback(tmp_path,kind):
    client,job,result,attempt,builder,legacy=client_fixture(tmp_path)
    before={p:sha(p) for p in (attempt/'trajectory.npz',client.storage.artifact_path('jobs',job.id,'.json'),
                              client.storage.artifact_path('masks',job.mask.id))}
    assert client.capabilities(job_id=job.id)['robot_preview_ready'] is False
    assert not builder.calls  # polling never runs native math
    claim=client.prepare(job_id=job.id,kind=kind)
    d,p,npz=verify_preview(claim,project=client.settings.project)
    assert d['sample_id']==job.scene.sample_id==result.sample_id==Path(p['h5']).stem==Path(p['obj']).stem
    assert d['backend']=='dataset_v2' and d['family']=='B_PP'
    assert d['source_point_count']==9 and d['playback_point_count']==17 and p['playback']['derived'] is True
    assert npz.read_bytes()==(attempt/'trajectory.npz').read_bytes()
    with np.load(npz) as data:
        assert data['predicted_path_m'].shape==(9,3)
        assert not np.array_equal(data['predicted_path_m'],data['ground_truth_path_m'])
    assert all(sha(path)==digest for path,digest in before.items())
    assert p['ade_mm']==result.ade_mm and p['fde_mm']==result.fde_mm
    assert p['orientation_source']=='simulator2_policy' and d['vla_orientation'] is False
    assert p['physical_robot_executable'] is False and p['simulation_only'] is True
    caps=client.capabilities(job_id=job.id)
    assert caps['robot_preview_ready']==(kind=='robot') and caps['playback_point_count']==17
    assert 'directory' not in json.dumps(caps) and str(tmp_path) not in json.dumps(caps)
    # The independent legacy source and registry are still configured identically.
    assert legacy.settings.simulator_root!=client.root


@pytest.mark.parametrize('code',['SIMULATOR2_SCENE_BUILD_FAIL','SIMULATOR2_IK_FAIL','SIMULATOR2_PLAYBACK_FAIL','SIMULATOR2_FRAME_MISMATCH'])
def test_native_failure_safe_code_no_launch_fallback_or_retry(tmp_path,code):
    client,job,_,_,builder,_=client_fixture(tmp_path,failure=code)
    with pytest.raises(CurrentPreviewError) as error:client.run(job_id=job.id)
    assert error.value.code==code and len(builder.calls)==1 and not client.runtime.calls


def test_gt_substitution_rejected(tmp_path):
    client,job,_,_,builder,_=client_fixture(tmp_path,substitute=True)
    with pytest.raises(CurrentPreviewError) as error:client.prepare(job_id=job.id,kind='path')
    assert error.value.code=='SIMULATOR2_PLAYBACK_FAIL' and len(builder.calls)==1


def test_frame_and_missing_exact_asset_reject_before_native_dispatch(tmp_path):
    client,job,_,_,builder,_=client_fixture(tmp_path)
    job.vla_prediction.coordinate_frame='camera_relative'
    client.storage.save_job(job)
    with pytest.raises(CurrentPreviewError) as error:client.prepare(job_id=job.id)
    assert error.value.code=='SIMULATOR2_FRAME_MISMATCH' and not builder.calls


def test_missing_obj_does_not_select_another_sample(tmp_path):
    client,job,_,_,builder,_=client_fixture(tmp_path)
    _,obj=exact_assets(client.settings.dataset_root,job.scene.sample_id)
    obj.rename(obj.with_name('B_PP_03_0002.obj'))
    with pytest.raises(CurrentPreviewError) as error:client.prepare(job_id=job.id)
    assert error.value.code=='SIMULATOR2_OBJ_MISSING' and not builder.calls


def test_missing_native_ik_solution_rejected_before_launcher(tmp_path):
    client,job,_,_,builder,_=client_fixture(tmp_path)
    build=builder.build
    def missing(**options):
        result=build(**options)
        file=options['output']/'trajectory_solution.npz'
        with np.load(file) as source:arrays={k:source[k].copy() for k in source.files if k!='joint_position_rad'}
        np.savez(file,**arrays)
        return result
    builder.build=missing
    with pytest.raises(CurrentPreviewError) as error:client.run(job_id=job.id,kind='robot')
    assert error.value.code=='SIMULATOR2_IK_FAIL' and not client.runtime.calls and len(builder.calls)==1


@pytest.mark.parametrize('which',['h5','obj','job','source','native','code'])
def test_changed_identity_assets_and_outputs_fail_closed(tmp_path,which):
    client,job,_,attempt,builder,_=client_fixture(tmp_path)
    claim=client.prepare(job_id=job.id,kind='path');d=read(claim['path']);p=read(d['package'])
    if which=='job':
        job.scene.sample_id='B_PP_03_0002';client.storage.save_job(job)
    elif which=='code':
        (client.root/'welding_scene_layout.py').write_text('# changed native contract')
    else:
        target={'h5':Path(p['h5']),'obj':Path(p['obj']),'source':attempt/'trajectory.npz',
                'native':Path(d['package']).parent/'native/trajectory_solution.npz'}[which]
        target.write_bytes(b'changed')
    with pytest.raises((ValueError,CurrentPreviewError)):verify_preview(claim,project=client.settings.project)
    assert not client.runtime.calls


def test_uuid_only_api_dispatch_preflight_and_legacy_replay(tmp_path):
    client,job,_,_,builder,_=client_fixture(tmp_path);old=FakeSimulator()
    with TestClient(create_app(workflow=Workflow(client.storage),simulator=old,current_vla_preview=client,preview_runtime=client.runtime)) as api:
        for path in ('/api/simulator/preview-current-vla/path','/api/simulator/preview-current-vla','/api/simulator/current-vla/preview-preflight'):
            assert api.post(path,json={'job_id':str(job.id),'family':'B_PP'}).status_code==422
        response=api.post('/api/simulator/current-vla/preview-preflight',json={'job_id':str(job.id)})
        assert response.status_code==200,response.text
        assert response.json()['robot_preview_ready'] is True
        assert len(builder.calls)==1 and not client.runtime.calls and not old.calls
        response=api.post('/api/simulator/preview-current-vla',json={'job_id':str(job.id)})
        assert response.status_code==202,response.text
        assert len(client.runtime.calls)==1 and len(builder.calls)==1  # verified cached package, no repeat IK
        assert api.post('/api/simulator/start',json={}).status_code==202
        assert old.calls==['start']


def test_simulator2_identity_mixed_and_exact_assets_no_discovery(tmp_path):
    assert identity('C_RR_M_0018')[0]=='C_RR'
    assert 'M(Mixed)' in str(identity('C_RR_M_0018')[1])
    for sample in ('X_PP_03_0001','B_PP_00_0001','B_PP_03_0000','../B_PP_03_0001','B_PP_03_0002/../B_PP_03_0001'):
        with pytest.raises(Simulator2ContractError):identity(sample)
    with pytest.raises(Simulator2ContractError) as error:exact_assets(tmp_path,'B_PP_03_0001')
    assert error.value.code=='SIMULATOR2_H5_MISSING'


def test_default_and_explicit_version_selection(tmp_path,monkeypatch):
    monkeypatch.delenv('WELD_SIM_BACKEND',raising=False)
    env=tmp_path/'empty.env';env.write_text('')
    assert backend_selection(env)[0]=='legacy'
    monkeypatch.setenv('WELD_SIM_BACKEND','dataset_v2');assert backend_selection(env)[0]=='dataset_v2'
    monkeypatch.setenv('WELD_SIM_BACKEND','typo')
    with pytest.raises(CurrentPreviewError):backend_selection(env)


def test_dataset_runtime_launch_failure_has_safe_code_and_releases_lease(tmp_path,monkeypatch):
    from backend.services.current_preview_runtime import CurrentPreviewRuntime
    from backend.services.simulator_client import SimulatorConfig
    import backend.services.current_preview_runtime as module
    root=tmp_path/'simulator2';root.mkdir()
    config=SimulatorConfig(root,None,'',tmp_path,tmp_path,tmp_path/'runtime')
    class NeverLauncher:
        calls=0
        def preview(self,*args):self.calls+=1;raise OSError('private native payload')
    launcher=NeverLauncher();runtime=CurrentPreviewRuntime(config,backend='dataset_v2',launcher=launcher,monitor=False)
    d=dict(simulator_root=str(root),job_id='job',artifact_id='artifact',package_id='package',sample_id='B_PP_03_0001',point_count=9,
        kind='robot',mode='CURRENT_VLA_UNVALIDATED_PREVIEW',fixture_ready=False,physical_robot_executable=False,validated_simulation=False,
        clearance_warning='SIMULATOR2_UNVALIDATED_SCENE',orientation_source='simulator2_policy',vla_orientation=False,
        coordinate_frame='source_robot_frame_unaligned_with_isaac',ade_mm=1,fde_mm=2,family='B_PP',playback_point_count=17)
    monkeypatch.setattr(module,'verify_preview',lambda claim:(d,{},None))
    monkeypatch.setattr(runtime,'check_configuration',lambda **kwargs:None)
    with pytest.raises(CurrentPreviewError) as error:runtime.submit({})
    assert error.value.code=='SIMULATOR2_PLAYBACK_FAIL' and 'private' not in str(error.value)
    assert launcher.calls==1 and runtime.lease is None and runtime.process is None
    assert runtime.latest['reason_code']=='SIMULATOR2_PLAYBACK_FAIL'


def test_validation_detects_lost_corner_overshoot_order_and_endpoints():
    raw=np.array([[0,0,0,0,0,0],[10,0,0,0,0,0],[10,10,0,0,0,0]],float)
    play=np.array([raw[0],(raw[0]+raw[1])/2,raw[1],(raw[1]+raw[2])/2,raw[2]])
    parameter=np.arange(5)*.5
    assert validate_playback(raw,play,parameter)['corners_preserved']
    bad=play.copy();bad[1,1]=2
    with pytest.raises(ValueError):validate_playback(raw,bad,parameter)
    with pytest.raises(ValueError):validate_playback(raw,play[::-1],parameter)
    with pytest.raises(ValueError):validate_playback(raw,play[[0,1,3,4]],parameter[[0,1,3,4]])
