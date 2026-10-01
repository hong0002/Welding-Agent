"""Stdlib-only immutable admission inside Isaac Python, before creating the GUI."""
import hashlib
import json
from pathlib import Path
from uuid import UUID


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
    if (d['schema_version'] != 'current-vla-preview-v1' or d['preview_id'] != path.parent.name or
            d['mode'] != 'CURRENT_VLA_UNVALIDATED_PREVIEW' or d['kind'] not in {'robot', 'path'} or
            d['point_count'] != 9 or d['fixture_ready'] is not False or d['validated_simulation'] is not False or
            d['physical_robot_executable'] is not False or d['registry_validated'] is not False or
            d['vla_orientation'] is not False or d['orientation_source'] != 'simulator_fixture_policy' or
            d['clearance_warning'] != 'B_PR_TOOL_CLEARANCE_FAIL'):
        raise ValueError('Diagnostic flags/identity invalid')
    package_path = Path(d['package']).resolve()
    if (package_path.parent.parent != project / '.cache/simulator/prediction-packages' or
            package_path.name != 'package.json' or sha(package_path) != d['package_sha256']):
        raise ValueError('Immutable package changed')
    p = read(package_path); provenance = p['provenance']; sample = p['sample_id']
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
               (provenance['source_mask'], provenance['source_mask_sha256']),
               (d['geometry'], d['geometry_sha256']), (d['clearance'], d['clearance_sha256'])]
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
