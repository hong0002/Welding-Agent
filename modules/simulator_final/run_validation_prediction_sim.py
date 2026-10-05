from isaacsim import SimulationApp

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--headless", action="store_true")
parser.add_argument("--auto-close", action="store_true")
parser.add_argument(
    "--duration-sec",
    type=float,
    default=30.0,
    help="Visual playback duration.",
)
args = parser.parse_args()

simulation_app = SimulationApp(
    {
        "headless": args.headless,
        "renderer": "RaytracedLighting",
    }
)

import json
import math
import time
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


# ============================================================
# Paths
# ============================================================

ROOT = Path(__file__).resolve().parent

SAMPLE_ID = "L_PR_03_0001"

VALIDATION_DIR = (
    ROOT
    / "welding_validation_all"
    / f"0000_{SAMPLE_ID}"
)

TRAJECTORY_NPZ = (
    VALIDATION_DIR
    / "trajectory.npz"
)

METADATA_JSON = (
    VALIDATION_DIR
    / "metadata.json"
)

URDF_PATH = (
    ROOT
    / "rbpodo_description"
    / "robots"
    / "rb10_1300e_u.urdf"
)

TOOL_USD_PATH = (
    ROOT
    / "ATU01035_welding_tool.usd"
)

# Use one already-validated RB10 joint pose only as the fixed
# simulation orientation / IK seed. No H5 reader is needed.
SEED_SOLUTION_PATH = (
    ROOT
    / "rb10_h5_trajectory_solution.npz"
)

JOINT_NAMES = (
    "base",
    "shoulder",
    "elbow",
    "wrist1",
    "wrist2",
    "wrist3",
)


# ============================================================
# Current provisional Panasonic CAD information
# ============================================================

CAD_TIP_LOCAL_MM = np.array(
    [
        0.1407694603715624,
        20.39885629926409,
        425.4869384765625,
    ],
    dtype=np.float64,
)

CAD_MOUNT_LOCAL_MM = np.array(
    [
        -1.0504137674967449,
        -21.709200586591447,
        -8.185713995070685,
    ],
    dtype=np.float64,
)


# ============================================================
# IK settings
# ============================================================

IK_MAX_ITER = 120
IK_POS_TOL_M = 0.0008          # 0.8 mm
IK_ORI_TOL_RAD = np.deg2rad(1.0)
IK_DAMPING = 0.025
IK_NUMERIC_EPS = 1e-5
IK_MAX_STEP_RAD = 0.10

# Convert orientation error into a comparable residual scale.
IK_ORIENTATION_WEIGHT_M_PER_RAD = 0.12


# ============================================================
# Basic transforms
# ============================================================

def rpy_matrix(rpy):
    r, p, y = [
        float(v)
        for v in rpy
    ]

    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)

    rx = np.array(
        [
            [1, 0, 0],
            [0, cr, -sr],
            [0, sr, cr],
        ],
        dtype=np.float64,
    )

    ry = np.array(
        [
            [cp, 0, sp],
            [0, 1, 0],
            [-sp, 0, cp],
        ],
        dtype=np.float64,
    )

    rz = np.array(
        [
            [cy, -sy, 0],
            [sy, cy, 0],
            [0, 0, 1],
        ],
        dtype=np.float64,
    )

    return rz @ ry @ rx


def make_transform(xyz=None, rotation=None):
    t = np.eye(
        4,
        dtype=np.float64,
    )

    if rotation is not None:
        t[:3, :3] = rotation

    if xyz is not None:
        t[:3, 3] = np.asarray(
            xyz,
            dtype=np.float64,
        )

    return t


def axis_angle_matrix(axis, angle):
    axis = np.asarray(
        axis,
        dtype=np.float64,
    )

    n = np.linalg.norm(axis)

    if n < 1e-12:
        return np.eye(3)

    axis = axis / n

    x, y, z = axis
    c = math.cos(angle)
    s = math.sin(angle)
    C = 1.0 - c

    return np.array(
        [
            [
                c + x*x*C,
                x*y*C - z*s,
                x*z*C + y*s,
            ],
            [
                y*x*C + z*s,
                c + y*y*C,
                y*z*C - x*s,
            ],
            [
                z*x*C - y*s,
                z*y*C + x*s,
                c + z*z*C,
            ],
        ],
        dtype=np.float64,
    )


def rotation_vector(rotation):
    """SO(3) rotation matrix -> axis-angle vector."""
    rotation = np.asarray(
        rotation,
        dtype=np.float64,
    )

    cos_angle = np.clip(
        (np.trace(rotation) - 1.0) * 0.5,
        -1.0,
        1.0,
    )

    angle = math.acos(
        float(cos_angle)
    )

    if angle < 1e-9:
        return np.zeros(
            3,
            dtype=np.float64,
        )

    if abs(math.pi - angle) < 1e-5:
        # Stable enough for the current solver.
        diag = np.maximum(
            np.diag(rotation) + 1.0,
            0.0,
        )
        axis = np.sqrt(
            diag * 0.5
        )

        if rotation[2, 1] - rotation[1, 2] < 0:
            axis[0] *= -1
        if rotation[0, 2] - rotation[2, 0] < 0:
            axis[1] *= -1
        if rotation[1, 0] - rotation[0, 1] < 0:
            axis[2] *= -1

        n = np.linalg.norm(axis)

        if n < 1e-8:
            axis = np.array(
                [1.0, 0.0, 0.0]
            )
        else:
            axis /= n

        return axis * angle

    axis = np.array(
        [
            rotation[2, 1] - rotation[1, 2],
            rotation[0, 2] - rotation[2, 0],
            rotation[1, 0] - rotation[0, 1],
        ],
        dtype=np.float64,
    )

    axis /= (
        2.0
        * math.sin(angle)
    )

    return axis * angle


def rotation_between(source, target):
    source = np.array(
        source,
        dtype=np.float64,
        copy=True,
    )
    target = np.array(
        target,
        dtype=np.float64,
        copy=True,
    )

    source /= np.linalg.norm(source)
    target /= np.linalg.norm(target)

    cross = np.cross(
        source,
        target,
    )

    dot = float(
        np.clip(
            np.dot(source, target),
            -1.0,
            1.0,
        )
    )

    if np.linalg.norm(cross) < 1e-12:
        if dot > 0.0:
            return np.eye(3)

        helper = np.array(
            [1.0, 0.0, 0.0]
        )

        if abs(
            np.dot(source, helper)
        ) > 0.9:
            helper = np.array(
                [0.0, 1.0, 0.0]
            )

        axis = np.cross(
            source,
            helper,
        )
        axis /= np.linalg.norm(axis)

        return (
            2.0
            * np.outer(axis, axis)
            - np.eye(3)
        )

    skew = np.array(
        [
            [0.0, -cross[2], cross[1]],
            [cross[2], 0.0, -cross[0]],
            [-cross[1], cross[0], 0.0],
        ],
        dtype=np.float64,
    )

    return (
        np.eye(3)
        + skew
        + skew @ skew
        * (
            (1.0 - dot)
            / np.dot(cross, cross)
        )
    )


