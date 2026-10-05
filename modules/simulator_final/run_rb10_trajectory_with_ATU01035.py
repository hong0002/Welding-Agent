r"""RB10-1300E H5 trajectory playback with Panasonic ATU01035 torch.

Visualization purpose:
- Real RB10 scale (1.0x)
- No red TCP sphere
- Matching sample workpiece when included in the prepared NPZ
- Translucent green surface = planned weld; red = measured torch-tip sweep
- Panasonic ATU01035 CAD attached provisionally at the robot TCP
- Smooth playback of the solved 150-waypoint joint trajectory

IMPORTANT:
The CAD rear mounting face is fixed at the robot flange. The source path and
orientation sequence are relocated into an upright simulation fixture, with an
explicit inferred tip reference rotation. This is not the recovered original
robot-to-workpiece calibration. Stored original poses are never overwritten.

The H5 data has no timestamps, so --duration-sec is visualization time only.
"""

import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--headless", action="store_true")
parser.add_argument("--auto-close", action="store_true")
parser.add_argument(
    "--duration-sec",
    type=float,
    default=30.0,
    help="Visual playback duration only; H5 has no physical timestamps.",
)
parser.add_argument("--solution", type=Path, help="Prepared sample trajectory NPZ")
parser.add_argument("--no-video", action="store_true", help="Disable automatic demo.mp4 recording")
parser.add_argument("--camera-distance-scale", type=float, default=1.0)
parser.add_argument("--video-dir", type=Path, help="Additional video archive folder")
parser.add_argument("--video-fps", type=int, default=30, help="Saved video FPS (default: 30)")
parser.add_argument("--capture-dir", type=Path, help="Save start/middle/end viewport images")
parser.add_argument("--output", type=Path, help="Output scene path")
from welding_command_queue import DEFAULT_QUEUE
parser.add_argument("--serve", action="store_true", help="Keep Isaac Sim open and accept queued samples")
parser.add_argument("--queue-dir", type=Path, default=DEFAULT_QUEUE)
args = parser.parse_args()
if not 1 <= args.video_fps <= 120:
    parser.error("--video-fps must be between 1 and 120")
if args.serve and (args.auto_close or args.solution or args.output):
    parser.error("--serve cannot be combined with --auto-close/--solution/--output")
import math
if not math.isfinite(args.duration_sec) or args.duration_sec <= 0:
    parser.error("--duration-sec must be finite and positive")

from isaacsim import SimulationApp

simulation_app = SimulationApp(
    {
        "headless": args.headless,
        "renderer": "RaytracedLighting",
        "sync_loads": False,
        "create_new_stage": False,
    }
)

import time
import traceback
from pathlib import Path

import numpy as np
import omni.kit.commands
import omni.timeline
import omni.usd

from isaacsim.core.prims import Articulation
from isaacsim.core.utils.viewports import set_camera_view
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics

omni.usd.get_context().new_stage()


# ============================================================
# Paths / constants
# ============================================================

ROOT = Path(__file__).resolve().parent

URDF_PATH = (
    ROOT
    / "rbpodo_description"
    / "robots"
    / "rb10_1300e_u.urdf"
)

SOLUTION_PATH = args.solution or ROOT / "rb10_h5_trajectory_solution.npz"
TOOL_USD_PATH = ROOT / "ATU01035_welding_tool.usd"

JOINT_NAMES = (
    "base",
    "shoulder",
    "elbow",
    "wrist1",
    "wrist2",
    "wrist3",
)

# Shared with the preparation step so IK and displayed CAD use the same offset.
from welding_tool_geometry import CAD_TIP_LOCAL_MM, CAD_MOUNT_LOCAL_MM, mounted_cad_transform


# ============================================================
# Helpers
# ============================================================

