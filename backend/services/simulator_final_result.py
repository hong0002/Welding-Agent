"""Mandatory native completion evidence; numpy + stdlib only in Isaac child."""
from pathlib import Path
import hashlib
import numpy as np
from backend.viewport_capture_compat import png_dimensions


def observed_completion(descriptor,latest,output,*,playback_finished,scene_saved):
    """Admit native stdout evidence only together with bound saved artifacts."""
    if not playback_finished or not scene_saved:
        raise ValueError('Native completion markers missing')
    data={key:latest[key] for key in ('job_id','artifact_id','package_id','sample_id',
        'point_count','playback_point_count','request_id','session_id')}
    data.update(state='done',backend='dataset_final',exact_xyz_preserved=True,
        robot_motion=True,physics_stepping=True,gt_is_target=False,
        physical_robot_executable=False,vla_orientation=False,fixture_ready=False,
        orientation_source='simulator_final_policy',playback_finished=True,
        completion_source='owned_native_stdout_and_saved_artifacts')
    validate(data,output,latest,descriptor)
    data['observed_artifacts_sha256']={name:hashlib.sha256((output/name).read_bytes()).hexdigest()
        for name in ('scene.usda','scene.actual_weld.npz','start.png','middle.png','end.png')}
    return data


def validate(data,output,latest,descriptor):
    for key in ('job_id','artifact_id','package_id','sample_id','point_count','request_id','session_id'):
        if data.get(key)!=latest.get(key):raise ValueError('Native completion binding differs')
    if (data.get('state')!='done' or data.get('backend')!='dataset_final'
            or data.get('physical_robot_executable') is not False or data.get('vla_orientation') is not False
            or data.get('gt_is_target') is not False or data.get('exact_xyz_preserved') is not True
            or data.get('physics_stepping') is not True or data.get('robot_motion') is not True
            or data.get('playback_finished') is not True or data.get('playback_point_count')!=latest['playback_point_count']):
        raise ValueError('Native completion policy differs')
    if not (output/'scene.usda').is_file():raise ValueError('Native scene not saved')
    for label in ('start','middle','end'):png_dimensions((output/(label+'.png')).read_bytes())
    package=Path(descriptor['package']).parent
    with np.load(output/'scene.actual_weld.npz',allow_pickle=False) as measured, np.load(package/'native/trajectory_solution.npz',allow_pickle=False) as native, np.load(package/'predictions'/latest['sample_id']/'trajectory.npz',allow_pickle=False) as original:
        points=measured['actual_tip_path_world_m'];targets=native['tcp_pose_xyz_mm_rpy_deg'][:,:3]*.001
        world=original['predicted_path_m'].astype(float)@native['source_to_scene'][:3,:3].T+native['source_to_scene'][:3,3]
        if (not np.array_equal(original['predicted_path_m'],native['predicted_source_xyz_m'])
                or not np.allclose(world,native['raw_tcp_pose_xyz_mm_rpy_deg'][:,:3]*.001,atol=1e-9,rtol=0)):
            raise ValueError('Native target parent differs from original prediction')
        if (len(points)<2 or points.ndim!=2 or points.shape[1]!=3 or not np.isfinite(points).all()
                or max(np.linalg.norm(points[0]-targets[0]),np.linalg.norm(points[-1]-targets[-1]))>.001):
            raise ValueError('Native measured endpoints are missing or inconsistent')
