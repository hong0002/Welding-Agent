"""Prepare a verified RB5 joint path from the real TCP poses stored in an H5 file."""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import h5py
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation


JOINT_NAMES = ("base", "shoulder", "elbow", "wrist1", "wrist2", "wrist3")


def matrix_from_xyz_rpy(xyz, rpy):
    result = np.eye(4)
    result[:3, :3] = Rotation.from_euler("xyz", rpy).as_matrix()
    result[:3, 3] = xyz
    return result


class UrdfChain:
    def __init__(self, urdf_path: Path):
        root = ET.parse(urdf_path).getroot()
        joints = {joint.attrib["name"]: joint for joint in root.findall("joint")}
        self.steps = []
        self.lower = []
        self.upper = []
        for name in (*JOINT_NAMES, "tcp_joint"):
            joint = joints[name]
            origin = joint.find("origin")
            xyz = np.fromstring(origin.attrib.get("xyz", "0 0 0"), sep=" ")
            rpy = np.fromstring(origin.attrib.get("rpy", "0 0 0"), sep=" ")
            fixed = joint.attrib["type"] == "fixed"
            axis = None if fixed else np.fromstring(joint.find("axis").attrib["xyz"], sep=" ")
            self.steps.append((matrix_from_xyz_rpy(xyz, rpy), axis))
            if not fixed:
                limit = joint.find("limit")
                self.lower.append(float(limit.attrib["lower"]))
                self.upper.append(float(limit.attrib["upper"]))
        self.lower = np.asarray(self.lower)
        self.upper = np.asarray(self.upper)

    def fk(self, joint_radians):
        result = np.eye(4)
        moving_index = 0
        for origin, axis in self.steps:
            result = result @ origin
            if axis is not None:
                rotation = np.eye(4)
                rotation[:3, :3] = Rotation.from_rotvec(axis * joint_radians[moving_index]).as_matrix()
                result = result @ rotation
                moving_index += 1
        return result


def average_tool_transform(chain, joint_deg, endpoint_poses):
    samples = []
    for joints, pose in zip(joint_deg, endpoint_poses):
        desired = matrix_from_xyz_rpy(pose[:3] / 1000.0, np.deg2rad(pose[3:]))
        samples.append(np.linalg.inv(chain.fk(np.deg2rad(joints))) @ desired)
    result = np.eye(4)
    result[:3, 3] = np.mean([sample[:3, 3] for sample in samples], axis=0)
    result[:3, :3] = Rotation.from_matrix([sample[:3, :3] for sample in samples]).mean().as_matrix()
    return result, samples


def solve_path(chain, tcp_poses, tool_transform, initial_deg):
    joint_path = []
    position_errors_mm = []
    orientation_errors_deg = []
    q = np.deg2rad(initial_deg)

    for index, pose in enumerate(tcp_poses):
        target_position = pose[:3] / 1000.0
        target_rotation = Rotation.from_euler("xyz", pose[3:], degrees=True)

        def residual(candidate):
            actual = chain.fk(candidate) @ tool_transform
            position = (actual[:3, 3] - target_position) / 0.001
            rotation = (target_rotation.inv() * Rotation.from_matrix(actual[:3, :3])).as_rotvec()
            return np.r_[position, rotation / np.deg2rad(0.5)]

        solution = least_squares(
            residual,
            q,
            bounds=(chain.lower, chain.upper),
            max_nfev=300,
            xtol=1e-11,
            ftol=1e-11,
            gtol=1e-11,
        )
        q = solution.x
        actual = chain.fk(q) @ tool_transform
        position_errors_mm.append(np.linalg.norm(actual[:3, 3] - target_position) * 1000.0)
        orientation_errors_deg.append(
            np.rad2deg(
                np.linalg.norm((target_rotation.inv() * Rotation.from_matrix(actual[:3, :3])).as_rotvec())
            )
        )
        joint_path.append(q.copy())
        if not solution.success:
            raise RuntimeError(f"IK failed at trajectory row {index}: {solution.message}")

    return np.asarray(joint_path), np.asarray(position_errors_mm), np.asarray(orientation_errors_deg)


def endpoint_residuals(chain, endpoint_joints_deg, endpoint_poses, tool_transform):
    results = []
    for joints, pose in zip(endpoint_joints_deg, endpoint_poses):
        actual = chain.fk(np.deg2rad(joints)) @ tool_transform
        desired = matrix_from_xyz_rpy(pose[:3] / 1000.0, np.deg2rad(pose[3:]))
        rotation_error = Rotation.from_matrix(desired[:3, :3]).inv() * Rotation.from_matrix(actual[:3, :3])
        results.append(
            {
                "fk_xyz_mm": (actual[:3, 3] * 1000.0).tolist(),
                "h5_xyz_mm": pose[:3].tolist(),
                "position_error_mm": float(np.linalg.norm(actual[:3, 3] - desired[:3, 3]) * 1000.0),
                "orientation_error_deg": float(np.rad2deg(np.linalg.norm(rotation_error.as_rotvec()))),
            }
        )
    return results


