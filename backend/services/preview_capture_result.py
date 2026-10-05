"""Backend completion admission: mandatory motion evidence, optional screenshots."""
import json
import numpy as np

from backend.services.preview_capture import CAPTURE_NAMES

CAPTURE_WARNING_CODES = frozenset({'CAPTURE_ASCII_PATH_UNAVAILABLE', 'CAPTURE_API_FAILED',
    'CAPTURE_FILE_WRITE_FAILED', 'CAPTURE_FILE_MISSING_TIMEOUT', 'CAPTURE_ZERO_BYTE',
    'CAPTURE_FILE_INCOMPLETE', 'CAPTURE_EVIDENCE_MISSING'})


def validate_result(data, output, latest, descriptor):
    expected = latest['playback_point_count'] if latest['kind']=='robot' else latest['point_count']
    if (data['playback_status']!='SUCCEEDED' or data['completed_playback_points']!=expected
            or data['displayed_playback_points']!=expected or data['robot_motion']!=(latest['kind']=='robot')
            or data['physics_stepping'] is not False or data['gt_is_target'] is not False
            or json.loads((output/'report.json').read_text(encoding='utf-8'))!=data):
        raise ValueError('Incomplete/mismatched playback report')
    from pathlib import Path
    package = Path(descriptor['package']).parent
    with np.load(package/'predictions'/latest['sample_id']/'trajectory.npz', allow_pickle=False) as source, \
            np.load(output/'waypoints.npz', allow_pickle=False) as recorded, \
            np.load(package/'native/trajectory_solution.npz', allow_pickle=False) as native:
        if descriptor.get('prediction_selection') and 'rendered_path_world_m' not in recorded.files:
            raise ValueError('Selected prediction requires actual rendered path evidence')
        transform = np.asarray(descriptor['source_to_scene'])
        world = source['predicted_path_m'].astype(float) @ transform[:3,:3].T + transform[:3,3]
        targets = native['tcp_pose_xyz_mm_rpy_deg'][:,:3]*.001 if latest['kind']=='robot' else world
        parameters = native['playback_waypoint_parameter'] if latest['kind']=='robot' else np.arange(latest['point_count'])
        if (not np.array_equal(recorded['predicted_path_m'],source['predicted_path_m'])
                or not np.array_equal(recorded['ground_truth_path_m'],source['ground_truth_path_m'])
                or not np.array_equal(recorded['source_to_scene'],transform)
                or not np.array_equal(recorded['playback_target_world_m'],targets)
                or not np.array_equal(recorded['playback_waypoint_parameter'],parameters)):
            raise ValueError('Source/derived playback evidence changed')
        # New renderer evidence includes the actual authored USD BasisCurves points.
        # Old completed reports remain readable; they are never relabelled as this proof.
        if 'rendered_path_world_m' in recorded.files:
            from backend.services.prediction_path_evidence import verify_rendered
            proof=verify_rendered(source['predicted_path_m'],transform,recorded['rendered_path_world_m'],native['predicted_source_xyz_m'])
            if any(data.get(k)!=v for k,v in proof.items()):raise ValueError('Prediction path proof differs')
            selection=descriptor.get('prediction_selection')
            if selection and (data.get('prediction_selection')!=selection or selection['source_xyz_sha256']!=proof['source_xyz_sha256']):
                raise ValueError('Selected artifact proof differs')
        measured = recorded['measured_tip_world_m']
        if (measured.shape!=(expected,3) or not np.isfinite(measured).all()
                or np.max(np.linalg.norm(measured-targets,axis=1))*1000>1):
            raise ValueError('FK playback incomplete or outside diagnostic tolerance')
    if latest['kind']=='robot' and (not data['robot_visual_meshes'] or
            any(v.get('finite') is not True or v.get('prim_created') is not True for v in data['robot_visual_meshes'])):
        raise ValueError('Robot visual evidence incomplete')
    attempts = data['capture_diagnostics']
    if len(attempts)!=4 or {x['name'] for x in attempts}!=set(CAPTURE_NAMES):
        raise ValueError('Capture diagnostic report invalid')
    warnings, successes = set(), []
    for entry in attempts:
        if entry['status']=='SUCCEEDED' and entry['reason_code'] is None:
            file = output/(entry['name']+'.png')
            if file.is_file() and file.stat().st_size>1000:
                successes.append(entry['name']+'.png')
            else:
                warnings.add('CAPTURE_EVIDENCE_MISSING')
        elif entry['status']=='FAILED' and entry['reason_code'] in CAPTURE_WARNING_CODES:
            warnings.add(entry['reason_code'])
        else:
            raise ValueError('Unknown diagnostic status')
    capture_status = 'FAILED' if not successes else 'PARTIAL_FAILED' if warnings else 'SUCCEEDED'
    return dict(playback_status='SUCCEEDED', capture_status=capture_status,
                path_source_is_current_prediction=data.get('path_source_is_current_prediction'),
                renderer_source_point_count=data.get('renderer_source_point_count'),
                capture_warning_codes=sorted(warnings),
                reason_code=('SIMULATOR_STP' if descriptor.get('backend')=='dataset_stp' else 'SIMULATOR2')+'_CAPTURE_WARNING' if warnings else None)
