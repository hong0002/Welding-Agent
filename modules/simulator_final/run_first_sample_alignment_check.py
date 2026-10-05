r"""Minimal RB10/H5 welding-tool check with CAD mount attached to robot TCP.

Current hypothesis being visualized:
    RB10 link6 -> raw tcp (URDF: 115.3 mm)
    CAD mount   -> raw tcp origin
    CAD nozzle  -> extends from that mount by the CAD's real mount-to-tip length

This script does NOT force the CAD nozzle tip onto the H5 waypoint.
"""

from isaacsim import SimulationApp

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--headless", action="store_true")
parser.add_argument("--auto-close", action="store_true")
parser.add_argument("--point-index", type=int, choices=range(150), default=0)
args = parser.parse_args()

simulation_app = SimulationApp(
    {
        "headless": args.headless,
        "renderer": "RaytracedLighting",
    }
)

import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import omni.kit.commands
import omni.timeline
import omni.usd

from isaacsim.core.prims import Articulation
from isaacsim.core.utils.viewports import set_camera_view
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics


ROOT = Path(__file__).resolve().parent

URDF_PATH = (
    ROOT
    / "rbpodo_description"
    / "robots"
    / "rb10_1300e_u.urdf"
)

SOLUTION_PATH = ROOT / "rb10_h5_trajectory_solution.npz"
TOOL_USD_PATH = ROOT / "ATU01035_welding_tool.usd"

JOINT_NAMES = (
    "base",
    "shoulder",
    "elbow",
    "wrist1",
    "wrist2",
    "wrist3",
)

from welding_tool_geometry import (
    CAD_TIP_LOCAL_MM, CAD_MOUNT_LOCAL_MM, mounted_cad_transform,
)


def inspect_tcp_joint(urdf_path):
    root = ET.parse(urdf_path).getroot()

    for joint in root.findall("joint"):
        if joint.attrib.get("name") != "tcp_joint":
            continue

        parent = joint.find("parent").attrib["link"]
        child = joint.find("child").attrib["link"]
        origin = joint.find("origin")

        xyz = np.fromstring(
            origin.attrib.get("xyz", "0 0 0"),
            sep=" ",
            dtype=np.float64,
        )

        rpy = np.fromstring(
            origin.attrib.get("rpy", "0 0 0"),
            sep=" ",
            dtype=np.float64,
        )

        print("\n[TCP JOINT]")
        print(f"  parent link          = {parent}")
        print(f"  child link           = {child}")
        print(f"  origin xyz [m]       = {xyz.tolist()}")
        print(f"  origin rpy [rad]     = {rpy.tolist()}")
        print(f"  parent->TCP distance = {np.linalg.norm(xyz) * 1000.0:.3f} mm")

        return xyz

    raise RuntimeError("tcp_joint not found")


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


def add_sphere(stage, path, position, radius, color):
    sphere = UsdGeom.Sphere.Define(stage, path)
    sphere.CreateRadiusAttr(radius)
    sphere.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    UsdGeom.Xformable(sphere).AddTranslateOp().Set(
        Gf.Vec3d(*[float(v) for v in position])
    )
    return sphere


def get_world_position(stage, prim_path):
    prim = stage.GetPrimAtPath(Sdf.Path(prim_path))
    if not prim.IsValid():
        raise RuntimeError(f"Invalid prim: {prim_path}")

    cache = UsdGeom.XformCache(Usd.TimeCode.Default())
    transform = cache.GetLocalToWorldTransform(prim)
    p = transform.ExtractTranslation()

    return np.array(
        [float(p[0]), float(p[1]), float(p[2])],
        dtype=np.float64,
    )