def matrix_to_quaternion(matrix):
    matrix = np.asarray(
        matrix,
        dtype=np.float64,
    )

    trace = float(
        np.trace(matrix)
    )

    if trace > 0.0:
        s = (
            np.sqrt(trace + 1.0)
            * 2.0
        )
        w = 0.25 * s
        x = (
            matrix[2, 1]
            - matrix[1, 2]
        ) / s
        y = (
            matrix[0, 2]
            - matrix[2, 0]
        ) / s
        z = (
            matrix[1, 0]
            - matrix[0, 1]
        ) / s

    else:
        i = int(
            np.argmax(
                np.diag(matrix)
            )
        )

        if i == 0:
            s = np.sqrt(
                1.0
                + matrix[0, 0]
                - matrix[1, 1]
                - matrix[2, 2]
            ) * 2.0

            w = (
                matrix[2, 1]
                - matrix[1, 2]
            ) / s

            x = 0.25 * s
            y = (
                matrix[0, 1]
                + matrix[1, 0]
            ) / s
            z = (
                matrix[0, 2]
                + matrix[2, 0]
            ) / s

        elif i == 1:
            s = np.sqrt(
                1.0
                + matrix[1, 1]
                - matrix[0, 0]
                - matrix[2, 2]
            ) * 2.0

            w = (
                matrix[0, 2]
                - matrix[2, 0]
            ) / s
            x = (
                matrix[0, 1]
                + matrix[1, 0]
            ) / s
            y = 0.25 * s
            z = (
                matrix[1, 2]
                + matrix[2, 1]
            ) / s

        else:
            s = np.sqrt(
                1.0
                + matrix[2, 2]
                - matrix[0, 0]
                - matrix[1, 1]
            ) * 2.0

            w = (
                matrix[1, 0]
                - matrix[0, 1]
            ) / s
            x = (
                matrix[0, 2]
                + matrix[2, 0]
            ) / s
            y = (
                matrix[1, 2]
                + matrix[2, 1]
            ) / s
            z = 0.25 * s

    return Gf.Quatf(
        float(w),
        Gf.Vec3f(
            float(x),
            float(y),
            float(z),
        ),
    )


# ============================================================
# URDF kinematics
# ============================================================

def parse_urdf_chain(
    urdf_path,
    end_link="tcp",
):
    root = ET.parse(
        urdf_path
    ).getroot()

    by_child = {}

    for joint in root.findall(
        "joint"
    ):
        child_node = joint.find(
            "child"
        )
        parent_node = joint.find(
            "parent"
        )

        if (
            child_node is None
            or parent_node is None
        ):
            continue

        child = child_node.attrib[
            "link"
        ]

        parent = parent_node.attrib[
            "link"
        ]

        origin_node = joint.find(
            "origin"
        )

        xyz = np.zeros(
            3,
            dtype=np.float64,
        )
        rpy = np.zeros(
            3,
            dtype=np.float64,
        )

        if origin_node is not None:
            xyz = np.fromstring(
                origin_node.attrib.get(
                    "xyz",
                    "0 0 0",
                ),
                sep=" ",
                dtype=np.float64,
            )

            rpy = np.fromstring(
                origin_node.attrib.get(
                    "rpy",
                    "0 0 0",
                ),
                sep=" ",
                dtype=np.float64,
            )

        axis_node = joint.find(
            "axis"
        )

        axis = np.array(
            [1.0, 0.0, 0.0],
            dtype=np.float64,
        )

        if axis_node is not None:
            axis = np.fromstring(
                axis_node.attrib.get(
                    "xyz",
                    "1 0 0",
                ),
                sep=" ",
                dtype=np.float64,
            )

        limit_node = joint.find(
            "limit"
        )

        lower = -np.inf
        upper = np.inf

        if limit_node is not None:
            if "lower" in limit_node.attrib:
                lower = float(
                    limit_node.attrib[
                        "lower"
                    ]
                )

            if "upper" in limit_node.attrib:
                upper = float(
                    limit_node.attrib[
                        "upper"
                    ]
                )

        by_child[child] = {
            "name": joint.attrib[
                "name"
            ],
            "type": joint.attrib.get(
                "type",
                "fixed",
            ),
            "parent": parent,
            "child": child,
            "xyz": xyz,
            "rpy": rpy,
            "axis": axis,
            "lower": lower,
            "upper": upper,
        }

    chain_rev = []
    link = end_link

    while link in by_child:
        joint = by_child[
            link
        ]
        chain_rev.append(
            joint
        )
        link = joint[
            "parent"
        ]

    if not chain_rev:
        raise RuntimeError(
            f"Could not build URDF chain "
            f"to link '{end_link}'."
        )

    chain = list(
        reversed(chain_rev)
    )

    limits = {}

    for joint in chain:
        if joint["name"] in JOINT_NAMES:
            limits[
                joint["name"]
            ] = (
                joint["lower"],
                joint["upper"],
            )

    missing = [
        name
        for name in JOINT_NAMES
        if name not in limits
    ]

    if missing:
        raise RuntimeError(
            f"URDF chain missing joints: "
            f"{missing}"
        )

    return chain, limits


def fk_tcp(
    chain,
    q,
):
    q_map = {
        name: float(value)
        for name, value in zip(
            JOINT_NAMES,
            q,
        )
    }

    transform = np.eye(
        4,
        dtype=np.float64,
    )

    for joint in chain:
        origin = make_transform(
            joint["xyz"],
            rpy_matrix(
                joint["rpy"]
            ),
        )

        transform = (
            transform
            @ origin
        )

        if (
            joint["type"]
            in ("revolute", "continuous")
            and joint["name"]
            in q_map
        ):
            rotation = axis_angle_matrix(
                joint["axis"],
                q_map[
                    joint["name"]
                ],
            )

            transform = (
                transform
                @ make_transform(
                    rotation=rotation
                )
            )

        elif (
            joint["type"]
            == "prismatic"
            and joint["name"]
            in q_map
        ):
            shift = (
                np.asarray(
                    joint["axis"],
                    dtype=np.float64,
                )
                * q_map[
                    joint["name"]
                ]
            )

            transform = (
                transform
                @ make_transform(
                    xyz=shift
                )
            )

    return transform


def clip_joint_limits(
    q,
    limits,
):
    q = np.array(
        q,
        dtype=np.float64,
        copy=True,
    )

    for i, name in enumerate(
        JOINT_NAMES
    ):
        lower, upper = limits[
            name
        ]

        if np.isfinite(lower):
            q[i] = max(
                q[i],
                lower + 1e-5,
            )

        if np.isfinite(upper):
            q[i] = min(
                q[i],
                upper - 1e-5,
            )

    return q


def pose_residual(
    chain,
    q,
    target_position,
    target_rotation,
):
    transform = fk_tcp(
        chain,
        q,
    )

    position = transform[
        :3,
        3,
    ]

    rotation = transform[
        :3,
        :3,
    ]

    position_error = (
        position
        - target_position
    )

    rotation_error_matrix = (
        target_rotation.T
        @ rotation
    )

    orientation_error = (
        rotation_vector(
            rotation_error_matrix
        )
    )

    residual = np.concatenate(
        [
            position_error,
            (
                IK_ORIENTATION_WEIGHT_M_PER_RAD
                * orientation_error
            ),
        ]
    )

    return (
        residual,
        position_error,
        orientation_error,
    )


