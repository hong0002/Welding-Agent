"""GPT2 native export verification. No inference, coordinate repair or NPZ writer."""
import hashlib
import json
from pathlib import Path
import numpy as np
from backend.model_clients.trajectory_contracts import GPT2PredictedTrajectory

FRAME = 'source_robot_frame_unaligned_with_isaac'
NPZ_KEYS = {'predicted_path_m', 'ground_truth_path_m', 'predicted_path_xyz',
            'ground_truth_path_xyz', 'start_xyz', 'predicted_delta_xyz',
            'ground_truth_delta_xyz', 'corner_indices', 'connections', 'original_ground_truth_path_m'}


PREDICTION_KEYS = {'predicted_path_xyz','predicted_path_m','start_xyz','predicted_delta_xyz','corner_indices','connections'}
PREDICTION_SCHEMA = 'gpt2-prediction-only-v1'

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def native_arrays(directory, manifest):
    """Use native numeric arrays directly. Known start/units must agree exactly."""
    directory = Path(directory)
    meta = read(directory / 'metadata.json')
    if (read(directory / 'status.json').get('status') != 'complete' or
            meta['episode_id'] != manifest['sample_id'] or meta['split'] != manifest['split'] or
            meta['coordinate_frame'] != FRAME or meta['source_units'] != 'mm' or
            meta['scale_to_meters'] != .001 or meta['output_points'] != manifest['output_points'] or
            meta['experiment'] != 'full' or meta['gt_path_used_as_model_input'] is not False or
            meta['gt_endpoint_used_as_model_input'] is not False or
            meta['gt_interior_path_used_as_model_input'] is not False or
            meta['mask_policy'] != 'all_available_gt_seam_annotations' or
            meta['retrieval_used'] is not True or meta['rough_stage_used'] is not True or
            set(meta['stages']) != {'rough', 'corners'}):
        raise ValueError('GPT2_NATIVE_OUTPUT_INVALID')
    prediction_only=manifest.get('prediction_only') is True
    if prediction_only and (meta.get('prediction_schema')!=PREDICTION_SCHEMA or meta.get('prediction_only') is not True or
            meta.get('evaluation_performed') is not False or meta.get('known_start_application_count')!=1 or
            meta.get('model')!=manifest['model'] or meta.get('reasoning_effort')!=manifest['reasoning_effort'] or
            read(directory/'status.json').get('prediction_only') is not True or
            read(directory/'status.json').get('prediction_schema')!=PREDICTION_SCHEMA or
            any('ground_truth' in k or 'metrics' in k or 'baseline' in k for k in meta)):
        raise ValueError('GPT2_PREDICTION_ONLY_CONTRACT_INVALID')
    with np.load(directory / 'trajectory.npz', allow_pickle=False) as archive:
        if set(archive.files) != (PREDICTION_KEYS if prediction_only else NPZ_KEYS): raise ValueError('GPT2_NPZ_SCHEMA_INVALID')
        a = {k: archive[k] for k in archive.files}
    n = meta['output_points']
    for name in (('predicted_path_m','predicted_path_xyz') if prediction_only else ('predicted_path_m', 'ground_truth_path_m', 'predicted_path_xyz', 'ground_truth_path_xyz')):
        if a[name].dtype != np.float64 or a[name].shape != (n, 3) or not np.isfinite(a[name]).all():
            raise ValueError('GPT2_NATIVE_OUTPUT_INVALID')
    start = a['start_xyz']
    if (start.dtype != np.float64 or start.shape != (3,) or not np.isfinite(start).all() or
            not np.array_equal(start, manifest['known_start_xyz_mm']) or
            not np.array_equal(start, meta['start_xyz'])):
        raise ValueError('GPT2_KNOWN_START_INVALID')
    for name in (('predicted',) if prediction_only else ('predicted', 'ground_truth')):
        xyz = a[name + '_path_xyz']
        units_equal=(np.array_equal(a[name+'_path_m'],xyz*.001) if name=='predicted' else
                     np.allclose(a[name+'_path_m'],xyz*.001,rtol=0,atol=1e-15))
        if (not units_equal or
                not np.array_equal(a[name + '_delta_xyz'], np.diff(xyz, axis=0))):
            raise ValueError('GPT2_UNIT_OR_DELTA_MISMATCH')
    modes = a['connections']
    if modes.shape != (n-1,) or any(str(v) not in ('within_segment', 'between_segments', 'unknown') for v in modes):
        raise ValueError('GPT2_CONNECTIONS_INVALID')
    corners = read(directory / 'corners.json')['proposal']['points']
    indices = a['corner_indices']
    if (indices.dtype.kind not in 'iu' or indices.ndim != 1 or len(indices) != len(corners) or
            len(indices) < 2 or indices[0] != 0 or indices[-1] != n-1 or
            np.any(np.diff(indices) <= 0)):
        raise ValueError('GPT2_CORNERS_INVALID')
    corner_xyz = np.asarray([[p['x'], p['y'], p['z']] for p in corners], dtype=float)
    if not np.array_equal(a['predicted_path_xyz'][indices], start + corner_xyz):
        raise ValueError('GPT2_START_OR_AXIS_MISMATCH')
    if prediction_only: return meta,a
    with np.load(manifest['baseline_snapshot_npz'], allow_pickle=False) as baseline:
        original_gt = np.asarray(baseline['ground_truth_path_m'], dtype=float)
    if not np.array_equal(a['original_ground_truth_path_m'], original_gt):
        raise ValueError('GPT2_BASELINE_GT_CHANGED')
    # GT resampling is checked with the original native evaluator, not reimplemented.
    if len(original_gt) != n:
        namespace = {'__name__': 'gpt2_native_evaluator'}
        file = Path(manifest['repository']) / 'interpolate.py'
        exec(compile(file.read_bytes(), str(file), 'exec'), namespace)
        expected_gt = namespace['uniform_arc'](original_gt * 1000, n)
    else: expected_gt = original_gt * 1000
    if not np.array_equal(a['ground_truth_path_xyz'], expected_gt):
        raise ValueError('GPT2_NATIVE_GT_POLICY_MISMATCH')
    errors = np.linalg.norm(a['predicted_path_xyz'] - expected_gt, axis=1)
    if not np.allclose([errors.mean(), errors[-1]],
                       [meta['metrics']['ade_source_units'], meta['metrics']['fde_source_units']], atol=1e-10, rtol=1e-10):
        raise ValueError('GPT2_METRICS_INVALID')
    return meta, a


