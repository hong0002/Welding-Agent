"""Stdlib-only immutable admission inside Isaac Python, before creating the GUI."""
import hashlib
import json
from pathlib import Path
from uuid import UUID
from backend.services.dataset_sample import resolve_sample


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def verify_preview(claim, *, project=None):
    project = (project or Path(__file__).resolve().parents[2]).resolve()
    path = Path(claim['path']).resolve()
    root = project / '.cache/simulator/current-previews/packages'
    if path.parent.parent != root or path.name != 'preview.json' or str(UUID(path.parent.name)) != path.parent.name:
        raise ValueError('Preview descriptor must be backend-owned')
    if sha(path) != claim['sha256']:
        raise ValueError('Preview descriptor changed')
    d = read(path)
    version = d['schema_version']
    if version=='current-vla-preview-final-v1':
        from backend.services.simulator_final_gate import verify
        return verify(d,path,project)
    if version=='robot-demo-preview-v1':
        from backend.services.robot_demo import verify
        return verify(d,path,project)
    if version in ('geometry-preview-v1','geometry-preview-v2'):
        from backend.services.geometry_preview import verify
        return verify(d,path,project)
    if version == 'current-vla-preview-stp-v1':
        from backend.services.simulator_stp_gate import verify
        return verify(d,path,project)
    if version == 'current-vla-preview-v3':
        from backend.services.simulator2_gate import verify
        return verify(d, path, project)
    if (version not in {'current-vla-preview-v1', 'current-vla-preview-v2'} or d['preview_id'] != path.parent.name or
            d['mode'] != 'CURRENT_VLA_UNVALIDATED_PREVIEW' or d['kind'] not in {'robot', 'path'} or
            d['point_count'] != 9 or d['fixture_ready'] is not False or d['validated_simulation'] is not False or
            d['physical_robot_executable'] is not False or d['registry_validated'] is not False or
            d['vla_orientation'] is not False):
        raise ValueError('Diagnostic flags/identity invalid')
    if version == 'current-vla-preview-v1':
        if d['orientation_source'] != 'simulator_fixture_policy' or d['clearance_warning'] != 'B_PR_TOOL_CLEARANCE_FAIL':
            raise ValueError('Legacy audited diagnostic flags changed')
    else:
        policy = d['policy']
        if (d['simulation_only'] is not True or d['orientation_source'] != 'simulator_preview_policy' or
                resolve_sample(d['sample_id']).family != d['family'] or policy['family'] != d['family'] or
                policy['supports_path_preview'] is not True or d['source_to_scene'] != policy['source_to_scene'] or
                d['show_workpiece'] != policy['workpiece_preview_ready'] or d['clearance_warning'] != policy['clearance_warning']):
            raise ValueError('Preview policy binding changed')
        if policy['frame_mode'] == 'source_frame':
            identity = [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
            if (d['kind'] != 'path' or d['show_workpiece'] or d['source_to_scene'] != identity or
                    d['object_translation_m'] is not None or d['flange_rotation'] is not None or
                    d['robot_base_placement'] is not None):
                raise ValueError('Neutral path preview must preserve source frame without fixture/robot')
        elif policy['frame_mode'] == 'audited_diagnostic_scene':
            if not policy['evidence_files'] or not d['show_workpiece'] or d['object_translation_m'] is None:
                raise ValueError('Unaudited scene placement')
        else:
            raise ValueError('Unknown display frame policy')
        if d['kind'] == 'robot' and (policy['supports_robot_preview'] is not True or not d['show_workpiece']):
            raise ValueError('Robot policy is pending')
    package_path = Path(d['package']).resolve()
    if (package_path.parent.parent != project / '.cache/simulator/prediction-packages' or
            package_path.name != 'package.json' or sha(package_path) != d['package_sha256']):
        raise ValueError('Immutable package changed')
    p = read(package_path); provenance = p['provenance']; sample = p['sample_id']
    if version == 'current-vla-preview-v2' and d['kind'] == 'path':
        if (p['schema_version'] != 'current-vla-path-package-v1' or p['orientation_policy'] != 'none_xyz_only' or
                p['orientation_source'] != 'simulator_preview_policy; not VLA' or
                p['preflight']['fixture_ready'] is not False or p['preflight'].get('current_preview_only') is not True):
            raise ValueError('Path-only package must not claim fixture orientation or readiness')
    if (p['artifact_id'] != d['artifact_id'] or p['package_id'] != d['package_id'] or sample != d['sample_id'] or
            p['point_count'] != 9 or p['physical_robot_executable'] is not False or p['is_robot_executable'] is not False or
            p['coordinate_frame'] != d['coordinate_frame'] or p['ade_mm'] != d['ade_mm'] or p['fde_mm'] != d['fde_mm']):
        raise ValueError('Current artifact differs from package')
    episode = package_path.parent / 'predictions' / sample
    if Path(p['prediction_root']).resolve() != episode.parent or Path(p['directory']).resolve() != package_path.parent:
        raise ValueError('Package prediction root changed')
    source = Path(provenance['source_attempt']).resolve()
    if not source.is_relative_to(project / '.cache') or source.name != p['attempt_id']:
        raise ValueError('Source attempt not backend-owned')
    checks = [(source / name, digest) for name, digest in provenance['source_files'].items()]
    checks += [(episode / 'trajectory.npz', provenance['source_files']['trajectory.npz']),
               (episode / 'metadata.json', provenance['metadata_sha256']),
               (p['h5'], provenance['h5_sha256']), (p['obj'], provenance['obj_sha256']),
               (source / 'completion.json', provenance['completion_sha256']),
               (source / 'request_manifest.json', provenance['request_manifest_sha256']),
               (provenance['source_job'], provenance['source_job_sha256']),
               (provenance['source_mask'], provenance['source_mask_sha256'])]
    if version == 'current-vla-preview-v1':
        checks += [(d['geometry'], d['geometry_sha256']), (d['clearance'], d['clearance_sha256'])]
    else:
        if (Path(p['h5']).stem != sample or Path(p['obj']).stem != sample or
                d['sample_assets']['h5_sha256'] != provenance['h5_sha256'] or
                d['sample_assets']['obj_sha256'] != provenance['obj_sha256']):
            raise ValueError('Exact query asset identity changed')
        checks += list(d['policy']['evidence_files'].items())
        code_root = Path(__file__).resolve().parents[2]
        expected_code = {'backend/current_vla_isaac_preview.py', 'backend/services/current_preview_gate.py',
                         'backend/services/preview_policy.py', 'backend/services/dataset_sample.py'}
        if set(d['owned_code']) != expected_code:
            raise ValueError('Owned renderer/policy fingerprint missing')
        checks += [(code_root/name, digest) for name, digest in d['owned_code'].items()]
    sim = Path(d['simulator_root']).resolve()
    for name, digest in provenance['simulator_files'].items():
        asset = (sim / name).resolve()
        if not asset.is_relative_to(sim):
            raise ValueError('Invalid simulator asset')
        checks.append((asset, digest))
    manifest = read(source / 'request_manifest.json')
    for name, digest in manifest['files'].items():
        file = (source / name).resolve()
        if not file.is_relative_to(source):
            raise ValueError('Invalid source input')
        checks.append((file, digest))
    if any(sha(file) != digest for file, digest in checks):
        raise ValueError('Prediction/approval/asset changed before preview')
    if d.get('job_id'):
        job_file = Path(d['job_file']).resolve()
        if not job_file.is_relative_to(project) or job_file.name != d['job_id'] + '.json':
            raise ValueError('Invalid job binding')
        job = read(job_file)
        conditioning = {k: job[k] for k in ('scene', 'mask', 'instruction', 'rough_mode', 'rough3d', 'rough_trajectory')}
        if job.get('native_output') is not None:
            conditioning['native_output'] = job['native_output']
        digest = hashlib.sha256(json.dumps(conditioning, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        if (job['state'] != 'VLA_READY' or job['vla_prediction']['artifact_id'] != d['artifact_id'] or
                digest != d['job_conditioning_sha256']):
            raise ValueError('Current job edited or replaced after admission')
    return d, p, episode / 'trajectory.npz'


def resolve_command(command, catalog, *, project=None):
    if (set(command) != {'type', 'artifact_id', 'mode', 'kind'} or command['type'] != 'preview_current_vla' or
            command['mode'] != 'unvalidated' or command['kind'] not in {'robot', 'path'}):
        raise ValueError('Preview queue does not accept paths/coordinates')
    artifact = str(UUID(command['artifact_id']))
    d, p, npz = verify_preview(catalog[artifact], project=project)
    if d['artifact_id'] != artifact or d['kind'] != command['kind']:
        raise ValueError('Queue artifact/kind differs')
    return d, p, npz
