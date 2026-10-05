r"""RB10-1300E + Panasonic ATU01035 + T_PP_03_0001 virtual welding.

Changes in this version
-----------------------
- RB10 stays at REAL scale (1.0x).
- No red TCP sphere.
- Uses the real T_PP_03_0001 OBJ.
- OBJ numeric coordinates are treated as millimetres -> metres (x0.001).
- The assumed T-joint weld seam is now:
    * along OBJ local Y
    * on ONE SIDE of the vertical plate
    * at the top surface of the 3 mm base plate
- The workpiece is rotated/translated so this seam follows the provisional
  ATU01035 nozzle-tip path.

IMPORTANT
---------
This is still a virtual alignment assumption.
The original dataset workpiece pose and the exact physical torch mounting/TCP
have not yet been confirmed by the dataset provider.
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
    help="Visual playback duration only.",
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
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics


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

SOLUTION_PATH = ROOT / "rb10_h5_trajectory_solution.npz"
TOOL_USD_PATH = ROOT / "ATU01035_welding_tool.usd"

WORKPIECE_OBJ_PATH = (
    ROOT
    / "Datase"
    / "other_data"
    / "Other"
    / "Other"
    / "모델링 데이터"
    / "Tee"
    / "PP(Plate-Plate)"
    / "03(3mm)"
    / "T_PP_03_0001"
    / "T_PP_03_0001.obj"
)

JOINT_NAMES = (
    "base",
    "shoulder",
    "elbow",
    "wrist1",
    "wrist2",
    "wrist3",
)

# Plate thickness for T_PP_03.
WORKPIECE_THICKNESS_MM = 3.0

# Visualization only:
# draw the blue planned nozzle path 10 mm above the REAL path
# so it does not disappear inside the plate/torch geometry.
GUIDE_PATH_Z_OFFSET_M = 0.010
GUIDE_PATH_SIDE_OFFSET_M = 0.008

# Which side of the vertical plate to use.
# -1 = local -X side
# +1 = local +X side
#
# If the weld line appears on the opposite fillet, change only this value.
WELD_SIDE = +1

# Current provisional Panasonic CAD points, millimetres.
CAD_TIP_LOCAL_MM = np.array(
    [0.1407694603715624, 20.39885629926409, 425.4869384765625],
    dtype=np.float64,
)

CAD_MOUNT_LOCAL_MM = np.array(
    [-1.0504137674967449, -21.709200586591447, -8.185713995070685],
    dtype=np.float64,
)


# ============================================================
# Math helpers
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
        ],
        dtype=np.float64,
    )

    return np.eye(3) + skew + skew @ skew * (
        (1.0 - dot) / np.dot(cross, cross)
    )


def matrix_to_quaternion(matrix):
    matrix = np.asarray(matrix, dtype=np.float64)
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


def build_frame_from_local_y(y_world):
    """Create workpiece orientation with local +Y following weld direction.

    Local +Z is kept as close as possible to world +Z.
    """
    y_world = np.asarray(y_world, dtype=np.float64)
    y_world /= np.linalg.norm(y_world)

    z_hint = np.array([0.0, 0.0, 1.0], dtype=np.float64)

    # Keep Z perpendicular to Y.
    z_world = z_hint - np.dot(z_hint, y_world) * y_world

    if np.linalg.norm(z_world) < 1e-8:
        z_hint = np.array([1.0, 0.0, 0.0], dtype=np.float64)
        z_world = z_hint - np.dot(z_hint, y_world) * y_world

    z_world /= np.linalg.norm(z_world)

    # Right-handed frame: X x Y = Z
    x_world = np.cross(y_world, z_world)
    x_world /= np.linalg.norm(x_world)

    # Recompute Z for numerical orthogonality.
    z_world = np.cross(x_world, y_world)
    z_world /= np.linalg.norm(z_world)

    # Columns = world directions of local X/Y/Z.
    return np.column_stack(
        (x_world, y_world, z_world)
    )


def world_position(stage, prim_path):
    cache = UsdGeom.XformCache(
        Usd.TimeCode.Default()
    )

    prim = stage.GetPrimAtPath(
        prim_path
    )

    if not prim.IsValid():
        raise RuntimeError(
            f"Invalid prim: {prim_path}"
        )

    matrix = cache.GetLocalToWorldTransform(
        prim
    )

    p = matrix.ExtractTranslation()

    return np.array(
        [float(p[0]), float(p[1]), float(p[2])],
        dtype=np.float64,
    )


# ============================================================
# OBJ loader
# ============================================================

def load_obj_mesh(obj_path):
    vertices = []
    counts = []
    indices = []

    with open(
        obj_path,
        "r",
        encoding="utf-8",
        errors="ignore",
    ) as f:
        for raw_line in f:
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            if line.startswith("v "):
                parts = line.split()

                if len(parts) >= 4:
                    vertices.append(
                        [
                            float(parts[1]),
                            float(parts[2]),
                            float(parts[3]),
                        ]
                    )

            elif line.startswith("f "):
                parts = line.split()[1:]
                face = []

                for token in parts:
                    first = token.split("/")[0]

                    if not first:
                        continue

                    idx = int(first)

                    if idx > 0:
                        idx -= 1
                    else:
                        idx = len(vertices) + idx

                    face.append(idx)

                if len(face) >= 3:
                    counts.append(len(face))
                    indices.extend(face)

    vertices = np.asarray(
        vertices,
        dtype=np.float64,
    )

    if len(vertices) == 0 or len(counts) == 0:
        raise RuntimeError(
            f"Could not read OBJ geometry: {obj_path}"
        )

    return vertices, counts, indices


# ============================================================
# Visualization helpers
# ============================================================

def add_curve(
    stage,
    path,
    points,
    width,
    color,
):
    points = np.asarray(
        points,
        dtype=np.float64,
    )

    curve = UsdGeom.BasisCurves.Define(
        stage,
        path,
    )

    curve.CreateTypeAttr("linear")
    curve.CreateCurveVertexCountsAttr(
        [len(points)]
    )

    curve.CreatePointsAttr(
        [
            Gf.Vec3f(
                float(p[0]),
                float(p[1]),
                float(p[2]),
            )
            for p in points
        ]
    )

    curve.CreateWidthsAttr(
        [float(width)]
    )

    curve.SetWidthsInterpolation(
        "constant"
    )

    curve.CreateDisplayColorAttr(
        [color]
    )



def create_dynamic_curve(
    stage,
    path,
    start_point,
    width,
    color,
):
    """Create a curve that can grow during playback."""
    p = np.asarray(
        start_point,
        dtype=np.float64,
    )

    curve = UsdGeom.BasisCurves.Define(
        stage,
        path,
    )

    curve.CreateTypeAttr("linear")
    curve.CreateCurveVertexCountsAttr([2])

    # Two identical points keep the curve valid before motion starts.
    curve.CreatePointsAttr(
        [
            Gf.Vec3f(
                float(p[0]),
                float(p[1]),
                float(p[2]),
            ),
            Gf.Vec3f(
                float(p[0]),
                float(p[1]),
                float(p[2]),
            ),
        ]
    )

    curve.CreateWidthsAttr(
        [float(width)]
    )
    curve.SetWidthsInterpolation(
        "constant"
    )
    curve.CreateDisplayColorAttr(
        [color]
    )

    return curve


def update_dynamic_curve(
    curve,
    points,
):
    """Update an existing BasisCurves object with a point list."""
    pts = np.asarray(
        points,
        dtype=np.float64,
    )

    if len(pts) == 0:
        return

    if len(pts) == 1:
        pts = np.vstack(
            [pts[0], pts[0]]
        )

    curve.GetCurveVertexCountsAttr().Set(
        [len(pts)]
    )

    curve.GetPointsAttr().Set(
        [
            Gf.Vec3f(
                float(p[0]),
                float(p[1]),
                float(p[2]),
            )
            for p in pts
        ]
    )


def add_torch_at_tcp(
    stage,
    tcp_path,
):
    mount_local_m = (
        CAD_MOUNT_LOCAL_MM
        * 0.001
    )

    cad_axis = (
        CAD_TIP_LOCAL_MM
        - CAD_MOUNT_LOCAL_MM
    )

    cad_axis /= np.linalg.norm(
        cad_axis
    )

    # Current provisional assumption.
    tcp_axis = np.array(
        [0.0, -1.0, 0.0],
        dtype=np.float64,
    )

    tool_rotation = rotation_between(
        cad_axis,
        tcp_axis,
    )

    tool_translation = -(
        tool_rotation
        @ mount_local_m
    )

    tool_path = (
        Sdf.Path(tcp_path)
        .AppendChild("WeldingTool")
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

    geometry_path = (
        tool_path
        .AppendChild("Geometry")
    )

    geometry = UsdGeom.Xform.Define(
        stage,
        geometry_path,
    )

    geometry.GetPrim().GetReferences().AddReference(
        TOOL_USD_PATH.as_posix()
    )

    # Panasonic CAD uses mm.
    geometry.AddScaleOp().Set(
        Gf.Vec3f(
            0.001,
            0.001,
            0.001,
        )
    )

    # Transform-only point, NOT a visible sphere.
    nozzle_tip_path = (
        tool_path
        .AppendChild("NozzleTip")
    )

    nozzle_tip = UsdGeom.Xform.Define(
        stage,
        nozzle_tip_path,
    )

    tip_m = (
        CAD_TIP_LOCAL_MM
        * 0.001
    )

    nozzle_tip.AddTranslateOp().Set(
        Gf.Vec3d(
            float(tip_m[0]),
            float(tip_m[1]),
            float(tip_m[2]),
        )
    )

    print("\n[TOOL]")
    print(
        "  Panasonic ATU01035 added"
    )
    print(
        "  NOTE: mounting is provisional."
    )

    return nozzle_tip_path.pathString


def sample_torch_tip_path(
    simulation_app,
    stage,
    robot,
    joint_path,
    indices,
    nozzle_tip_path,
):
    tip_positions = []

    print(
        "\n[PRECOMPUTE] sampling "
        "provisional nozzle-tip path..."
    )

    for i, q in enumerate(
        joint_path
    ):
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

        tip_positions.append(
            world_position(
                stage,
                nozzle_tip_path,
            )
        )

        if i in (
            0,
            len(joint_path) // 2,
            len(joint_path) - 1,
        ):
            print(
                f"  sample "
                f"{i + 1}/{len(joint_path)} "
                f"tip="
                f"{tip_positions[-1].tolist()}"
            )

    return np.asarray(
        tip_positions,
        dtype=np.float64,
    )


# ============================================================
# Workpiece / weld seam
# ============================================================

def add_workpiece(
    stage,
    obj_path,
    target_tip_path,
):
    vertices_mm, face_counts, face_indices = (
        load_obj_mesh(obj_path)
    )

    bbox_min_mm = vertices_mm.min(
        axis=0
    )
    bbox_max_mm = vertices_mm.max(
        axis=0
    )
    dims_mm = (
        bbox_max_mm
        - bbox_min_mm
    )

    print("\n[WORKPIECE]")
    print(
        f"  dimensions mm = "
        f"{dims_mm.tolist()}"
    )

    # OBJ mm -> Isaac metres.
    vertices_m = (
        vertices_mm
        * 0.001
    )

    bbox_min_m = (
        bbox_min_mm
        * 0.001
    )
    bbox_max_m = (
        bbox_max_mm
        * 0.001
    )

    thickness_m = (
        WORKPIECE_THICKNESS_MM
        * 0.001
    )

    # --------------------------------------------------------
    # T-joint seam assumption
    #
    # Base plate:
    #   top surface = bbox_min_z + 3 mm
    #
    # Vertical plate:
    #   assumed centered around bbox center X
    #   thickness = 3 mm
    #
    # Weld seam:
    #   along local Y
    #   at either -X side or +X side of vertical plate
    # --------------------------------------------------------

    center_x = 0.5 * (
        bbox_min_m[0]
        + bbox_max_m[0]
    )

    seam_x = (
        center_x
        + WELD_SIDE
        * 0.5
        * thickness_m
    )

    seam_z = (
        bbox_min_m[2]
        + thickness_m
    )

    # Full geometric seam along local Y.
    seam_local_start = np.array(
        [
            seam_x,
            bbox_min_m[1],
            seam_z,
        ],
        dtype=np.float64,
    )

    seam_local_end = np.array(
        [
            seam_x,
            bbox_max_m[1],
            seam_z,
        ],
        dtype=np.float64,
    )

    seam_local_center = (
        0.5
        * (
            seam_local_start
            + seam_local_end
        )
    )

    tip_start = np.asarray(
        target_tip_path[0],
        dtype=np.float64,
    )

    tip_end = np.asarray(
        target_tip_path[-1],
        dtype=np.float64,
    )

    tip_vector = (
        tip_end
        - tip_start
    )

    tip_length = np.linalg.norm(
        tip_vector
    )

    if tip_length < 1e-8:
        raise RuntimeError(
            "Nozzle-tip path start/end "
            "are too close."
        )

    tip_center = (
        0.5
        * (
            tip_start
            + tip_end
        )
    )

    # THIS is the key change:
    # local Y follows the welding travel direction.
    rotation = build_frame_from_local_y(
        tip_vector
    )

    # Put the assumed seam center directly under the
    # provisional nozzle-tip path center.
    translation = (
        tip_center
        - rotation
        @ seam_local_center
    )

    root_path = Sdf.Path(
        "/Workpiece"
    )

    root = UsdGeom.Xform.Define(
        stage,
        root_path,
    )

    root.AddTranslateOp().Set(
        Gf.Vec3d(
            float(translation[0]),
            float(translation[1]),
            float(translation[2]),
        )
    )

    root.AddOrientOp().Set(
        matrix_to_quaternion(
            rotation
        )
    )

    mesh_path = (
        root_path
        .AppendChild("T_PP_03_0001")
    )

    mesh = UsdGeom.Mesh.Define(
        stage,
        mesh_path,
    )

    mesh.CreatePointsAttr(
        [
            Gf.Vec3f(
                float(v[0]),
                float(v[1]),
                float(v[2]),
            )
            for v in vertices_m
        ]
    )

    mesh.CreateFaceVertexCountsAttr(
        face_counts
    )

    mesh.CreateFaceVertexIndicesAttr(
        face_indices
    )

    mesh.CreateSubdivisionSchemeAttr().Set(
        "none"
    )

    mesh.CreateDoubleSidedAttr(
        True
    )

    mesh.CreateDisplayColorAttr(
        [
            Gf.Vec3f(
                0.55,
                0.58,
                0.62,
            )
        ]
    )

    seam_world_start = (
        rotation
        @ seam_local_start
        + translation
    )

    seam_world_end = (
        rotation
        @ seam_local_end
        + translation
    )

    print(
        f"  weld side = "
        f"{'local -X' if WELD_SIDE < 0 else 'local +X'}"
    )
    print(
        "  weld direction = local Y"
    )
    print(
        f"  full seam length = "
        f"{np.linalg.norm(seam_local_end - seam_local_start) * 1000.0:.3f} mm"
    )
    print(
        f"  nozzle start->end = "
        f"{tip_length * 1000.0:.3f} mm"
    )

    return tip_center


# ============================================================
# Main
# ============================================================

def main():
    for path in (
        URDF_PATH,
        SOLUTION_PATH,
        TOOL_USD_PATH,
        WORKPIECE_OBJ_PATH,
    ):
        if not path.is_file():
            raise FileNotFoundError(
                path
            )

    solution = np.load(
        SOLUTION_PATH
    )

    joint_path = np.asarray(
        solution[
            "joint_position_rad"
        ],
        dtype=np.float64,
    )

    tcp_pose = np.asarray(
        solution[
            "tcp_pose_xyz_mm_rpy_deg"
        ],
        dtype=np.float64,
    )

    if (
        joint_path.ndim != 2
        or joint_path.shape[1] != 6
    ):
        raise RuntimeError(
            f"Expected (N,6), "
            f"got {joint_path.shape}"
        )

    n = len(
        joint_path
    )

    h5_positions_m = (
        tcp_pose[:, :3]
        / 1000.0
    )

    print(
        f"[TRAJECTORY] "
        f"waypoints={n}"
    )

    print(
        f"[TRAJECTORY] "
        f"H5 TCP start->end="
        f"{np.linalg.norm(h5_positions_m[-1] - h5_positions_m[0]) * 1000.0:.3f} mm"
    )

    # --------------------------------------------------------
    # RB10 real scale
    # --------------------------------------------------------

    status, config = (
        omni.kit.commands.execute(
            "URDFCreateImportConfig"
        )
    )

    if not status:
        raise RuntimeError(
            "URDFCreateImportConfig failed"
        )

    config.merge_fixed_joints = False
    config.convex_decomp = False
    config.import_inertia_tensor = True
    config.fix_base = True

    # REAL robot scale.
    config.distance_scale = 1.0

    config.make_default_prim = False

    status, robot_path = (
        omni.kit.commands.execute(
            "URDFParseAndImportFile",
            urdf_path=str(
                URDF_PATH
            ),
            import_config=config,
            get_articulation_root=True,
        )
    )

    if not status:
        raise RuntimeError(
            "RB10 URDF import failed"
        )

    stage = (
        omni.usd
        .get_context()
        .get_stage()
    )

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
            f"Expected one tcp, "
            f"found {tcp_paths}"
        )

    tcp_path = tcp_paths[0]

    # --------------------------------------------------------
    # Scene
    # --------------------------------------------------------

    scene = UsdPhysics.Scene.Define(
        stage,
        "/physicsScene",
    )

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

    nozzle_tip_path = (
        add_torch_at_tcp(
            stage,
            tcp_path,
        )
    )

    # --------------------------------------------------------
    # Articulation
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
            f"Missing joints "
            f"{missing}; "
            f"DOFs={dof_names}"
        )

    indices = [
        dof_names.index(name)
        for name in JOINT_NAMES
    ]

    # --------------------------------------------------------
    # Sample provisional nozzle path
    # --------------------------------------------------------

    tip_path = sample_torch_tip_path(
        simulation_app,
        stage,
        robot,
        joint_path,
        indices,
        nozzle_tip_path,
    )

    # Cyan = nozzle-tip path.
    # --------------------------------------------------------
    # Add T joint with corrected seam direction/side
    # --------------------------------------------------------

    scene_center = add_workpiece(
        stage,
        WORKPIECE_OBJ_PATH,
        tip_path,
    )

    # --------------------------------------------------------
    # Workpiece frame used ONLY for camera placement.
    # Keep this even though the blue guide path has been removed.
    # --------------------------------------------------------

    workpiece_rotation_for_view = build_frame_from_local_y(
        tip_path[-1] - tip_path[0]
    )

    local_x_world = workpiece_rotation_for_view[:, 0]
    local_y_world = workpiece_rotation_for_view[:, 1]
    local_z_world = workpiece_rotation_for_view[:, 2]

    weld_side_world = (
        float(WELD_SIDE)
        * local_x_world
    )

    # --------------------------------------------------------
    # Dynamic welding visualization
    #
    # Dark red-orange = already welded bead.
    # Bright orange-red = recently molten/hot section.
    # There is NO static yellow seam line.
    # --------------------------------------------------------

    weld_bead_curve = create_dynamic_curve(
        stage,
        "/DynamicWeldBead",
        tip_path[0],
        width=0.0055,
        color=Gf.Vec3f(
            0.65,
            0.08,
            0.015,
        ),
    )

    hot_weld_curve = create_dynamic_curve(
        stage,
        "/HotWeldPoolTrail",
        tip_path[0],
        width=0.0075,
        color=Gf.Vec3f(
            1.0,
            0.22,
            0.02,
        ),
    )

    weld_bead_points = [
        np.array(
            tip_path[0],
            dtype=np.float64,
        )
    ]

    # Add a new bead point only after ~0.5 mm movement.
    bead_point_spacing_m = 0.0005

    # Number of newest points shown as "hot/molten".
    hot_tail_points = 12

    # Return to first pose.
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

    # --------------------------------------------------------
    # Close-up camera from the ACTIVE welding side.
    #
    # This keeps the selected fillet in front of the camera and
    # frames the nozzle + ~50 mm weld motion tightly.
    # --------------------------------------------------------

    camera_eye = (
        scene_center
        + weld_side_world * 0.24
        - local_y_world * 0.12
        + local_z_world * 0.14
    )

    camera_target = (
        scene_center
        + local_z_world * 0.008
    )

    set_camera_view(
        eye=camera_eye.tolist(),
        target=camera_target.tolist(),
    )

    # --------------------------------------------------------
    # Playback
    # --------------------------------------------------------

    print("\n[PLAYBACK] start")
    print(
        "  red-orange trail = weld bead growing behind the torch"
    )

    duration = max(
        float(args.duration_sec),
        1.0,
    )

    start_time = (
        time.perf_counter()
    )

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

        # ----------------------------------------------------
        # Grow the weld bead behind the moving nozzle.
        # ----------------------------------------------------
        current_tip = world_position(
            stage,
            nozzle_tip_path,
        )

        if (
            np.linalg.norm(
                current_tip
                - weld_bead_points[-1]
            )
            >= bead_point_spacing_m
        ):
            weld_bead_points.append(
                current_tip.copy()
            )

            # Completed bead.
            update_dynamic_curve(
                weld_bead_curve,
                weld_bead_points,
            )

            # Only the newest short section stays "hot".
            hot_points = weld_bead_points[
                -hot_tail_points:
            ]

            update_dynamic_curve(
                hot_weld_curve,
                hot_points,
            )

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
                f"  progress="
                f"{percentage:3d}% "
                f"waypoint≈"
                f"{trajectory_position + 1:.1f}/{n}"
            )

        time.sleep(
            0.005
        )

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

    final_tip = world_position(
        stage,
        nozzle_tip_path,
    )

    if (
        np.linalg.norm(
            final_tip
            - weld_bead_points[-1]
        )
        > 1e-8
    ):
        weld_bead_points.append(
            final_tip.copy()
        )

    update_dynamic_curve(
        weld_bead_curve,
        weld_bead_points,
    )

    update_dynamic_curve(
        hot_weld_curve,
        weld_bead_points[
            -hot_tail_points:
        ],
    )

    timeline.pause()

    print(
        "  progress=100%"
    )
    print(
        "[PLAYBACK] finished"
    )

    output = (
        ROOT
        / "rb10_T_PP_03_virtual_welding.usda"
    )

    omni.usd.get_context().save_as_stage(
        output.as_posix()
    )

    print(
        f"[SAVE] {output}"
    )

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