def add_tool_at_tcp(
    stage,
    tcp_path,
    correction,
    selected_h5_point,
):
    mount_local_m = CAD_MOUNT_LOCAL_MM * 0.001
    tip_local_m = CAD_TIP_LOCAL_MM * 0.001

    # Align the rear mounting face, not the chord to the bent nozzle tip.
    transform = mounted_cad_transform()
    tool_rotation = transform[:3, :3]
    tool_translation = transform[:3, 3]

    tool_path = Sdf.Path(tcp_path).AppendChild("WeldingTool")
    tool_root = UsdGeom.Xform.Define(stage, tool_path)

    tool_root.AddTranslateOp().Set(
        Gf.Vec3d(*[float(v) for v in tool_translation])
    )
    tool_root.AddOrientOp().Set(
        matrix_to_quaternion(tool_rotation)
    )

    geometry_path = tool_path.AppendChild("Geometry")
    geometry = UsdGeom.Xform.Define(stage, geometry_path)

    geometry.GetPrim().GetReferences().AddReference(
        TOOL_USD_PATH.as_posix()
    )

    geometry.AddScaleOp().Set(
        Gf.Vec3f(0.001, 0.001, 0.001)
    )

    mount_in_tcp = (
        tool_translation
        + tool_rotation @ mount_local_m
    )

    tip_in_tcp = (
        tool_translation
        + tool_rotation @ tip_local_m
    )

    print("\n[TOOL @ TCP]")
    print(f"  CAD mount in TCP      = {mount_in_tcp.tolist()}")
    print(f"  mount/TCP error       = {np.linalg.norm(mount_in_tcp) * 1000.0:.9f} mm")
    print(f"  CAD nozzle in TCP     = {tip_in_tcp.tolist()}")
    print(f"  mount->tip distance   = {np.linalg.norm(tip_in_tcp - mount_in_tcp) * 1000.0:.3f} mm")

    # Blue = CAD mount == raw TCP origin
    mount_marker_path = tool_path.AppendChild("CadMountMarker")
    add_sphere(
        stage,
        mount_marker_path,
        mount_local_m,
        0.015,
        (0.0, 0.3, 1.0),
    )

    # Yellow = CAD nozzle tip
    tip_marker_path = tool_path.AppendChild("CadTipMarker")
    add_sphere(
        stage,
        tip_marker_path,
        tip_local_m,
        0.012,
        (1.0, 1.0, 0.0),
    )

    # Red = corrected/calibrated RB10 TCP
    actual_tcp_marker_path = (
        Sdf.Path(tcp_path)
        .AppendChild("ActualTcpMarker")
    )
    add_sphere(
        stage,
        actual_tcp_marker_path,
        correction[:3, 3],
        0.010,
        (1.0, 0.0, 0.0),
    )

    # Cyan = H5 selected waypoint, already known to share Isaac world.
    h5_marker_path = Sdf.Path("/SelectedH5Waypoint")
    add_sphere(
        stage,
        h5_marker_path,
        selected_h5_point,
        0.011,
        (0.0, 1.0, 1.0),
    )

    return (
        mount_marker_path,
        tip_marker_path,
        actual_tcp_marker_path,
        h5_marker_path,
    )