def rotation_between(source, target):
    source = np.array(source, dtype=np.float64, copy=True)
    target = np.array(target, dtype=np.float64, copy=True)

    source /= np.linalg.norm(source)
    target /= np.linalg.norm(target)

    cross = np.cross(source, target)
    dot = float(np.clip(np.dot(source, target), -1.0, 1.0))

    if np.linalg.norm(cross) < 1e-12:
        if dot > 0.0:
            return np.eye(3)

        helper = np.array([1.0, 0.0, 0.0])
        if abs(np.dot(source, helper)) > 0.9:
            helper = np.array([0.0, 1.0, 0.0])

        axis = np.cross(source, helper)
        axis /= np.linalg.norm(axis)

        return 2.0 * np.outer(axis, axis) - np.eye(3)

    skew = np.array(
        [
            [0.0, -cross[2], cross[1]],
            [cross[2], 0.0, -cross[0]],
            [-cross[1], cross[0], 0.0],
        ]
    )

    return np.eye(3) + skew + skew @ skew * (
        (1.0 - dot) / np.dot(cross, cross)
    )


def matrix_to_quaternion(matrix):
    trace = float(np.trace(matrix))

    if trace > 0.0:
        s = np.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (matrix[2, 1] - matrix[1, 2]) / s
        y = (matrix[0, 2] - matrix[2, 0]) / s
        z = (matrix[1, 0] - matrix[0, 1]) / s

    else:
        i = int(np.argmax(np.diag(matrix)))

        if i == 0:
            s = np.sqrt(
                1.0 + matrix[0, 0] - matrix[1, 1] - matrix[2, 2]
            ) * 2.0
            w = (matrix[2, 1] - matrix[1, 2]) / s
            x = 0.25 * s
            y = (matrix[0, 1] + matrix[1, 0]) / s
            z = (matrix[0, 2] + matrix[2, 0]) / s

        elif i == 1:
            s = np.sqrt(
                1.0 + matrix[1, 1] - matrix[0, 0] - matrix[2, 2]
            ) * 2.0
            w = (matrix[0, 2] - matrix[2, 0]) / s
            x = (matrix[0, 1] + matrix[1, 0]) / s
            y = 0.25 * s
            z = (matrix[1, 2] + matrix[2, 1]) / s

        else:
            s = np.sqrt(
                1.0 + matrix[2, 2] - matrix[0, 0] - matrix[1, 1]
            ) * 2.0
            w = (matrix[1, 0] - matrix[0, 1]) / s
            x = (matrix[0, 2] + matrix[2, 0]) / s
            y = (matrix[1, 2] + matrix[2, 1]) / s
            z = 0.25 * s

    return Gf.Quatf(
        float(w),
        Gf.Vec3f(float(x), float(y), float(z)),
    )


def add_h5_path(stage, h5_positions_m):
    curve = UsdGeom.BasisCurves.Define(
        stage,
        "/H5TcpPath",
    )

    curve.CreateTypeAttr("linear")
    curve.CreateCurveVertexCountsAttr(
        [len(h5_positions_m)]
    )

    curve.CreatePointsAttr(
        [
            Gf.Vec3f(
                float(p[0]),
                float(p[1]),
                float(p[2]),
            )
            for p in h5_positions_m
        ]
    )

    # Visible, but not huge.
    curve.CreateWidthsAttr([0.002])
    curve.SetWidthsInterpolation("constant")

    curve.CreateDisplayColorAttr(
        [Gf.Vec3f(0.1, 1.0, 0.1)]
    )


