"""Synthetic family/asset/renderer admission; all runtime/model execution is fake."""
import json
from pathlib import Path
from uuid import uuid4
import h5py
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.orchestrator.workflow import Workflow
from backend.services.dataset_sample import resolve_sample, exact_assets
from backend.services.preview_policy import BppPreviewPolicy, SourceFramePreviewPolicy, PreviewPolicyRegistry, default_registry
from backend.services.current_preview_config import CurrentPreviewError, configuration
from backend.services.current_preview_gate import verify_preview
from backend.services.simulator_package_gate import verify_current_package
from backend.services.simulator_prediction_package import sha, read
from tests.test_current_vla_preview import prepared
from tests.agent_fakes import FakeSimulator


@pytest.mark.parametrize('sample,family,joint,pairing', [
    ('B_PR_03_0001','B_PR','Butt','PR(Plate-Round)'),
    ('B_PP_03_0001','B_PP','Butt','PP(Plate-Plate)'),
    ('T_PR_03_0001','T_PR','Tee','PR(Plate-Round)'),
    ('T_PP_06_0007','T_PP','Tee','PP(Plate-Plate)'),
    ('L_PR_03_0001','L_PR','Lap','PR(Plate-Round)'),
])
def test_dataset_identity_directory_contract(tmp_path,sample,family,joint,pairing):
    identity=resolve_sample(sample)
    assert identity.family==family
    h5,obj=exact_assets(tmp_path,sample)
    assert h5.stem==obj.stem==sample
    assert h5.parent.parts[-4:]==(joint,pairing,f'{identity.thickness}({int(identity.thickness)}mm)',sample)


@pytest.mark.parametrize('sample',['B_PP_3_0001','B_PP_00_0001','B_PP_03_0000','B_PP_03_0001_extra','X_PP_03_0001','B_XY_03_0001','../B_PP_03_0001'])
def test_malformed_identity_rejected(sample):
    with pytest.raises(ValueError):resolve_sample(sample)


def test_registry_bpp_path_only_and_readonly_capabilities(tmp_path):
    service,job,_,attempt=prepared(tmp_path,'B_PP_03_0001')
    class NeverFixture:
        def inspect(self,*args):raise AssertionError('Path must not run robot fixture probe')
    service.fixtures=NeverFixture()
    assert isinstance(service.registry.resolve(job.scene.sample_id),BppPreviewPolicy)
    before={str(p):sha(p) for p in service.settings.project.rglob('*') if p.is_file()}
    caps=service.capabilities(job_id=job.id)
    assert caps['family']=='B_PP' and caps['path_preview_ready']
    assert not caps['robot_preview_ready'] and not caps['workpiece_preview_ready']
    assert caps['robot_reason_code']=='PREVIEW_PATH_SUPPORTED_ROBOT_PENDING'
    assert before=={str(p):sha(p) for p in service.settings.project.rglob('*') if p.is_file()}
    claim=service.prepare(job_id=job.id,kind='path')
    d,p,npz=verify_preview(claim,project=service.settings.project)
    assert d['sample_id']=='B_PP_03_0001' and d['family']=='B_PP'
    assert d['source_to_scene']==np.eye(4).tolist() and not d['show_workpiece']
    assert d['object_translation_m'] is None and d['flange_rotation'] is None
    assert not d['policy']['evidence_files'] and not p['provenance']['simulator_files']
    assert d['orientation_source']=='simulator_preview_policy' and not d['vla_orientation']
    assert p['orientation_policy']=='none_xyz_only' and p['orientation_source']=='simulator_preview_policy; not VLA'
    assert p['schema_version']=='current-vla-path-package-v1'
    assert p['preflight']['fixture_ready'] is False
    assert npz.read_bytes()==(attempt/'trajectory.npz').read_bytes()
    with np.load(npz) as exported,np.load(attempt/'trajectory.npz') as source:
        assert exported['predicted_path_m'].shape==(9,3)
        np.testing.assert_array_equal(exported['predicted_path_m'],source['predicted_path_m'])
        assert not np.array_equal(exported['predicted_path_m'],exported['ground_truth_path_m'])
    assert p['preflight']['gt_h5_frame_error_mm_max']<.05
    # Diagnostic path package cannot enter the existing validated replay gate.
    with pytest.raises(ValueError):verify_current_package({'package':d['package'],'sha256':d['package_sha256']},service.settings.simulator_root,[],project=service.settings.project)


