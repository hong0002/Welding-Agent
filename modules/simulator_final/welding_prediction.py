"""Read exported VLA XYZ predictions without aligning away prediction error."""
import json
from pathlib import Path

import numpy as np

DEFAULT_PREDICTIONS = Path(__file__).resolve().parents[2] / 'welding_validation_all'


def penultimate_error_mm(predicted_m, gt_m):
    """Pointwise error at index -2 of the stored path, before simulator densification."""
    predicted, gt = np.asarray(predicted_m), np.asarray(gt_m)
    if predicted.shape != gt.shape or predicted.ndim != 2 or predicted.shape[1] != 3 or len(predicted) < 2:
        raise ValueError('PRE-END requires matching (N>=2,3) paths')
    error = float(np.linalg.norm(predicted[-2]-gt[-2])*1000)
    if not np.isfinite(error):
        raise ValueError('PRE-END contains a non-finite coordinate')
    return error


def _point_to_polyline_distances(points, polyline):
    """Return each point's Euclidean distance to a piecewise-linear path."""
    points = np.asarray(points, dtype=float)
    polyline = np.asarray(polyline, dtype=float)
    starts, vectors = polyline[:-1], np.diff(polyline, axis=0)
    squared_lengths = np.einsum('ij,ij->i', vectors, vectors)
    valid = squared_lengths > 1e-18
    starts, vectors, squared_lengths = starts[valid], vectors[valid], squared_lengths[valid]
    if not len(starts):
        return np.linalg.norm(points - polyline[0], axis=1)
    offsets = points[:, None, :] - starts[None, :, :]
    fractions = np.einsum('nsi,si->ns', offsets, vectors) / squared_lengths
    fractions = np.clip(fractions, 0., 1.)
    projections = starts[None, :, :] + fractions[:, :, None] * vectors[None, :, :]
    return np.sqrt(np.min(np.sum((points[:, None, :] - projections) ** 2, axis=2), axis=1))


def _polyline_geometry_error_mm(first, second):
    """Symmetric path error with ordered endpoints, independent of point spacing."""
    endpoint_error = max(np.linalg.norm(first[0] - second[0]),
                         np.linalg.norm(first[-1] - second[-1]))
    return float(max(endpoint_error,
                     _point_to_polyline_distances(first, second).max(),
                     _point_to_polyline_distances(second, first).max()) * 1000)


def prediction_index(root):
    result = {}
    root = Path(root)
    paths = sorted(root.glob('*/metadata.json'))
    if not paths:
        # Container exports may have train/valid children; reference banks are not predictions.
        paths = sorted(p for p in root.glob('*/*/metadata.json')
                       if p.parent.parent.name != 'retrieval_bank')
    for path in paths:
        metadata = json.loads(path.read_text(encoding='utf-8'))
        sample = metadata.get('episode_id') or metadata.get('sample_id')
        if not sample:
            continue
        if sample in result:
            raise ValueError(f'Duplicate VLA episode {sample}: {result[sample]} and {path.parent}; select a specific export folder')
        if not (path.parent / 'trajectory.npz').is_file():
            raise FileNotFoundError(path.parent / 'trajectory.npz')
        result[sample] = path.parent
    if not result:
        raise FileNotFoundError(f'No exported VLA episodes under {root}')
    return result


