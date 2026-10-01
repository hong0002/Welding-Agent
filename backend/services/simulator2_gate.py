"""Stdlib gate for dataset-v2 descriptors, before any Isaac import."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from backend.services.simulator2_contract import exact_assets, identity, NATIVE_FILES

OWNED_CODE = ('backend/current_vla_isaac_preview.py', 'backend/services/current_preview_gate.py',
    'backend/services/simulator2_gate.py', 'backend/services/simulator2_client.py',
    'backend/services/simulator2_contract.py', 'backend/simulator2_prepare.py')


def verify(d, path, project):
    from backend.services.current_preview_gate import read, sha
    if (d['backend']!='dataset_v2' or d['simulator_version']!='dataset_v2' or d['preview_id']!=path.parent.name
            or d['kind'] not in {'path','robot'} or d['point_count']!=9 or d['source_point_count']!=9
            or d['mode']!='CURRENT_VLA_UNVALIDATED_PREVIEW' or d['orientation_source']!='simulator2_policy'
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
    if (p['schema_version']!='simulator2-current-package-v1' or p['orientation_source']!='simulator2_policy'
            or p['orientation_policy']!='simulator2_native_fixture_policy' or p['artifact_id']!=d['artifact_id']
            or p['sample_id']!=d['sample_id'] or p['package_id']!=d['package_id'] or p['point_count']!=9
            or p['playback']!=d['playback'] or p['coordinate_frame']!=d['coordinate_frame']
            or p['ade_mm']!=d['ade_mm'] or p['fde_mm']!=d['fde_mm']
            or p['is_robot_executable'] is not False or p['physical_robot_executable'] is not False
            or p['simulation_only'] is not True or p['preflight']['fixture_ready'] is not False):
        raise ValueError('Dataset-v2 source/package flags differ')
    playback=p['playback']; native=p['preflight']['native']
    if (playback['source_artifact_id']!=d['artifact_id'] or playback['source_point_count']!=9
            or playback['derived'] is not True or playback['coordinate_frame']!='simulator2_scene' or playback['units']!='mm'
            or playback['playback_point_count']!=d['playback_point_count'] or d['playback_point_count']<9
            or native['sample_id']!=sample or native['kind']!=d['kind'] or native['prediction_input'] is not True
            or native['source_to_scene']!=d['source_to_scene']
            or (d['kind']=='robot' and native['robot_ready'] is not True)):
        raise ValueError('Dataset-v2 derived playback binding differs')
    episode=package_path.parent/'predictions'/sample
    if Path(p['directory']).resolve()!=package_path.parent or Path(p['prediction_root']).resolve()!=episode.parent:
        raise ValueError('Dataset-v2 source package path differs')
    h5,obj=exact_assets(d['dataset_root'],sample)
    if Path(p['h5']).resolve()!=h5 or Path(p['obj']).resolve()!=obj:
        raise ValueError('Dataset-v2 exact sample assets differ')
    source=Path(prov['source_attempt']).resolve()
    if not source.is_relative_to(project/'.cache') or source.name!=p['attempt_id']:
        raise ValueError('Invalid owned VLA attempt')
    checks=[(h5,prov['h5_sha256']),(obj,prov['obj_sha256']),
        (episode/'trajectory.npz',prov['source_files']['trajectory.npz']),
        (episode/'metadata.json',prov['metadata_sha256']),
        (source/'request_manifest.json',prov['request_manifest_sha256']), (source/'completion.json',prov['completion_sha256']),
        (prov['source_job'],prov['source_job_sha256']), (prov['source_mask'],prov['source_mask_sha256'])]
    if set(prov['source_files'])!={'response.json','trajectory.npz','metadata.json'}:
        raise ValueError('Invalid source file contract')
    checks += [(source/name,digest) for name,digest in prov['source_files'].items()]
    if set(d['native_files'])!={'trajectory_solution.npz','report.json'} or set(d['owned_code'])!=set(OWNED_CODE):
        raise ValueError('Native/owned code fingerprint missing')
    checks += [(package_path.parent/'native'/name,digest) for name,digest in d['native_files'].items()]
    code_root=Path(__file__).resolve().parents[2]
    checks += [(code_root/name,digest) for name,digest in d['owned_code'].items()]
    sim=Path(d['simulator_root']).resolve()
    if not set(NATIVE_FILES).issubset(prov['simulator_files']): raise ValueError('Native fingerprints missing')
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
    conditioning={k:job[k] for k in ('scene','mask','instruction','rough_mode','rough3d','rough_trajectory')}
    if job.get('native_output') is not None: conditioning['native_output']=job['native_output']
    digest=hashlib.sha256(json.dumps(conditioning,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    if (job['state']!='VLA_READY' or job['scene']['sample_id']!=sample or job['vla_prediction']['sample_id']!=sample
            or job['vla_prediction']['artifact_id']!=d['artifact_id'] or digest!=d['job_conditioning_sha256']
            or manifest['workflow_conditioning_sha256']!=digest or manifest['workflow_job_id']!=d['job_id']
            or manifest['sample_id']!=sample or manifest['split']!=job['scene']['split']
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
