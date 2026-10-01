"""Offline diagnostic math only. Does not register fixtures or admit playback.

Candidate matrices compare the ideal CAD tangent-line hypothesis. A small GT
residual is not tool clearance, a weld tolerance, or a runtime approval.
"""
from dataclasses import dataclass, field
import numpy as np


@dataclass(frozen=True)
class ContactLineDiagnostic:
    anchor_mm: np.ndarray
    axis: np.ndarray
    low_mm: float
    high_mm: float
    plate_normal: np.ndarray
    contact_gap_mm: float
    transverse_spread_mm: float
    tangent_vertex_count: int
    runtime_approved: bool = field(default=False, init=False)


def unit(vector):
    value = np.asarray(vector, dtype=float)
    if value.shape != (3,) or not np.isfinite(value).all() or np.linalg.norm(value) < 1e-12:
        raise ValueError("Diagnostic basis needs a finite nonzero XYZ direction")
    return value / np.linalg.norm(value)


def canonical_axis(vector):
    axis = unit(vector)
    return axis if axis[np.argmax(abs(axis))] > 0 else -axis


def frame(seam, outward):
    y = unit(seam)
    z = unit(np.asarray(outward) - y * np.dot(outward,y))
    return np.column_stack((np.cross(y,z),y,z))


def pca(points):
    points = np.asarray(points,dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 8 or not np.isfinite(points).all():
        raise ValueError("Diagnostic PCA requires finite mesh XYZ")
    center = points.mean(0)
    _, axes = np.linalg.eigh((points-center).T@(points-center)/len(points))
    axes = axes[:,::-1]
    return dict(points=points,center=center,axes=axes,extents=np.ptp((points-center)@axes,axis=0))


def contact_line(vertices, components):
    """Report a tangent-plane hypothesis from exact mesh extrema, without PASS."""
    vertices = np.asarray(vertices,dtype=float)
    if len(components) != 2:
        raise ValueError("B_PR diagnostic expects two connected mesh bodies")
    parts = [pca(vertices[np.asarray(indices,dtype=int)]) for indices in components]
    parts.sort(key=lambda p:p['extents'].min()/p['extents'].max())
    plate, tube = parts
    normal = canonical_axis(plate['axes'][:,np.argmin(plate['extents'])])
    axis = canonical_axis(tube['axes'][:,np.argmax(tube['extents'])])
    offset = tube['center']-plate['center']
    edge = unit(offset-normal*np.dot(offset,normal)-axis*np.dot(offset,axis))
    values = tube['points']@edge
    # Select numerical equal extrema only; no weld-distance/geometry PASS tolerance.
    near = values.min()
    equality_budget = np.finfo(float).eps * max(1.,float(np.max(abs(values)))) * 16
    contact = tube['points'][abs(values-near)<=equality_budget]
    if len(contact)<2:
        raise ValueError("No axial tangent-vertex evidence")
    perpendicular = contact-(contact@axis)[:,None]*axis
    low = max(float((contact@axis).min()),float((plate['points']@axis).min()))
    high = min(float((contact@axis).max()),float((plate['points']@axis).max()))
    if high<=low:
        raise ValueError("Candidate bodies have no overlapping axial contact interval")
    anchor = perpendicular.mean(0)+axis*(low+high)/2
    for array in (anchor,axis,normal): array.flags.writeable=False
    return ContactLineDiagnostic(anchor,axis,low,high,normal,
        float(near-(plate['points']@edge).max()),
        float(np.linalg.norm(perpendicular-perpendicular.mean(0),axis=1).max()),len(contact))


def candidate_transform(source_xyz_mm, source_mean_tcp_y, contact, outward_sign, native_center_m):
    """A diagnostic hypothesis only; native center must be supplied as evidence."""
    source = np.asarray(source_xyz_mm,dtype=float)
    center = np.asarray(native_center_m,dtype=float)
    if (source.ndim!=2 or source.shape[1]!=3 or len(source)<2 or not np.isfinite(source).all()
            or center.shape!=(3,) or not np.isfinite(center).all() or outward_sign not in (-1,1)):
        raise ValueError("Invalid diagnostic source/center/sign")
    rotation = frame(contact.axis,contact.plate_normal*outward_sign) @ frame(source[-1]-source[0],source_mean_tcp_y).T
    transform = np.eye(4)
    transform[:3,:3] = rotation
    transform[:3,3] = center-rotation@(source.mean(0)*.001)
    return transform


def apply_rigid(points_m, transform):
    points, transform = np.asarray(points_m,dtype=float),np.asarray(transform,dtype=float)
    if (points.ndim!=2 or points.shape[1]!=3 or not np.isfinite(points).all() or transform.shape!=(4,4)
            or not np.isfinite(transform).all() or not np.allclose(transform[3],[0,0,0,1],atol=1e-12,rtol=0)
            or not np.allclose(transform[:3,:3].T@transform[:3,:3],np.eye(3),atol=1e-12,rtol=0)
            or not np.isclose(np.linalg.det(transform[:3,:3]),1,atol=1e-12,rtol=0)):
        raise ValueError("Diagnostic requires finite proper rigid transform")
    return points@transform[:3,:3].T+transform[:3,3]


def seam_distances(cad_points_mm, contact):
    points = np.asarray(cad_points_mm,dtype=float)
    if points.ndim!=2 or points.shape[1]!=3 or not np.isfinite(points).all() or len(points)<2:
        raise ValueError("Invalid diagnostic points")
    projection = (points-contact.anchor_mm)@contact.axis
    center_along = contact.anchor_mm@contact.axis
    closest = contact.anchor_mm+np.clip(projection,contact.low_mm-center_along,contact.high_mm-center_along)[:,None]*contact.axis
    distance = np.linalg.norm(points-closest,axis=1)
    return dict(mean_mm=float(distance.mean()),max_mm=float(distance.max()),start_mm=float(distance[0]),end_mm=float(distance[-1]),
                start_seam_mm=float(projection[0]),end_seam_mm=float(projection[-1]),
                distance_is_diagnostic=True,weld_pass_threshold_mm=None,runtime_approved=False)
