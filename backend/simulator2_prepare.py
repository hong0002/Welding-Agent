"""Fixed offline bridge to simulator2 native math. Never imports Isaac/starts a queue."""
import contextlib
import io
import json
from pathlib import Path
import sys


def validate_playback(raw, playback, parameters):
    import numpy as np
    raw, playback, parameters = map(np.asarray, (raw, playback, parameters))
    if (raw.ndim != 2 or raw.shape[1] != 6 or len(raw) < 2 or playback.shape != (len(parameters), 6)
            or not all(np.isfinite(a).all() for a in (raw, playback, parameters))
            or parameters[0] != 0 or parameters[-1] != len(raw)-1 or np.any(np.diff(parameters) <= 0)):
        raise ValueError('Invalid native playback parameter contract')
    for index, source in enumerate(raw):
        matches = np.flatnonzero(np.isclose(parameters, index, atol=1e-12, rtol=0))
        if len(matches) != 1 or not np.allclose(playback[matches[0], :3], source[:3], atol=1e-7, rtol=0):
            raise ValueError('Native interpolation lost an original corner/endpoint')
    # Validation of native output only; no new interpolation is generated here.
    index = np.minimum(np.floor(parameters).astype(int), len(raw)-2)
    fraction = parameters-index
    expected = raw[index, :3]+fraction[:, None]*(raw[index+1, :3]-raw[index, :3])
    if not np.allclose(playback[:, :3], expected, atol=1e-7, rtol=0):
        raise ValueError('Native playback changed a Cartesian segment or overshot')
    return dict(endpoint_preserved=True, corners_preserved=True, order_preserved=True, overshoot=False,
                source_point_count=len(raw), playback_point_count=len(playback), units='mm', frame='simulator2_scene')