def find_default_h5(root: Path):
    matches = list((root / "Datase").rglob("T_PP_03_0001.h5"))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected exactly one T_PP_03_0001.h5, found {len(matches)}")
    return matches[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--urdf", type=Path, default=Path("rb5_850e_u.urdf"))
    parser.add_argument("--h5", type=Path)
    parser.add_argument("--output", type=Path, default=Path("rb5_h5_trajectory_solution.npz"))
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    urdf_path = args.urdf if args.urdf.is_absolute() else root / args.urdf
    h5_path = args.h5 or find_default_h5(root)
    chain = UrdfChain(urdf_path)

    with h5py.File(h5_path, "r") as handle:
        required = {"trajectory", "joint_values", "original_points"}
        if not required.issubset(handle.keys()):
            raise KeyError(f"H5 is missing datasets: {sorted(required - set(handle.keys()))}")
        tcp_poses = np.asarray(handle["trajectory"], dtype=np.float64)
        endpoint_joints_deg = np.asarray(handle["joint_values"], dtype=np.float64)
        endpoint_poses = np.asarray(handle["original_points"], dtype=np.float64)

    if tcp_poses.ndim != 2 or tcp_poses.shape[1] != 6:
        raise ValueError(f"Expected trajectory shape (N, 6), got {tcp_poses.shape}")

    tool_transform, calibration_samples = average_tool_transform(chain, endpoint_joints_deg, endpoint_poses)
    endpoint_checks = endpoint_residuals(chain, endpoint_joints_deg, endpoint_poses, tool_transform)
    joint_path, position_error, orientation_error = solve_path(
        chain, tcp_poses, tool_transform, endpoint_joints_deg[0]
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        tcp_pose_xyz_mm_rpy_deg=tcp_poses.astype(np.float32),
        joint_position_rad=joint_path.astype(np.float32),
        joint_names=np.asarray(JOINT_NAMES),
        urdf_tcp_to_weld_tcp=tool_transform,
        position_error_mm=position_error.astype(np.float32),
        orientation_error_deg=orientation_error.astype(np.float32),
    )
    report = {
        "source_h5": str(h5_path.resolve()),
        "source_urdf": str(urdf_path.resolve()),
        "h5_datasets": {
            "trajectory": {"shape": list(tcp_poses.shape), "format": "XYZ mm + XYZ Euler degrees"},
            "joint_values": {"shape": list(endpoint_joints_deg.shape), "unit": "degrees"},
            "original_points": {"shape": list(endpoint_poses.shape), "format": "XYZ mm + XYZ Euler degrees"},
        },
        "urdf_tcp_to_weld_tcp": tool_transform.tolist(),
        "calibration_sample_translations_m": [sample[:3, 3].tolist() for sample in calibration_samples],
        "calibration_translation_difference_mm": float(
            np.linalg.norm(calibration_samples[0][:3, 3] - calibration_samples[1][:3, 3]) * 1000.0
        ),
        "mean_transform_endpoint_checks": endpoint_checks,
        "ik": {
            "point_count": int(len(joint_path)),
            "position_error_mm_mean": float(position_error.mean()),
            "position_error_mm_max": float(position_error.max()),
            "orientation_error_deg_mean": float(orientation_error.mean()),
            "orientation_error_deg_max": float(orientation_error.max()),
        },
        "note": "The fixed TCP correction is estimated from the two recorded endpoint joint/pose pairs.",
    }
    report_path = args.output.with_suffix(".json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] {len(joint_path)} TCP poses solved")
    print(f"[IK] position error mean/max: {position_error.mean():.6f}/{position_error.max():.6f} mm")
    print(f"[IK] orientation error mean/max: {orientation_error.mean():.6f}/{orientation_error.max():.6f} deg")
    print(
        "[CALIBRATION] endpoint translation disagreement: "
        f"{report['calibration_translation_difference_mm']:.6f} mm"
    )
    for index, check in enumerate(endpoint_checks):
        print(
            f"[ENDPOINT {index}] position/orientation error with mean transform: "
            f"{check['position_error_mm']:.6f} mm / {check['orientation_error_deg']:.6f} deg"
        )
    print(f"[SAVE] {args.output.resolve()}")
    print(f"[SAVE] {report_path.resolve()}")


if __name__ == "__main__":
    main()
