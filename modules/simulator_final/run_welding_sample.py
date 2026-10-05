"""Select an extracted H5 teaching sample (or ZIP), solve RB10 IK, and play it."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA = ROOT.parent.parent / '42.용접로봇 행동 생성 데이터' / '3.개방데이터'


class ExtractedSamples:
    """Expose the same read interface for extracted H5 files as for ZIP members."""
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.filename = str(self.root)
        self.members = sorted(p.relative_to(self.root).as_posix()
                              for p in self.root.rglob('*')
                              if p.is_file() and p.suffix.lower() == '.h5')

    def namelist(self):
        return self.members

    def read(self, member):
        if member not in self.members:
            raise KeyError(member)
        return (self.root / member).read_bytes()


@contextmanager
def open_samples(data_root, explicit_zip=None, extracted_dir=None):
    if explicit_zip is not None:
        with zipfile.ZipFile(explicit_zip) as archive:
            yield archive
        return
    directory = extracted_dir or data_root / '1.데이터/Other'
    source = ExtractedSamples(directory)
    if source.members:
        yield source
        return
    if extracted_dir is not None:
        raise FileNotFoundError(f'No H5 samples found under {directory}')
    archive_path = data_root / '1.데이터/Other/Other.zip'
    if not archive_path.is_file():
        raise FileNotFoundError(
            f'No extracted H5 samples under {directory}, and no {archive_path}. '
            'Use --samples-dir to specify the extracted teaching-data folder.')
    with zipfile.ZipFile(archive_path) as archive:
        yield archive


def sample_index(archive):
    result = {}
    for name in archive.namelist():
        if name.lower().endswith('.h5'):
            sample = Path(name).stem
            if sample in result:
                raise ValueError(f'Duplicate sample ID: {sample}')
            result[sample] = name
    return result


def prepare(archive, member, output, prediction_dir=None, layout="stp", prediction_stage="final"):
    import h5py
    import numpy as np
    from scipy.spatial.transform import Rotation, Slerp
    from prepare_rb5_h5_trajectory import JOINT_NAMES, UrdfChain, average_tool_transform, endpoint_residuals
    from welding_tool_geometry import mounted_cad_transform, mounted_tip_transform, CAD_MOUNT_LOCAL_MM, CAD_TIP_LOCAL_MM
    from welding_scene_layout import build_scene, solve_mounted_path, LEGACY_FIXTURES, densify_poses

    with h5py.File(io.BytesIO(archive.read(member)), 'r') as handle:
        arrays = {key: np.asarray(handle[key], dtype=float)
                  for key in ('trajectory', 'joint_values', 'original_points')}
    for key, value in arrays.items():
        widths=(3,6) if key=='trajectory' else (6,)
        if value.ndim != 2 or value.shape[1] not in widths or len(value) < 2:
            raise ValueError(f'{key}: expected N>=2 with columns {widths}, got {value.shape}')
        if not np.isfinite(value).all():
            raise ValueError(f'{key}: source data contains NaN/Inf; cannot prepare this sample')
    fixed_fixture = not Path(member).stem.startswith(LEGACY_FIXTURES)
    source_trajectory=arrays['trajectory']
    xyz_only=source_trajectory.shape[1]==3
    source_poses=(np.column_stack((source_trajectory,np.zeros_like(source_trajectory)))
                  if xyz_only else source_trajectory)
    joints, endpoints = arrays['joint_values'], arrays['original_points']
    if joints.shape != endpoints.shape:
        raise ValueError('Teaching joints and poses must have matching shapes')
    chain = UrdfChain(ROOT / 'rbpodo_description/robots/rb10_1300e_u.urdf')
    teaching_transform, _ = average_tool_transform(chain, joints, endpoints)
    checks = endpoint_residuals(chain, joints, endpoints, teaching_transform)
    teaching_inconsistent = any(c['position_error_mm'] > 5 or c['orientation_error_deg'] > 2 for c in checks)
    if teaching_inconsistent:
        print('[SOURCE] Original teaching joints/pose calibration is inconsistent; '
              'diagnostic only; continuing with newly solved simulation joints.', flush=True)
    output.mkdir(parents=True, exist_ok=True)
    obj_member = str(Path(member).with_suffix('.obj')).replace('로봇티칭데이터/', '모델링 데이터/')
    if isinstance(archive, ExtractedSamples):
        obj_path = archive.root / obj_member
        if not obj_path.is_file():
            teaching_root = next((p for p in (archive.root, *archive.root.parents)
                                  if p.name == '로봇티칭데이터'), None)
            if teaching_root is not None:
                relative = (archive.root / member).relative_to(teaching_root).with_suffix('.obj')
                obj_path = teaching_root.parent / '모델링 데이터' / relative
    else:
        obj_path = output / (Path(member).stem + '.obj')
        obj_path.write_bytes(archive.read(obj_member))
    if not obj_path.is_file():
        raise FileNotFoundError(f'Matching workpiece OBJ not found: {obj_path}')
    poses, scene_arrays, workpiece_report = build_scene(obj_path, Path(member).stem, source_poses)
    from welding_environment import apply_environment
    poses, scene_arrays, workpiece_report = apply_environment(poses, scene_arrays, workpiece_report, layout)
    scene_arrays['source_trajectory_raw']=source_trajectory
    scene_arrays['source_has_orientation']=np.asarray(not xyz_only)
    cad_transform, tool = mounted_cad_transform(), mounted_tip_transform()
    tip_local_mm = CAD_TIP_LOCAL_MM.copy()
    round_fixture = Path(member).stem.startswith('T_RR_')
    if round_fixture:
        from welding_round_orientation import round_weld_tip_local_mm
        tip_local_mm = round_weld_tip_local_mm()
        tool[:3,3] = (cad_transform @ np.r_[tip_local_mm*.001,1.])[:3]
        scene_arrays['weld_tip_local_mm'] = tip_local_mm
    # The H5 orientation axes are not the CAD mount axes. Define a fixed tip
    # reference frame per fixture so the physical torch approaches from outside,
    # instead of forcing the wrist underneath/through the support table.
    if 'fixture_outward' in scene_arrays:
        outward=scene_arrays['fixture_outward']
    elif Path(member).stem.startswith('L_PR_'):
        outward = np.array([0.,-1.,0.])
    else:
        outward = np.array([-1.,0.,1.]); outward /= np.linalg.norm(outward)
    flange_y = outward
    flange_z = np.array([0.,0.,1.])
    if abs(np.dot(flange_y,flange_z))>.95:
        flange_z=np.array([0.,1.,0.])
    flange_x=np.cross(flange_y,flange_z);flange_x/=np.linalg.norm(flange_x)
    flange_z=np.cross(flange_x,flange_y)
    flange_reference=np.column_stack((flange_x,flange_y,flange_z))
    mean_pose=Rotation.from_euler('xyz',poses[:,3:],degrees=True).mean().as_matrix()
    tool[:3,:3]=flange_reference.T @ mean_pose
    workpiece_report['tip_reference_rotation_in_flange']=tool[:3,:3].tolist()
    workpiece_report['tip_reference_note']='Fixed inferred orientation reference for this fixture, not supplied dataset calibration.'
    prediction_report = None
    if prediction_dir is not None:
        from welding_prediction import prediction_targets
        poses, prediction_arrays, prediction_report = prediction_targets(
            prediction_dir, Path(member).stem, source_poses, poses, scene_arrays['source_to_scene'], stage=prediction_stage)
        scene_arrays.update(prediction_arrays)
    scene_arrays['raw_tcp_pose_xyz_mm_rpy_deg'] = poses.copy()
    if round_fixture:
        from welding_round_orientation import orient_round_path, POLICY
        # Compute directions along the actual GT/predicted path, never substitute GT XYZ.
        poses, base_parameters = densify_poses(poses)
        poses, orientation_report = orient_round_path(poses, scene_arrays, tool)
        workpiece_report['torch_orientation'] = orientation_report
        workpiece_report['orientation_policy'] = POLICY
        scene_arrays['fixture_fixed_orientation'] = np.asarray(False)
        if prediction_report is not None:
            prediction_report['orientation_policy'] = POLICY
            scene_arrays['prediction_orientation_policy'] = np.asarray(POLICY)
    poses, playback_parameters = densify_poses(poses)
    if round_fixture:
        playback_parameters = np.interp(playback_parameters, np.arange(len(base_parameters)), base_parameters)
        (output/'torch_orientation_report.json').write_text(json.dumps(orientation_report,indent=2),encoding='utf-8')
        print(f'[TORCH] T_RR exterior approach; virtual wire=15 mm; '
              'XYZ unchanged; no interference checks',flush=True)
    scene_arrays['playback_waypoint_parameter'] = playback_parameters
    # VLA playback does not depend on the source robot's teaching joint angles.
    seed = joints[0] if prediction_dir is None and not xyz_only and not fixed_fixture else [0,-30,100,-60,-90,0]
    q, position_error, rotation_error = solve_mounted_path(chain, poses, tool, seed)
    position_checks, orientation_checks, mount_checks = [], [], []
    for i in range(len(q)-1):
        rotations = Slerp([0,1], Rotation.from_euler('xyz', poses[i:i+2,3:], degrees=True))
        for a in (0, .25, .5, .75, 1):
            fk = chain.fk((1-a)*q[i]+a*q[i+1])
            tip = (fk @ cad_transform @ np.r_[tip_local_mm*.001, 1])[:3]
            mount = (fk @ cad_transform @ np.r_[CAD_MOUNT_LOCAL_MM*.001, 1])[:3]
            target = ((1-a)*poses[i,:3]+a*poses[i+1,:3])*.001
            position_checks.append(np.linalg.norm(tip-target)*1000)
            mount_checks.append(np.linalg.norm(mount-fk[:3,3])*1000)
            orientation_checks.append(np.rad2deg((rotations(a).inv()*Rotation.from_matrix((fk@tool)[:3,:3])).magnitude()))
    if max(position_checks)>1 or max(orientation_checks)>1 or max(mount_checks)>1e-6:
        raise ValueError(f'interpolation_residual: tip={max(position_checks):.3f} mm, '
                         f'orientation={max(orientation_checks):.3f} deg, mount gap={max(mount_checks):.6f} mm')
    solution = output / 'trajectory_solution.npz'
    np.savez_compressed(solution, **scene_arrays, tcp_pose_xyz_mm_rpy_deg=poses,
                        tracking_point=np.asarray('mounted_fixture_v2'),
                        cad_to_robot_tcp=cad_transform, teaching_tcp_transform=teaching_transform,
                        joint_position_rad=q, joint_names=np.asarray(JOINT_NAMES),
                        urdf_tcp_to_weld_tcp=tool, position_error_mm=position_error,
                        orientation_error_deg=rotation_error)
    is_directory = isinstance(archive, ExtractedSamples)
    report = dict(sample_id=Path(member).stem, workpiece=workpiece_report,
                  source_type='directory' if is_directory else 'zip',
                  source_h5=str(archive.root/member) if is_directory else None,
                  source_zip=None if is_directory else str(archive.filename),source_member=member,
                  point_count=len(q), raw_point_count=len(scene_arrays['raw_tcp_pose_xyz_mm_rpy_deg']),
                  playback_resampling='same Cartesian segments, <=5 mm / 3 degrees; original corners retained',
                  tracking_point='mounted_fixture_v2',
                  position_error_mm_max=float(position_error.max()),
                  orientation_error_deg_max=float(rotation_error.max()),
                  interpolated_tip_error_mm_max=float(max(position_checks)),
                  interpolated_orientation_error_deg_max=float(max(orientation_checks)),
                  cad_mount_to_flange_gap_mm_max=float(max(mount_checks)),
                  endpoint_checks=checks,
                  source_has_orientation=not xyz_only,
                  orientation_policy=(POLICY if round_fixture else 'fixed initial fixture orientation; model predicts XYZ only' if prediction_dir is not None
                                      else 'fixed fixture orientation; source orientation not replayed' if fixed_fixture
                                      else 'fixed fixture orientation; source XYZ only' if xyz_only
                                      else 'source orientation with inferred tool reference'),
                  teaching_joint_checks_applicability='diagnostic only; playback uses newly solved simulation joints',
                  teaching_joint_pose_inconsistent=teaching_inconsistent,
                  max_joint_step_deg=float(np.rad2deg(np.abs(np.diff(q,axis=0))).max()),
                  trajectory_source='vla_prediction' if prediction_dir is not None else 'h5_ground_truth',
                  prediction=prediction_report,
                  note='Rigidly relocated task with fixed flange-mounted CAD. Original poses stored separately. No collision/dynamics certification.')
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'[OK] {report["sample_id"]}: flange gap={max(mount_checks):.6f} mm, '
          f'tip error={max(position_checks):.6f} mm, orientation error={max(orientation_checks):.6f} deg',flush=True)
    print(f'[SAVE] {solution}',flush=True)
    return solution


def main():
    if len(sys.argv) == 1:
        from welding_menu import main as menu_main
        menu_main()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=DEFAULT_DATA, help='3.개방데이터 directory')
    source_options = parser.add_mutually_exclusive_group()
    source_options.add_argument('--zip', type=Path, help='Explicit Other.zip path (overrides extracted data)')
    source_options.add_argument('--samples-dir', type=Path, help='Directory containing extracted H5 files (recursive)')
    parser.add_argument('--list', action='store_true', help='List sample IDs without Isaac Sim')
    parser.add_argument('--filter', default='', help='Filter sample IDs, e.g. L_PR or T_PP_03')
    parser.add_argument('--sample', nargs='+', help='Exact sample ID, e.g. L_PR_03_0001')
    parser.add_argument('--dataset-split', choices=('train', 'valid', 'unassigned'), help='Dataset label recorded by the interactive menu')
    from welding_prediction import DEFAULT_PREDICTIONS
    parser.add_argument('--prediction', action='store_true', help='Replay VLA XYZ output; keep GT as the green target')
    parser.add_argument('--model', type=Path, help='Model export folder; implies --prediction --send and video recording. Relative paths also resolve from workspace root.')
    parser.add_argument('--prediction-stage', choices=('final', 'rough'), default='final', help='rough: replay saved GPT rough.json control points')
    parser.add_argument('--prediction-root', type=Path, default=DEFAULT_PREDICTIONS,
                        help='Exported welding_validation_all folder (requires --prediction)')
    parser.add_argument('--layout', choices=('legacy', 'stp'), default='stp', help='Measured STEP environment (default) or legacy fixture')
    parser.add_argument('--send', action='store_true', help='Queue playback in an already running --serve simulator')
    parser.add_argument('--wait', action='store_true', help='Wait for each queued playback and video save to complete')
    parser.add_argument('--status', action='store_true', help='Show queued command results')
    from welding_command_queue import DEFAULT_QUEUE
    parser.add_argument('--queue-dir', type=Path, default=DEFAULT_QUEUE)
    parser.add_argument('--prepare-only', action='store_true', help='Solve and save without Isaac Sim')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'welding_sample_outputs')
    parser.add_argument('--isaac-python', type=Path, help='Isaac Sim Python executable or python.sh')
    parser.add_argument('--camera-distance-scale', type=float, default=1.0, help='Camera distance multiplier; 0.7 moves closer to the GT seam')
    parser.add_argument('--video-dir', type=Path, help='Additional video-only archive folder (default: workspace VIDEO)')
    parser.add_argument('--duration-sec', type=float, default=15)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--auto-close', action='store_true')
    args = parser.parse_args()
    if args.model is not None:
        model = args.model.expanduser()
        if not model.is_absolute():
            workspace_model = ROOT.parent.parent / model
            model = workspace_model if workspace_model.is_dir() else model
        if not model.is_dir():
            parser.error(f'Model export folder not found: {model}')
        args.prediction = True
        args.prediction_root = model.resolve()
        if not (args.prepare_only or args.list or args.status):
            args.send = True
    if args.sample and len(args.sample) > 1 and not (args.prepare_only or args.list or args.status):
        args.send = True
    if args.wait and not (args.prepare_only or args.list or args.status):
        args.send = True
    if args.send and (args.prepare_only or args.isaac_python or args.headless or args.auto_close):
        parser.error('--send cannot be combined with --prepare-only/--isaac-python/--headless/--auto-close')
    if args.status:
        from welding_command_queue import print_status
        print_status(args.queue_dir)
        return
    import math
    if not math.isfinite(args.camera_distance_scale) or args.camera_distance_scale <= 0:
        print('[CAMERA] Invalid scale; using 1.0', flush=True)
        args.camera_distance_scale = 1.0
    if not math.isfinite(args.duration_sec) or args.duration_sec <= 0:
        parser.error('--duration-sec must be finite and positive')
    with open_samples(args.data_root, args.zip, args.samples_dir) as archive:
        print(f'[SOURCE] {"directory" if isinstance(archive, ExtractedSamples) else "zip"}: {archive.filename}', flush=True)
        index = sample_index(archive)
        missing = [sample for sample in (args.sample or []) if sample not in index]
        if missing:
            parser.error(f'Original H5 samples not found: {missing}; check --samples-dir or --data-root')
        predictions = None
        if args.prediction:
            from welding_prediction import prediction_index
            predictions = prediction_index(args.prediction_root)
            missing = [sample for sample in (args.sample or []) if sample not in predictions]
            if missing:
                parser.error(f'H5 exists, but this model export has no predictions for {missing}: '
                             f'{args.prediction_root}. Select an exported sample with --list, '
                             'or use a model export containing this sample.')
            index = {sample: member for sample, member in index.items() if sample in predictions}
        if args.list:
            from welding_scene_layout import fixture_supported
            matches = sorted(s for s in index if args.filter.lower() in s.lower())
            for sample in matches:
                suffix = '' if predictions is None else (' [fixture supported]' if fixture_supported(sample) else ' [fixture unsupported]')
                print(sample + suffix)
            print(f'[SAMPLES] {len(matches)} / {len(index)}')
            return
        if not args.sample:
            parser.error('Use --sample SAMPLE_ID or --list')
        failures = []
        for sample in args.sample:
            print(f'[SAMPLE] {sample}', flush=True)
            try:
                output = args.output_dir.resolve() / sample
                if args.prediction:
                    output = output / 'vla_prediction'
                if args.layout != 'legacy':
                    output = output / args.layout
                if args.send:
                    # Each queued request owns its files, even for repeated sample IDs.
                    import uuid
                    output = output / 'requests' / uuid.uuid4().hex
                solution = prepare(archive, index[sample], output,
                                   predictions[sample] if predictions is not None else None, layout=args.layout, prediction_stage=args.prediction_stage)
                if args.prepare_only:
                    continue
                if args.send:
                    from welding_command_queue import submit
                    request_id = submit(args.queue_dir, solution, output / 'scene.usda', args.duration_sec, sample,
                                        playback_mode='model_predict' if args.prediction else 'gt',
                                        dataset_split=args.dataset_split,
                                        record_video=True if args.model is not None or args.video_dir is not None or len(args.sample)>1 else None,
                                        video_dir=args.video_dir, camera_distance_scale=args.camera_distance_scale)
                    print(f'[QUEUED] {request_id} (queued, not yet confirmed as played)', flush=True)
                    if args.wait:
                        from welding_command_queue import wait_for_result
                        if not wait_for_result(args.queue_dir, request_id):
                            failures.append(sample)
                    else:
                        print('Check --status; start the simulator with --serve if it is not running.', flush=True)
                    continue
                executable = str(args.isaac_python.resolve()) if args.isaac_python else sys.executable
                command = [executable, str(ROOT / 'run_rb10_trajectory_with_ATU01035.py'),
                           '--solution', str(solution), '--output', str(output / 'scene.usda'),
                           '--duration-sec', str(args.duration_sec)]
                command += ['--camera-distance-scale', str(args.camera_distance_scale)]
                if args.video_dir is not None:
                    command += ['--video-dir', str(args.video_dir.expanduser().resolve())]
                for flag in ('headless', 'auto_close'):
                    if getattr(args, flag):
                        command.append('--' + flag.replace('_', '-'))
                print('[PLAY] Starting Isaac Sim (requires an Isaac Sim Python environment)', flush=True)
                subprocess.run(command, check=True)
            except (OSError, ValueError, KeyError, RuntimeError) as exc:
                if len(args.sample) == 1:
                    raise
                failures.append(sample)
                print(f'[FAILED] {sample}: {exc}', flush=True)
        if failures:
            raise RuntimeError(f'Preparation/playback failed for {failures}; see errors above')



if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
        print(f'[ERROR] {exc}', file=sys.stderr)
        sys.exit(1)