@pytest.mark.parametrize('edit,code',[('h5','PREVIEW_H5_MISMATCH'),('missing_h5','PREVIEW_SAMPLE_ASSET_MISSING'),
    ('missing_obj','PREVIEW_OBJ_MISSING'),('invalid_obj','PREVIEW_POLICY_NOT_READY')])
def test_exact_sample_asset_faults_never_dispatch(tmp_path,edit,code):
    service,job,_,_=prepared(tmp_path,'B_PP_03_0001')
    h5,obj=exact_assets(service.settings.dataset_root,job.scene.sample_id)
    if edit=='h5':
        with h5py.File(h5,'r+') as handle:
            values=handle['trajectory'][:];values[:,0]+=10;handle['trajectory'][:]=values
    elif edit=='missing_h5':h5.unlink()
    elif edit=='missing_obj':obj.unlink()
    else:obj.write_text('v nan 0 0\nf 1 1 1\n')
    with pytest.raises(CurrentPreviewError) as exc:service.prepare(job_id=job.id,kind='path')
    assert exc.value.code==code and service.runtime.calls==[]


@pytest.mark.parametrize('replacement',['T_PP_03_0001','B_PP_03_0002'])
def test_wrong_family_or_same_family_other_sample_never_reused(tmp_path,monkeypatch,replacement):
    service,job,_,_=prepared(tmp_path,'B_PP_03_0001')
    other_h5,_=exact_assets(service.settings.dataset_root,replacement)
    monkeypatch.setattr(BppPreviewPolicy,'resolve_h5',lambda self,root,sample:other_h5)
    with pytest.raises(CurrentPreviewError) as exc:service.prepare(job_id=job.id,kind='path')
    assert exc.value.code=='PREVIEW_H5_MISMATCH' and not service.runtime.calls


def test_same_family_samples_resolve_own_asset_paths(tmp_path):
    policy=BppPreviewPolicy()
    first=policy.resolve_h5(tmp_path,'B_PP_03_0001')
    second=policy.resolve_h5(tmp_path,'B_PP_06_0007')
    assert first!=second and second.parent.name=='B_PP_06_0007'
    assert second.parent.parent.name=='06(6mm)'
    with pytest.raises(CurrentPreviewError):policy.resolve_obj(tmp_path,'B_PR_03_0001')


def test_bpp_api_path_robot_split_and_existing_replay(tmp_path):
    service,job,_,_=prepared(tmp_path,'B_PP_03_0001');replay=FakeSimulator()
    with TestClient(create_app(workflow=Workflow(service.storage),simulator=replay,current_vla_preview=service,preview_runtime=service.runtime)) as api:
        caps=api.get('/api/simulator/current-vla/capabilities',params={'job_id':str(job.id)}).json()
        assert caps['path_preview_ready'] and not caps['robot_preview_ready']
        assert 'h5' not in json.dumps(caps).lower() and 'sha256' not in json.dumps(caps)
        for key in ('family','h5','obj','matrix'):
            assert api.post('/api/simulator/preview-current-vla/path',json={'job_id':str(job.id),key:'injected'}).status_code==422
        denied=api.post('/api/simulator/preview-current-vla',json={'job_id':str(job.id)})
        assert denied.status_code==409 and denied.json()['code']=='PREVIEW_PATH_SUPPORTED_ROBOT_PENDING'
        assert not service.runtime.calls
        assert api.post('/api/simulator/preview-current-vla/path',json={'job_id':str(job.id)}).status_code==202
        assert len(service.runtime.calls)==1 and not replay.calls
        assert api.post('/api/simulator/start',json={}).status_code==202
        replay.status()
        assert api.post('/api/simulator/run-sample',json={}).status_code==202
        assert replay.calls==['start','run']