def main(options):
    import numpy as np
    import h5py
    stp = options.get('backend') == 'dataset_stp'
    prefix = 'SIMULATOR_STP' if stp else 'SIMULATOR2'
    if stp and options.get('layout') != 'stp':
        raise ValueError('STP bridge only accepts the backend-owned stp layout')
    root, h5, obj, output = map(lambda key: Path(options[key]).resolve(), ('root', 'h5', 'obj', 'output'))
    project = Path(__file__).resolve().parents[1]
    if not output.is_relative_to(project/'.cache') or output.is_relative_to(root):
        raise ValueError('Output must be repository-owned cache')
    if h5.stem != options['sample_id'] or obj.stem != options['sample_id']:
        raise ValueError('Exact sample identity differs')
    sys.path.insert(0, str(root))
    from welding_scene_layout import build_scene, fixture_supported, densify_poses
    from welding_prediction import prediction_targets
    if not fixture_supported(options['sample_id']):
        return dict(ok=False, code=prefix+'_SAMPLE_UNSUPPORTED')
    output.mkdir(parents=True, exist_ok=False)
    phase = 'scene'
    try:
        with h5py.File(h5, 'r') as handle:
            source = np.asarray(handle['trajectory'], dtype=float)
        if source.ndim != 2 or source.shape[1] not in (3, 6) or len(source) < 2 or not np.isfinite(source).all():
            raise ValueError('Invalid H5 source trajectory')
        poses = np.column_stack((source, np.zeros_like(source))) if source.shape[1] == 3 else source.copy()
        if options['kind'] == 'robot':
            # Reuse ALL native orientation, interpolation, IK and residual policy.
            from run_welding_sample import ExtractedSamples, sample_index, prepare
            archive = ExtractedSamples(h5.parent)  # Only the exact sample directory, never the dataset tree.
            index = sample_index(archive)
            if set(index) != {options['sample_id']}:
                raise ValueError('Native resolver did not select one exact sample')
            # Native OBJ rule must agree with the backend exact resolver.
            teaching = next(p for p in h5.parents if p.name == '로봇티칭데이터')
            if teaching.parent/'모델링 데이터'/h5.relative_to(teaching).with_suffix('.obj') != obj:
                raise ValueError('Native OBJ mapping differs')
            phase = 'robot'
            kwargs = {'layout':'stp'} if stp else {}
            solution = prepare(archive, index[options['sample_id']], output, Path(options['prediction']), **kwargs)
            with np.load(solution, allow_pickle=False) as data:
                arrays = {key: data[key].copy() for key in data.files}
            report = json.loads((output/'report.json').read_text(encoding='utf-8'))
            raw = arrays['raw_tcp_pose_xyz_mm_rpy_deg']
            playback = arrays['tcp_pose_xyz_mm_rpy_deg']
            parameters = arrays['playback_waypoint_parameter']
        else:
            gt_poses, arrays, workpiece = build_scene(obj, options['sample_id'], poses)
            if stp:
                from welding_environment import apply_environment
                gt_poses, arrays, workpiece = apply_environment(gt_poses, arrays, workpiece, layout='stp')
            report = dict(sample_id=options['sample_id'], workpiece=workpiece)
            if options.get('prediction'):
                raw, predicted, prediction_report = prediction_targets(Path(options['prediction']), options['sample_id'],
                    poses, gt_poses, arrays['source_to_scene'])
                arrays.update(predicted); report['prediction'] = prediction_report
            else:
                # Family scene preflight has no VLA result. Never label H5 as a prediction.
                raw = gt_poses
            playback, parameters = densify_poses(raw)
            arrays.update(raw_tcp_pose_xyz_mm_rpy_deg=raw, tcp_pose_xyz_mm_rpy_deg=playback,
                          playback_waypoint_parameter=parameters, source_trajectory_raw=source)
            solution = output/'trajectory_solution.npz'
            np.savez_compressed(solution, **arrays)
            (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        check = validate_playback(raw, playback, parameters)
        if stp:
            check['frame'] = 'simulator_stp_scene'
        matrix = arrays['source_to_scene']
        if (matrix.shape != (4,4) or not np.isfinite(matrix).all() or not np.allclose(matrix[3], [0,0,0,1])
                or not np.allclose(matrix[:3,:3].T@matrix[:3,:3], np.eye(3)) or not np.isclose(np.linalg.det(matrix[:3,:3]), 1)):
            raise ValueError('Native builder returned a non-rigid scene transform')
        result = dict(ok=True, sample_id=options['sample_id'], kind=options['kind'], validation=check,
                    source_to_scene=matrix.tolist(), orientation_source='simulator_stp_policy' if stp else 'simulator2_policy', vla_orientation=False,
                    prediction_input=bool(options.get('prediction')), robot_ready=options['kind']=='robot',
                    gt_h5_frame_error_mm_max=(report.get('prediction') or {}).get('gt_h5_frame_error_mm_max'))
        if stp:
            result.update(native_layout='stp', native_flags=['--layout','stp'], cad_source='sample_obj',
                environment=report['workpiece']['environment'],
                fk_residual_mm_max=report.get('interpolated_tip_error_mm_max'),
                orientation_residual_deg_max=report.get('interpolated_orientation_error_deg_max'))
            if str(arrays.get('environment_layout')) != 'stp': raise ValueError('Native STP layout missing')
        return result
    except (ValueError, RuntimeError, OSError, KeyError, ImportError) as exc:
        code = ('SIMULATOR2_FRAME_MISMATCH' if 'H5 coordinate frame' in str(exc) or 'units/frame' in str(exc)
                else 'SIMULATOR2_IK_FAIL' if phase=='robot' and isinstance(exc, RuntimeError)
                else 'SIMULATOR2_PLAYBACK_FAIL' if 'interpolation' in str(exc) or 'playback' in str(exc)
                else 'SIMULATOR2_SCENE_BUILD_FAIL')
        return dict(ok=False, code=code.replace('SIMULATOR2',prefix), exception_class=type(exc).__name__)


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    project = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project/'.cache/simulator2/python-deps'))
    options = json.loads(sys.stdin.read())
    # Native prints are geometry summaries; keep private output out of the HTTP response.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        result = main(options)
    print(json.dumps(result, allow_nan=False))