def add_torch_at_tcp(stage, tcp_path, cad_transform=None, weld_tip_local_mm=None):
    transform = mounted_cad_transform() if cad_transform is None else np.asarray(cad_transform)
    tool_rotation = transform[:3, :3]
    tool_translation = transform[:3, 3]
    print('[TOOL] CAD rear mounting face fixed at robot flange', flush=True)

    tool_path = Sdf.Path(tcp_path).AppendChild(
        "WeldingTool"
    )

    tool_root = UsdGeom.Xform.Define(
        stage,
        tool_path,
    )

    tool_root.AddTranslateOp().Set(
        Gf.Vec3d(
            float(tool_translation[0]),
            float(tool_translation[1]),
            float(tool_translation[2]),
        )
    )

    tool_root.AddOrientOp().Set(
        matrix_to_quaternion(
            tool_rotation
        )
    )

    geometry_path = tool_path.AppendChild(
        "Geometry"
    )

    geometry = UsdGeom.Xform.Define(
        stage,
        geometry_path,
    )

    geometry.GetPrim().GetReferences().AddReference(
        TOOL_USD_PATH.as_posix()
    )

    # CAD file is in millimetres.
    geometry.AddScaleOp().Set(
        Gf.Vec3f(
            0.001,
            0.001,
            0.001,
        )
    )

    tip = CAD_TIP_LOCAL_MM if weld_tip_local_mm is None else np.asarray(weld_tip_local_mm)
    tool_root.GetPrim().CreateAttribute('weldTipLocalMm', Sdf.ValueTypeNames.Double3).Set(Gf.Vec3d(*map(float,tip)))
    wire_path = tool_path.AppendChild('VirtualWire')
    if stage.GetPrimAtPath(wire_path).IsValid():
        stage.RemovePrim(wire_path)
    if not np.allclose(tip, CAD_TIP_LOCAL_MM):
        wire = UsdGeom.BasisCurves.Define(stage, wire_path)
        wire.CreateTypeAttr('linear')
        wire.CreateCurveVertexCountsAttr([2])
        wire.CreatePointsAttr([Gf.Vec3f(*map(float,p*.001)) for p in (CAD_TIP_LOCAL_MM,tip)])
        wire.CreateWidthsAttr([.0008]); wire.SetWidthsInterpolation('constant')
        wire.CreateDisplayColorAttr([Gf.Vec3f(.8,.65,.3)])

    mount_to_tip_mm = np.linalg.norm(
        CAD_TIP_LOCAL_MM
        - CAD_MOUNT_LOCAL_MM
    )

    print("\n[TOOL]")
    print("  Panasonic ATU01035 added at robot TCP")
    print(
        f"  CAD mount->tip distance = "
        f"{mount_to_tip_mm:.3f} mm"
    )
    print(
        "  NOTE: mounting is provisional; "
        "final adapter/bracket geometry is not validated yet."
    )


# ============================================================
# Main
# ============================================================

def measured_tip_position(stage,tcp_path):
    cache=UsdGeom.XformCache(Usd.TimeCode.Default())
    prim=stage.GetPrimAtPath(tcp_path+'/WeldingTool')
    transform=cache.GetLocalToWorldTransform(prim)
    value=prim.GetAttribute('weldTipLocalMm').Get()
    tip=CAD_TIP_LOCAL_MM if value is None else np.asarray(value)
    return np.asarray(transform.Transform(Gf.Vec3d(*map(float,tip*.001))))


def verify_attachment(stage, tcp_path, target, label):
    cache = UsdGeom.XformCache(Usd.TimeCode.Default())
    flange = cache.GetLocalToWorldTransform(stage.GetPrimAtPath(tcp_path))
    cad = cache.GetLocalToWorldTransform(stage.GetPrimAtPath(tcp_path+'/WeldingTool'))
    origin = np.asarray(flange.Transform(Gf.Vec3d(0,0,0)))
    mount = np.asarray(cad.Transform(Gf.Vec3d(*map(float,CAD_MOUNT_LOCAL_MM*.001))))
    tip = measured_tip_position(stage,tcp_path)
    flange_normal = np.asarray(flange.TransformDir(Gf.Vec3d(0, -1, 0)))
    cad_normal = np.asarray(cad.TransformDir(Gf.Vec3d(0, 0, 1)))
    cosine = np.dot(flange_normal, cad_normal) / (np.linalg.norm(flange_normal)*np.linalg.norm(cad_normal))
    mount_angle = float(np.rad2deg(np.arccos(np.clip(cosine, -1., 1.))))
    gap = float(np.linalg.norm(mount-origin)*1000)
    error = float(np.linalg.norm(tip-target)*1000)
    print(f'[VERIFY {label}] actual USD mount gap={gap:.6f} mm; tip error={error:.6f} mm; mount axis angle={mount_angle:.6f} deg',flush=True)
    if gap > .1 or error > 2 or mount_angle > .1:
        raise RuntimeError(f'Actual stage attachment/tracking failed: gap={gap}, tip={error}, mount angle={mount_angle} mm')


