r"""Isaac Sim 4.5 minimum RB5 playback test for T_PP_03_0001.h5.

Run with Isaac Sim's Python, not ordinary Python:
  .\python.bat C:\Users\sen\Desktop\isaacsim_source_code\run_rb5_h5_weld_test.py
"""

from isaacsim import SimulationApp

import argparse


parser = argparse.ArgumentParser()
parser.add_argument("--headless", action="store_true")
parser.add_argument("--auto-close", action="store_true")
parser.add_argument("--frames-per-point", type=int, default=4)
parser.add_argument("--tool-rpy-deg", nargs=3, type=float, default=(0.0, 0.0, 0.0))
args = parser.parse_args()

simulation_app = SimulationApp({"headless": args.headless, "renderer": "RaytracedLighting"})

from pathlib import Path
import traceback

import numpy as np
import omni.kit.commands
import omni.timeline
import omni.usd
from isaacsim.core.prims import Articulation
from isaacsim.core.utils.viewports import set_camera_view
from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdPhysics


ROOT = Path(__file__).resolve().parent
URDF_PATH = ROOT / "rb5_850e_u.urdf"
TOOL_USD_PATH = ROOT / "ATU01035_welding_tool.usd"
SOLUTION_PATH = ROOT / "rb5_h5_trajectory_solution.npz"
JOINT_NAMES = ("base", "shoulder", "elbow", "wrist1", "wrist2", "wrist3")


def require_files():
    missing = [str(path) for path in (URDF_PATH, TOOL_USD_PATH, SOLUTION_PATH) if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required file(s):\n" + "\n".join(missing))


def add_tool_reference(stage, tcp_prim_path, tcp_correction):
    tool_path = Sdf.Path(tcp_prim_path).AppendChild("WeldingTool")
    tool_xform = UsdGeom.Xform.Define(stage, tool_path)
    tool_xform.GetPrim().GetReferences().AddReference(TOOL_USD_PATH.as_posix())
    # The converted STEP layer contains millimetre-valued geometry. The main
    # Isaac stage is in metres, so an explicit 0.001 reference scale is needed.
    tool_xform.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 0.0))
    rpy = Gf.Vec3f(*args.tool_rpy_deg)
    tool_xform.AddRotateXYZOp().Set(rpy)
    tool_xform.AddScaleOp().Set(Gf.Vec3f(0.001, 0.001, 0.001))

    marker_path = Sdf.Path(tcp_prim_path).AppendChild("RecordedWeldTCP")
    marker = UsdGeom.Sphere.Define(stage, marker_path)
    marker.CreateRadiusAttr(0.008)
    marker.CreateDisplayColorAttr([Gf.Vec3f(1.0, 0.05, 0.02)])
    marker_xform = UsdGeom.Xformable(marker)
    marker_xform.AddTranslateOp().Set(Gf.Vec3d(*tcp_correction[:3, 3]))
    return str(tool_path), str(marker_path)


def add_scene(stage, tcp_positions):
    scene = UsdPhysics.Scene.Define(stage, Sdf.Path("/physicsScene"))
    scene.CreateGravityDirectionAttr().Set(Gf.Vec3f(0.0, 0.0, -1.0))
    scene.CreateGravityMagnitudeAttr().Set(9.81)
    light = UsdLux.DomeLight.Define(stage, Sdf.Path("/WorldLight"))
    light.CreateIntensityAttr(900.0)
    ground = UsdGeom.Cube.Define(stage, Sdf.Path("/Ground"))
    ground.CreateSizeAttr(1.0)
    ground.CreateDisplayColorAttr([Gf.Vec3f(0.17, 0.19, 0.22)])
    ground_xform = UsdGeom.Xformable(ground)
    ground_xform.AddScaleOp().Set(Gf.Vec3f(2.0, 2.0, 0.02))
    ground_xform.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, -0.02))

    # Persistent visual guide for the recorded Cartesian TCP line.
    curve = UsdGeom.BasisCurves.Define(stage, Sdf.Path("/RecordedTcpTrajectory"))
    curve.CreateTypeAttr("linear")
    curve.CreateCurveVertexCountsAttr([len(tcp_positions)])
    curve.CreatePointsAttr([Gf.Vec3f(*point) for point in tcp_positions])
    curve.CreateWidthsAttr([0.004])
    curve.SetWidthsInterpolation("constant")
    curve.CreateDisplayColorAttr([Gf.Vec3f(0.0, 0.9, 1.0)])


