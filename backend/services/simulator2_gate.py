"""Stdlib gate for dataset-v2 descriptors, before any Isaac import."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from backend.services.simulator2_contract import exact_assets, identity, NATIVE_FILES

OWNED_CODE = ('backend/current_vla_isaac_preview.py', 'backend/services/current_preview_gate.py',
    'backend/services/simulator2_gate.py', 'backend/services/simulator2_client.py',
    'backend/services/simulator2_contract.py', 'backend/simulator2_prepare.py',
    'backend/services/preview_capture.py', 'backend/services/preview_visual_style.py',
    'backend/services/preview_live_producer.py', 'backend/services/final_prediction_proof.py',
    'backend/services/prediction_path_evidence.py','backend/services/sample_scene.py',
    'backend/services/gpt2_prediction_proof.py','backend/model_clients/trajectory_contracts.py')


def verify(d, path, project, *, stp=False, final=False):
    from backend.services.current_preview_gate import read, sha
    backend='dataset_stp' if stp else 'dataset_v2'
    orientation='simulator_stp_policy' if stp else 'simulator2_policy'
    policy='simulator_stp_native_fixture_policy' if stp else 'simulator2_native_fixture_policy'
    schema='simulator-stp-current-package-v1' if stp else 'simulator2-current-package-v1'
    frame='simulator_stp_scene' if stp else 'simulator2_scene'
    files,owned=NATIVE_FILES,OWNED_CODE
    if final:
        backend,orientation,policy,schema,frame=('dataset_final','simulator_final_policy',
            'simulator_final_native_fixture_policy','simulator-final-current-package-v1','simulator_final_scene')
        from backend.services.simulator_final_contract import NATIVE_FILES as files
        from backend.services.simulator_final_gate import OWNED_CODE as owned
        if d.get('native_layout')!='stp' or d.get('cad_source')!='sample_obj' or d.get('environment_source')!='stp_reference_layout' or d['kind']!='robot':
            raise ValueError('Final native renderer contract differs')
    prediction_source=d.get('prediction_source','guided_vla')
    visualization_source=d.get('visualization_source',False)
    if prediction_source not in {'guided_vla','vlm_final_gpt','vlm_final_gpt2'}:raise ValueError('Unknown final predictor')
    count=d['point_count'] if prediction_source=='vlm_final_gpt2' else 33 if prediction_source=='vlm_final_gpt' else 9
    if type(count) is not int or not 2<=count<=4096:raise ValueError('Invalid native point count')
    if stp:
        from backend.services.simulator_stp_contract import NATIVE_FILES as files
        from backend.services.simulator_stp_gate import OWNED_CODE as owned
        if d.get('native_layout')!='stp' or d.get('cad_source')!='sample_obj' or d.get('environment_source')!='stp_reference_layout':
            raise ValueError('STP layout descriptor differs')
    if (d['backend']!=backend or d['simulator_version']!=backend or d['preview_id']!=path.parent.name
            or d['kind'] not in {'path','robot'} or d['point_count']!=count or d['source_point_count']!=count
            or d['mode']!='CURRENT_VLA_UNVALIDATED_PREVIEW' or d['orientation_source']!=orientation
            or d['coordinate_frame']!='source_robot_frame_unaligned_with_isaac'
            or any(d[k] is not False for k in ('fixture_ready','physical_robot_executable','validated_simulation','registry_validated','vla_orientation'))
            or d['simulation_only'] is not True or identity(d['sample_id'])[0]!=d['family']):
        raise ValueError('Dataset-v2 diagnostic contract differs')
    package_path=Path(d['package']).resolve()
    if (package_path.name!='package.json' or package_path.parent.parent!=project/'.cache/simulator/prediction-packages'
            or package_path.parent.name!=d['package_id'] or str(UUID(d['package_id']))!=d['package_id']
            or sha(package_path)!=d['package_sha256']):
        raise ValueError('Dataset-v2 package ownership/hash differs')
    p=read(package_path); prov=p['provenance']; sample=p['sample_id']
    if (p['schema_version']!=schema or p['orientation_source']!=orientation
            or p['orientation_policy']!=policy or p['artifact_id']!=d['artifact_id']
            or p['sample_id']!=d['sample_id'] or p['package_id']!=d['package_id'] or p['point_count']!=count
            or p.get('prediction_source','guided_vla')!=prediction_source
            or p['playback']!=d['playback'] or p['coordinate_frame']!=d['coordinate_frame']
            or p['ade_mm']!=d['ade_mm'] or p['fde_mm']!=d['fde_mm']
            or p['is_robot_executable'] is not False or p['physical_robot_executable'] is not False
            or p['simulation_only'] is not True or p['preflight']['fixture_ready'] is not False):
        raise ValueError('Dataset-v2 source/package flags differ')
    playback=p['playback']; native=p['preflight']['native']
    if (playback['source_artifact_id']!=d['artifact_id'] or playback['source_point_count']!=count
            or playback['derived'] is not True or playback['coordinate_frame']!=frame or playback['units']!='mm'
            or playback['playback_point_count']!=d['playback_point_count'] or d['playback_point_count']<count
            or native['sample_id']!=sample or native['kind']!=d['kind'] or native['prediction_input'] is not True
            or native['source_to_scene']!=d['source_to_scene']
            or (d['kind']=='robot' and native['robot_ready'] is not True)):
        raise ValueError('Dataset-v2 derived playback binding differs')
    if (stp or final) and (native.get('native_layout')!='stp' or native.get('native_flags')!=['--layout','stp']
            or native.get('cad_source')!='sample_obj' or native['environment']['layout']!='stp'):
        raise ValueError('Native STP evidence missing')
    episode=package_path.parent/'predictions'/sample
    if Path(p['directory']).resolve()!=package_path.parent or Path(p['prediction_root']).resolve()!=episode.parent:
        raise ValueError('Dataset-v2 source package path differs')
    h5,obj=exact_assets(d['dataset_root'],sample)
    if Path(p['h5']).resolve()!=h5 or Path(p['obj']).resolve()!=obj:
        raise ValueError('Dataset-v2 exact sample assets differ')
    source=Path(prov['source_attempt']).resolve()
    if not source.is_relative_to(project/'.cache') or source.name!=p['attempt_id']:
        raise ValueError('Invalid owned VLA attempt')
    companion=prov.get('prediction_companion')
    if companion is not None:
        if not final or prediction_source!='vlm_final_gpt2' or visualization_source:
            raise ValueError('Prediction-only companion requires completed GPT2 STRICT final')
        from backend.services.gpt2_simulator_companion import verify_companion
        verify_companion(episode,source/'trajectory.npz',h5,companion)
    checks=[(h5,prov['h5_sha256']),(obj,prov['obj_sha256']),
        (episode/'trajectory.npz',companion['simulator_input_sha256'] if companion else prov['source_files']['trajectory.npz']),
        (episode/'metadata.json',prov['metadata_sha256']),
        (source/'request_manifest.json',prov['request_manifest_sha256']),
        (prov['source_job'],prov['source_job_sha256']), (prov['source_mask'],prov['source_mask_sha256'])]
    if prov.get('completion_sha256') is not None:
        checks.append((source/'completion.json',prov['completion_sha256']))
    elif not visualization_source:raise ValueError('Missing source completion')
    if set(prov['source_files'])!={'response.json','trajectory.npz','metadata.json'}:
        raise ValueError('Invalid source file contract')
    checks += [(source/name,digest) for name,digest in prov['source_files'].items()]
    if set(d['native_files'])!={'trajectory_solution.npz','report.json'} or set(d['owned_code'])!=set(owned):
        raise ValueError('Native/owned code fingerprint missing')
    checks += [(package_path.parent/'native'/name,digest) for name,digest in d['native_files'].items()]
    code_root=Path(__file__).resolve().parents[2]
    checks += [(code_root/name,digest) for name,digest in d['owned_code'].items()]
    sim=Path(d['simulator_root']).resolve()
    if not set(files).issubset(prov['simulator_files']): raise ValueError('Native fingerprints missing')
    for name,digest in prov['simulator_files'].items():
        file=(sim/name).resolve()
        if not file.is_relative_to(sim): raise ValueError('Invalid native asset path')
        checks.append((file,digest))
    manifest=read(source/'request_manifest.json')
    for name,digest in manifest['files'].items():
        file=(source/name).resolve()
        if not file.is_relative_to(source): raise ValueError('Invalid attempt input')
        checks.append((file,digest))
    job_file=Path(d['job_file']).resolve()
    if not job_file.is_relative_to(project) or job_file.name!=d['job_id']+'.json': raise ValueError('Wrong job file')
    job=read(job_file)
    if prediction_source=='vlm_final_gpt':
        from backend.services.final_prediction_proof import verify_completed_gpt
        verify_completed_gpt(source,manifest,job,simulation_preview=visualization_source)
    if prediction_source=='vlm_final_gpt2':
        from backend.services.gpt2_prediction_proof import verify_completed_gpt2
        result=verify_completed_gpt2(source,manifest,job,simulation_preview=True)
        if result.point_count!=count:raise ValueError('GPT2 native count differs')
        if result.prediction_only and final and companion is None:
            raise ValueError('Prediction-only requires simulator diagnostic companion')
    conditioning={k:job[k] for k in ('scene','mask','instruction','rough_mode','rough3d','rough_trajectory')}
    if job.get('native_output') is not None: conditioning['native_output']=job['native_output']
    digest=hashlib.sha256(json.dumps(conditioning,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    if (job['scene']['sample_id']!=sample or digest!=d['job_conditioning_sha256']
            or manifest['workflow_conditioning_sha256']!=digest or manifest['workflow_job_id']!=d['job_id']
            or manifest['sample_id']!=sample or manifest['split']!=job['scene']['split']):
        raise ValueError('Current job/approval/identity changed')
    if visualization_source:
        if prediction_source not in {'vlm_final_gpt','vlm_final_gpt2'} or job['raw_final_prediction']['artifact_id']!=d['artifact_id']:
            raise ValueError('Current GPT source changed')
    elif (job['state']!='VLA_READY' or job['vla_prediction']['sample_id']!=sample or job['vla_prediction']['artifact_id']!=d['artifact_id']
            or manifest['source_mask_id']!=job['mask']['id']
            or datetime.fromisoformat(manifest['approved_at'])!=datetime.fromisoformat(job['mask']['approved_at'])):
        raise ValueError('Current job/approval/identity changed')
    scene=read(job_file.parent.parent/'native_context'/(d['job_id']+'.scene.json'))
    checks += [(scene['images'][view],digest) for view,digest in manifest['scene_source_sha256'].items()]
    checks += [(job_file.parent.parent/'scenes'/(job['scene']['views'][view]['image_id']+'.png'),digest)
               for view,digest in manifest['scene_normalized_sha256'].items()]
    checks += [(Path(manifest['rough_session'])/name,digest) for name,digest in manifest['rough_source_files'].items()]
    if any(sha(file)!=digest for file,digest in checks): raise ValueError('Immutable source/native/asset hash changed')
    return d,p,episode/'trajectory.npz'