def prediction_targets(directory, sample, source_poses, gt_scene_poses, source_to_scene, stage="final"):
    directory = Path(directory)
    metadata = json.loads((directory / 'metadata.json').read_text(encoding='utf-8'))
    if (metadata.get('episode_id') or metadata.get('sample_id')) != sample:
        raise ValueError('VLA episode does not match the selected H5 sample')
    if (metadata.get('coordinate_frame') not in ('source_robot_frame_unaligned_with_isaac', 'dataset/source-frame')
            or metadata.get('source_units') != 'mm'
            or not np.isclose(metadata.get('scale_to_meters', 0), .001)):
        raise ValueError('Unsupported VLA export units/frame; refusing to guess a transform')
    with np.load(directory / 'trajectory.npz', allow_pickle=False) as data:
        predicted = np.asarray(data['predicted_path_m'], dtype=float)
        gt = np.asarray(data['ground_truth_path_m'], dtype=float)
        for name, points in (('predicted', predicted), ('ground_truth', gt)):
            if points.ndim != 2 or points.shape[1] != 3 or len(points) < 2 or not np.isfinite(points).all():
                raise ValueError(f'{name}: expected finite (N>=2,3) XYZ positions')
            source_key = name + '_path_xyz'
            if source_key in data and not np.allclose(points, data[source_key] * .001, atol=1e-7, rtol=0):
                raise ValueError(f'{name}: inconsistent meters/source-unit arrays')
    if predicted.shape != gt.shape:
        raise ValueError('Prediction and GT export lengths differ')
    # Exports use index, arc-length, or nonuniform corner-preserving keypoints.
    # Accept only an explicit match to the same H5 geometry; never align/warp GT.
    source = source_poses[:, :3] * .001
    index_grid = np.arange(len(source))
    arc_grid = np.r_[0., np.linalg.norm(np.diff(source, axis=0), axis=1).cumsum()]
    errors = {}
    for method, grid in (('index', index_grid), ('arc_length', arc_grid)):
        if grid[-1] <= 0:
            continue
        unique, positions = np.unique(grid, return_index=True)
        expected = np.column_stack([
            np.interp(np.linspace(0, grid[-1], len(gt)), unique, source[positions, j])
            for j in range(3)])
        errors[method] = float(np.linalg.norm(gt-expected, axis=1).max() * 1000)
    errors['polyline_geometry'] = _polyline_geometry_error_mm(source, gt)
    resampling = min(errors, key=errors.get) if errors else 'none'
    frame_error_mm = errors.get(resampling, float('inf'))
    if frame_error_mm > .05:
        raise ValueError(f'VLA GT does not match the H5 coordinate frame ({frame_error_mm:.3f} mm; '
                         f'alignment checks: {errors})')
    if stage == 'rough':
        response = json.loads((directory / 'rough.json').read_text(encoding='utf-8'))
        offsets = np.asarray([[point[axis] for axis in ('x', 'y', 'z')]
                              for point in response['proposal']['points']], dtype=float)
        predicted = (offsets + np.asarray(metadata['start_xyz'], dtype=float)) * .001
        if predicted.ndim != 2 or predicted.shape[1] != 3 or len(predicted) < 2 or not np.isfinite(predicted).all():
            raise ValueError('rough.json requires finite XYZ points')
        # Match the evaluator: retain native rough points; sample GT at their arc progress.
        progress = np.r_[0., np.linalg.norm(np.diff(predicted, axis=0), axis=1).cumsum()]
        progress = progress / progress[-1] if progress[-1] > 0 else np.linspace(0, 1, len(predicted))
        gt_arc = np.r_[0., np.linalg.norm(np.diff(gt, axis=0), axis=1).cumsum()]
        unique, indices = np.unique(gt_arc, return_index=True)
        gt = np.column_stack([np.interp(progress * gt_arc[-1], unique, gt[indices, axis]) for axis in range(3)])
        print(f'[ROUGH] {sample}: replaying {len(predicted)} original GPT points (no 33-point refinement)', flush=True)
    rotation, translation = source_to_scene[:3, :3], source_to_scene[:3, 3]
    predicted_world = predicted @ rotation.T + translation
    gt_world = gt @ rotation.T + translation
    # XYZ-only model: retain one declared initial orientation, no GT pose sequence
    # is substituted for the model's position outputs.
    poses = np.tile(gt_scene_poses[0], (len(predicted), 1))
    poses[:, :3] = predicted_world * 1000
    errors_mm = np.linalg.norm(predicted-gt, axis=1) * 1000
    arrays = dict(trajectory_source=np.asarray('vla_prediction'),
                  predicted_source_xyz_m=predicted, ground_truth_source_xyz_m=gt,
                  predicted_world_xyz_m=predicted_world, ground_truth_world_xyz_m=gt_world,
                  planned_tcp_xyz_world_m=gt_world,
                  prediction_orientation_policy=np.asarray('fixed_initial_fixture_pose'))
    report = dict(source_directory=str(directory.resolve()),
                  position_source='GPT rough.json' if stage == 'rough' else 'VLA predicted_path_m',
                  prediction_stage=stage, native_point_count=len(predicted),
                  orientation_policy='Fixed initial fixture pose; VLA export contains XYZ only',
                  gt_h5_frame_error_mm_max=frame_error_mm,
                  gt_h5_resampling=resampling,
                  ade_mm=float(errors_mm[1:].mean()), fde_mm=float(errors_mm[-1]),
                  penultimate_error_mm=penultimate_error_mm(predicted, gt),
                  penultimate_error_index=-2,
                  max_error_mm=float(errors_mm[1:].max()),
                  error_alignment='One identical GT-derived rigid transform for GT and prediction')
    print(f'[VLA] {sample}: {len(poses)} XYZ points; fixed initial orientation; '
          f'ADE={report["ade_mm"]:.3f} mm, FDE={report["fde_mm"]:.3f} mm, '
          f'PRE-END={report["penultimate_error_mm"]:.3f} mm', flush=True)
    return poses, arrays, report