def solve_ik(
    chain,
    limits,
    target_position,
    target_rotation,
    q_seed,
):
    q = clip_joint_limits(
        q_seed,
        limits,
    )

    best_q = q.copy()
    best_score = float(
        "inf"
    )

    for iteration in range(
        IK_MAX_ITER
    ):
        (
            residual,
            position_error,
            orientation_error,
        ) = pose_residual(
            chain,
            q,
            target_position,
            target_rotation,
        )

        position_norm = float(
            np.linalg.norm(
                position_error
            )
        )

        orientation_norm = float(
            np.linalg.norm(
                orientation_error
            )
        )

        score = (
            position_norm
            + 0.05
            * orientation_norm
        )

        if score < best_score:
            best_score = score
            best_q = q.copy()

        if (
            position_norm
            <= IK_POS_TOL_M
            and orientation_norm
            <= IK_ORI_TOL_RAD
        ):
            return (
                q,
                True,
                position_norm,
                orientation_norm,
                iteration + 1,
            )

        jacobian = np.zeros(
            (6, 6),
            dtype=np.float64,
        )

        for j in range(6):
            q_eps = q.copy()
            q_eps[j] += (
                IK_NUMERIC_EPS
            )

            residual_eps, _, _ = (
                pose_residual(
                    chain,
                    q_eps,
                    target_position,
                    target_rotation,
                )
            )

            jacobian[
                :,
                j,
            ] = (
                residual_eps
                - residual
            ) / IK_NUMERIC_EPS

        # Damped least-squares step:
        # dq = -J^T (J J^T + lambda^2 I)^-1 r
        jj_t = (
            jacobian
            @ jacobian.T
        )

        damping_matrix = (
            IK_DAMPING
            * IK_DAMPING
            * np.eye(6)
        )

        try:
            step = -(
                jacobian.T
                @ np.linalg.solve(
                    jj_t
                    + damping_matrix,
                    residual,
                )
            )

        except np.linalg.LinAlgError:
            step = -(
                np.linalg.pinv(
                    jacobian
                )
                @ residual
            )

        max_abs = float(
            np.max(
                np.abs(step)
            )
        )

        if (
            max_abs
            > IK_MAX_STEP_RAD
        ):
            step *= (
                IK_MAX_STEP_RAD
                / max_abs
            )

        q = clip_joint_limits(
            q + step,
            limits,
        )

    # Return best pose found.
    (
        _,
        position_error,
        orientation_error,
    ) = pose_residual(
        chain,
        best_q,
        target_position,
        target_rotation,
    )

    return (
        best_q,
        False,
        float(
            np.linalg.norm(
                position_error
            )
        ),
        float(
            np.linalg.norm(
                orientation_error
            )
        ),
        IK_MAX_ITER,
    )


# ============================================================
# Dataset helpers
# ============================================================

def find_dataset_file(
    filename,
):
    matches = list(
        (
            ROOT
            / "Datase"
        ).rglob(
            filename
        )
    )

    if not matches:
        return None

    # Prefer paths that are not raw backup copies.
    preferred = [
        path
        for path in matches
        if "raw_data"
        not in [
            p.lower()
            for p in path.parts
        ]
    ]

    if preferred:
        return preferred[0]

    return matches[0]



def find_labeled_pointcloud_csv(
    sample_id,
):
    """Find the large 3D labelled CSV for this validation sample.

    Several dataset branches can contain a CSV with the same basename.
    The annotated point-cloud CSV is by far the largest one, so exact-name
    matches are ranked primarily by file size.  Validation / labelled-data
    paths receive a small preference only as a tie-breaker.
    """
    filename = f"{sample_id}.csv"

    matches = list(
        (
            ROOT
            / "Datase"
        ).rglob(
            filename
        )
    )

    if not matches:
        return None

    def rank(path):
        try:
            size = path.stat().st_size
        except OSError:
            size = 0

        lower = str(path).lower()

        bonus = 0

        if "validation" in lower:
            bonus += 1_000_000

        if "라벨링데이터" in str(path):
            bonus += 500_000

        if "원천데이터" in str(path):
            bonus += 250_000

        return (
            size + bonus,
            size,
        )

    return max(
        matches,
        key=rank,
    )


# ============================================================
# OBJ
# ============================================================

def load_obj_mesh(
    obj_path,
):
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

            if (
                not line
                or line.startswith("#")
            ):
                continue

            if line.startswith(
                "v "
            ):
                parts = line.split()

                if len(parts) >= 4:
                    vertices.append(
                        [
                            float(
                                parts[1]
                            ),
                            float(
                                parts[2]
                            ),
                            float(
                                parts[3]
                            ),
                        ]
                    )

            elif line.startswith(
                "f "
            ):
                face = []

                for token in line.split()[1:]:
                    first = token.split(
                        "/"
                    )[0]

                    if not first:
                        continue

                    idx = int(
                        first
                    )

                    if idx > 0:
                        idx -= 1
                    else:
                        idx = (
                            len(vertices)
                            + idx
                        )

                    face.append(
                        idx
                    )

                if len(face) >= 3:
                    counts.append(
                        len(face)
                    )
                    indices.extend(
                        face
                    )

    vertices = np.asarray(
        vertices,
        dtype=np.float64,
    )

    if (
        len(vertices) == 0
        or len(counts) == 0
    ):
        raise RuntimeError(
            f"Could not read OBJ: "
            f"{obj_path}"
        )

    return (
        vertices,
        counts,
        indices,
    )


def build_frame_from_y(
    y_world,
):
    y_world = np.asarray(
        y_world,
        dtype=np.float64,
    )

    y_world /= np.linalg.norm(
        y_world
    )

    z_hint = np.array(
        [0.0, 0.0, 1.0],
        dtype=np.float64,
    )

    z_world = (
        z_hint
        - np.dot(
            z_hint,
            y_world,
        )
        * y_world
    )

    if np.linalg.norm(
        z_world
    ) < 1e-8:
        z_hint = np.array(
            [1.0, 0.0, 0.0],
            dtype=np.float64,
        )

        z_world = (
            z_hint
            - np.dot(
                z_hint,
                y_world,
            )
            * y_world
        )

    z_world /= np.linalg.norm(
        z_world
    )

    x_world = np.cross(
        y_world,
        z_world,
    )

    x_world /= np.linalg.norm(
        x_world
    )

    z_world = np.cross(
        x_world,
        y_world,
    )

    z_world /= np.linalg.norm(
        z_world
    )

    return np.column_stack(
        (
            x_world,
            y_world,
            z_world,
        )
    )



def _obj_connected_components(
    vertex_count,
    counts,
    indices,
):
    """Return face-connected OBJ vertex components."""
    parent = np.arange(
        vertex_count,
        dtype=np.int64,
    )

    def find(x):
        while parent[x] != x:
            parent[x] = parent[
                parent[x]
            ]
            x = parent[x]
        return x

    def union(a, b):
        ra = find(a)
        rb = find(b)

        if ra != rb:
            parent[rb] = ra

    cursor = 0

    for count in counts:
        face = indices[
            cursor:
            cursor + count
        ]
        cursor += count

        if len(face) < 2:
            continue

        first = int(
            face[0]
        )

        for idx in face[1:]:
            union(
                first,
                int(idx),
            )

    groups = {}

    for index in range(
        vertex_count
    ):
        root = find(index)

        groups.setdefault(
            root,
            []
        ).append(
            index
        )

    components = [
        np.asarray(
            values,
            dtype=np.int64,
        )
        for values
        in groups.values()
        if len(values) >= 8
    ]

    components.sort(
        key=len,
        reverse=True,
    )

    return components


def _pca_component(
    vertices_mm,
    component_indices,
):
    points = vertices_mm[
        component_indices
    ]

    center = points.mean(
        axis=0
    )

    centered = (
        points
        - center
    )

    covariance = (
        centered.T
        @ centered
        / max(
            len(points),
            1,
        )
    )

    eigenvalues, eigenvectors = (
        np.linalg.eigh(
            covariance
        )
    )

    order = np.argsort(
        eigenvalues
    )[::-1]

    axes = eigenvectors[
        :,
        order
    ]

    projected = (
        centered
        @ axes
    )

    extents = (
        projected.max(
            axis=0
        )
        - projected.min(
            axis=0
        )
    )

    return {
        "indices": component_indices,
        "points": points,
        "center": center,
        "axes": axes,
        "extents": extents,
    }