def capture_frame(label):
    if args.capture_dir is None:
        return
    from viewport_capture_compat import capture_native_frame
    path=(args.capture_dir/(label+'.png')).resolve()
    capture_native_frame(simulation_app,path)
    print(f'[CAPTURE] {path}',flush=True)


def main():
    for path in (
        URDF_PATH,
        SOLUTION_PATH,
        TOOL_USD_PATH,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)

    solution = np.load(
        SOLUTION_PATH
    )

    tracking_point = str(solution["tracking_point"]) if "tracking_point" in solution else "data_tcp"
    print(f"[TRACKING] {tracking_point}", flush=True)
    if tracking_point != "mounted_fixture_v2":
        raise ValueError("Stale trajectory: regenerate with run_welding_sample.py after restarting the server")

    joint_path = np.asarray(
        solution["joint_position_rad"],
        dtype=np.float64,
    )

    tcp_pose = np.asarray(
        solution["tcp_pose_xyz_mm_rpy_deg"],
        dtype=np.float64,
    )

    h5_positions_m = (
        tcp_pose[:, :3]
        / 1000.0
    )

    if joint_path.ndim != 2 or joint_path.shape[1] != 6:
        raise RuntimeError(
            f"Expected joint trajectory shape (N, 6), "
            f"got {joint_path.shape}"
        )

    n = len(joint_path)

    endpoint_distance_mm = (
        np.linalg.norm(
            h5_positions_m[-1]
            - h5_positions_m[0]
        )
        * 1000.0
    )

    print(
        f"[TRAJECTORY] waypoints={n}"
    )
    print(
        f"[TRAJECTORY] TCP start->end="
        f"{endpoint_distance_mm:.3f} mm"
    )
    print(
        f"[TRAJECTORY] visual duration="
        f"{args.duration_sec:.1f} sec"
    )

    # --------------------------------------------------------
    # Import RB10 at real scale
    # --------------------------------------------------------

    from urdf_import_compat import import_urdf_isaac61
    robot_path = import_urdf_isaac61(
        URDF_PATH, None,
        dict(merge_fixed_joints=False, convex_decomp=False,
             import_inertia_tensor=True, fix_base=True,
             distance_scale=1.0, make_default_prim=False),
    )

    stage = omni.usd.get_context().get_stage()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    robot_scope = (
        Sdf.Path(robot_path)
        .GetParentPath()
    )

    tcp_paths = [
        prim.GetPath().pathString
        for prim in stage.Traverse()
        if (
            prim.GetName() == "tcp"
            and prim.GetPath().HasPrefix(
                robot_scope
            )
        )
    ]

    if len(tcp_paths) != 1:
        raise RuntimeError(
            f"Expected one tcp, found {tcp_paths}"
        )

    tcp_path = tcp_paths[0]

    print(
        f"[ROBOT] tcp path={tcp_path}"
    )

    # --------------------------------------------------------
    # Scene
    # --------------------------------------------------------

    scene = UsdPhysics.Scene.Define(
        stage,
        "/physicsScene",
    )

    # Visual playback only.
    scene.CreateGravityDirectionAttr().Set(
        Gf.Vec3f(
            0.0,
            0.0,
            -1.0,
        )
    )

    scene.CreateGravityMagnitudeAttr().Set(
        0.0
    )

    light = UsdLux.DomeLight.Define(
        stage,
        "/WorldLight",
    )

    light.CreateIntensityAttr(
        1200.0
    )

    from welding_workpiece import add_workpiece
    add_workpiece(stage, solution)
    floor_z = float(solution.get('environment_floor_z_m', 0.))
    if str(solution.get('environment_layout', 'legacy')) == 'stp':
        # Approximate PROFILE BASE support: installation plane stays at world z=0.
        pedestal = UsdGeom.Cube.Define(stage, '/RobotPedestal')
        pedestal.CreateSizeAttr(1.)
        pedestal.AddTranslateOp().Set(Gf.Vec3d(0., 0., floor_z/2))
        pedestal.AddScaleOp().Set(Gf.Vec3f(.600, .800, -floor_z))
        pedestal.CreateDisplayColorAttr([Gf.Vec3f(.22, .25, .28)])
    # The CAD bottom rests on a visible fixture; no floating workpiece.
    if 'fixture_table_top_m' in solution:
        top=float(solution['fixture_table_top_m'])
        table=UsdGeom.Cube.Define(stage,'/FixtureTable')
        table.CreateSizeAttr(1.)
        workpiece_points = np.asarray(solution['workpiece_vertices_world_m'])
        table_center = (workpiece_points.min(axis=0) + workpiece_points.max(axis=0))/2
        table_size = np.maximum(np.ptp(workpiece_points[:, :2], axis=0) + .06, .30)
        if 'environment_table_center_xy_m' in solution:
            table_center[:2] = solution['environment_table_center_xy_m']
            table_size = solution['environment_table_size_xy_m']
        table.AddTranslateOp().Set(Gf.Vec3d(float(table_center[0]),float(table_center[1]),top-.02))
        table.AddScaleOp().Set(Gf.Vec3f(float(table_size[0]),float(table_size[1]),.04))
        table.CreateDisplayColorAttr([Gf.Vec3f(.18,.21,.24)])
        leg_x, leg_y = table_size/2 - .03
        for j,(dx,dy) in enumerate(((-leg_x,-leg_y),(-leg_x,leg_y),(leg_x,-leg_y),(leg_x,leg_y))):
            leg=UsdGeom.Cube.Define(stage,f'/FixtureLeg{j}')
            leg.CreateSizeAttr(1.)
            leg.AddTranslateOp().Set(Gf.Vec3d(float(table_center[0])+dx,float(table_center[1])+dy,(top-.04+floor_z)/2))
            leg.AddScaleOp().Set(Gf.Vec3f(.025,.025,top-.04-floor_z))
            leg.CreateDisplayColorAttr([Gf.Vec3f(.18,.21,.24)])
    ground=UsdGeom.Cube.Define(stage,'/Ground')
    ground.CreateSizeAttr(1.)
    ground.AddTranslateOp().Set(Gf.Vec3d(0.,0.,floor_z-.025))
    ground.AddScaleOp().Set(Gf.Vec3f(3.,3.,.05))
    ground.CreateDisplayColorAttr([Gf.Vec3f(.28,.3,.32)])

    from welding_path_marks import WeldMarks
    planned_path = np.asarray(solution['planned_tcp_xyz_world_m']) if 'planned_tcp_xyz_world_m' in solution else h5_positions_m
    marks = WeldMarks(stage, solution, planned_path)
    if 'trajectory_source' in solution:
        print(f'[MOTION SOURCE] {solution["trajectory_source"]}; green=GT; red=measured tip', flush=True)

    add_torch_at_tcp(
        stage,
        tcp_path,
        np.asarray(solution['cad_to_robot_tcp']) if 'cad_to_robot_tcp' in solution else None,
        np.asarray(solution['weld_tip_local_mm']) if 'weld_tip_local_mm' in solution else None,
    )

    # Common GT reference for all methods, independent of prediction error.
    if 'source_tcp_pose_xyz_mm_rpy_deg' in solution and 'source_to_scene' in solution:
        source = np.asarray(solution['source_tcp_pose_xyz_mm_rpy_deg'])[:, :3] * .001
        transform = np.asarray(solution['source_to_scene'])
        center = source.mean(axis=0) @ transform[:3, :3].T + transform[:3, 3]
    else:
        center = np.mean(solution.get('planned_tcp_xyz_world_m', h5_positions_m), axis=0)
    scale = args.camera_distance_scale
    if not math.isfinite(scale) or scale <= 0:
        scale = 1.0
    offset = np.asarray(solution.get('camera_eye_offset_m', [-0.9, -1.6, 0.8]))
    set_camera_view(eye=(center + scale * offset).tolist(), target=center.tolist())
    print(f'[CAMERA] GT seam center; distance scale={scale:g}', flush=True)

    # --------------------------------------------------------
    # Articulation
    # --------------------------------------------------------

    timeline = (
        omni.timeline
        .get_timeline_interface()
    )

    print("[INIT] Starting physics", flush=True)
    timeline.play()

    for _ in range(8):
        simulation_app.update()

    robot = Articulation(
        robot_path
    )

    print("[INIT] Initializing articulation", flush=True)
    robot.initialize()

    dof_names = list(
        robot.dof_names
    )

    missing = [
        name
        for name in JOINT_NAMES
        if name not in dof_names
    ]

    if missing:
        raise RuntimeError(
            f"Missing joints {missing}; "
            f"DOFs={dof_names}"
        )

    indices = [
        dof_names.index(name)
        for name in JOINT_NAMES
    ]

    robot.set_joint_position_targets(joint_path[0], joint_indices=indices)
    robot.set_joint_positions(
        joint_path[0],
        joint_indices=indices,
    )

    robot.set_joint_velocities(
        np.zeros(
            len(indices),
            dtype=np.float64,
        ),
        joint_indices=indices,
    )

    for _ in range(8):
        simulation_app.update()

    verify_attachment(stage, tcp_path, h5_positions_m[0], "start")
    capture_frame("start")
    verify_attachment(stage, tcp_path, h5_positions_m[0], "start held")

    marks.begin(measured_tip_position(stage,tcp_path))

    print("\n[PLAYBACK] start")
    print(
        "[PLAYBACK] translucent green = target; red = measured completed weld"
    )

    # --------------------------------------------------------
    # Smooth playback
    # --------------------------------------------------------

    duration = max(
        float(args.duration_sec),
        1.0,
    )

    recorder = None
    if not args.no_video:
        from welding_video import ViewportVideo, recording_label
        video_dir = args.output.parent if args.output else SOLUTION_PATH.parent
        recorder = ViewportVideo(simulation_app, video_dir / 'demo.mp4', args.video_fps,
                                 archive_dir=args.video_dir or ROOT.parent.parent / 'VIDEO',
                                 archive_label=recording_label(SOLUTION_PATH,
                                     str(solution.get('environment_layout', 'legacy'))) + f'_cam{scale:g}')
    video_complete = False
    try:
        frame_count = max(2, int(math.ceil(duration * args.video_fps)))
        frame_index = 0
        start_time = time.perf_counter()
        last_report = -1
        captured_mid = False

        while simulation_app.is_running():
            elapsed = (
                time.perf_counter()
                - start_time
            )

            if recorder is not None:
                if frame_index >= frame_count - 1:
                    break
            elif elapsed >= duration:
                break

            progress = (
                elapsed
                / duration
            )

            if recorder is not None:
                progress = frame_index / (frame_count - 1)

            trajectory_position = (
                progress
                * (n - 1)
            )

            i0 = int(
                np.floor(
                    trajectory_position
                )
            )

            i1 = min(
                i0 + 1,
                n - 1,
            )

            alpha = (
                trajectory_position
                - i0
            )

            q = (
                (1.0 - alpha)
                * joint_path[i0]
                + alpha
                * joint_path[i1]
            )

            robot.set_joint_position_targets(q, joint_indices=indices)
            robot.set_joint_positions(
                q,
                joint_indices=indices,
            )

            robot.set_joint_velocities(
                np.zeros(
                    len(indices),
                    dtype=np.float64,
                ),
                joint_indices=indices,
            )

            simulation_app.update()
            marks.record(measured_tip_position(stage,tcp_path))
            if recorder is not None:
                recorder.add_frame()
                frame_index += 1
            if args.capture_dir is not None and not captured_mid and progress >= .5:
                pause_start=time.perf_counter()
                capture_frame("middle")
                start_time += time.perf_counter()-pause_start
                captured_mid=True

            percentage = int(
                progress
                * 100.0
            )

            bucket = (
                percentage
                // 25
            )

            if bucket != last_report:
                last_report = bucket

                print(
                    f"  progress={percentage:3d}% "
                    f"waypoint≈"
                    f"{trajectory_position + 1:.1f}/{n}"
                )

            time.sleep(0.005)

        if not simulation_app.is_running():
            raise RuntimeError("Simulator closed before playback completed")

        # Exact final pose.
        robot.set_joint_position_targets(joint_path[-1], joint_indices=indices)
        robot.set_joint_positions(
            joint_path[-1],
            joint_indices=indices,
        )

        robot.set_joint_velocities(
            np.zeros(
                len(indices),
                dtype=np.float64,
            ),
            joint_indices=indices,
        )

        for _ in range(5):
            simulation_app.update()

        marks.record(measured_tip_position(stage,tcp_path),force=True)
        verify_attachment(stage, tcp_path, h5_positions_m[-1], "end")
        timeline.pause()
        capture_frame("end")
        verify_attachment(stage, tcp_path, h5_positions_m[-1], "end held")
        if recorder is not None:
            recorder.add_frame()

        video_complete = True
    finally:
        if recorder is not None:
            recorder.close(video_complete)

    print("  progress=100%")
    print("[PLAYBACK] finished")

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    output = (
        ROOT
        / "rb10_trajectory_with_ATU01035.usda"
    )

    output = args.output or output
    output.parent.mkdir(parents=True, exist_ok=True)
    marks.save(output.with_suffix(".actual_weld.npz"))

    omni.usd.get_context().save_as_stage(
        output.as_posix()
    )

    print(
        f"[SAVE] {output}"
    )

    if (
        not args.auto_close
        and not args.serve
        and not args.headless
    ):
        print(
            "[INFO] Final pose stays open "
            "until you close Isaac Sim."
        )

        while simulation_app.is_running():
            simulation_app.update()


