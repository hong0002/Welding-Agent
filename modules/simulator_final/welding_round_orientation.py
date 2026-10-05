"""T_RR geometric preview orientations. Preserve XYZ; no interference checks."""
import numpy as np
from scipy.spatial.transform import Rotation

from welding_workpiece import _obj_connected_components
from welding_tool_geometry import CAD_TIP_LOCAL_MM

POLICY = 'T_RR per-point outer-tube approach; unchanged XYZ; no interference checks'
# Explicit simulation fixture setting, not a measured dataset TCP calibration.
ROUND_WIRE_EXTENSION_MM = 15.
ROUND_WIRE_DIRECTION = np.array([0., -.6487, .7611])


def round_weld_tip_local_mm():
    return CAD_TIP_LOCAL_MM + ROUND_WIRE_EXTENSION_MM * unit(ROUND_WIRE_DIRECTION)


def unit(v):
    norm = np.linalg.norm(v)
    if norm < 1e-9:
        raise ValueError('undefined tube approach direction')
    return v / norm


def fit_tubes(arrays):
    vertices = arrays['workpiece_vertices_world_m'] * 1000.
    components = _obj_connected_components(len(vertices), arrays['workpiece_face_counts'],
                                            arrays['workpiece_face_indices'])
    if len(components) != 2:
        raise ValueError('T_RR requires two CAD bodies')
    tubes = []
    for ids in components:
        p = vertices[ids]
        _, _, basis = np.linalg.svd(p-p.mean(0), full_matrices=False)
        candidates = []
        for axis in basis:
            origin = (p.min(0)+p.max(0))/2
            axial = (p-origin) @ axis
            radial = p-origin-axial[:, None]*axis
            radii = np.linalg.norm(radial, axis=1)
            # Outer and inner circular rings have small radial spread along the true axis.
            spread = (np.quantile(radii, .95)-np.quantile(radii, .05))/max(radii.max(), 1.)
            candidates.append((spread, origin, axis, axial, radii))
        spread, origin, axis, axial, radii = min(candidates, key=lambda c:c[0])
        if spread > .35:
            raise ValueError('T_RR CAD is not a supported circular tube')
        center = origin+axis*(axial.max()+axial.min())/2
        tubes.append((center, axis, (axial.max()-axial.min())/2, radii.max()))
    return tubes


def flange_rotation(outward, roll, tool):
    local_z = unit(-tool[:3, 3])  # TCP -> flange, not the nozzle's nominal CAD Z.
    local_x = unit(np.array([1.,0,0])-local_z*local_z[0])
    local = np.column_stack((local_x, np.cross(local_z, local_x), local_z))
    z = unit(outward)
    reference = np.array([0.,0,1.]) if abs(z[2]) < .95 else np.array([0.,1.,0.])
    x = unit(np.cross(z, reference))
    world = np.column_stack((x, np.cross(z, x), z))
    return Rotation.from_rotvec(z*np.deg2rad(roll)).as_matrix() @ world @ local.T


def orient_round_path(poses, arrays, tool):
    tubes = fit_tubes(arrays)
    candidates, preferences = [], []
    for xyz in poses[:, :3]:
        normals = []
        for center, axis, _, _ in tubes:
            delta = xyz-center
            normals.append(unit(delta-axis*np.dot(delta, axis)))
        options, penalties = [], []
        for weight in (.25, .5, .75):
            direction = unit(weight*normals[0]+(1-weight)*normals[1])
            for roll in (-135, -90, -45, 0, 45, 90, 135, 180):
                rotation = flange_rotation(direction, roll, tool)
                options.append(rotation)
                # Geometry-only preference: bisect the exterior directions and
                # avoid unnecessary axial roll. No clearance scoring or rejection.
                penalties.append(.01*(weight-.5)**2 + .0001*np.deg2rad(roll)**2)
        candidates.append(np.asarray(options)); preferences.append(np.asarray(penalties))
    # Global angular continuity avoids independent per-point roll flips.
    costs = preferences[0].copy()
    parents = []
    for i in range(1, len(candidates)):
        relative = np.einsum('aji,bjk->abik', candidates[i-1], candidates[i])
        angles = np.arccos(np.clip((np.trace(relative, axis1=-2, axis2=-1)-1)/2, -1, 1))
        transition = costs[:,None]+angles**2
        parents.append(np.argmin(transition, axis=0))
        costs = transition.min(0)+preferences[i]
    chosen = [int(np.argmin(costs))]
    for parent in reversed(parents):
        chosen.append(int(parent[chosen[-1]]))
    chosen.reverse()
    flange = np.array([c[k] for c,k in zip(candidates,chosen)])
    result = poses.copy()
    result[:,3:] = Rotation.from_matrix(flange @ tool[:3,:3]).as_euler('xyz', degrees=True)
    report = dict(policy=POLICY, xyz_modified=False, source_orientation_used=False,
                  torch_interference_checked=False,
                  virtual_wire_extension_mm=ROUND_WIRE_EXTENSION_MM,
                  wire_is_simulation_setting=True,
                  whole_robot_collision_checked=False,
                  tubes=[dict(center_mm=c.tolist(), axis=a.tolist(), half_length_mm=float(h), radius_mm=float(r))
                         for c,a,h,r in tubes])
    return result, report