def test_unknown_family_has_explicit_blocked_policy(tmp_path):
    with pytest.raises(CurrentPreviewError) as exc:default_registry().resolve('B_SS_03_0001')
    assert exc.value.code=='PREVIEW_FAMILY_UNSUPPORTED'


def test_new_family_needs_registration_only_not_main_preview_branch(tmp_path):
    service,job,_,_=prepared(tmp_path,'B_SS_03_0001')
    service.registry=PreviewPolicyRegistry([SourceFramePreviewPolicy('B_SS')])
    service.geometry.unlink();service.clearance.unlink()
    assert service.capabilities(job_id=job.id)['path_preview_ready']
    claim=service.prepare(job_id=job.id,kind='path')
    d,_,_=verify_preview(claim,project=service.settings.project)
    assert d['family']=='B_SS' and not d['show_workpiece']


def test_bpr_exact_audit_still_required_even_for_path(tmp_path):
    service,job,_,_=prepared(tmp_path)
    h5,_=exact_assets(service.settings.dataset_root,job.scene.sample_id)
    # Change an H5 attribute, keeping XYZ/GT identical: exact audit hash must still fail.
    with h5py.File(h5,'r+') as handle:handle.attrs['changed']='true'
    for kind in ('path','robot'):
        with pytest.raises(CurrentPreviewError) as exc:service.prepare(job_id=job.id,kind=kind)
        assert exc.value.code=='PREVIEW_H5_MISMATCH'


def test_owned_gate_conditioning_includes_native_output_and_rejects_edit(tmp_path):
    from backend.model_clients.guided_workflow import conditioning_hash
    from backend.schemas import NativeOutputReport, NativeCandidateValidation
    service,job,_,attempt=prepared(tmp_path,'B_PP_03_0001')
    job.native_output=NativeOutputReport(status='NATIVE_OUTPUT_VALIDATED',native_output_generated=True,
        validation=NativeCandidateValidation(status='PASS'))
    service.storage.save_job(job)
    manifest=read(attempt/'request_manifest.json');manifest['workflow_conditioning_sha256']=conditioning_hash(job)
    (attempt/'request_manifest.json').write_text(json.dumps(manifest))
    proof_path=service.storage.artifact_path('native_context',job.vla_prediction.artifact_id,'.vla.json')
    proof=read(proof_path);proof['files']['request_manifest.json']=sha(attempt/'request_manifest.json')
    proof_path.write_text(json.dumps(proof))
    claim=service.prepare(job_id=job.id,kind='path')
    verify_preview(claim,project=service.settings.project)
    job.native_output.artifacts['changed']=True;service.storage.save_job(job)
    with pytest.raises(ValueError):verify_preview(claim,project=service.settings.project)


@pytest.mark.parametrize('edit',['workpiece','transform','robot','physical'])
def test_neutral_path_child_gate_rejects_fixture_or_flag_injection(tmp_path,edit):
    service,job,_,_=prepared(tmp_path,'B_PP_03_0001');claim=service.prepare(job_id=job.id,kind='path')
    d=read(claim['path'])
    if edit=='workpiece':d['show_workpiece']=True;d['policy']['workpiece_preview_ready']=True
    elif edit=='transform':d['source_to_scene'][0][3]=1;d['policy']['source_to_scene']=d['source_to_scene']
    elif edit=='robot':d['kind']='robot';d['policy']['supports_robot_preview']=True
    else:d['physical_robot_executable']=True
    Path(claim['path']).write_text(json.dumps(d));claim['sha256']=sha(claim['path'])
    with pytest.raises(ValueError):verify_preview(claim,project=service.settings.project)


def test_path_runtime_does_not_require_robot_assets_or_bpr_evidence(tmp_path,monkeypatch):
    from tests.test_current_preview_configuration import configured
    _,service,_,_,_,launcher=configured(tmp_path,monkeypatch)
    (service.settings.simulator_root/'ATU01035_welding_tool.usd').unlink()
    service.geometry.unlink();service.clearance.unlink()
    assert configuration(service.runtime.config,kind='path')['configured']
    assert not configuration(service.runtime.config,kind='robot')['configured']
    assert not launcher.calls