def serve():
    import fcntl
    from welding_command_queue import process_next, write_json

    directory = args.queue_dir.resolve()
    capture_root = args.capture_dir
    directory.mkdir(parents=True, exist_ok=True)
    # Lock released by the OS even if Isaac Sim crashes.
    with (directory / "server.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(f"A simulator already serves {directory}")
        for path in (directory / "active").glob("*.json"):
            write_json(directory / "results" / path.name,
                       dict(id=path.stem, state="interrupted", error="Previous simulator exited"))
            path.unlink()

        def play(request):
            global SOLUTION_PATH
            duration = float(request["duration_sec"])
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError("Invalid playback duration")
            solution = Path(request["solution"])
            with np.load(solution, allow_pickle=False) as data:
                q = data["joint_position_rad"]
                poses = data["tcp_pose_xyz_mm_rpy_deg"]
                if (q.ndim != 2 or q.shape[1] != 6 or len(q) < 2
                        or poses.shape != q.shape or not np.isfinite(q).all()
                        or not np.isfinite(poses).all()):
                    raise ValueError("Invalid trajectory arrays")
            SOLUTION_PATH = solution
            args.duration_sec = duration
            args.output = Path(request["output"])
            if capture_root is not None:
                args.capture_dir = capture_root / request["sample"]
            omni.timeline.get_timeline_interface().stop()
            omni.usd.get_context().new_stage()
            print(f'[COMMAND] {request["sample"]} ({request["id"]})', flush=True)
            default_no_video = args.no_video
            default_video_dir = args.video_dir
            default_camera_scale = args.camera_distance_scale
            try:
                args.camera_distance_scale = float(request.get('camera_distance_scale', default_camera_scale))
                args.video_dir = Path(request['video_dir']) if request.get('video_dir') else default_video_dir
                if 'record_video' in request:
                    args.no_video = not request['record_video']
                main()
            finally:
                args.no_video = default_no_video
                args.video_dir = default_video_dir
                args.camera_distance_scale = default_camera_scale

        print(f"[READY] Waiting for samples in {directory}", flush=True)
        print("Send samples from another terminal using run_welding_sample.py --send --sample ID", flush=True)
        while simulation_app.is_running():
            if not process_next(directory, play):
                simulation_app.update()
                time.sleep(0.01)


try:
    if args.serve:
        serve()
    else:
        main()

except Exception:
    traceback.print_exc()
    raise

finally:
    simulation_app.close()