def main():
    require_files()
    solution = np.load(SOLUTION_PATH)
    joint_path = np.asarray(solution["joint_position_rad"], dtype=np.float64)
    tcp_poses = np.asarray(solution["tcp_pose_xyz_mm_rpy_deg"], dtype=np.float64)
    tcp_correction = np.asarray(solution["urdf_tcp_to_weld_tcp"], dtype=np.float64)

    status, import_config = omni.kit.commands.execute("URDFCreateImportConfig")
    if not status:
        raise RuntimeError("URDFCreateImportConfig failed")
    import_config.merge_fixed_joints = False
    import_config.convex_decomp = False
    import_config.import_inertia_tensor = True
    import_config.fix_base = True
    import_config.distance_scale = 1.0
    import_config.make_default_prim = False
    status, robot_path = omni.kit.commands.execute(
        "URDFParseAndImportFile",
        urdf_path=str(URDF_PATH),
        import_config=import_config,
        get_articulation_root=True,
    )
    if not status:
        raise RuntimeError(f"URDF import failed: {URDF_PATH}")

    stage = omni.usd.get_context().get_stage()
    robot_scope = Sdf.Path(robot_path).GetParentPath()
    tcp_candidates = [
        prim.GetPath().pathString
        for prim in stage.Traverse()
        if prim.GetName() == "tcp" and prim.GetPath().HasPrefix(robot_scope)
    ]
    if len(tcp_candidates) != 1:
        raise RuntimeError(f"Expected one imported tcp link below {robot_path}, found {tcp_candidates}")
    tool_path, marker_path = add_tool_reference(stage, tcp_candidates[0], tcp_correction)
    add_scene(stage, tcp_poses[:, :3] / 1000.0)
    set_camera_view(eye=[1.35, -1.25, 1.05], target=[0.42, -0.10, 0.25])

    timeline = omni.timeline.get_timeline_interface()
    timeline.play()
    for _ in range(5):
        simulation_app.update()

    robot = Articulation(robot_path)
    robot.initialize()
    dof_names = list(robot.dof_names)
    missing_joints = [name for name in JOINT_NAMES if name not in dof_names]
    if missing_joints:
        raise RuntimeError(f"Imported articulation is missing joints {missing_joints}; DOFs={dof_names}")
    joint_indices = [dof_names.index(name) for name in JOINT_NAMES]

    print(f"[ROBOT] articulation={robot_path}")
    print(f"[TOOL] attached={tool_path}")
    print(f"[TCP] calibrated marker={marker_path}")
    print(f"[PLAYBACK] {len(joint_path)} TCP poses, {args.frames_per_point} frames/pose")
    for index, positions in enumerate(joint_path):
        robot.set_joint_positions(positions, joint_indices=joint_indices)
        for _ in range(max(1, args.frames_per_point)):
            simulation_app.update()
        if index in (0, len(joint_path) - 1):
            print(f"[PLAYBACK] reached point {index + 1}/{len(joint_path)}")

    stage_path = ROOT / "rb5_h5_weld_test_scene.usda"
    omni.usd.get_context().save_as_stage(stage_path.as_posix())
    print(f"[DONE] Playback complete; scene saved to {stage_path}")
    if not args.auto_close and not args.headless:
        print("[INFO] Isaac Sim stays open. Close the window when finished.")
        while simulation_app.is_running():
            simulation_app.update()
    timeline.stop()


try:
    main()
except Exception:
    traceback.print_exc()
    raise
finally:
    simulation_app.close()
