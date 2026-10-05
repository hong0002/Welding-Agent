"""Inspect welding-tool mesh vertices without starting SimulationApp."""

from pathlib import Path

import numpy as np
from pxr import Usd, UsdGeom


path = Path(__file__).resolve().parent / "ATU01035_welding_tool.usd"
stage = Usd.Stage.Open(str(path))
stage = Usd.Stage.Open(stage.Flatten())
cache = UsdGeom.XformCache(Usd.TimeCode.Default())
points = []
for prim in stage.TraverseAll():
    if prim.IsA(UsdGeom.Mesh):
        matrix = cache.GetLocalToWorldTransform(prim)
        mesh_points = UsdGeom.Mesh(prim).GetPointsAttr().Get() or []
        points.extend(tuple(matrix.Transform(point)) for point in mesh_points)

points = np.asarray(points, dtype=np.float64)
if not len(points):
    raise RuntimeError("No mesh vertices found")
distance = np.linalg.norm(points, axis=1)
print(f"point_count={len(points)}")
print(f"bounds_min_mm={points.min(axis=0).tolist()}")
print(f"bounds_max_mm={points.max(axis=0).tolist()}")
print(f"closest_to_cad_origin_mm={points[np.argmin(distance)].tolist()}")
print(f"closest_distance_mm={distance.min():.6f}")
centred = points - points.mean(axis=0)
_, _, vh = np.linalg.svd(centred, full_matrices=False)
pca_axis = vh[0]
projection = points @ pca_axis
low = points[projection <= projection.min() + 1.0].mean(axis=0)
high = points[projection >= projection.max() - 1.0].mean(axis=0)
if np.linalg.norm(low) > np.linalg.norm(high):
    pca_axis = -pca_axis
    projection = -projection
pca_tip = points[projection >= projection.max() - 1.0].mean(axis=0)
pca_mount = points[projection <= projection.min() + 1.0].mean(axis=0)
print(f"pca_distal_axis={pca_axis.tolist()}")
print(f"pca_mount_center_mm={pca_mount.tolist()}")
print(f"pca_distal_tip_mm={pca_tip.tolist()}")
print(f"pca_mount_to_tip_mm={(pca_tip - pca_mount).tolist()}")
print(f"pca_distal_tip_distance_mm={np.linalg.norm(pca_tip):.6f}")
for axis, name in enumerate("xyz"):
    print(f"min_{name}_vertex_mm={points[np.argmin(points[:, axis])].tolist()}")
    print(f"max_{name}_vertex_mm={points[np.argmax(points[:, axis])].tolist()}")