def infer_plate_round_seam(
    vertices_mm,
    counts,
    indices,
):
    """Infer the physical Plate-Round seam from the OBJ geometry."""
    components = _obj_connected_components(
        len(vertices_mm),
        counts,
        indices,
    )

    if len(components) < 2:
        raise RuntimeError(
            "L_PR OBJ could not be separated into Plate + Round bodies. "
            f"Detected {len(components)} connected component(s)."
        )

    info = [
        _pca_component(
            vertices_mm,
            comp,
        )
        for comp in components
    ]

    print(
        "\n[OBJ GEOMETRY]"
    )

    for i, item in enumerate(
        info
    ):
        print(
            f"  component {i}: "
            f"vertices={len(item['indices'])}, "
            f"PCA extents mm={item['extents'].tolist()}"
        )

    # Plate is the component whose smallest PCA extent is closest to 3 mm.
    plate_index = min(
        range(
            len(info)
        ),
        key=lambda i: abs(
            float(
                np.min(
                    info[i]["extents"]
                )
            )
            - 3.0
        ),
    )

    plate = info[
        plate_index
    ]

    plate_thickness_mm = float(
        np.min(
            plate["extents"]
        )
    )

    if abs(
        plate_thickness_mm
        - 3.0
    ) > 3.0:
        raise RuntimeError(
            "Could not identify a believable 3 mm plate. "
            f"Best thickness={plate_thickness_mm:.3f} mm."
        )

    remaining = [
        (i, item)
        for i, item in enumerate(
            info
        )
        if i != plate_index
    ]

    round_index, round_body = max(
        remaining,
        key=lambda pair: len(
            pair[1]["indices"]
        ),
    )

    # Plate normal: from the plate toward the round body.
    plate_small_axis = int(
        np.argmin(
            plate["extents"]
        )
    )

    plate_normal = np.array(
        plate["axes"][
            :,
            plate_small_axis,
        ],
        dtype=np.float64,
        copy=True,
    )

    if np.dot(
        round_body["center"]
        - plate["center"],
        plate_normal,
    ) < 0.0:
        plate_normal *= -1.0

    plate_normal /= np.linalg.norm(
        plate_normal
    )

    # Round axis / weld direction.
    round_major_axis = int(
        np.argmax(
            round_body["extents"]
        )
    )

    round_axis = np.array(
        round_body["axes"][
            :,
            round_major_axis,
        ],
        dtype=np.float64,
        copy=True,
    )

    round_axis = (
        round_axis
        - np.dot(
            round_axis,
            plate_normal,
        )
        * plate_normal
    )

    round_axis_norm = np.linalg.norm(
        round_axis
    )

    if round_axis_norm < 1e-8:
        raise RuntimeError(
            "Round axis is parallel to plate normal; "
            "cannot infer Plate-Round seam."
        )

    round_axis /= round_axis_norm

    # Give the otherwise sign-ambiguous PCA axis a deterministic sign.
    dominant = int(
        np.argmax(
            np.abs(
                round_axis
            )
        )
    )

    if round_axis[
        dominant
    ] < 0.0:
        round_axis *= -1.0

    side_axis = np.cross(
        round_axis,
        plate_normal,
    )

    side_axis /= np.linalg.norm(
        side_axis
    )

    # Plate contact plane on the round-body side.
    plate_projection = (
        plate["points"]
        @ plate_normal
    )

    plate_contact_plane = float(
        np.max(
            plate_projection
        )
    )

    round_points = round_body[
        "points"
    ]

    round_projection = (
        round_points
        @ plate_normal
    )

    # The round body touches the plate at the minimum projection because the
    # chosen plate normal points from the plate toward the round body.
    contact_level = float(
        np.min(
            round_projection
        )
    )

    contact_tolerance_mm = 1.5

    contact_mask = (
        round_projection
        <= contact_level
        + contact_tolerance_mm
    )

    contact_points = round_points[
        contact_mask
    ]

    if len(
        contact_points
    ) < 4:
        contact_tolerance_mm = 3.0

        contact_mask = (
            round_projection
            <= contact_level
            + contact_tolerance_mm
        )

        contact_points = round_points[
            contact_mask
        ]

    if len(
        contact_points
    ) < 2:
        raise RuntimeError(
            "Could not detect the Plate-Round contact seam from OBJ vertices."
        )

    contact_center = np.mean(
        contact_points,
        axis=0,
    )

    current_level = float(
        np.dot(
            contact_center,
            plate_normal,
        )
    )

    seam_center_mm = (
        contact_center
        + (
            plate_contact_plane
            - current_level
        )
        * plate_normal
    )

    round_axis_coord = (
        round_points
        @ round_axis
    )

    seam_axis_min_mm = float(
        np.min(
            round_axis_coord
        )
    )

    seam_axis_max_mm = float(
        np.max(
            round_axis_coord
        )
    )

    seam_length_mm = (
        seam_axis_max_mm
        - seam_axis_min_mm
    )

    # Right-handed geometry frame:
    #   X = side across the joint
    #   Y = seam / round axis
    #   Z = from plate toward round body
    local_basis = np.column_stack(
        (
            side_axis,
            round_axis,
            plate_normal,
        )
    )

    print(
        f"[OBJ GEOMETRY] plate component={plate_index}, "
        f"thickness≈{plate_thickness_mm:.3f} mm"
    )
    print(
        f"[OBJ GEOMETRY] round component={round_index}, "
        f"axis={round_axis.tolist()}"
    )
    print(
        f"[OBJ GEOMETRY] plate->round normal={plate_normal.tolist()}"
    )
    print(
        f"[OBJ GEOMETRY] seam centre mm={seam_center_mm.tolist()}"
    )
    print(
        f"[OBJ GEOMETRY] seam length≈{seam_length_mm:.3f} mm"
    )

    return {
        "plate": plate,
        "round": round_body,
        "local_basis": local_basis,
        "side_axis": side_axis,
        "seam_axis": round_axis,
        "plate_normal": plate_normal,
        "seam_center_mm": seam_center_mm,
        "seam_length_mm": seam_length_mm,
    }


def _fit_principal_line(
    points,
):
    points = np.asarray(
        points,
        dtype=np.float64,
    )

    center = np.mean(
        points,
        axis=0,
    )

    centered = (
        points
        - center
    )

    covariance = (
        centered.T
        @ centered
        / max(
            len(points),
            1,
        )
    )

    eigenvalues, eigenvectors = np.linalg.eigh(
        covariance
    )

    direction = np.array(
        eigenvectors[
            :,
            int(
                np.argmax(
                    eigenvalues
                )
            ),
        ],
        dtype=np.float64,
        copy=True,
    )

    direction /= np.linalg.norm(
        direction
    )

    dominant = int(
        np.argmax(
            np.abs(
                direction
            )
        )
    )

    if direction[
        dominant
    ] < 0.0:
        direction *= -1.0

    axial = (
        centered
        @ direction
    )

    residual = (
        centered
        - axial[:, None]
        * direction[None, :]
    )

    radial = np.linalg.norm(
        residual,
        axis=1,
    )

    return {
        "center": center,
        "direction": direction,
        "length_m": float(
            np.max(axial)
            - np.min(axial)
        ),
        "rms_radius_m": float(
            np.sqrt(
                np.mean(
                    radial * radial
                )
            )
        ),
        "max_radius_m": float(
            np.max(
                radial
            )
        ),
    }


