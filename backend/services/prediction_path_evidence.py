"""Numeric source identity; no alignment, scaling, GT substitution or inference."""
import hashlib


def xyz_hash(points):
    import numpy as np
    a = np.asarray(points, dtype='<f8')
    if a.ndim != 2 or a.shape[1] != 3 or not np.isfinite(a).all():
        raise ValueError('Invalid prediction XYZ')
    return hashlib.sha256(a.tobytes(order='C')).hexdigest()


def selected_xyz(row):
    import numpy as np
    # A native continuous path must never bridge separate finite runs.
    if len(row['runs']) != 1 or row['units'] not in {'m', 'mm'}:
        raise ValueError('Selected source requires one continuous metric XYZ run')
    return np.asarray(row['runs'][0], dtype=float) * (.001 if row['units'] == 'mm' else 1.)


def verify_selection(row, predicted):
    import numpy as np
    selected = selected_xyz(row)
    # float32 Guided files and decimal JSON may differ by representational rounding.
    # This is a numeric comparison, never a transform or correction.
    if selected.shape != predicted.shape or not np.allclose(selected, predicted, atol=1e-8, rtol=0):
        raise ValueError('Selected XYZ differs from immutable model prediction')
    return dict(artifact_id=row['id'], output_kind=row.get('stage'), stage_index=row.get('stage_index'),
                label=row.get('label', 'Model prediction'), coordinate_frame=row['coordinate_frame'],
                units=row['units'], source_point_count=len(predicted), source_xyz_sha256=xyz_hash(predicted))


def verify_rendered(predicted, transform, rendered_world, playback_parent):
    import numpy as np
    predicted, transform, rendered_world = map(np.asarray, (predicted, transform, rendered_world))
    if (transform.shape!=(4,4) or not np.isfinite(transform).all() or
            not np.allclose(transform[3],[0,0,0,1],atol=1e-12,rtol=0) or
            not np.allclose(transform[:3,:3].T@transform[:3,:3],np.eye(3),atol=1e-9,rtol=0) or
            not np.isclose(np.linalg.det(transform[:3,:3]),1,atol=1e-9,rtol=0)):
        raise ValueError('Strict prediction render transform must be rigid SE(3)')
    world = predicted.astype(float) @ transform[:3, :3].T + transform[:3, 3]
    # USD points are Vec3f: allow only storage quantization, not trajectory changes.
    if rendered_world.shape != world.shape or not np.allclose(rendered_world, world, atol=2e-7, rtol=0):
        raise ValueError('Red BasisCurves differs from current prediction')
    if not np.array_equal(predicted, playback_parent):
        raise ValueError('Playback parent differs from current prediction')
    inverse = (rendered_world - transform[:3, 3]) @ transform[:3, :3]
    return dict(source_xyz_sha256=xyz_hash(predicted), package_source_xyz_sha256=xyz_hash(predicted),
                playback_parent_xyz_sha256=xyz_hash(playback_parent), renderer_source_point_count=len(rendered_world),
                renderer_inverse_error_m_max=float(np.max(np.abs(inverse-predicted))),
                path_source_is_current_prediction=True, path_parent_is_current_prediction=True,
                playback_parent_is_current_prediction=True, gt_is_target=False)


def verify_demo_source(geometry, arrays, mapping):
    import numpy as np
    original=np.asarray([p for run in geometry['runs'] for p in run],dtype=float)
    indices=arrays['source_indices']
    if (indices.ndim!=1 or indices.dtype.kind not in 'iu' or len(indices)<2 or
            np.any(indices<0) or np.any(indices>=len(original)) or np.any(np.diff(indices)<=0)):
        raise ValueError('Demo source indices differ')
    expected=(original[indices]-original[0])*mapping['uniform_scale']+np.asarray(mapping['anchor_tcp_m'])
    targets=arrays['demo_playback_points']
    if expected.shape!=targets.shape or not np.allclose(expected,targets,atol=1e-10,rtol=0):
        raise ValueError('Demo playback is not derived from selected prediction')
    digest=xyz_hash(original)
    return dict(source_xyz_sha256=digest,package_source_xyz_sha256=digest,
                playback_parent_xyz_sha256=digest,playback_parent_is_current_prediction=True,
                path_source_is_current_prediction=False,path_parent_is_current_prediction=True,
                path_transformed_from_current_prediction=True,gt_is_target=False)