def main():
    for path in (
        URDF_PATH,
        SOLUTION_PATH,
        TOOL_USD_PATH,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)

    tcp_joint_xyz = inspect_tcp_joint(URDF_PATH)

    print(
        f"[CAD] mount->tip distance = "
        f"{np.linalg.norm(CAD_TIP_LOCAL_MM - CAD_MOUNT_LOCAL_MM):.3f} mm"
    )

    solution = np.load(SOLUTION_PATH)

    joint_path = np.asarray(
        solution["joint_position_rad"],
        dtype=np.float64,
    )

    tcp_pose = np.asarray(
        solution["tcp_pose_xyz_mm_rpy_deg"],
        dtype=np.float64,
    )

    correction = np.asarray(
        solution["urdf_tcp_to_weld_tcp"],
        dtype=np.float64,
    )

    h5_positions_m = tcp_pose[:, :3] / 1000.0

    # --------------------------------------------------------
    # Import RB10
    # --------------------------------------------------------

    status, config = omni.kit.commands.execute(
        "URDFCreateImportConfig"
    )

    if not status:
        raise RuntimeError("URDFCreateImportConfig failed")

    config.merge_fixed_joints = False
    config.convex_decomp = False
    config.import_inertia_tensor = True
    config.fix_base = True
    config.distance_scale = 1.0
    config.make_default_prim = False

    status, robot_path = omni.kit.commands.execute(
        "URDFParseAndImportFile",
        urdf_path=str(URDF_PATH),
        import_config=config,
        get_articulation_root=True,
    )

    if not status:
        raise RuntimeError("RB10 URDF import failed")

    stage = omni.usd.get_context().get_stage()
    robot_scope = Sdf.Path(robot_path).GetParentPath()

    tcp_paths = [
        prim.GetPath().pathString
        for prim in stage.Traverse()
        if (
            prim.GetName() == "tcp"
            and prim.GetPath().HasPrefix(robot_scope)
        )
    ]

    if len(tcp_paths) != 1:
        raise RuntimeError(
            f"Expected one tcp, found {tcp_paths}"
        )

    tcp_path = tcp_paths[0]

    print(f"[ROBOT] tcp path={tcp_path}")

    # --------------------------------------------------------
    # Minimal scene / tool
    # --------------------------------------------------------

    scene = UsdPhysics.Scene.Define(
        stage,
        "/physicsScene",
    )

    # Zero gravity only for this static diagnostic.
    scene.CreateGravityDirectionAttr().Set(
        Gf.Vec3f(0.0, 0.0, -1.0)
    )
    scene.CreateGravityMagnitudeAttr().Set(0.0)

    light = UsdLux.DomeLight.Define(
        stage,
        "/WorldLight",
    )
    light.CreateIntensityAttr(1000.0)

    (
        mount_marker_path,
        tip_marker_path,
        actual_tcp_marker_path,
        h5_marker_path,
    ) = add_tool_at_tcp(
        stage,
        tcp_path,
        correction,
        h5_positions_m[args.point_index],
    )

    # --------------------------------------------------------
    # Articulation
    # --------------------------------------------------------

    timeline = omni.timeline.get_timeline_interface()
    timeline.play()

    for _ in range(8):
        simulation_app.update()

    robot = Articulation(robot_path)
    robot.initialize()

    dof_names = list(robot.dof_names)

    missing = [
        name
        for name in JOINT_NAMES
        if name not in dof_names
    ]

    if missing:
        raise RuntimeError(
            f"Missing joints {missing}; DOFs={dof_names}"
        )

    indices = [
        dof_names.index(name)
        for name in JOINT_NAMES
    ]

    # --------------------------------------------------------
    # Apply selected H5 point
    # --------------------------------------------------------

    q = np.asarray(
        joint_path[args.point_index],
        dtype=np.float64,
    )

    robot.set_joint_positions(
        q,
        joint_indices=indices,
    )

    robot.set_joint_velocities(
        np.zeros(len(indices), dtype=np.float64),
        joint_indices=indices,
    )

    for _ in range(3):
        simulation_app.update()

    q_read = np.asarray(
        robot.get_joint_positions(
            joint_indices=indices
        ),
        dtype=np.float64,
    ).reshape(-1)

    joint_error_deg = np.max(
        np.abs(
            np.rad2deg(q_read - q)
        )
    )

    timeline.pause()

    # --------------------------------------------------------
    # Final selected-point check
    # --------------------------------------------------------

    mount_world = get_world_position(
        stage,
        mount_marker_path,
    )

    tip_world = get_world_position(
        stage,
        tip_marker_path,
    )

    rb10_tcp_world = get_world_position(
        stage,
        actual_tcp_marker_path,
    )

    h5_world = np.asarray(
        h5_positions_m[args.point_index],
        dtype=np.float64,
    )

    mount_to_h5_mm = (
        np.linalg.norm(
            mount_world - h5_world
        )
        * 1000.0
    )

    tip_to_h5_mm = (
        np.linalg.norm(
            tip_world - h5_world
        )
        * 1000.0
    )

    tcp_to_h5_mm = (
        np.linalg.norm(
            rb10_tcp_world - h5_world
        )
        * 1000.0
    )

    print("\n[SELECTED POINT CHECK]")
    print(f"  point index            = {args.point_index}")
    print(f"  max joint error        = {joint_error_deg:.6f} deg")
    print(f"  CAD mount world        = {mount_world.tolist()}")
    print(f"  CAD nozzle world       = {tip_world.tolist()}")
    print(f"  calibrated TCP world   = {rb10_tcp_world.tolist()}")
    print(f"  H5 waypoint world      = {h5_world.tolist()}")
    print(f"  CAD mount -> H5        = {mount_to_h5_mm:.3f} mm")
    print(f"  calibrated TCP -> H5   = {tcp_to_h5_mm:.3f} mm")
    print(f"  CAD nozzle -> H5       = {tip_to_h5_mm:.3f} mm")

    print(
        "\n[COLOR] "
        "blue=CAD mount/raw TCP, "
        "red=calibrated TCP, "
        "cyan=H5 waypoint, "
        "yellow=CAD nozzle tip"
    )

    # Camera around selected H5 point.
    h5 = h5_world
    set_camera_view(
        eye=(h5 + np.array([0.45, -0.45, 0.30])).tolist(),
        target=h5.tolist(),
    )

    output = (
        ROOT
        / "first_sample_alignment_check.usda"
    )

    omni.usd.get_context().save_as_stage(
        output.as_posix()
    )

    print(f"\n[SAVE] {output}")

    if not args.auto_close and not args.headless:
        print(
            "[INFO] Scene stays open until you close Isaac Sim."
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