def verify_completed_gpt2(attempt, manifest, job, *, simulation_preview=False):
    attempt = Path(attempt).resolve()
    done = read(attempt / 'completion.json')
    if (done.get('response_validated') is not True or done['attempt_id'] != attempt.name or
            set(done['files']) != {'response.json', 'metadata.json', 'trajectory.npz'} or
            any(sha(attempt / n) != h for n, h in done['files'].items())):
        raise ValueError('GPT2_COMPLETION_CHANGED')
    if (manifest['backend'] != 'gpt2' or manifest['source'] != 'vlm_final_gpt2' or
            manifest['workflow_job_id'] != job['id'] or manifest['sample_id'] != job['scene']['sample_id'] or
            manifest['split'] != job['scene']['split'] or manifest['attempt_id'] != attempt.name or
            manifest['web_masks_used_as_input'] is not False or
            manifest['trajectory3_used_as_input'] is not False or manifest['reference_in_request'] is not True or
            manifest['references_supplied_by_adapter'] is not False):
        raise ValueError('GPT2_LINEAGE_INVALID')
    conditioning = {k: job[k] for k in ('scene','mask','instruction','rough_mode','rough3d','rough_trajectory')}
    if job.get('native_output') is not None: conditioning['native_output'] = job['native_output']
    digest = hashlib.sha256(json.dumps(conditioning, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    if digest != manifest['workflow_conditioning_sha256']: raise ValueError('GPT2_CURRENT_INPUT_CHANGED')
    checks = [(manifest['source_job'], manifest['source_job_sha256']),
              (manifest['source_mask'], manifest['source_mask_sha256']),
              (manifest['h5'], manifest['h5_sha256']), (manifest['obj'], manifest['obj_sha256'])]
    for n, h in manifest['files'].items():
        path = (attempt / n).resolve()
        if not path.is_relative_to(attempt): raise ValueError('GPT2_INPUT_PATH_INVALID')
        checks.append((path, h))
    checks += [(Path(manifest['repository']) / n, h) for n, h in manifest['native_code'].items()]
    checks += [(Path(manifest['shared_root']) / n, h) for n, h in manifest['shared_code'].items()]
    native = (attempt / manifest['native_directory']).resolve()
    if not native.is_relative_to(attempt / 'native'): raise ValueError('GPT2_NATIVE_PATH_INVALID')
    for n, h in done['native_files'].items():
        path = (attempt / n).resolve()
        if not path.is_relative_to(attempt / 'native'): raise ValueError('GPT2_NATIVE_PATH_INVALID')
        checks.append((path, h))
    if any(sha(path) != h for path, h in checks): raise ValueError('GPT2_IMMUTABLE_INPUT_CHANGED')
    if read(attempt / 'process_exit.json').get('exit_code') != 0: raise ValueError('GPT2_PROCESS_FAILED')
    metadata, arrays = native_arrays(native, manifest)
    if sha(native / 'trajectory.npz') != sha(attempt / 'trajectory.npz'):
        raise ValueError('GPT2_NPZ_COPY_CHANGED')
    response = GPT2PredictedTrajectory.model_validate(read(attempt / 'response.json'))
    if (str(response.artifact_id) != manifest['artifact_id'] or response.sample_id != manifest['sample_id'] or
            response.split != manifest['split'] or response.point_count != len(arrays['predicted_path_m']) or
            not np.array_equal(response.predicted_path_xyz_mm, arrays['predicted_path_xyz']) or
            (not response.prediction_only and not np.array_equal(response.ground_truth_path_xyz_mm, arrays['ground_truth_path_xyz'])) or
            response.prediction_only != manifest.get('prediction_only',False) or
            response.connections != arrays['connections'].tolist()):
        raise ValueError('GPT2_NORMALIZATION_CHANGED')
    owned_meta = read(attempt / 'metadata.json')
    if (owned_meta['source'] != 'vlm_final_gpt2' or owned_meta['native_output_hash'] != sha(native / 'trajectory.npz') or
            owned_meta['artifact_id'] != str(response.artifact_id) or owned_meta['attempt_id'] != attempt.name):
        raise ValueError('GPT2_PROVENANCE_CHANGED')
    if simulation_preview and any(v != 'within_segment' for v in response.connections):
        raise ValueError('GPT2_DISCONNECTED_PATH_NOT_EXECUTABLE')
    return response