def load_labeled_pointcloud_geometry(
    csv_path,
):
    """Load the measured 3D label CSV and infer its seam/body frame.

    CSV columns used here:
        X, Y, Z, ..., label

    For this dataset sample the three label populations are very different:
    smallest = weld seam, middle = workpiece, largest = background.
    The code infers those roles from population size instead of hard-coding
    label IDs 0/1/2.
    """
    print(
        f"\n[3D LABEL] loading {csv_path}"
    )

    raw = np.loadtxt(
        csv_path,
        delimiter=",",
        usecols=(
            0,
            1,
            2,
            6,
        ),
        dtype=np.float64,
    )

    if (
        raw.ndim != 2
        or raw.shape[1] != 4
    ):
        raise RuntimeError(
            f"Unexpected labelled CSV shape: {raw.shape}"
        )

    xyz = raw[
        :,
        :3
    ]

    labels = np.rint(
        raw[
            :,
            3
        ]
    ).astype(
        np.int64
    )

    unique_labels, label_counts = np.unique(
        labels,
        return_counts=True,
    )

    if len(
        unique_labels
    ) < 3:
        raise RuntimeError(
            "Expected at least three 3D labels "
            "(weld / workpiece / background). "
            f"Found {dict(zip(unique_labels.tolist(), label_counts.tolist()))}."
        )

    populations = sorted(
        [
            (
                int(count),
                int(label),
            )
            for label, count in zip(
                unique_labels,
                label_counts,
            )
        ]
    )

    weld_count, weld_label = populations[
        0
    ]
    workpiece_count, workpiece_label = populations[
        -2
    ]
    background_count, background_label = populations[
        -1
    ]

    print(
        "[3D LABEL] populations="
        + ", ".join(
            f"label {label}: {count}"
            for count, label in populations
        )
    )

    if weld_count < 20:
        raise RuntimeError(
            f"Too few weld-label points: {weld_count}"
        )

    if workpiece_count < 100:
        raise RuntimeError(
            f"Too few workpiece-label points: {workpiece_count}"
        )

    weld_points = xyz[
        labels
        == weld_label
    ]

    workpiece_points = xyz[
        labels
        == workpiece_label
    ]

    line = _fit_principal_line(
        weld_points
    )

    seam_center = line[
        "center"
    ]

    seam_direction = line[
        "direction"
    ]

    # The measured object centroid lies on the physical body side of the
    # labelled seam.  Remove any component along the seam; the remaining
    # direction is the measured plate->round/body-side direction.
    workpiece_center = np.median(
        workpiece_points,
        axis=0,
    )

    body_direction = (
        workpiece_center
        - seam_center
    )

    body_direction = (
        body_direction
        - np.dot(
            body_direction,
            seam_direction,
        )
        * seam_direction
    )

    body_norm = float(
        np.linalg.norm(
            body_direction
        )
    )

    if body_norm < 1e-5:
        raise RuntimeError(
            "Could not infer measured workpiece side from 3D labels."
        )

    plate_to_round = (
        body_direction
        / body_norm
    )

    side_axis = np.cross(
        seam_direction,
        plate_to_round,
    )

    side_axis /= np.linalg.norm(
        side_axis
    )

    # Re-orthogonalize the body-side direction.
    plate_to_round = np.cross(
        side_axis,
        seam_direction,
    )

    plate_to_round /= np.linalg.norm(
        plate_to_round
    )

    measured_basis = np.column_stack(
        (
            side_axis,
            seam_direction,
            plate_to_round,
        )
    )

    print(
        f"[3D LABEL] weld label={weld_label}, points={weld_count}"
    )
    print(
        f"[3D LABEL] workpiece label={workpiece_label}, points={workpiece_count}"
    )
    print(
        f"[3D LABEL] background label={background_label}, points={background_count}"
    )
    print(
        f"[3D LABEL] measured seam centre m={seam_center.tolist()}"
    )
    print(
        f"[3D LABEL] measured seam direction={seam_direction.tolist()}"
    )
    print(
        f"[3D LABEL] measured plate->round direction={plate_to_round.tolist()}"
    )
    print(
        f"[3D LABEL] seam length≈{line['length_m'] * 1000.0:.3f} mm, "
        f"RMS label width≈{line['rms_radius_m'] * 1000.0:.3f} mm"
    )

    return {
        "weld_label": weld_label,
        "workpiece_label": workpiece_label,
        "background_label": background_label,
        "weld_points_m": weld_points,
        "workpiece_points_m": workpiece_points,
        "seam_center_m": seam_center,
        "seam_direction": seam_direction,
        "plate_to_round": plate_to_round,
        "side_axis": side_axis,
        "basis": measured_basis,
        "seam_length_m": line[
            "length_m"
        ],
        "seam_rms_radius_m": line[
            "rms_radius_m"
        ],
    }


