r"""RB10-1300E trajectory playback with 3x visual scale.

Visualization only:
- Robot geometry/kinematic distances are imported at 3x scale.
- H5 TCP positions are also multiplied by 3 so the displayed path matches.
- Joint angles are unchanged.
- No welding torch.
- No workpiece.

IMPORTANT:
This is NOT for real-size FK validation.
It is only for making the motion easier to see.

The H5 data has no timestamps, so --duration-sec is visualization time only.
"""

from isaacsim import SimulationApp

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--headless", action="store_true")
parser.add_argument("--auto-close", action="store_true")
parser.add_argument(
    "--duration-sec",
    type=float,
    default=30.0,
    help="Visual playback duration only; H5 has no physical timestamps.",
)
args = parser.parse_args()

simulation_app = SimulationApp(
    {
        "headless": args.headless,
        "renderer": "RaytracedLighting",
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
from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdPhysics


# ============================================================
# Settings
# ============================================================

ROOT = Path(__file__).resolve().parent

URDF_PATH = (
    ROOT
    / "rbpodo_description"
    / "robots"
    / "rb10_1300e_u.urdf"
)

SOLUTION_PATH = ROOT / "rb10_h5_trajectory_solution.npz"

JOINT_NAMES = (
    "base",
    "shoulder",
    "elbow",
    "wrist1",
    "wrist2",
    "wrist3",
)

# Visual-only enlargement.
VIS_SCALE = 3.0


# ============================================================
# Visualization helpers
# ============================================================

def add_h5_path(stage, h5_positions_scaled):
    """Thick green H5 TCP path."""
    curve = UsdGeom.BasisCurves.Define(
        stage,
        "/H5TcpPath",
    )

    curve.CreateTypeAttr("linear")

    curve.CreateCurveVertexCountsAttr(
        [len(h5_positions_scaled)]
    )

    curve.CreatePointsAttr(
        [
            Gf.Vec3f(
                float(p[0]),
                float(p[1]),
                float(p[2]),
            )
            for p in h5_positions_scaled
        ]
    )

    curve.CreateWidthsAttr([0.05])
    curve.SetWidthsInterpolation("constant")

    curve.CreateDisplayColorAttr(
        [Gf.Vec3f(0.1, 1.0, 0.1)]
    )


# ============================================================
# Main
# ============================================================

def main():
    if not URDF_PATH.is_file():
        raise FileNotFoundError(URDF_PATH)

    if not SOLUTION_PATH.is_file():
        raise FileNotFoundError(SOLUTION_PATH)

    # --------------------------------------------------------
    # Load trajectory
    # --------------------------------------------------------

    solution = np.load(SOLUTION_PATH)

    joint_path = np.asarray(
        solution["joint_position_rad"],
        dtype=np.float64,
    )

    tcp_pose = np.asarray(
        solution["tcp_pose_xyz_mm_rpy_deg"],
        dtype=np.float64,
    )

    if joint_path.ndim != 2 or joint_path.shape[1] != 6:
        raise RuntimeError(
            f"Expected joint trajectory shape (N, 6), "
            f"got {joint_path.shape}"
        )

    n = len(joint_path)

    # Real H5 positions in metres.
    h5_positions_real = (
        tcp_pose[:, :3]
        / 1000.0
    )

    # Visual-only scaled H5 positions.
    h5_positions_scaled = (
        h5_positions_real
        * VIS_SCALE
    )

    real_endpoint_distance_mm = (
        np.linalg.norm(
            h5_positions_real[-1]
            - h5_positions_real[0]
        )
        * 1000.0
    )

    visual_endpoint_distance_mm = (
        np.linalg.norm(
            h5_positions_scaled[-1]
            - h5_positions_scaled[0]
        )
        * 1000.0
    )

    joint_range_deg = np.rad2deg(
        np.max(joint_path, axis=0)
        - np.min(joint_path, axis=0)
    )

    print(f"[SCALE] visual scale = {VIS_SCALE:.1f}x")
    print(f"[TRAJECTORY] waypoints = {n}")
    print(
        f"[TRAJECTORY] real TCP start->end = "
        f"{real_endpoint_distance_mm:.3f} mm"
    )
    print(
        f"[TRAJECTORY] displayed TCP start->end = "
        f"{visual_endpoint_distance_mm:.3f} mm"
    )
    print(
        "[TRAJECTORY] joint motion range deg = "
        f"{joint_range_deg.tolist()}"
    )
    print(
        f"[TRAJECTORY] visual duration = "
        f"{args.duration_sec:.1f} sec"
    )

    # --------------------------------------------------------
    # Import RB10 at 3x scale
    # --------------------------------------------------------

    status, config = omni.kit.commands.execute(
        "URDFCreateImportConfig"
    )

    if not status:
        raise RuntimeError(
            "URDFCreateImportConfig failed"
        )

    config.merge_fixed_joints = False
    config.convex_decomp = False
    config.import_inertia_tensor = True
    config.fix_base = True

    # THIS enlarges all robot distances/geometry.
    config.distance_scale = VIS_SCALE

    config.make_default_prim = False

    status, robot_path = omni.kit.commands.execute(
        "URDFParseAndImportFile",
        urdf_path=str(URDF_PATH),
        import_config=config,
        get_articulation_root=True,
    )

    if not status:
        raise RuntimeError(
            "RB10 URDF import failed"
        )

    stage = omni.usd.get_context().get_stage()

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

    # --------------------------------------------------------
    # Minimal scene
    # --------------------------------------------------------

    scene = UsdPhysics.Scene.Define(
        stage,
        "/physicsScene",
    )

    # Visual playback only.
    # Zero gravity prevents sag while teleporting joint poses.
    scene.CreateGravityDirectionAttr().Set(
        Gf.Vec3f(0.0, 0.0, -1.0)
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

    # Green scaled H5 path.
    add_h5_path(
        stage,
        h5_positions_scaled,
    )

    # --------------------------------------------------------
    # Camera
    # --------------------------------------------------------

    center = np.mean(
        h5_positions_scaled,
        axis=0,
    )

    # Scaled scene -> farther camera.
    set_camera_view(
        eye=(
            center
            + np.array(
                [0.90, -0.90, 0.60]
            )
        ).tolist(),
        target=center.tolist(),
    )

    # --------------------------------------------------------
    # Initialize articulation
    # --------------------------------------------------------

    timeline = (
        omni.timeline
        .get_timeline_interface()
    )

    timeline.play()

    for _ in range(8):
        simulation_app.update()

    robot = Articulation(
        robot_path
    )

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

    # --------------------------------------------------------
    # Start pose
    # --------------------------------------------------------

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

    print("\n[PLAYBACK] start")
    print(
        "[PLAYBACK] red sphere = TCP, "
        "green line = 3x visualized H5 path"
    )

    # --------------------------------------------------------
    # Smooth playback
    # --------------------------------------------------------

    duration = max(
        float(args.duration_sec),
        1.0,
    )

    start_time = time.perf_counter()
    last_report = -1

    while True:
        elapsed = (
            time.perf_counter()
            - start_time
        )

        if elapsed >= duration:
            break

        progress = (
            elapsed
            / duration
        )

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

        # Linear interpolation between solved joint waypoints.
        q = (
            (1.0 - alpha)
            * joint_path[i0]
            + alpha
            * joint_path[i1]
        )

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

        # Prevent a busy loop.
        time.sleep(0.005)

    # --------------------------------------------------------
    # Exact final pose
    # --------------------------------------------------------

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

    timeline.pause()

    print("  progress=100%")
    print("[PLAYBACK] finished")

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    output = (
        ROOT
        / "rb10_trajectory_3x.usda"
    )

    omni.usd.get_context().save_as_stage(
        output.as_posix()
    )

    print(f"[SAVE] {output}")

    if (
        not args.auto_close
        and not args.headless
    ):
        print(
            "[INFO] Final pose stays open "
            "until you close Isaac Sim."
        )

        while simulation_app.is_running():
            simulation_app.update()


try:
    main()

except Exception:
    traceback.print_exc()
    raise

finally:
    simulation_app.close()