def add_validation_workpiece(
    stage,
    obj_path,
    labeled_csv_path,
    gt_path_world,
):
    """Register OBJ -> measured 3D seam -> validation GT trajectory.

    This intentionally removes the previous 'keep the plate upright' rule.
    The roll around the seam comes from the measured labelled point cloud.

    The labelled cloud itself is not claimed to be in the source robot frame;
    the dataset does not provide that camera/robot extrinsic here.  Therefore
    its measured frame is transferred to Isaac with the *minimal* rotation
    that aligns the measured seam direction to the GT direction.  That keeps
    the measured Plate-Round cross-section orientation instead of inventing a
    new upright pose.
    """
    (
        vertices_mm,
        counts,
        indices,
    ) = load_obj_mesh(
        obj_path
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

    print(
        f"\n[WORKPIECE] {obj_path}"
    )
    print(
        f"[WORKPIECE] raw dimensions mm={dims_mm.tolist()}"
    )

    obj_geometry = infer_plate_round_seam(
        vertices_mm,
        counts,
        indices,
    )

    measured = load_labeled_pointcloud_geometry(
        labeled_csv_path
    )

    obj_local_basis = obj_geometry[
        "local_basis"
    ]

    measured_basis = measured[
        "basis"
    ]

    # OBJ geometric frame -> measured labelled-cloud geometric frame.
    obj_to_measured_rotation = (
        measured_basis
        @ obj_local_basis.T
    )

    obj_seam_center_m = (
        obj_geometry[
            "seam_center_mm"
        ]
        * 0.001
    )

    measured_seam_center_m = measured[
        "seam_center_m"
    ]

    obj_to_measured_translation = (
        measured_seam_center_m
        - obj_to_measured_rotation
        @ obj_seam_center_m
    )

    # Fit GT as a line.  Its sign follows actual waypoint order.
    gt_path_world = np.asarray(
        gt_path_world,
        dtype=np.float64,
    )

    gt_center = np.mean(
        gt_path_world,
        axis=0,
    )

    gt_centered = (
        gt_path_world
        - gt_center
    )

    gt_cov = (
        gt_centered.T
        @ gt_centered
        / max(
            len(gt_path_world),
            1,
        )
    )

    gt_values, gt_vectors = np.linalg.eigh(
        gt_cov
    )

    gt_direction = np.array(
        gt_vectors[
            :,
            int(
                np.argmax(
                    gt_values
                )
            ),
        ],
        dtype=np.float64,
        copy=True,
    )

    gt_direction /= np.linalg.norm(
        gt_direction
    )

    ordered_direction = (
        gt_path_world[-1]
        - gt_path_world[0]
    )

    if np.dot(
        gt_direction,
        ordered_direction,
    ) < 0.0:
        gt_direction *= -1.0

    gt_axial = (
        gt_centered
        @ gt_direction
    )

    gt_length_m = float(
        np.max(
            gt_axial
        )
        - np.min(
            gt_axial
        )
    )

    # Measured cloud -> Isaac world.
    # rotation_between() gives the minimum-angle rotation and therefore does
    # not introduce a second arbitrary roll around the seam.
    measured_to_world_rotation = rotation_between(
        measured[
            "seam_direction"
        ],
        gt_direction,
    )

    measured_to_world_translation = (
        gt_center
        - measured_to_world_rotation
        @ measured_seam_center_m
    )

    # Compose OBJ -> measured -> world.
    obj_to_world_rotation = (
        measured_to_world_rotation
        @ obj_to_measured_rotation
    )

    obj_to_world_translation = (
        measured_to_world_rotation
        @ obj_to_measured_translation
        + measured_to_world_translation
    )

    measured_plate_normal_world = (
        measured_to_world_rotation
        @ measured[
            "plate_to_round"
        ]
    )

    measured_side_axis_world = (
        measured_to_world_rotation
        @ measured[
            "side_axis"
        ]
    )

    measured_seam_world = (
        (
            measured_to_world_rotation
            @ measured[
                "weld_points_m"
            ].T
        ).T
        + measured_to_world_translation
    )

    measured_seam_center_world = np.mean(
        measured_seam_world,
        axis=0,
    )

    center_error_mm = float(
        np.linalg.norm(
            measured_seam_center_world
            - gt_center
        )
        * 1000.0
    )

    print(
        "\n[REGISTRATION] OBJ seam -> measured 3D weld label -> GT trajectory"
    )
    print(
        f"[REGISTRATION] GT length≈{gt_length_m * 1000.0:.3f} mm"
    )
    print(
        f"[REGISTRATION] measured labelled seam length≈"
        f"{measured['seam_length_m'] * 1000.0:.3f} mm"
    )
    print(
        f"[REGISTRATION] OBJ available seam length≈"
        f"{obj_geometry['seam_length_mm']:.3f} mm"
    )
    print(
        f"[REGISTRATION] seam-centre alignment error="
        f"{center_error_mm:.6f} mm"
    )
    print(
        "[REGISTRATION] old arbitrary upright-roll heuristic = REMOVED"
    )
    print(
        "[REGISTRATION] NOTE: no camera->robot extrinsic was present; "
        "measured frame uses minimum-angle seam alignment to GT."
    )

    if (
        gt_length_m
        > measured[
            "seam_length_m"
        ]
        + 0.005
    ):
        print(
            "[REGISTRATION] WARNING: GT is longer than the measured weld label."
        )

    root_path = Sdf.Path(
        "/ValidationWorkpiece"
    )

    root = UsdGeom.Xform.Define(
        stage,
        root_path,
    )

    root.AddTranslateOp().Set(
        Gf.Vec3d(
            float(
                obj_to_world_translation[0]
            ),
            float(
                obj_to_world_translation[1]
            ),
            float(
                obj_to_world_translation[2]
            ),
        )
    )

    root.AddOrientOp().Set(
        matrix_to_quaternion(
            obj_to_world_rotation
        )
    )

    vertices_m = (
        vertices_mm
        * 0.001
    )

    mesh = UsdGeom.Mesh.Define(
        stage,
        root_path.AppendChild(
            SAMPLE_ID
        ),
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
        counts
    )

    mesh.CreateFaceVertexIndicesAttr(
        indices
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

    registration = {
        "obj_to_world_rotation": obj_to_world_rotation,
        "obj_to_world_translation": obj_to_world_translation,
        "measured_to_world_rotation": measured_to_world_rotation,
        "measured_to_world_translation": measured_to_world_translation,
        "measured_seam_center_m": measured_seam_center_m,
        "measured_seam_direction": measured[
            "seam_direction"
        ],
        "plate_normal_world": measured_plate_normal_world,
        "side_axis_world": measured_side_axis_world,
        "weld_label": measured[
            "weld_label"
        ],
        "workpiece_label": measured[
            "workpiece_label"
        ],
        "background_label": measured[
            "background_label"
        ],
    }

    return (
        gt_center,
        obj_to_world_rotation,
        registration,
    )


# ============================================================
# Torch + weld trail
# ============================================================

def add_torch_at_tcp(
    stage,
    tcp_path,
):
    mount_local_m = (
        CAD_MOUNT_LOCAL_MM
        * 0.001
    )

    tip_local_m = (
        CAD_TIP_LOCAL_MM
        * 0.001
    )

    cad_axis = (
        CAD_TIP_LOCAL_MM
        - CAD_MOUNT_LOCAL_MM
    )

    cad_axis /= np.linalg.norm(
        cad_axis
    )

    # Same provisional mounting convention used in the earlier demo.
    tcp_axis = np.array(
        [0.0, -1.0, 0.0],
        dtype=np.float64,
    )

    tool_rotation = rotation_between(
        cad_axis,
        tcp_axis,
    )

    # CAD mounting-point candidate == RB10 tcp.
    tool_translation = -(
        tool_rotation
        @ mount_local_m
    )

    # This is the CAD nozzle-tip offset expressed in RB10 tcp coordinates.
    nozzle_tip_in_tcp = (
        tool_translation
        + tool_rotation
        @ tip_local_m
    )

    tool_path = (
        Sdf.Path(
            tcp_path
        )
        .AppendChild(
            "WeldingTool"
        )
    )

    tool_root = UsdGeom.Xform.Define(
        stage,
        tool_path,
    )

    tool_root.AddTranslateOp().Set(
        Gf.Vec3d(
            float(
                tool_translation[0]
            ),
            float(
                tool_translation[1]
            ),
            float(
                tool_translation[2]
            ),
        )
    )

    tool_root.AddOrientOp().Set(
        matrix_to_quaternion(
            tool_rotation
        )
    )

    geometry = UsdGeom.Xform.Define(
        stage,
        tool_path.AppendChild(
            "Geometry"
        ),
    )

    geometry.GetPrim().GetReferences().AddReference(
        TOOL_USD_PATH.as_posix()
    )

    geometry.AddScaleOp().Set(
        Gf.Vec3f(
            0.001,
            0.001,
            0.001,
        )
    )

    nozzle_tip_path = (
        tool_path
        .AppendChild(
            "NozzleTip"
        )
    )

    nozzle_tip = UsdGeom.Xform.Define(
        stage,
        nozzle_tip_path,
    )

    # NozzleTip is a child of WeldingTool, so use CAD-local tip coordinates.
    nozzle_tip.AddTranslateOp().Set(
        Gf.Vec3d(
            float(
                tip_local_m[0]
            ),
            float(
                tip_local_m[1]
            ),
            float(
                tip_local_m[2]
            ),
        )
    )

    print(
        "[TOOL] provisional ATU01035 "
        "attached"
    )
    print(
        "[TOOL] nozzle offset in tcp [m]="
        f"{nozzle_tip_in_tcp.tolist()}"
    )

    return (
        nozzle_tip_path.pathString,
        nozzle_tip_in_tcp,
    )


def world_position(
    stage,
    prim_path,
):
    cache = UsdGeom.XformCache(
        Usd.TimeCode.Default()
    )

    prim = stage.GetPrimAtPath(
        prim_path
    )

    matrix = cache.GetLocalToWorldTransform(
        prim
    )

    p = matrix.ExtractTranslation()

    return np.array(
        [
            float(p[0]),
            float(p[1]),
            float(p[2]),
        ],
        dtype=np.float64,
    )



def add_static_curve(
    stage,
    path,
    points,
    width,
    color,
):
    """Draw a fixed reference trajectory."""
    points = np.asarray(
        points,
        dtype=np.float64,
    )

    curve = UsdGeom.BasisCurves.Define(
        stage,
        path,
    )

    curve.CreateTypeAttr(
        "linear"
    )

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

    return curve



def add_gt_waypoint_markers(
    stage,
    points,
):
    """Make the exact GT XYZ visibly protrude from the workpiece surface."""
    points = np.asarray(
        points,
        dtype=np.float64,
    )

    # Show every second waypoint to keep the scene readable.
    show_indices = list(
        range(
            0,
            len(points),
            2,
        )
    )

    if (
        len(points) - 1
        not in show_indices
    ):
        show_indices.append(
            len(points) - 1
        )

    for idx in show_indices:
        point = points[idx]

        sphere = UsdGeom.Sphere.Define(
            stage,
            f"/GroundTruthMarkers/GT_{idx:03d}",
        )

        # Sphere centre is the exact GT XYZ.
        # Radius makes part of it visible even when the trajectory
        # lies exactly on the physical contact seam.
        sphere.CreateRadiusAttr(
            0.0035
        )

        sphere.CreateDisplayColorAttr(
            [
                Gf.Vec3f(
                    0.0,
                    1.0,
                    0.0,
                )
            ]
        )

        UsdGeom.Xformable(
            sphere
        ).AddTranslateOp().Set(
            Gf.Vec3d(
                float(point[0]),
                float(point[1]),
                float(point[2]),
            )
        )


def create_dynamic_curve(
    stage,
    path,
    start_point,
    width,
    color,
):
    p = np.asarray(
        start_point,
        dtype=np.float64,
    )

    curve = UsdGeom.BasisCurves.Define(
        stage,
        path,
    )

    curve.CreateTypeAttr(
        "linear"
    )
    curve.CreateCurveVertexCountsAttr(
        [2]
    )
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
    points = np.asarray(
        points,
        dtype=np.float64,
    )

    if len(points) == 0:
        return

    if len(points) == 1:
        points = np.vstack(
            [
                points[0],
                points[0],
            ]
        )

    curve.GetCurveVertexCountsAttr().Set(
        [len(points)]
    )

    curve.GetPointsAttr().Set(
        [
            Gf.Vec3f(
                float(p[0]),
                float(p[1]),
                float(p[2]),
            )
            for p in points
        ]
    )


# ============================================================
# Main
# ============================================================

def main():
    required = (
        TRAJECTORY_NPZ,
        URDF_PATH,
        TOOL_USD_PATH,
        SEED_SOLUTION_PATH,
    )

    missing = [
        str(path)
        for path in required
        if not path.is_file()
    ]

    if missing:
        raise FileNotFoundError(
            "Missing required files:\n"
            + "\n".join(
                missing
            )
        )

    obj_path = find_dataset_file(
        f"{SAMPLE_ID}.obj"
    )

    if obj_path is None:
        raise FileNotFoundError(
            f"Could not find "
            f"{SAMPLE_ID}.obj "
            f"under {ROOT / 'Datase'}"
        )

    labeled_csv_path = find_labeled_pointcloud_csv(
        SAMPLE_ID
    )

    if labeled_csv_path is None:
        raise FileNotFoundError(
            f"Could not find the labelled 3D point-cloud CSV "
            f"{SAMPLE_ID}.csv under {ROOT / 'Datase'}. "
            "Extract the Validation source/label ZIPs first."
        )

    print(
        f"[DATASET] OBJ={obj_path}"
    )
    print(
        f"[DATASET] labelled 3D CSV={labeled_csv_path}"
    )

    data = np.load(
        TRAJECTORY_NPZ
    )

    predicted_source = np.asarray(
        data[
            "predicted_path_m"
        ],
        dtype=np.float64,
    )

    gt_source = np.asarray(
        data[
            "ground_truth_path_m"
        ],
        dtype=np.float64,
    )

    if (
        predicted_source.ndim != 2
        or predicted_source.shape[1] != 3
    ):
        raise RuntimeError(
            "predicted_path_m must be (N,3), "
            f"got {predicted_source.shape}"
        )

    print(
        f"[VALIDATION] sample="
        f"{SAMPLE_ID}"
    )
    print(
        f"[VALIDATION] prediction="
        f"{predicted_source.shape}"
    )
    print(
        f"[VALIDATION] GT="
        f"{gt_source.shape}"
    )

    if "point_error" in data:
        point_error = np.asarray(
            data[
                "point_error"
            ],
            dtype=np.float64,
        )

        print(
            f"[METRIC] point-error mean="
            f"{np.mean(point_error) * 1000.0:.3f} mm "
            f"max="
            f"{np.max(point_error) * 1000.0:.3f} mm"
        )

    if METADATA_JSON.is_file():
        metadata = json.loads(
            METADATA_JSON.read_text(
                encoding="utf-8"
            )
        )

        metrics = metadata.get(
            "metrics",
            {},
        )

        if metrics:
            print(
                "[METRIC] metadata "
                f"ADE={metrics.get('ade_source_units')} mm "
                f"FDE={metrics.get('fde_source_units')} mm "
                f"MAX={metrics.get('max_error_source_units')} mm"
            )

    # --------------------------------------------------------
    # URDF chain + fixed orientation
    # --------------------------------------------------------

    chain, limits = (
        parse_urdf_chain(
            URDF_PATH,
            end_link="tcp",
        )
    )

    seed_solution = np.load(
        SEED_SOLUTION_PATH
    )

    q_seed_fixed = np.asarray(
        seed_solution[
            "joint_position_rad"
        ][0],
        dtype=np.float64,
    )

    q_seed_fixed = clip_joint_limits(
        q_seed_fixed,
        limits,
    )

    start_fk = fk_tcp(
        chain,
        q_seed_fixed,
    )

    fixed_tcp_rotation = (
        start_fk[
            :3,
            :3
        ].copy()
    )

    print(
        "[ORIENTATION] fixed from one "
        "already-validated RB10 seed pose; "
        "model predicts XYZ only."
    )

    # --------------------------------------------------------
    # Import robot
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
        Sdf.Path(
            robot_path
        )
        .GetParentPath()
    )

    tcp_paths = [
        prim.GetPath().pathString
        for prim in stage.Traverse()
        if (
            prim.GetName()
            == "tcp"
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
    # Scene + torch
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

    # Kinematic visualization.
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

    (
        nozzle_tip_path,
        nozzle_tip_in_tcp,
    ) = add_torch_at_tcp(
        stage,
        tcp_path,
    )

    # --------------------------------------------------------
    # Coordinate alignment
    #
    # Validation XYZ starts in the source robot frame.
    # For this first visualization we preserve its axes and align its
    # starting point to the CAD nozzle start of the fixed RB10 seed pose.
    # --------------------------------------------------------

    tcp_start_position = (
        start_fk[
            :3,
            3
        ]
    )

    actual_nozzle_start = (
        tcp_start_position
        + fixed_tcp_rotation
        @ nozzle_tip_in_tcp
    )

    source_to_world_translation = (
        actual_nozzle_start
        - gt_source[0]
    )

    gt_world = (
        gt_source
        + source_to_world_translation
    )

    predicted_world = (
        predicted_source
        + source_to_world_translation
    )

    print(
        "[FRAME] source path translated so "
        "GT start == current CAD nozzle start"
    )
    print(
        "[FRAME] translation [m]="
        f"{source_to_world_translation.tolist()}"
    )

    # --------------------------------------------------------
    # IK:
    # CAD nozzle target XYZ -> required RB10 tcp XYZ.
    #
    # orientation is fixed, therefore nozzle offset in world is constant.
    # --------------------------------------------------------

    nozzle_offset_world = (
        fixed_tcp_rotation
        @ nozzle_tip_in_tcp
    )

    target_tcp_positions = (
        predicted_world
        - nozzle_offset_world
    )

    q_path = []

    q_seed = (
        q_seed_fixed.copy()
    )

    failures = 0
    position_errors_mm = []

    print(
        "\n[IK] solving predicted XYZ "
        "with one fixed orientation..."
    )

    for i, target_tcp in enumerate(
        target_tcp_positions
    ):
        (
            q_solution,
            success,
            position_error_m,
            orientation_error_rad,
            iterations,
        ) = solve_ik(
            chain,
            limits,
            target_tcp,
            fixed_tcp_rotation,
            q_seed,
        )

        q_path.append(
            q_solution
        )

        q_seed = (
            q_solution.copy()
        )

        position_errors_mm.append(
            position_error_m
            * 1000.0
        )

        if not success:
            failures += 1

        print(
            f"  {i + 1:02d}/"
            f"{len(target_tcp_positions):02d} "
            f"{'OK' if success else 'WARN'} "
            f"pos_err="
            f"{position_error_m * 1000.0:.3f} mm "
            f"ori_err="
            f"{np.rad2deg(orientation_error_rad):.3f} deg "
            f"iter={iterations}"
        )

    q_path = np.asarray(
        q_path,
        dtype=np.float64,
    )

    print(
        f"[IK] solved="
        f"{len(q_path) - failures}/"
        f"{len(q_path)}, "
        f"warnings={failures}, "
        f"mean position residual="
        f"{np.mean(position_errors_mm):.3f} mm"
    )

    # --------------------------------------------------------
    # Actual L_PR object registration:
    # OBJ geometry -> measured 3D labelled seam -> GT path
    # --------------------------------------------------------

    (
        scene_center,
        workpiece_rotation,
        workpiece_registration,
    ) = add_validation_workpiece(
        stage,
        obj_path,
        labeled_csv_path,
        gt_world,
    )

    # --------------------------------------------------------
    # Ground-truth reference trajectory
    #
    # GREEN = actual/ground-truth XYZ trajectory.
    # The robot itself does NOT follow this line.
    # The robot follows the MODEL PREDICTION only.
    # --------------------------------------------------------

    add_static_curve(
        stage,
        "/GroundTruthTrajectory",
        gt_world,
        width=0.0080,
        color=Gf.Vec3f(
            0.0,
            1.0,
            0.0,
        ),
    )

    # The exact GT line can be partly hidden by the pipe/plate contact
    # because it lies directly on the physical seam.  Green spheres are
    # centred on the exact GT XYZ so the reference remains visible.
    add_gt_waypoint_markers(
        stage,
        gt_world,
    )

    # --------------------------------------------------------
    # Start simulation / articulation
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

    missing_dofs = [
        name
        for name in JOINT_NAMES
        if name not in dof_names
    ]

    if missing_dofs:
        raise RuntimeError(
            f"Missing DOFs: "
            f"{missing_dofs}; "
            f"all={dof_names}"
        )

    indices = [
        dof_names.index(
            name
        )
        for name in JOINT_NAMES
    ]

    robot.set_joint_positions(
        q_path[0],
        joint_indices=indices,
    )

    robot.set_joint_velocities(
        np.zeros(
            len(indices),
            dtype=np.float64,
        ),
        joint_indices=indices,
    )

    for _ in range(10):
        simulation_app.update()

    # --------------------------------------------------------
    # Dynamic predicted weld bead only
    # --------------------------------------------------------

    first_tip = world_position(
        stage,
        nozzle_tip_path,
    )

    weld_bead = create_dynamic_curve(
        stage,
        "/PredictedWeldBead",
        first_tip,
        width=0.0055,
        color=Gf.Vec3f(
            0.62,
            0.07,
            0.015,
        ),
    )

    hot_pool = create_dynamic_curve(
        stage,
        "/PredictedHotPool",
        first_tip,
        width=0.0075,
        color=Gf.Vec3f(
            1.0,
            0.20,
            0.015,
        ),
    )

    bead_points = [
        first_tip.copy()
    ]

    bead_spacing_m = (
        0.0005
    )

    hot_tail_points = 10

    # --------------------------------------------------------
    # Camera: close welding view derived from registered geometry
    # --------------------------------------------------------

    path_direction = (
        gt_world[-1]
        - gt_world[0]
    )

    path_direction /= np.linalg.norm(
        path_direction
    )

    plate_to_round_world = np.asarray(
        workpiece_registration[
            "plate_normal_world"
        ],
        dtype=np.float64,
    )

    plate_to_round_world /= np.linalg.norm(
        plate_to_round_world
    )

    side_world = np.asarray(
        workpiece_registration[
            "side_axis_world"
        ],
        dtype=np.float64,
    )

    side_world /= np.linalg.norm(
        side_world
    )

    # Camera stays on the outer plate side (opposite the round body),
    # with a small axial/side offset for a readable 3/4 view.
    camera_eye = (
        scene_center
        - plate_to_round_world
        * 0.30
        - path_direction
        * 0.08
        + side_world
        * 0.05
    )

    camera_target = (
        scene_center
        + plate_to_round_world
        * 0.005
    )

    set_camera_view(
        eye=camera_eye.tolist(),
        target=camera_target.tolist(),
    )

    # --------------------------------------------------------
    # Playback
    # --------------------------------------------------------

    n = len(
        q_path
    )

    duration = max(
        float(
            args.duration_sec
        ),
        1.0,
    )

    print(
        "\n[PLAYBACK] MODEL PREDICTION"
    )
    print(
        "  GREEN line = ground-truth / actual trajectory"
    )
    print(
        "  robot motion = MODEL predicted XYZ"
    )
    print(
        "  orientation = fixed"
    )
    print(
        "  red/orange trail = predicted weld result"
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

        path_position = (
            progress
            * (n - 1)
        )

        i0 = int(
            np.floor(
                path_position
            )
        )

        i1 = min(
            i0 + 1,
            n - 1,
        )

        alpha = (
            path_position
            - i0
        )

        q = (
            (1.0 - alpha)
            * q_path[i0]
            + alpha
            * q_path[i1]
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

        current_tip = world_position(
            stage,
            nozzle_tip_path,
        )

        if (
            np.linalg.norm(
                current_tip
                - bead_points[-1]
            )
            >= bead_spacing_m
        ):
            bead_points.append(
                current_tip.copy()
            )

            update_dynamic_curve(
                weld_bead,
                bead_points,
            )

            update_dynamic_curve(
                hot_pool,
                bead_points[
                    -hot_tail_points:
                ],
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
                f"{path_position + 1:.1f}/{n}"
            )

        time.sleep(
            0.005
        )

    # Exact final predicted pose.
    robot.set_joint_positions(
        q_path[-1],
        joint_indices=indices,
    )

    robot.set_joint_velocities(
        np.zeros(
            len(indices),
            dtype=np.float64,
        ),
        joint_indices=indices,
    )

    for _ in range(6):
        simulation_app.update()

    final_tip = world_position(
        stage,
        nozzle_tip_path,
    )

    if (
        np.linalg.norm(
            final_tip
            - bead_points[-1]
        )
        > 1e-8
    ):
        bead_points.append(
            final_tip.copy()
        )

    update_dynamic_curve(
        weld_bead,
        bead_points,
    )

    update_dynamic_curve(
        hot_pool,
        bead_points[
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

    # --------------------------------------------------------
    # Save solved prediction for reuse
    # --------------------------------------------------------

    output_npz = (
        ROOT
        / "validation_prediction_rb10_solution.npz"
    )

    np.savez(
        output_npz,
        predicted_source_m=predicted_source,
        ground_truth_source_m=gt_source,
        predicted_world_m=predicted_world,
        ground_truth_world_m=gt_world,
        target_tcp_world_m=target_tcp_positions,
        joint_position_rad=q_path,
        fixed_tcp_rotation=fixed_tcp_rotation,
        nozzle_tip_in_tcp_m=nozzle_tip_in_tcp,
        source_to_world_translation=source_to_world_translation,
        obj_to_world_rotation=workpiece_registration[
            "obj_to_world_rotation"
        ],
        obj_to_world_translation=workpiece_registration[
            "obj_to_world_translation"
        ],
        measured_to_world_rotation=workpiece_registration[
            "measured_to_world_rotation"
        ],
        measured_to_world_translation=workpiece_registration[
            "measured_to_world_translation"
        ],
        measured_seam_center_m=workpiece_registration[
            "measured_seam_center_m"
        ],
        measured_seam_direction=workpiece_registration[
            "measured_seam_direction"
        ],
        ik_position_error_mm=np.asarray(
            position_errors_mm
        ),
    )

    output_usda = (
        ROOT
        / "validation_prediction_sim.usda"
    )

    omni.usd.get_context().save_as_stage(
        output_usda.as_posix()
    )

    print(
        f"[SAVE] {output_npz}"
    )
    print(
        f"[SAVE] {output_usda}"
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
